"""Служебные действия над банком (Арх. 5.8, 9.5): состояние семейств, смена статуса, поиск утечки по тексту."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from rapidfuzz import fuzz
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.errors import ApiException, not_found
from app.modules.assessment import repo
from app.modules.assessment.config import get_config
from app.modules.assessment.models import (
    BlueprintCounter,
    ExposureRow,
    FamilyLevelRow,
    FamilyRow,
    SessionItemRow,
    SessionRow,
    VariantRow,
)
from app.modules.assessment.schemas import (
    BankHealthView,
    FamilyHealth,
    FamilyStatusView,
    LeakLookupResult,
    LeakMatch,
)
from app.modules.catalog import service as catalog
from app.shared.enums import FamilyStatus, VariantStatus

#: Подсветка экспозиции (Арх. 5.8).
EXPOSURE_HIGH = 0.60
#: Сходство текста, с которого вариант считается найденным.
FUZZY_THRESHOLD = 85.0
MAX_MATCHES = 10

#: Разрешённые переходы статуса семейства; из `retired` возврата нет.
TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"active", "retired"}),
    "active": frozenset({"suspect", "quarantined", "retired"}),
    "suspect": frozenset({"active", "quarantined", "retired"}),
    "quarantined": frozenset({"active", "retired"}),
    "retired": frozenset(),
}

_WS = re.compile(r"\s+")


def bank_health(db: Session) -> BankHealthView:
    """Состояние семейств: статус, экспозиция, ответы, запас вариантов (мониторинг сдвига — P2)."""
    sessions_by_pair = {
        (spec, grade): count
        for spec, grade, count in db.execute(
            select(BlueprintCounter.specialization_code, BlueprintCounter.grade_code, BlueprintCounter.sessions_count)
        )
    }
    exposure: dict[str, float] = {}
    for served in db.scalars(select(ExposureRow)):
        total = sessions_by_pair.get((served.specialization_code, served.grade_code), 0)
        if total:
            exposure[served.family_id] = max(exposure.get(served.family_id, 0.0), served.served_count / total)
    variants: dict[str, dict[int, tuple[int, int]]] = {}
    for family_id, level, total, unserved in db.execute(
        select(
            VariantRow.family_id,
            VariantRow.level,
            func.count(),
            func.sum(case((VariantRow.served_count == 0, 1), else_=0)),
        )
        .where(VariantRow.status == VariantStatus.ACTIVE.value)
        .group_by(VariantRow.family_id, VariantRow.level)
    ):
        variants.setdefault(family_id, {})[level] = (int(total), int(unserved or 0))
    answers = {
        family_id: (int(total), int(correct or 0))
        for family_id, total, correct in db.execute(
            select(SessionItemRow.family_id, func.count(), func.sum(SessionItemRow.score))
            .where(SessionItemRow.status.in_(repo.COUNTED))
            .group_by(SessionItemRow.family_id)
        )
    }
    levels: dict[str, int] = {
        family_id: int(count)
        for family_id, count in db.execute(
            select(FamilyLevelRow.family_id, func.count()).group_by(FamilyLevelRow.family_id)
        )
    }
    families = []
    for row in db.scalars(select(FamilyRow).order_by(FamilyRow.id)):
        per_level = variants.get(row.id, {})
        unserved = min((u for _, u in per_level.values()), default=0)
        total_answers, correct = answers.get(row.id, (0, 0))
        share = exposure.get(row.id, 0.0)
        families.append(
            FamilyHealth(
                id=row.id,
                title=row.title,
                group_code=row.group_code,
                status=row.status,
                status_reason=row.status_reason,
                priority=row.priority,
                levels=levels.get(row.id, 0),
                variants_active=sum(t for t, _ in per_level.values()),
                variants_unserved_min=unserved,
                variants_low=unserved == 0,
                exposure_max=round(share, 3),
                exposure_high=share > EXPOSURE_HIGH,
                answers=total_answers,
                correct_share=round(correct / total_answers, 3) if total_answers else None,
            )
        )
    return BankHealthView(
        bank_version=get_config().bank_version,
        families=families,
        available_categories=catalog.get_catalog().available_categories,
    )


def set_family_status(db: Session, family_id: str, status: str, reason: str, now: datetime) -> FamilyStatusView:
    """Карантин, возврат, вывод семейства из банка; после смены статуса доступность пар пересчитывается (Арх. 5.2)."""
    row = db.get(FamilyRow, family_id)
    if row is None:
        raise not_found()
    if status not in TRANSITIONS.get(row.status, frozenset()) or status not in {s.value for s in FamilyStatus}:
        raise ApiException(422, "invalid_transition", f"Переход {row.status} → {status} не разрешён")
    row.status = status
    row.status_reason = reason or None
    row.status_changed_at = now
    db.flush()
    pairs = repo.refresh_availability(db)
    return FamilyStatusView(
        id=row.id,
        status=row.status,
        status_reason=row.status_reason,
        available_categories=sorted(f"{spec}:{grade}" for spec, grade in pairs),
    )


def _normalize(text: str) -> str:
    return _WS.sub(" ", text).strip().lower()


def leak_lookup(db: Session, text: str) -> LeakLookupResult:
    """Вариант как водяной знак (Арх. 5.8): по тексту найти вариант, семейство и сессии, которым он выдавался."""
    needle = _normalize(text)
    scored: list[tuple[float, Literal["exact", "fuzzy"], VariantRow]] = []
    for variant in db.scalars(select(VariantRow).where(VariantRow.status != VariantStatus.DEMO.value)):
        payload = variant.payload
        code = (payload.get("code") or {}).get("text", "")
        options = " ".join(o["text"] for o in payload.get("options") or [])
        hay = _normalize(" ".join(part for part in (payload.get("prompt", ""), code, options) if part))
        if not hay:
            continue
        if needle in hay or hay in needle:
            scored.append((100.0, "exact", variant))
            continue
        score = float(fuzz.partial_ratio(needle, hay))
        if score >= FUZZY_THRESHOLD:
            scored.append((score, "fuzzy", variant))
    scored.sort(key=lambda item: (-item[0], str(item[2].id)))
    matches = []
    for score, kind, variant in scored[:MAX_MATCHES]:
        served = db.execute(
            select(SessionRow.id, SessionRow.candidate_id, SessionItemRow.shown_at)
            .join(SessionItemRow, SessionItemRow.session_id == SessionRow.id)
            .where(SessionItemRow.variant_id == variant.id)
            .order_by(SessionItemRow.shown_at)
        ).all()
        matches.append(
            LeakMatch(
                variant_id=str(variant.id),
                family_id=variant.family_id,
                level=variant.level,
                match=kind,
                similarity=round(score / 100.0, 3),
                sessions=[
                    {
                        "session_id": str(session_id),
                        "candidate_id": str(candidate_id),
                        "shown_at": shown_at.isoformat() if shown_at else None,
                    }
                    for session_id, candidate_id, shown_at in served
                ],
            )
        )
    return LeakLookupResult(matches=matches)
