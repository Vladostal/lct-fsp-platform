"""Общие и служебные эндпоинты модуля `contact` (Арх. 9.9): медиана вилок, показатели платформы, жалобы."""

from __future__ import annotations

import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.core.db import TxRoute, run_in_tx
from app.core.deps import Admin, AnyUser, Db, Now
from app.core.errors import error_responses, field_error, validation_error
from app.modules.assessment import service as assessment_service
from app.modules.contact import insights, service, texts
from app.modules.contact.models import EmployerContactState, InvitationTerms
from app.modules.contact.schemas import (
    ComplaintAdminView,
    ComplaintResolveRequest,
    PlatformMetricsView,
    SalaryHint,
)
from app.shared.enums import ComplaintStatus, Role

router = APIRouter(route_class=TxRoute)

_CATEGORY_RE = re.compile(r"^[a-z0-9_-]{1,64}:[a-z0-9_-]{1,64}$")


@router.get(
    "/contact/salary-hint",
    response_model=SalaryHint | None,
    responses=error_responses(401, 422),
    summary="Медиана вилок принятых приглашений категории — «ориентир рынка»; null, если данных мало",
)
def salary_hint(
    user: AnyUser, db: Db, now: Now, category: Annotated[str | None, Query(max_length=130)] = None
) -> SalaryHint | None:
    if category is None and user.role == Role.CANDIDATE:
        own = assessment_service.get_category(db, user.id)
        if own is None:
            return None
        category = own.category_code
    if category is None or not _CATEGORY_RE.fullmatch(category):
        raise validation_error(field_error("category", "category_invalid", texts.field_message("category")))
    return insights.salary_hint_for(db, now, category)


@router.get(
    "/contact/metrics",
    response_model=PlatformMetricsView,
    summary="P1: живые показатели платформы",
)
def contact_metrics(db: Db, now: Now) -> PlatformMetricsView:
    return insights.platform_metrics(db, now)


@router.get(
    "/admin/complaints",
    response_model=list[ComplaintAdminView],
    responses=error_responses(403),
    summary="P1: жалобы кандидатов (служебный доступ)",
)
def list_complaints(_: Admin, db: Db) -> list[ComplaintAdminView]:
    return insights.complaints(db)


@router.post(
    "/admin/complaints/{complaint_id}/resolve",
    response_model=ComplaintAdminView,
    responses=error_responses(403, 404, 422),
    summary="P1: разобрать жалобу; unfreeze снимает заморозку отправки",
)
def resolve_complaint(
    complaint_id: UUID, body: ComplaintResolveRequest, _: Admin, db: Db, now: Now
) -> ComplaintAdminView:
    complaint = run_in_tx(
        db, lambda s: service.resolve_complaint(s, now, complaint_id, ComplaintStatus(body.status), body.unfreeze)
    )
    terms = db.get(InvitationTerms, complaint.invitation_id)
    state = db.get(EmployerContactState, complaint.employer_id)
    return insights.complaint_view(
        complaint, terms.company_name if terms else "", bool(state and state.sending_frozen_at is not None)
    )
