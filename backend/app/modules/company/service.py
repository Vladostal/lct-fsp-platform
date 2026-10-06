"""Фасад модуля `company` (Арх. 2.5): профиль компании работодателя.

Чтение (`get_company`, `companies`, `is_complete`) вызывают `contact`, `matching`, `vacancies`; запись
(`save_company`) — роутер модуля, сид и `demo`. Сервис `commit` не вызывает (Арх. 2.4, п. 4).
"""

from __future__ import annotations

import re
from collections.abc import Collection
from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.errors import ApiException, field_error
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
from app.modules.company.dto import CompanyData, CompanyDTO
from app.modules.company.models import Company
from app.shared.contact_method import normalize_contact_value, validate_contact_method
from app.shared.enums import ContactKind, TrustLevel
from app.shared.schemas import ContactMethod

_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_HOST_RE = re.compile(r"^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z0-9-]{2,63}$")


def _normalize_site(value: str | None) -> str | None:
    """Адрес сайта: пустое значение — `None`; без схемы добавляется `https://`; допустимы только http и https.

    Формула проверки: схема `http|https`, имя узла из меток через точки (с доменом верхнего уровня), без пробелов,
    итоговая длина ≤ 200. Иначе 422 `site_invalid` на поле `site` (приложение E, экран E1).
    """
    value = (value or "").strip()
    if not value:
        return None
    candidate = value if _SCHEME_RE.match(value) else f"https://{value}"
    parts = urlsplit(candidate)
    host = parts.hostname or ""
    if (
        parts.scheme.lower() not in ("http", "https")
        or not _HOST_RE.fullmatch(host)
        or any(ch.isspace() for ch in candidate)
        or len(candidate) > SITE_MAX
    ):
        raise ApiException(
            422,
            "validation_error",
            fields=[field_error("site", "site_invalid", "Укажите адрес сайта, например example.com")],
        )
    return candidate


def _to_dto(row: Company) -> CompanyDTO:
    method = ContactMethod(kind=ContactKind(row.contact_kind), value=row.contact_value)
    return CompanyDTO(
        name=row.name,
        sphere=row.sphere,
        description=row.description,
        site=row.site,
        city=row.city,
        contact_method=method,
        trust_level=TrustLevel(row.trust_level),
        created_at=row.created_at,
        is_complete=_complete(row),
    )


def _complete(row: Company) -> bool:
    """Заполнены все обязательные поля в пределах границ формы E1 (название, сфера, описание, способ связи).

    Значение способа связи проверяется тем же правилом, что при сохранении: строка, записанная в обход
    `save_company`, не даст работодателю отправлять приглашения с негодным контактом.
    """
    return (
        NAME_MIN <= len(row.name.strip()) <= NAME_MAX
        and SPHERE_MIN <= len(row.sphere.strip()) <= SPHERE_MAX
        and DESCRIPTION_MIN <= len(row.description.strip()) <= DESCRIPTION_MAX
        and normalize_contact_value(ContactKind(row.contact_kind), row.contact_value) is not None
    )


def get_company(db: Session, employer_id: UUID) -> CompanyDTO | None:
    """Профиль компании работодателя; `None` — профиль не сохранён."""
    row = db.get(Company, employer_id)
    return _to_dto(row) if row is not None else None


def companies(db: Session, employer_ids: Collection[UUID]) -> dict[UUID, CompanyDTO]:
    """Профили одним запросом; работодатели без профиля в ответ не попадают."""
    ids = set(employer_ids)
    if not ids:
        return {}
    return {row.employer_id: _to_dto(row) for row in db.scalars(select(Company).where(Company.employer_id.in_(ids)))}


def is_complete(db: Session, employer_id: UUID) -> bool:
    """Профиль сохранён и заполнен: без этого нельзя создавать потребности и отправлять приглашения."""
    row = db.get(Company, employer_id)
    return row is not None and _complete(row)


def save_company(
    db: Session, employer_id: UUID, data: CompanyData, now: datetime, *, trust_level: TrustLevel | None = None
) -> CompanyDTO:
    """Создать или заменить профиль компании. Функция записи: её вызывают роутер модуля, сид и `demo`.

    Данные проверяются здесь, а не только схемой запроса: сид и `demo` приходят в обход HTTP. Нарушение —
    422 `validation_error` с именами полей формы. Способ связи нормализуется по виду (`shared.contact_method`),
    сайт без схемы получает `https://`. `trust_level=None` оставляет уровень как был (для нового профиля — `basic`);
    уровень меняет только сид и `demo`, пользовательский запрос его не несёт.
    """
    name, sphere, description = data.name.strip(), data.sphere.strip(), data.description.strip()
    errors = []
    if not NAME_MIN <= len(name) <= NAME_MAX:
        errors.append(field_error("name", "length", f"Название: от {NAME_MIN} до {NAME_MAX} знаков"))
    if not SPHERE_MIN <= len(sphere) <= SPHERE_MAX:
        errors.append(field_error("sphere", "length", f"Сфера: от {SPHERE_MIN} до {SPHERE_MAX} знаков"))
    if not DESCRIPTION_MIN <= len(description) <= DESCRIPTION_MAX:
        errors.append(
            field_error("description", "length", f"Описание: от {DESCRIPTION_MIN} до {DESCRIPTION_MAX} знаков")
        )
    city = (data.city or "").strip() or None
    if city is not None and len(city) > CITY_MAX:
        errors.append(field_error("city", "length", f"Город: не больше {CITY_MAX} знаков"))
    if errors:
        raise ApiException(422, "validation_error", fields=errors)
    site = _normalize_site(data.site)
    method = validate_contact_method(data.contact_method.kind, data.contact_method.value)

    values = {
        "name": name,
        "sphere": sphere,
        "description": description,
        "site": site,
        "city": city,
        "contact_kind": method.kind.value,
        "contact_value": method.value,
        "updated_at": now,
    }
    insert = pg_insert(Company).values(
        employer_id=employer_id,
        trust_level=(trust_level or TrustLevel.BASIC).value,
        created_at=now,
        **values,
    )
    update = dict(values)
    if trust_level is not None:
        update["trust_level"] = trust_level.value
    # Одним оператором: две одновременные первые записи не падают на первичном ключе.
    db.execute(insert.on_conflict_do_update(index_elements=[Company.employer_id], set_=update))
    row = db.scalar(select(Company).where(Company.employer_id == employer_id).execution_options(populate_existing=True))
    assert row is not None
    return _to_dto(row)
