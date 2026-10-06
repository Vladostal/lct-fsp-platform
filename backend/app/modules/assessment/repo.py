"""Чтение банка и общих строк модуля из базы; публикация доступности пар (Арх. 5.2).

Здесь нет правил: функции превращают строки таблиц в значения, которые понимает чистое ядро `engine/`.
"""

from __future__ import annotations

import logging
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.assessment import blueprints
from app.modules.assessment.config import get_config
from app.modules.assessment.engine.model import Response
from app.modules.assessment.models import (
    AssessmentProfile,
    CategoryRow,
    FamilyLevelRow,
    FamilyRow,
    SessionItemRow,
    SessionRow,
    VariantRow,
)
from app.modules.catalog import service as catalog
from app.shared.enums import FamilyStatus, ItemStatus, VariantStatus

log = logging.getLogger("app.assessment")

#: Статусы заданий, ответы на которые учитываются в оценке (Арх. 5.5): отвечено, пропущено, показано без ответа.
COUNTED: tuple[str, ...] = (ItemStatus.ANSWERED.value, ItemStatus.SKIPPED.value, ItemStatus.UNREACHED.value)
#: Семейства, из которых собираются формы: `suspect` продолжает выдаваться, `quarantined` и `retired` — нет.
SERVED_STATUSES: tuple[str, ...] = (FamilyStatus.ACTIVE.value, FamilyStatus.SUSPECT.value)


@dataclass(frozen=True)
class BankLevel:
    level: int
    b: float
    time_budget_s: int


@dataclass(frozen=True)
class BankFamily:
    """Семейство банка в памяти: то, что нужно планам (`blueprints.pool_family`) и правилу навыков."""

    id: str
    title: str
    group: str
    kind: str
    specializations: tuple[str, ...]
    skill_tags: tuple[str, ...]
    levels: tuple[BankLevel, ...]
    status: str = FamilyStatus.ACTIVE.value

    def b(self, level: int) -> float:
        return next(item.b for item in self.levels if item.level == level)


def load_families(db: Session, statuses: Collection[str] | None = SERVED_STATUSES) -> list[BankFamily]:
    """Семейства банка с уровнями; по умолчанию — только те, что выдаются в сессиях."""
    stmt = select(FamilyRow).order_by(FamilyRow.id)
    if statuses is not None:
        stmt = stmt.where(FamilyRow.status.in_(list(statuses)))
    rows = list(db.scalars(stmt))
    levels: dict[str, list[BankLevel]] = {}
    for level in db.scalars(select(FamilyLevelRow).order_by(FamilyLevelRow.family_id, FamilyLevelRow.level)):
        levels.setdefault(level.family_id, []).append(BankLevel(level.level, float(level.b), level.time_budget_s))
    return [
        BankFamily(
            id=row.id,
            title=row.title,
            group=row.group_code,
            kind=row.kind,
            specializations=tuple(row.specializations),
            skill_tags=tuple(row.skill_tags),
            levels=tuple(levels.get(row.id, ())),
            status=row.status,
        )
        for row in rows
        if levels.get(row.id)
    ]


def available_pairs(db: Session) -> set[tuple[str, str]]:
    """Доступные пары (специализация, грейд) по активным семействам банка; `DISABLED_SPECIALIZATIONS` выключает."""
    families = load_families(db)
    return blueprints.available_pairs(families, disabled=get_settings().disabled_specializations)


def refresh_availability(db: Session) -> set[tuple[str, str]]:
    """Пересчитать доступность пар и опубликовать её в каталог (Арх. 5.2). Вызывается при старте и после смены банка."""
    pairs = available_pairs(db)
    catalog.publish_availability(pairs)
    log.info("доступные пары теста: %s", ", ".join(sorted(f"{s}:{g}" for s, g in pairs)) or "нет")
    return pairs


def profile(db: Session, candidate_id: UUID) -> AssessmentProfile | None:
    return db.get(AssessmentProfile, candidate_id)


def category(db: Session, candidate_id: UUID) -> CategoryRow | None:
    return db.get(CategoryRow, candidate_id)


def sessions(db: Session, candidate_id: UUID) -> list[SessionRow]:
    """Все сессии аккаунта от старых к новым."""
    stmt = select(SessionRow).where(SessionRow.candidate_id == candidate_id).order_by(SessionRow.started_at)
    return list(db.scalars(stmt))


def window_items(db: Session, candidate_id: UUID, specialization: str, now: datetime) -> list[SessionItemRow]:
    """Учтённые ответы кандидата в специализации за `EVIDENCE_WINDOW_DAYS`, включая текущую сессию (Арх. 5.5)."""
    since = now - timedelta(days=get_config().evidence_window_days)
    stmt = (
        select(SessionItemRow)
        .join(SessionRow, SessionRow.id == SessionItemRow.session_id)
        .where(
            SessionRow.candidate_id == candidate_id,
            SessionRow.specialization_code == specialization,
            SessionRow.started_at >= since,
            SessionItemRow.status.in_(COUNTED),
        )
        .order_by(SessionRow.started_at, SessionItemRow.position)
    )
    return list(db.scalars(stmt))


def responses(items: Collection[SessionItemRow]) -> list[Response]:
    return [Response(b=item.b_used, c=item.c_used, score=int(item.score or 0), a=item.a_used) for item in items]


def seen_families(db: Session, candidate_id: UUID, specialization: str, now: datetime) -> set[str]:
    """Семейства, которые кандидат видел в этой специализации за окно: выбираются в последнюю очередь."""
    since = now - timedelta(days=get_config().evidence_window_days)
    stmt = (
        select(SessionItemRow.family_id)
        .join(SessionRow, SessionRow.id == SessionItemRow.session_id)
        .where(
            SessionRow.candidate_id == candidate_id,
            SessionRow.specialization_code == specialization,
            SessionRow.started_at >= since,
            SessionItemRow.status != ItemStatus.NOT_SHOWN.value,
        )
        .distinct()
    )
    return set(db.scalars(stmt))


def seen_variants_subquery(candidate_id: UUID):  # type: ignore[no-untyped-def]
    """Варианты, когда-либо выданные кандидату: такой вариант ему не выдаётся никогда (Арх. 5.3)."""
    return (
        select(SessionItemRow.variant_id)
        .join(SessionRow, SessionRow.id == SessionItemRow.session_id)
        .where(SessionRow.candidate_id == candidate_id)
    )


def blocked_levels(db: Session, candidate_id: UUID) -> set[tuple[str, int]]:
    """Пары (семейство, уровень), у которых не осталось активного варианта, не показанного этому кандидату."""
    active = {
        (family_id, level): count
        for family_id, level, count in db.execute(
            select(VariantRow.family_id, VariantRow.level, func.count())
            .where(VariantRow.status == VariantStatus.ACTIVE.value)
            .group_by(VariantRow.family_id, VariantRow.level)
        )
    }
    seen = {
        (family_id, level): count
        for family_id, level, count in db.execute(
            select(VariantRow.family_id, VariantRow.level, func.count(func.distinct(VariantRow.id)))
            .where(
                VariantRow.status == VariantStatus.ACTIVE.value,
                VariantRow.id.in_(seen_variants_subquery(candidate_id)),
            )
            .group_by(VariantRow.family_id, VariantRow.level)
        )
    }
    known = db.execute(select(FamilyLevelRow.family_id, FamilyLevelRow.level)).all()
    return {(f, lv) for f, lv in known if active.get((f, lv), 0) - seen.get((f, lv), 0) <= 0}
