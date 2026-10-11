"""Эндпоинты работодателя модуля `contact` (Арх. 9.9).

Изменяющие операции — через `core.db.run_in_tx`. Читающие не вызывают `settle` и не берут блокировок строк
состояния; единственная запись при чтении — отметка `employer_seen_at` в `GET /employer/invitations/{id}`
(Арх. 4.4, 10.1).
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response
from sqlalchemy.orm import Session

from app.core.db import TxRoute, run_in_tx
from app.core.deps import Db, Employer, Now, Paging
from app.core.errors import error_responses, field_error, not_found, validation_error
from app.modules.contact import constants as c
from app.modules.contact import insights, projections, service, texts
from app.modules.contact.dto import InvitationData
from app.modules.contact.models import Invitation
from app.modules.contact.schemas import (
    EmployerOutcomeRequest,
    InvitationCreate,
    InvitationEmployerBrief,
    InvitationEmployerView,
    InvitationPrecheckView,
    InvitationStatsView,
    NeedInsightsView,
    PairStatesView,
    QuotaView,
)
from app.shared.schemas import Page

router = APIRouter(route_class=TxRoute)

_AUTH = (401, 403)


def _own(db: Session, employer_id: UUID, invitation_id: UUID) -> Invitation:
    inv = db.get(Invitation, invitation_id)
    if inv is None or inv.employer_id != employer_id:
        raise not_found()
    return inv


@router.get(
    "/employer/invitations/precheck",
    response_model=InvitationPrecheckView,
    responses=error_responses(*_AUTH, 404, 422),
    summary="Несекретная предпроверка отправки; вилка и минимум кандидата не участвуют",
)
def precheck_invitation(
    user: Employer, db: Db, now: Now, candidate_id: UUID, need_id: UUID | None = None
) -> InvitationPrecheckView:
    return insights.precheck(db, now, user.id, candidate_id, need_id)


@router.post(
    "/employer/invitations",
    response_model=InvitationEmployerView,
    status_code=201,
    responses={
        200: {"model": InvitationEmployerView, "description": "Повтор ключа идемпотентности: уже созданное"},
        **error_responses(*_AUTH, 404, 409, 422, 429),
    },
    summary="Отправить приглашение; status = sent | bounced",
)
def create_invitation(
    body: InvitationCreate,
    response: Response,
    user: Employer,
    db: Db,
    now: Now,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key", description="UUID запроса")],
) -> InvitationEmployerView:
    data = InvitationData.model_validate(body.model_dump())
    inv, created = run_in_tx(db, lambda s: service.send(s, now, user.id, data, idempotency_key, is_demo=False))
    if not created:
        response.status_code = 200
    return projections.employer_view(db, now, inv)


@router.get(
    "/employer/invitations",
    response_model=Page[InvitationEmployerBrief],
    responses=error_responses(*_AUTH, 422),
    summary="Приглашения работодателя",
)
def list_employer_invitations(
    user: Employer,
    db: Db,
    now: Now,
    paging: Paging,
    status: Annotated[
        Literal["all", "awaiting", "accepted", "declined", "expired", "withdrawn", "bounced"], Query()
    ] = "all",
    need_id: UUID | None = None,
) -> Page[InvitationEmployerBrief]:
    return projections.employer_list(db, now, user.id, status, need_id, paging)


@router.get(
    "/employer/invitations/quota",
    response_model=QuotaView,
    responses=error_responses(*_AUTH),
    summary="Суточный лимит отправки",
)
def invitations_quota(user: Employer, db: Db, now: Now) -> QuotaView:
    return insights.quota(db, now, user.id)


@router.get(
    "/employer/invitations/stats",
    response_model=InvitationStatsView,
    responses=error_responses(*_AUTH),
    summary="Собственная воронка: итог и разбивка по потребностям",
)
def invitations_stats(user: Employer, db: Db, now: Now) -> InvitationStatsView:
    return insights.stats(db, now, user.id)


@router.get(
    "/employer/invitations/pair-states",
    response_model=PairStatesView,
    responses=error_responses(*_AUTH, 422),
    summary="Состояние пар «я — кандидат»; до 100 идентификаторов через запятую",
)
def invitations_pair_states(
    user: Employer, db: Db, now: Now, candidate_ids: Annotated[str, Query(max_length=4000)]
) -> PairStatesView:
    parts = [part.strip() for part in candidate_ids.split(",") if part.strip()]
    try:
        ids = [UUID(part) for part in parts]
    except ValueError:
        ids = []
    if not 1 <= len(ids) <= c.PAIR_STATES_MAX_IDS:
        raise validation_error(
            field_error("candidate_ids", "candidate_ids_invalid", texts.field_message("candidate_ids"))
        )
    return insights.pair_states(db, now, user.id, ids)


@router.get(
    "/employer/invitations/{invitation_id}",
    response_model=InvitationEmployerView,
    responses=error_responses(*_AUTH, 404),
    summary="Приглашение глазами отправителя; ставит отметку просмотра",
)
def get_employer_invitation(invitation_id: UUID, user: Employer, db: Db, now: Now) -> InvitationEmployerView:
    inv = _own(db, user.id, invitation_id)
    view = projections.employer_view(db, now, inv)
    # Единственная запись при чтении в модуле (Арх. 4.4, 10.1): статусы и счётчики не меняются.
    inv.employer_seen_at = now
    return view


@router.post(
    "/employer/invitations/{invitation_id}/withdraw",
    response_model=InvitationEmployerView,
    responses=error_responses(*_AUTH, 404, 409),
    summary="Отозвать приглашение",
)
def withdraw_employer_invitation(invitation_id: UUID, user: Employer, db: Db, now: Now) -> InvitationEmployerView:
    run_in_tx(db, lambda s: service.withdraw_invitation(s, now, user.id, invitation_id))
    return projections.employer_view(db, now, _own(db, user.id, invitation_id))


@router.post(
    "/employer/invitations/{invitation_id}/outcome",
    response_model=InvitationEmployerView,
    responses=error_responses(*_AUTH, 404, 409, 422),
    summary="P1: отметка «связались»",
)
def employer_invitation_outcome(
    invitation_id: UUID, body: EmployerOutcomeRequest, user: Employer, db: Db, now: Now
) -> InvitationEmployerView:
    _own(db, user.id, invitation_id)
    run_in_tx(db, lambda s: service.mark_outcome(s, now, user.id, invitation_id, contacted=body.contacted))
    return projections.employer_view(db, now, _own(db, user.id, invitation_id))


@router.get(
    "/employer/needs/{need_id}/insights",
    response_model=NeedInsightsView,
    responses=error_responses(*_AUTH, 404),
    summary="Сводка причин по потребности и подсказки к запросу",
)
def need_insights(need_id: UUID, user: Employer, db: Db, now: Now) -> NeedInsightsView:
    return insights.need_insights(db, now, user.id, need_id)
