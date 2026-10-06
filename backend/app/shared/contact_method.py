"""Проверка способа связи: значение должно соответствовать виду (Арх. 4.5, шаг 2; приложение E, экран E1).

Одни правила для профиля компании, приглашения и вакансии:

* `email` — адрес почты (без проверки доставки), приводится к нижнему регистру;
* `phone` — 8–15 цифр, допускаются пробелы, скобки, дефисы; хранится как `+цифры` (E.164), `8XXXXXXXXXX` → `+7…`;
* `telegram` — `@имя`, 5–32 знака из латиницы, цифр и `_`; ссылка `t.me/имя` приводится к `@имя`;
* `other` — произвольный текст 3–200 знаков.
"""

from __future__ import annotations

import re

from email_validator import EmailNotValidError, validate_email

from app.core.errors import ApiException, field_error
from app.shared.enums import ContactKind
from app.shared.schemas import ContactMethod

OTHER_MIN_LENGTH = 3
OTHER_MAX_LENGTH = 200
EMAIL_MAX_LENGTH = 254

_TELEGRAM_RE = re.compile(r"^@[A-Za-z0-9_]{5,32}$")
_TELEGRAM_LINK_RE = re.compile(r"^(?:https?://)?t\.me/([A-Za-z0-9_]{5,32})/?$", re.IGNORECASE)
_PHONE_ALLOWED_RE = re.compile(r"^\+?[\d\s()\-]+$")

CONTACT_KIND_LABELS: dict[ContactKind, str] = {
    ContactKind.EMAIL: "E-mail",
    ContactKind.PHONE: "Телефон",
    ContactKind.TELEGRAM: "Telegram",
    ContactKind.OTHER: "Другое",
}

_MESSAGES: dict[ContactKind, str] = {
    ContactKind.EMAIL: "Укажите адрес почты, например hr@example.com",
    ContactKind.PHONE: "Укажите телефон: от 8 до 15 цифр",
    ContactKind.TELEGRAM: "Укажите имя в Telegram: @ и 5–32 знака (латиница, цифры, _)",
    ContactKind.OTHER: f"Опишите способ связи: от {OTHER_MIN_LENGTH} до {OTHER_MAX_LENGTH} знаков",
}


def normalize_email(value: str) -> str | None:
    """Адрес почты в нижнем регистре либо `None`, если это не адрес."""
    value = value.strip()
    if len(value) > EMAIL_MAX_LENGTH:
        return None
    try:
        return validate_email(value, check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        return None


def normalize_phone(value: str) -> str | None:
    """Телефон как `+цифры` (8–15 цифр) либо `None`. Российский номер с ведущей 8 приводится к `+7`."""
    value = value.strip()
    if not _PHONE_ALLOWED_RE.fullmatch(value):
        return None
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits.startswith("8") and not value.startswith("+"):
        digits = "7" + digits[1:]
    if not 8 <= len(digits) <= 15:
        return None
    return "+" + digits


def normalize_telegram(value: str) -> str | None:
    """Имя в Telegram как `@имя` либо `None`."""
    value = value.strip()
    link = _TELEGRAM_LINK_RE.fullmatch(value)
    if link:
        value = "@" + link.group(1)
    return value if _TELEGRAM_RE.fullmatch(value) else None


def normalize_contact_value(kind: ContactKind, value: str) -> str | None:
    """Нормализованное значение способа связи либо `None`, если оно не соответствует виду."""
    if kind is ContactKind.EMAIL:
        return normalize_email(value)
    if kind is ContactKind.PHONE:
        return normalize_phone(value)
    if kind is ContactKind.TELEGRAM:
        return normalize_telegram(value)
    value = " ".join(value.split())
    return value if OTHER_MIN_LENGTH <= len(value) <= OTHER_MAX_LENGTH else None


def validate_contact_method(
    kind: ContactKind | str, value: str, *, field: str = "contact_method.value"
) -> ContactMethod:
    """Проверить и нормализовать способ связи; при несоответствии — 422 `validation_error` с ошибкой поля `field`."""
    kind = ContactKind(kind)
    normalized = normalize_contact_value(kind, value)
    if normalized is None:
        raise ApiException(
            422, "validation_error", fields=[field_error(field, "contact_value_invalid", _MESSAGES[kind])]
        )
    return ContactMethod(kind=kind, value=normalized)


def contact_method_label(method: ContactMethod) -> str:
    """Подпись способа связи для писем и PDF: «Telegram: @hr_orbita»."""
    return f"{CONTACT_KIND_LABELS[method.kind]}: {method.value}"
