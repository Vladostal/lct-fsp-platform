"""Эндпоинты `company` (Арх. 9.4): `GET` и `PUT /employer/company`."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

from app.core.db import TxRoute
from app.core.deps import Db, Employer, Now
from app.core.errors import error_responses
from app.modules.company import service
from app.modules.company.constants import TRUST_LABELS
from app.modules.company.dto import CompanyData, CompanyDTO
from app.modules.company.schemas import CompanyUpdate, CompanyView
from app.modules.identity import service as identity
from app.shared.enums import TrustLevel

router = APIRouter(route_class=TxRoute)


def _view(company: CompanyDTO | None, employer_registered_at: datetime | None) -> CompanyView:
    """Профиль для клиента; без профиля — пустая форма (`on_platform_since` — дата регистрации работодателя)."""
    if company is None:
        assert employer_registered_at is not None
        return CompanyView(
            name=None,
            sphere=None,
            description=None,
            site=None,
            city=None,
            contact_method=None,
            trust_level=TrustLevel.BASIC,
            trust_label=TRUST_LABELS[TrustLevel.BASIC],
            on_platform_since=employer_registered_at,
            is_complete=False,
        )
    return CompanyView(
        name=company.name,
        sphere=company.sphere,
        description=company.description,
        site=company.site,
        city=company.city,
        contact_method=company.contact_method,
        trust_level=company.trust_level,
        trust_label=TRUST_LABELS[company.trust_level],
        on_platform_since=company.created_at,
        is_complete=company.is_complete,
    )


@router.get(
    "/employer/company",
    response_model=CompanyView,
    responses=error_responses(401, 403),
    summary="Профиль компании работодателя",
)
def get_company(user: Employer, db: Db) -> CompanyView:
    company = service.get_company(db, user.id)
    return _view(company, None if company else identity.get_user(db, user.id).created_at)


@router.put(
    "/employer/company",
    response_model=CompanyView,
    responses=error_responses(401, 403, 422),
    summary="Сохранить профиль компании",
)
def put_company(body: CompanyUpdate, user: Employer, db: Db, now: Now) -> CompanyView:
    """422 `validation_error`: `fields[].name` — `name`, `sphere`, `description`, `site`, `city`,
    `contact_method.value`. Уровень доверия запрос не меняет.
    """
    saved = service.save_company(
        db,
        user.id,
        CompanyData(
            name=body.name,
            sphere=body.sphere,
            description=body.description,
            site=body.site,
            city=body.city,
            contact_method=body.contact_method,
        ),
        now,
    )
    return _view(saved, None)
