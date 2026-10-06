"""Проекции сведений ФСП: загрузка, подписи, блок для работодателя (Арх. 7.7, 7.8; приложение D, §6, §10.2).

Все подписи (`*_label`, `headline`, `note`) формирует сервер из словарей `constants.py`: интерфейс их не собирает.
Загрузка пакетная: не больше трёх запросов независимо от числа кандидатов (привязки, факты, разряды); остальное —
чистые функции `signal.py`. Сюда не приходит ничего, чего кандидат не разрешил показать: решение о режиме принимает
`signal.display_mode`, а настройки приватности передаёт вызывающий.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.fsp import constants as c
from app.modules.fsp import signal as sig
from app.modules.fsp.dto import (
    FspAchievementView,
    FspCredentialView,
    FspEmployerBlock,
    FspLeadership,
    FspPublicSummary,
    FspSource,
)
from app.modules.fsp.models import ExternalIdentity, FspAchievement, FspCredential, FspSnapshot, FspSyncAttempt


@dataclass(slots=True)
class UserData:
    """Что платформа знает о ФСП одного пользователя."""

    user_id: UUID
    identity: ExternalIdentity | None = None
    achievements: list[FspAchievement] = field(default_factory=list)
    credentials: list[FspCredential] = field(default_factory=list)

    @property
    def linked(self) -> bool:
        return self.identity is not None

    def facts(self) -> list[sig.Fact]:
        return [to_fact(row) for row in self.achievements]

    def ranks(self) -> list[sig.Rank]:
        return [to_rank(row) for row in self.credentials if row.kind == "rank"]


def to_fact(row: FspAchievement) -> sig.Fact:
    return sig.Fact(
        id=row.id,
        entry_id=row.entry_id,
        discipline_code=row.discipline_code,
        level=row.level,
        stage=row.stage,
        tier=row.tier,
        participation=row.participation,
        member_role=row.member_role,
        is_captain=row.is_captain,
        result_bucket=row.result_bucket,
        event_date=row.event_date,
        verified=row.verified,
        counted=row.counted,
        base_points=float(row.base_points),
        anon_period=row.anon_period,
        anon_k_a=row.anon_k_a,
        anon_k_b=row.anon_k_b,
    )


def to_rank(row: FspCredential) -> sig.Rank:
    return sig.Rank(
        id=row.id,
        code=row.code,
        discipline_code=row.discipline_code,
        assigned_on=row.assigned_on,
        valid_until=row.valid_until,
        revoked_on=row.revoked_on,
    )


def load(db: Session, user_ids: Collection[UUID], *, only_evidence: bool = True) -> dict[UUID, UserData]:
    """Привязки, факты и разряды пачкой: три запроса независимо от числа пользователей.

    `only_evidence` — только факты, влияющие на сигнал и показ (подтверждённые или зачтённые): для подбора
    остальное не нужно. Экран кандидата просит все записи.
    """
    ids = set(user_ids)
    data = {user_id: UserData(user_id) for user_id in ids}
    if not ids:
        return data
    for identity in db.scalars(select(ExternalIdentity).where(ExternalIdentity.user_id.in_(ids))):
        data[identity.user_id].identity = identity
    linked = {user_id for user_id, item in data.items() if item.linked}
    if not linked:
        return data
    statement = select(FspAchievement).where(FspAchievement.user_id.in_(linked))
    if only_evidence:
        statement = statement.where(or_(FspAchievement.verified.is_(True), FspAchievement.counted.is_(True)))
    for row in db.scalars(statement.order_by(FspAchievement.event_date.desc().nulls_last(), FspAchievement.entry_id)):
        data[row.user_id].achievements.append(row)
    for credential in db.scalars(
        select(FspCredential).where(FspCredential.user_id.in_(linked), FspCredential.kind == "rank")
    ):
        data[credential.user_id].credentials.append(credential)
    return data


def has_filter_evidence(facts: Iterable[sig.Fact], ranks: Iterable[sig.Rank]) -> bool:
    """Подтверждение для фильтра работодателя и довода «достижение ФСП» (поправка R3-tz-compliance-8).

    Зачтённый результат роли `athlete` либо разряд без отзыва. Роль тренера даёт показ и подтверждение навыка
    наставничества, но не «достижение»: кандидат с нулевым сигналом не должен проходить фильтр «есть достижения».
    """
    return any(f.counted and f.member_role == sig.ROLE_ATHLETE for f in facts) or any(
        rank.revoked_on is None for rank in ranks
    )


# ---------------------------------------------------------------------------------------------------------------------
# Подписи
# ---------------------------------------------------------------------------------------------------------------------


def place_label(place: int | None, place_to: int | None, field_size: int | None) -> str:
    """«2 место из 16» | «2–3 место из 10» | «участие»."""
    if place is None:
        return "участие"
    span = f"{place}–{place_to}" if place_to is not None and place_to != place else f"{place}"
    return f"{span} место из {field_size}" if field_size else f"{span} место"


def row_place_label(row: FspAchievement) -> str:
    return place_label(row.place, row.place_to, row.field_size)


def discipline_label(code: str) -> str:
    return c.DISCIPLINE_LABEL.get(code, c.DISCIPLINE_LABEL[c.DISCIPLINE_OTHER])


def _number(value: Decimal | float) -> str:
    text = f"{float(value):.1f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def score_label(row: FspAchievement) -> str | None:
    """«решено 9 из 12» | «87,5 из 100 баллов»."""
    if row.solved is not None and row.problems_total:
        return f"решено {row.solved} из {row.problems_total}"
    if row.score is not None and row.score_max is not None:
        return f"{_number(row.score)} из {_number(row.score_max)} баллов"
    return None


def role_label(row: FspAchievement) -> str:
    if row.member_role == sig.ROLE_ATHLETE and row.is_captain and row.participation == sig.TEAM:
        return c.ROLE_LABEL_CAPTAIN
    return c.ROLE_LABEL.get(row.member_role, row.member_role)


def achievement_view(row: FspAchievement, as_of: date, *, for_candidate: bool) -> FspAchievementView:
    """Достижение для кандидата (с причиной «не зачтено») либо для работодателя (без неё)."""
    counted = row.counted
    uncounted = row.uncounted_reason if for_candidate and not counted else None
    return FspAchievementView(
        id=row.id,
        competition_title=row.competition_title,
        discipline_code=row.discipline_code,
        discipline_label=c.DISCIPLINE_LABEL.get(row.discipline_code, c.DISCIPLINE_LABEL[c.DISCIPLINE_OTHER]),
        level=row.level,
        level_label=c.LEVEL_LABEL.get(row.level, "уровень не распознан"),
        stage_label=c.STAGE_LABEL.get(row.stage),
        date_end=row.event_date,
        city=row.city,
        format_label=c.FORMAT_LABEL.get(row.format),
        member_role=row.member_role,
        role_label=role_label(row),
        is_captain=row.is_captain,
        team_name=row.team_name,
        team_size=row.team_size,
        place=row.place,
        place_to=row.place_to,
        field_size=row.field_size,
        place_label=place_label(row.place, row.place_to, row.field_size),
        score_label=score_label(row),
        counted=counted,
        uncounted_reason=uncounted,
        uncounted_label=c.UNCOUNTED_LABEL.get(uncounted) if uncounted else None,
        recency_percent=round(100 * sig.decay(row.event_date, as_of)) if counted and row.event_date else None,
        norm=None,
        protocol_url=row.protocol_url,
    )


def credential_view(row: FspCredential, as_of: date) -> FspCredentialView:
    active = row.revoked_on is None and (row.valid_until is None or row.valid_until >= as_of)
    if row.valid_until is None:
        status = "бессрочно"
    elif active:
        status = f"действует до {row.valid_until:%d.%m.%Y}"
    else:
        status = f"срок действия истёк {row.valid_until:%d.%m.%Y}"
    return FspCredentialView(
        id=row.id,
        kind="rank",
        code=row.code,
        label=c.RANK_LABEL.get(row.code, row.code),
        discipline_label=c.DISCIPLINE_LABEL.get(row.discipline_code) if row.discipline_code else None,
        assigned_on=row.assigned_on,
        valid_until=row.valid_until,
        active=active,
        status_label=status,
    )


def _plural_in(count: int) -> str:
    """«в 1 соревновании», «в 2 соревнованиях»."""
    return f"в {count} соревновании" if count % 10 == 1 and count % 100 != 11 else f"в {count} соревнованиях"


def leadership(facts: list[sig.Fact], as_of: date) -> FspLeadership | None:
    level = sig.leadership_level(facts, as_of)
    if level == "none":
        return None
    parts = []
    captain = len(sig.captain_facts(facts, as_of))
    coach = len(sig.coach_facts(facts, as_of))
    if captain:
        parts.append(f"капитан {_plural_in(captain)}")
    if coach:
        parts.append(f"тренер команды {_plural_in(coach)}")
    return FspLeadership(level=level, label="Опыт ведения команды: " + ", ".join(parts))


def source_of(db: Session, identity: ExternalIdentity | None) -> FspSource | None:
    if identity is None:
        return None
    snapshot = db.scalar(
        select(FspSnapshot).where(FspSnapshot.identity_id == identity.id, FspSnapshot.is_current.is_(True))
    )
    if snapshot is None:
        return None
    label = c.SOURCE_LABEL.get(identity.provider_mode, c.SOURCE_LABEL["keycloak"])
    return FspSource(label=label, checked_at=snapshot.checked_at)


# ---------------------------------------------------------------------------------------------------------------------
# Блок для работодателя
# ---------------------------------------------------------------------------------------------------------------------


def neutral_block() -> FspEmployerBlock:
    """Нейтральный блок: одинаков побайтно для «не привязал», «истории нет», «скрыл» и «реестр недоступен»."""
    return FspEmployerBlock(mode="none", neutral_text=c.NEUTRAL_TEXT)


def employer_block(
    db: Session,
    data: UserData,
    *,
    specialization: str | None,
    show_summary: bool,
    reveal_details: bool,
    disclosed: bool,
    as_of: date,
) -> FspEmployerBlock:
    """Блок ФСП в карточке и PDF (Арх. 7.7). Режим выбирает `signal.display_mode`; данные — только своего режима."""
    facts, ranks = data.facts(), data.ranks()
    mode = sig.display_mode(
        linked=data.linked,
        has_verified=sig.has_verified_facts(facts, ranks),
        show_summary=show_summary,
        reveal_details=reveal_details,
        disclosed=disclosed,
    )
    if mode == "none":
        return neutral_block()
    summary = sig.public_summary(facts, ranks, specialization, as_of, get_settings().fsp_k_anon)
    public = (
        FspPublicSummary(
            level=summary.level,
            headline=summary.headline,
            short=summary.short,
            more=summary.more,
            shortened=summary.shortened,
        )
        if summary is not None
        else None
    )
    source = source_of(db, data.identity)
    if mode == "summary":
        note = c.NOTE_BEFORE_DISCLOSURE if not disclosed else c.NOTE_SUMMARY_ONLY
        return FspEmployerBlock(mode="summary", summary=public, note=note, source=source)
    return FspEmployerBlock(
        mode="detailed",
        summary=public,
        achievements=detailed_achievements(data, as_of, for_candidate=False),
        credentials=[credential_view(row, as_of) for row in _visible_ranks(data)],
        leadership=leadership(facts, as_of),
        source=source,
    )


def _visible_ranks(data: UserData) -> list[FspCredential]:
    return sorted(
        (row for row in data.credentials if row.kind == "rank" and row.revoked_on is None),
        key=lambda row: (row.assigned_on or date.min, row.code),
        reverse=True,
    )


def detailed_achievements(data: UserData, as_of: date, *, for_candidate: bool) -> list[FspAchievementView]:
    """Результаты по убыванию даты (приложение D, §6.3).

    Работодателю — зачтённые, вытесненные в серии и подтверждённые роли тренера; кандидату — все записи
    (с причиной «не зачтено»). Незачтённые записи работодателю не показываются никогда.
    """
    rows = []
    for row in data.achievements:
        shown = (
            row.counted
            or row.uncounted_reason == "superseded_in_series"
            or (row.verified and row.member_role == "coach")
        )
        if for_candidate or shown:
            rows.append(row)
    rows.sort(key=lambda row: (row.event_date or date.min, row.entry_id), reverse=True)
    return [achievement_view(row, as_of, for_candidate=for_candidate) for row in rows]


# ---------------------------------------------------------------------------------------------------------------------
# Состояние для экрана
# ---------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class History:
    status: str
    reason: str | None = None


def last_attempt(db: Session, user_id: UUID) -> FspSyncAttempt | None:
    return db.scalar(
        select(FspSyncAttempt)
        .where(FspSyncAttempt.user_id == user_id, FspSyncAttempt.identity_id.is_not(None))
        .order_by(FspSyncAttempt.started_at.desc(), FspSyncAttempt.id)
        .limit(1)
    )


def history_of(
    data: UserData, snapshot: FspSnapshot | None, attempt: FspSyncAttempt | None, now: datetime
) -> History | None:
    """`history_status` и `no_history_reason` (приложение D, §4.5); `None` — привязки нет."""
    if not data.linked:
        return None
    if (
        attempt is not None
        and attempt.finished_at is None
        and now - attempt.started_at < timedelta(seconds=c.SYNC_STUCK_SECONDS)
    ):
        return History("sync_pending")
    if snapshot is None:
        return History("sync_failed")
    facts, ranks = data.facts(), data.ranks()
    if sig.has_verified_facts(facts, ranks):
        return History("has_history")
    if not snapshot.athlete_registered:
        return History("no_history", "athlete_not_found")
    if not any(row.result_status != "pending" for row in data.achievements):
        return History("no_history", "no_results")
    return History("no_history", "no_counted_results")


def group_by_user(rows: Iterable[FspAchievement]) -> dict[UUID, list[FspAchievement]]:
    grouped: dict[UUID, list[FspAchievement]] = defaultdict(list)
    for row in rows:
        grouped[row.user_id].append(row)
    return grouped
