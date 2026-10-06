"""Схемы эндпоинтов `company` (Арх. 9.4, 9.11).

Имена полей совпадают с именами полей формы E1: ошибка попадает в `fields[].name`. Ошибка значения способа связи
называется `contact_method.value` (её поднимает `shared.contact_method`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, StringConstraints

from app.modules.company.constants import (
    CITY_MAX,
    DESCRIPTION_MAX,
    DESCRIPTION_MIN,
    NAME_MAX,
    NAME_MIN,
    SITE_MAX,
    SPHERE_MAX,
    SPHERE_MIN,
)
from app.shared.enums import TrustLevel
from app.shared.schemas import ContactMethod

_Stripped = {"strip_whitespace": True}


class CompanyUpdate(BaseModel):
    """Профиль компании целиком (PUT заменяет профиль). Пробелы по краям обрезаются."""

    name: Annotated[str, StringConstraints(min_length=NAME_MIN, max_length=NAME_MAX, **_Stripped)]
    sphere: Annotated[str, StringConstraints(min_length=SPHERE_MIN, max_length=SPHERE_MAX, **_Stripped)]
    description: Annotated[str, StringConstraints(min_length=DESCRIPTION_MIN, max_length=DESCRIPTION_MAX, **_Stripped)]
    site: Annotated[str, StringConstraints(max_length=SITE_MAX, **_Stripped)] | None = None
    city: Annotated[str, StringConstraints(max_length=CITY_MAX, **_Stripped)] | None = None
    contact_method: ContactMethod


class CompanyView(BaseModel):
    """Профиль компании. Пока он не сохранён, текстовые поля и `contact_method` — `null`, `is_complete` — `false`."""

    name: str | None
    sphere: str | None
    description: str | None
    site: str | None
    city: str | None
    contact_method: ContactMethod | None
    trust_level: TrustLevel
    trust_label: str
    on_platform_since: datetime
    is_complete: bool
