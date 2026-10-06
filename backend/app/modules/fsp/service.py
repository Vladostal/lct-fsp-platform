"""Фасад модуля `fsp` (Арх. 2.5, 7.6, 7.7; приложение D, §10.3).

Вызывающий передаёт настройки приватности и признак раскрытия; фасад не обращается к реестру и не запускает
синхронизацию (запросы работодателя реестр не трогают никогда). Пакетные функции делают не больше трёх запросов
независимо от числа кандидатов. Кандидат без привязки или со скрытыми достижениями получает нулевой сигнал:
отрицательных меток и значений по умолчанию нет. Транзакцию фиксирует вызывающий (`TxRoute`, `run_in_tx`).

Дополнительно к нормативным сигнатурам: `resync_batch` — для сценария `python -m app.scripts.fsp_resync`.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Collection, Sequence
from datetime import date, timedelta
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.modules.catalog import service as catalog
from app.modules.fsp import constants as c
from app.modules.fsp import linking, sync, views
from app.modules.fsp import signal as sig
from app.modules.fsp.dto import (
    DemoAthlete,
    FspContribution,
    FspEmployerBlock,
    FspLinkBrief,
    FspPublicSummary,
    FspSignal,
    FspSkillEvidence,
    FspSubject,
    UnlinkReason,
)
from app.modules.fsp.gateway import factory
from app.modules.fsp.models import ExternalIdentity, FspSnapshot

if TYPE_CHECKING:
    from app.modules.fsp.gateway.mock import MockFspGateway


def _public(summary: sig.PublicSummary | None) -> FspPublicSummary | None:
    if summary is None:
        return None
    return FspPublicSummary(
        level=summary.level,
        headline=summary.headline,
        short=summary.short,
        more=summary.more,
        shortened=summary.shortened,
    )


def link_brief(db: Session, user_id: UUID) -> FspLinkBrief:
    """Кратко о привязке для строки «Усилить профиль»."""
    data = views.load(db, [user_id])[user_id]
    if not data.linked or data.identity is None:
        return FspLinkBrief(status="not_linked")
    snapshot = sync.current_snapshot(db, data.identity.id)
    history = views.history_of(data, snapshot, views.last_attempt(db, user_id), clock.real_now())
    counted = sum(1 for row in data.achievements if row.counted)
    return FspLinkBrief(status="linked", history_status=history.status if history else None, counted=counted)


def get_signals(db: Session, subjects: Sequence[FspSubject], *, as_of: date) -> dict[UUID, FspSignal]:
    """Сигнал достижений ФСП для пачки кандидатов (Арх. 7.6).

    Без привязки или при `show_summary = false` — нулевой: `value = 0`, `band = none`, `visible = false`,
    `verified = false`, `public = None`. Скрыто — значит не учитывается.
    """
    data = views.load(db, [subject.user_id for subject in subjects])
    k_anon = get_settings().fsp_k_anon
    result: dict[UUID, FspSignal] = {}
    for subject in subjects:
        item = data[subject.user_id]
        if not sig.is_visible(linked=item.linked, show_summary=subject.show_summary):
            result[subject.user_id] = FspSignal(user_id=subject.user_id, version=c.FSP_SIGNAL_VERSION)
            continue
        facts, ranks = item.facts(), item.ranks()
        calculated = sig.compute_signal(facts, ranks, subject.specialization, as_of)
        has_verified = sig.has_verified_facts(facts, ranks)
        public = sig.public_summary(facts, ranks, subject.specialization, as_of, k_anon) if has_verified else None
        result[subject.user_id] = FspSignal(
            user_id=subject.user_id,
            value=calculated.value,
            results_value=calculated.results_value,
            floor_value=calculated.floor_value,
            floor_source=calculated.floor_source,
            counted=calculated.counted,
            contributions=[
                FspContribution(
                    fact_id=entry.fact_id,
                    p=entry.p,
                    base_points=entry.base_points,
                    decay=entry.decay,
                    relevance=entry.relevance,
                    order_weight=entry.order_weight,
                )
                for entry in calculated.contributions
            ],
            leadership_level=sig.leadership_level(facts, as_of),
            band=calculated.band,
            visible=True,
            verified=views.has_filter_evidence(facts, ranks),
            public=_public(public),
            version=c.FSP_SIGNAL_VERSION,
        )
    return result


def get_skill_evidence(
    db: Session, subjects: Sequence[FspSubject], *, as_of: date
) -> dict[UUID, list[FspSkillEvidence]]:
    """Навыки, подтверждённые фактами ФСП: только у видимых кандидатов (Арх. 7.6; приложение D, §5.7, §6.6)."""
    data = views.load(db, [subject.user_id for subject in subjects])
    result: dict[UUID, list[FspSkillEvidence]] = {}
    for subject in subjects:
        item = data[subject.user_id]
        result[subject.user_id] = []
        if not sig.is_visible(linked=item.linked, show_summary=subject.show_summary):
            continue
        rows = {row.id: row for row in item.achievements}
        for evidence in sig.skill_evidence(item.facts(), as_of, catalog.is_skill):
            row = rows[evidence.fact_id]
            if evidence.source == "discipline":
                public = f"{c.EVIDENCE_PUBLIC_PREFIX} · {views.discipline_label(row.discipline_code)}"
                full = f"{row.competition_title} · {views.row_place_label(row)}"
            else:
                public = c.EVIDENCE_ROLE_PUBLIC
                full = f"{views.role_label(row).capitalize()} · {row.competition_title}"
            result[subject.user_id].append(
                FspSkillEvidence(
                    skill_code=evidence.skill_code,
                    source=evidence.source,
                    fact_id=evidence.fact_id,
                    confirmed_at=evidence.confirmed_at,
                    detail_public=public,
                    detail_full=full,
                )
            )
    return result


def verified_user_ids(db: Session, subjects: Sequence[FspSubject]) -> set[UUID]:
    """Кандидаты, проходящие фильтр «есть подтверждённые достижения ФСП»: видимые, с зачтённым результатом
    спортсмена либо разрядом (поправка R3-tz-compliance-8: одна роль тренера фильтр не проходит)."""
    data = views.load(db, [subject.user_id for subject in subjects])
    return {
        subject.user_id
        for subject in subjects
        if sig.is_visible(linked=data[subject.user_id].linked, show_summary=subject.show_summary)
        and views.has_filter_evidence(data[subject.user_id].facts(), data[subject.user_id].ranks())
    }


def is_visible(db: Session, user_id: UUID, *, show_summary: bool) -> bool:
    """`visible = linked and show_summary` (Арх. 7.7)."""
    linked = db.scalar(select(ExternalIdentity.id).where(ExternalIdentity.user_id == user_id)) is not None
    return sig.is_visible(linked=linked, show_summary=show_summary)


def employer_block(
    db: Session,
    user_id: UUID,
    *,
    specialization: str | None,
    show_summary: bool,
    reveal_details: bool,
    disclosed: bool,
    as_of: date,
) -> FspEmployerBlock:
    """Блок ФСП в карточке кандидата: `none` | `summary` | `detailed` (Арх. 7.7)."""
    data = views.load(db, [user_id])[user_id]
    return views.employer_block(
        db,
        data,
        specialization=specialization,
        show_summary=show_summary,
        reveal_details=reveal_details,
        disclosed=disclosed,
        as_of=as_of,
    )


def render_evidence(
    db: Session, user_id: UUID, fact_ids: Collection[UUID], *, show_summary: bool, reveal_details: bool, disclosed: bool
) -> dict[UUID, str | None]:
    """Текст довода «Достижение ФСП: …» по сохранённому `fact_id` (приложение D, §6.6).

    В версии подборки хранятся только идентификатор факта и обобщённый текст; подробный строится здесь при
    чтении. После отвязки или скрытия достижений — `None`, и довод не выводится.
    """
    result: dict[UUID, str | None] = dict.fromkeys(fact_ids)
    data = views.load(db, [user_id])[user_id]
    if not sig.is_visible(linked=data.linked, show_summary=show_summary):
        return result
    rows = {row.id: row for row in data.achievements}
    as_of = clock.today(db)
    k_anon = get_settings().fsp_k_anon
    detailed = disclosed and reveal_details
    for fact_id in result:
        row = rows.get(fact_id)
        if row is None:
            continue
        if row.counted and row.member_role == sig.ROLE_ATHLETE:
            if detailed:
                result[fact_id] = f"Достижение ФСП: {row.competition_title}, {views.row_place_label(row)}"
            else:
                summary = sig.public_summary([views.to_fact(row)], [], None, as_of, k_anon)
                result[fact_id] = f"Достижение ФСП: {summary.headline}" if summary else None
        elif row.verified:
            result[fact_id] = (
                f"{views.role_label(row).capitalize()} · {row.competition_title}"
                if detailed
                else c.EVIDENCE_ROLE_PUBLIC
            )
    return result


def pdf_block(
    db: Session,
    user_id: UUID,
    *,
    audience: Literal["self", "employer"],
    specialization: str | None,
    show_summary: bool,
    reveal_details: bool,
    as_of: date,
) -> FspEmployerBlock:
    """Блок ФСП для PDF-профиля: кандидату — подробный; работодателю (только после раскрытия) — по правилам 7.7."""
    data = views.load(db, [user_id])[user_id]
    if audience == "self":
        show_summary = reveal_details = True
    return views.employer_block(
        db,
        data,
        specialization=specialization,
        show_summary=show_summary,
        reveal_details=reveal_details,
        disclosed=True,
        as_of=as_of,
    )


def unlink(db: Session, user_id: UUID, *, reason: UnlinkReason) -> None:
    """Отвязка: сведения удаляются в одной транзакции, разрешение в реестре снимается после фиксации."""
    linking.unlink(db, user_id, reason=reason)


def seed_link(db: Session, user_id: UUID, fsp_id: str) -> None:
    """Привязать синтетического кандидата к спортсмену демо-реестра — только для сида (Арх. 7.5, триггер `seed`)."""
    linking.seed_link(db, user_id, fsp_id)


def demo_persona_id(key: str) -> str:
    """`fsp_id` типового персонажа демо-реестра (`anna`, `olga`, `mikhail`, …); только в режиме `mock`."""
    return _mock_gateway().persona_id(key)


def demo_athlete_pool(*, with_history: bool) -> list[DemoAthlete]:
    """Свободные взрослые спортсмены демо-реестра: с зачтённым результатом либо без участий (только режим `mock`).

    Для сида: он не импортирует `app.fsp_mock`, а берёт пул здесь и раздаёт кандидатам через `seed_link`.
    """
    return [
        DemoAthlete(fsp_id=fsp_id, latent_skill=latent)
        for fsp_id, latent in _mock_gateway().athlete_pool(with_history=with_history)
    ]


def _mock_gateway() -> MockFspGateway:
    gateway = factory.get_fsp_gateway()
    if not hasattr(gateway, "athlete_pool"):
        raise RuntimeError("демо-реестр доступен только при FSP_MODE=mock")
    return gateway  # type: ignore[return-value]


def demo_reset(db: Session, user_ids: Collection[UUID]) -> None:
    linking.demo_reset(db, list(user_ids))


def on_user_delete(db: Session, user_id: UUID) -> None:
    """Обработчик `USER_CLEANUP` (Арх. 2.6): удаляет сведения до каскада, разрешение снимает после фиксации."""
    linking.on_user_delete(db, user_id)


def resync_batch(
    db: Session, *, older_than_hours: float, limit: int, pause_s: float = c.RESYNC_PAUSE_SECONDS
) -> Counter[str]:
    """Обновить снимки старше `older_than_hours` (триггер `cli`): последовательно, с паузой. Исходы — счётчиком.

    Сначала идут привязки без снимка, затем самые старые. Ошибка одного пользователя остальных не останавливает.
    """
    now = clock.real_now()
    threshold = now - timedelta(hours=older_than_hours)
    rows = db.execute(
        select(ExternalIdentity.user_id, FspSnapshot.checked_at)
        .select_from(ExternalIdentity)
        .outerjoin(FspSnapshot, (FspSnapshot.identity_id == ExternalIdentity.id) & FspSnapshot.is_current.is_(True))
        .where((FspSnapshot.checked_at.is_(None)) | (FspSnapshot.checked_at < threshold))
        .order_by(FspSnapshot.checked_at.asc().nulls_first(), ExternalIdentity.user_id)
        .limit(limit)
    ).all()
    outcomes: Counter[str] = Counter()
    for user_id, _ in rows:
        try:
            outcomes[sync.run_sync(db, user_id, "cli").outcome] += 1
        except Exception as exc:
            db.rollback()
            outcomes[f"error:{type(exc).__name__}"] += 1
        if pause_s:
            time.sleep(pause_s)
    return outcomes
