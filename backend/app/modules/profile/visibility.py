"""Состояние показа кандидата работодателям (Арх. 6.1) и ручная пауза.

Состояние не хранится: его вычисляет `compute` из четырёх фактов — есть ли категория, действует ли согласие на
публикацию, стоит ли ручная пауза и не вышел ли срок автопаузы. Срок автопаузы проверяется при каждом чтении,
поэтому по истечении она перестаёт действовать без записи в базу.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.errors import ApiException
from app.modules.assessment import service as assessment
from app.modules.identity import service as identity
from app.modules.profile.dto import VisibilityDTO
from app.modules.profile.models import CandidateProfile
from app.shared.enums import PauseReason, VisibilityState


def compute(
    *,
    has_category: bool,
    consent_active: bool,
    paused_at: datetime | None,
    auto_paused_until: datetime | None,
    now: datetime,
) -> VisibilityDTO:
    """Первое подходящее состояние из таблицы Арх. 6.1.

    При обеих паузах сразу причина — `auto_silence`: её снимает модуль `contact`, а кандидат должен увидеть срок.
    """
    if not has_category:
        return VisibilityDTO(state=VisibilityState.NOT_READY)
    if not consent_active:
        return VisibilityDTO(state=VisibilityState.UNPUBLISHED)
    if auto_paused_until is not None and now < auto_paused_until:
        return VisibilityDTO(
            state=VisibilityState.PAUSED, pause_reason=PauseReason.AUTO_SILENCE, auto_paused_until=auto_paused_until
        )
    if paused_at is not None:
        return VisibilityDTO(state=VisibilityState.PAUSED, pause_reason=PauseReason.MANUAL)
    return VisibilityDTO(state=VisibilityState.VISIBLE)


def for_candidate(db: Session, candidate_id: UUID, now: datetime) -> VisibilityDTO:
    """Состояние одного кандидата: читает категорию, согласие и поля паузы."""
    row = db.get(CandidateProfile, candidate_id)
    return compute(
        has_category=assessment.get_category(db, candidate_id) is not None,
        consent_active=candidate_id in identity.publication_consent_active(db, [candidate_id]),
        paused_at=row.paused_at if row else None,
        auto_paused_until=row.auto_paused_until if row else None,
        now=now,
    )


def set_manual_pause(db: Session, candidate_id: UUID, *, paused: bool, now: datetime) -> VisibilityDTO:
    """Ручная пауза: `paused = True` ставит, `False` снимает. Без действующего согласия на публикацию —
    409 `publication_consent_required`: нечего приостанавливать.
    """
    from app.modules.profile.profiles import ensure_profile  # локально: profiles импортирует этот модуль

    if candidate_id not in identity.publication_consent_active(db, [candidate_id]):
        raise ApiException(409, "publication_consent_required", "Сначала дайте согласие на публикацию профиля")
    row = ensure_profile(db, candidate_id, now)
    row.paused_at = (row.paused_at or now) if paused else None
    row.updated_at = now
    db.flush()
    return for_candidate(db, candidate_id, now)
