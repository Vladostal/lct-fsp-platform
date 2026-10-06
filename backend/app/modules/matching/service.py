"""Фасад модуля `matching` (Арх. 2.5). Другие модули импортируют только этот файл и `dto.py`.

Модуль `contact` стоит выше: подбор о приглашениях не знает и состояние пары не читает (Арх. 15.1, № 1).
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import not_found
from app.modules.identity import service as identity
from app.modules.matching import cards, exposure, needs, snapshots
from app.modules.matching import constants as C
from app.modules.matching.dto import (
    ExposureStats,
    InvitationExplain,
    NeedData,
    NeedRefDTO,
    RelaxationHint,
    ShortlistItemView,
    ShortlistQuery,
    ShortlistRefinement,
)
from app.modules.matching.models import Need, ShortlistItem, ShortlistSnapshot
from app.shared.enums import NeedStatus


def need_ref(db: Session, employer_id: UUID, need_id: UUID, snapshot_id: UUID | None = None) -> NeedRefDTO:
    """Потребность работодателя; чужая или несуществующая (как и чужая версия) — 404 `not_found`."""
    need = needs.get_owned(db, employer_id, need_id)
    if snapshot_id is not None:
        snapshot = db.get(ShortlistSnapshot, snapshot_id)
        if snapshot is None or snapshot.need_id != need.id:
            raise not_found()
    return needs.to_ref(need, snapshot_id)


def explain_for_invitation(
    db: Session, employer_id: UUID, candidate_id: UUID, need_id: UUID | None, snapshot_id: UUID | None, now: datetime
) -> InvitationExplain:
    """«Почему вас пригласили» (публичная проекция, Арх. 4.9), полоса совпадения и версия оценщика."""
    return cards.explain_for_invitation(db, employer_id, candidate_id, need_id, snapshot_id, now)


def relaxation_hints(
    db: Session, employer_id: UUID, need_id: UUID, kinds: Collection[str], now: datetime
) -> list[RelaxationHint]:
    """Подсказки заданных видов для запроса последней версии потребности (Арх. 6.12)."""
    return snapshots.relaxation_hints(db, employer_id, need_id, kinds, now)


def exposure_stats(db: Session, candidate_id: UUID, since: datetime, now: datetime) -> ExposureStats:
    """Показы кандидата для воронки (Арх. 6.13)."""
    return exposure.stats(db, candidate_id, since, now)


def demo_need_for(db: Session, category_code: str) -> NeedRefDTO | None:
    """Действующая потребность демо-компании сида под категорию — для демо-приглашения (Арх. 4.14).

    Потребности именованных аккаунтов сценария (`orbita`) не возвращаются: демо-приглашение живому кандидату
    отправляет одна из демо-компаний сида.
    """
    specialization, _, grade = category_code.partition(":")
    statement = (
        select(Need)
        .where(
            Need.is_demo.is_(True),
            Need.status == NeedStatus.ACTIVE.value,
            Need.specialization_code == specialization,
            Need.grade_code == grade,
        )
        .order_by(Need.created_at, Need.id)
    )
    scenario = identity.demo_user_ids(db, C.DEMO_SCENARIO_EMPLOYER_KEYS)
    if scenario:
        statement = statement.where(Need.employer_id.not_in(scenario))
    need = db.scalar(statement.limit(1))
    return needs.to_ref(need, need.latest_snapshot_id) if need else None


def needs_with_candidate(db: Session, candidate_id: UUID) -> list[NeedRefDTO]:
    """Действующие потребности, в версиях которых есть кандидат; `snapshot_id` — самая поздняя такая версия."""
    rows = db.execute(
        select(Need, ShortlistSnapshot.id)
        .join(ShortlistSnapshot, ShortlistSnapshot.need_id == Need.id)
        .join(ShortlistItem, ShortlistItem.snapshot_id == ShortlistSnapshot.id)
        .where(ShortlistItem.candidate_id == candidate_id, Need.status == NeedStatus.ACTIVE.value)
        .order_by(Need.created_at, Need.id, ShortlistSnapshot.version_no.desc())
    ).all()
    found: dict[UUID, NeedRefDTO] = {}
    for need, snapshot_id in rows:
        found.setdefault(need.id, needs.to_ref(need, snapshot_id))
    return list(found.values())


def score_for_query(
    db: Session, employer_id: UUID, query: ShortlistQuery, candidate_ids: Collection[UUID], now: datetime
) -> dict[UUID, ShortlistItemView]:
    """Оценка названных кандидатов по запросу без создания версии (отклики на вакансию)."""
    return cards.score_for_query(db, employer_id, query, candidate_ids, now)


def candidate_export(db: Session, employer_id: UUID, candidate_id: UUID, now: datetime) -> dict[str, Any]:
    """Данные кандидата для выгрузки раскрытой пары; пара не раскрыта — 403 `not_disclosed`."""
    return cards.candidate_export(db, employer_id, candidate_id, now)


# --- функции записи: их вызывают роутер модуля, сид и demo; другие модули — нет -------------------------------------


def create_need(db: Session, employer_id: UUID, data: NeedData, now: datetime, *, is_demo: bool = False) -> UUID:
    """Создать потребность; правила полей те же, что у `POST /employer/needs` (Арх. 6.14)."""
    return needs.create(db, employer_id, data, now, is_demo=is_demo).id


def create_snapshot(
    db: Session,
    employer_id: UUID,
    need_id: UUID,
    now: datetime,
    *,
    parent_id: UUID | None = None,
    refinement: ShortlistRefinement | None = None,
) -> UUID:
    """Создать версию подборки (Арх. 6.11); повтор того же запроса в пределах 10 минут возвращает прежнюю."""
    snapshot, _ = snapshots.create(db, employer_id, need_id, now, parent_id=parent_id, refinement=refinement)
    return snapshot.id
