"""Типы фасада `company.service` (Арх. 2.5). Заглушка пакета-фундамента: файл заменяет владелец модуля."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.shared.enums import TrustLevel
from app.shared.schemas import ContactMethod


class CompanyDTO(BaseModel):
    """Профиль компании работодателя."""

    name: str
    sphere: str
    description: str
    site: str | None = None
    city: str | None = None
    contact_method: ContactMethod
    trust_level: TrustLevel = TrustLevel.BASIC
    created_at: datetime
    #: Заполнены все обязательные поля: без этого нельзя создавать потребности и приглашать.
    is_complete: bool


class CompanyData(BaseModel):
    """Входные данные `save_company`; роутер строит их из своей схемы запроса."""

    name: str
    sphere: str
    description: str
    site: str | None = None
    city: str | None = None
    contact_method: ContactMethod
