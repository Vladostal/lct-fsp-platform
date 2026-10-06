"""Эндпоинты кандидата модуля `contact` (Арх. 9.9).

Изменяющие операции выполняются через `core.db.run_in_tx` (повтор при `40001` и `40P01`, Арх. 2.4, п. 4);
читающие не вызывают `settle`, не берут блокировок и ничего не пишут (Арх. 4.4, 10.1).
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy.orm import Session

from app.core.db import TxRoute, run_in_tx
from app.core.deps import Candidate, Db, Now, Paging
from app.core.errors import error_responses, not_found
from app.modules.contact import insights, projections, service
from app.modules.contact.models import Invitation
from app.modules.contact.schemas import (
    AcceptRequest,
    CandidateOutcomeRequest,
    ComplaintRequest,
    DeclineRequest,
    FunnelView,
    InvitationCandidateBrief,
    InvitationCandidateView,
    InvitationSummaryView,
)
from app.modules.profile import service as profile_service
from app.modules.profile.dto import VisibilityDTO
from app.shared.enums import InvitationStatus
from app.shared.schemas import Page

router = APIRouter(route_class=TxRoute)

_AUTH = (401, 403)


def _own(db: Session, candidate_id: UUID, invitation_id: UUID) -> Invitation:
    """Приглашение адресата; чужое, отсутствующее и `bounced` — 404."""
    inv = db.get(Invitation, invitation_id)
    if inv is None or inv.candidate_id != candidate_id or inv.status == InvitationStatus.BOUNCED.value:
        raise not_found()
    return inv


@router.get(
    "/candidate/invitations",
    response_model=Page[InvitationCandidateBrief],
    responses=error_responses(*_AUTH, 422),
    summary="Входящие приглашения; bounced не возвращается никогда",
)
def list_candidate_invitations(
    user: Candidate,
    db: Db,
    now: Now,
    paging: Paging,
    status: Annotated[Literal["awaiting", "accepted", "archived"], Query()] = "awaiting",
) -> Page[InvitationCandidateBrief]:
    return projections.candidate_list(db, now, user.id, status, paging)


@router.get(
    "/candidate/invitations/summary",
    response_model=InvitationSummaryView,
    responses=error_responses(*_AUTH),
    summary="Счётчики вкладок, счётчик молчания, состояние показа; ничего не пишет",
)
def candidate_invitations_summary(user: Candidate, db: Db, now: Now) -> InvitationSummaryView:
    return insights.candidate_summary(db, now, user.id)


@router.post(
    "/candidate/invitations/resume",
    response_model=VisibilityDTO,
    responses=error_responses(*_AUTH),
    summary="«Я на связи»: снять автопаузу и обнулить счётчик молчания",
)
def resume_invitations(user: Candidate, db: Db, now: Now) -> VisibilityDTO:
    run_in_tx(db, lambda s: service.resume(s, now, user.id))
    return profile_service.visibility(db, user.id, now)


@router.get(
    "/candidate/funnel",
    response_model=FunnelView,
    responses=error_responses(*_AUTH),
    summary="Воронка спроса кандидата за 30 дней",
)
def candidate_funnel(user: Candidate, db: Db, now: Now) -> FunnelView:
    return insights.candidate_funnel(db, now, user.id)


@router.get(
    "/candidate/invitations/{invitation_id}",
    response_model=InvitationCandidateView,
    responses=error_responses(*_AUTH, 404),
    summary="Приглашение глазами адресата",
)
def get_candidate_invitation(invitation_id: UUID, user: Candidate, db: Db, now: Now) -> InvitationCandidateView:
    return projections.candidate_view(db, now, _own(db, user.id, invitation_id))


@router.post(
    "/candidate/invitations/{invitation_id}/view",
    response_model=InvitationCandidateView,
    responses=error_responses(*_AUTH, 404),
    summary="Отметка о просмотре",
)
def view_candidate_invitation(invitation_id: UUID, user: Candidate, db: Db, now: Now) -> InvitationCandidateView:
    run_in_tx(db, lambda s: service.view_invitation(s, now, user.id, invitation_id))
    return projections.candidate_view(db, now, _own(db, user.id, invitation_id))


@router.post(
    "/candidate/invitations/{invitation_id}/accept",
    response_model=InvitationCandidateView,
    responses=error_responses(*_AUTH, 404, 409, 422),
    summary="Принять приглашение и раскрыть выбранные каналы связи",
)
def accept_candidate_invitation(
    invitation_id: UUID, user: Candidate, db: Db, now: Now, body: AcceptRequest | None = None
) -> InvitationCandidateView:
    disclose = body.disclose if body is not None else None
    run_in_tx(db, lambda s: service.accept_invitation(s, now, user.id, invitation_id, disclose))
    return projections.candidate_view(db, now, _own(db, user.id, invitation_id))


@router.post(
    "/candidate/invitations/{invitation_id}/decline",
    response_model=InvitationCandidateView,
    responses=error_responses(*_AUTH, 404, 409, 422),
    summary="Отклонить приглашение с причиной и необязательным условием",
)
def decline_candidate_invitation(
    invitation_id: UUID, body: DeclineRequest, user: Candidate, db: Db, now: Now
) -> InvitationCandidateView:
    run_in_tx(
        db,
        lambda s: service.decline_invitation(
            s, now, user.id, invitation_id, body.reason_code, body.condition, body.comment
        ),
    )
    return projections.candidate_view(db, now, _own(db, user.id, invitation_id))


@router.post(
    "/candidate/invitations/{invitation_id}/outcome",
    response_model=InvitationCandidateView,
    responses=error_responses(*_AUTH, 404, 409, 422),
    summary="P1: связался ли работодатель и совпали ли условия",
)
def candidate_invitation_outcome(
    invitation_id: UUID, body: CandidateOutcomeRequest, user: Candidate, db: Db, now: Now
) -> InvitationCandidateView:
    run_in_tx(
        db,
        lambda s: service.mark_outcome(
            s, now, user.id, invitation_id, contacted=body.contacted, terms_matched=body.terms_matched
        ),
    )
    return projections.candidate_view(db, now, _own(db, user.id, invitation_id))


@router.post(
    "/candidate/invitations/{invitation_id}/complaint",
    response_model=InvitationCandidateView,
    responses=error_responses(*_AUTH, 404, 409, 422),
    summary="P1: жалоба на приглашение; одна на приглашение",
)
def candidate_invitation_complaint(
    invitation_id: UUID, body: ComplaintRequest, user: Candidate, db: Db, now: Now
) -> InvitationCandidateView:
    run_in_tx(db, lambda s: service.file_complaint(s, now, user.id, invitation_id, body.reason_code, body.comment))
    return projections.candidate_view(db, now, _own(db, user.id, invitation_id))
