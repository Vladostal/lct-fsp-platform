"""Служебные эндпоинты `/admin/assessment/*` (Арх. 9.5): доступ по заголовку `X-Admin-Token`."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.db import TxRoute
from app.core.deps import Admin, Db, Now
from app.core.errors import error_responses
from app.modules.assessment import admin
from app.modules.assessment.schemas import (
    BankHealthView,
    FamilyStatusRequest,
    FamilyStatusView,
    LeakLookupRequest,
    LeakLookupResult,
)

router = APIRouter(prefix="/admin/assessment", tags=["admin"], route_class=TxRoute)


@router.get("/bank/health", response_model=BankHealthView, responses=error_responses(403))
def get_bank_health(_: Admin, db: Db) -> BankHealthView:
    """Состояние семейств: статус, экспозиция (подсветка выше 0.60), ответы, запас вариантов."""
    return admin.bank_health(db)


@router.post("/families/{family_id}/status", response_model=FamilyStatusView, responses=error_responses(403, 404, 422))
def post_family_status(family_id: str, payload: FamilyStatusRequest, _: Admin, db: Db, now: Now) -> FamilyStatusView:
    """Карантин, возврат, вывод из банка. 422 `invalid_transition`."""
    return admin.set_family_status(db, family_id, payload.status, payload.reason, now)


@router.post("/leaks/lookup", response_model=LeakLookupResult, responses=error_responses(403, 422))
def post_leak_lookup(payload: LeakLookupRequest, _: Admin, db: Db) -> LeakLookupResult:
    """По тексту найти вариант, семейство и сессии, которым он выдавался."""
    return admin.leak_lookup(db, payload.text)
