"""Эндпоинт `reports` (Арх. 9.4): `GET /validation/summary` — без входа."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.db import TxRoute
from app.modules.reports import service
from app.modules.reports.schemas import ValidationSummary

router = APIRouter(route_class=TxRoute)


@router.get(
    "/validation/summary",
    response_model=ValidationSummary,
    summary="Сводки отчётов валидации; отсутствующая секция — null",
)
def validation_summary() -> ValidationSummary:
    return service.validation_summary()
