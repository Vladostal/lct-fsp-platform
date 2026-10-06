"""Проверка и нормализация полей формы профиля (приложение B, §1.1; приложение E, экран C1).

Функции чистые: принимают введённое значение и возвращают нормализованное либо поднимают `PydanticCustomError`
с кодом ошибки поля и русским текстом. Их вызывают валидаторы `ProfileData` (`dto.py`), поэтому одни и те же правила
действуют и для запроса `PUT /candidate/profile`, и для сида.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from pydantic_core import PydanticCustomError

from app.modules.profile.constants import (
    ABOUT_MAX,
    CITY_MAX,
    CUSTOM_LABEL_MAX,
    EXPERIENCE_MAX_YEARS,
    EXPERIENCE_STEP,
    LINK_MAX,
    NAME_MAX,
)
from app.shared.contact_method import normalize_phone, normalize_telegram

_NAME_EXTRA = frozenset(" -'")
_SPACES_RE = re.compile(r"\s+")
_DOMAIN_RE = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9а-яё](?:[a-z0-9а-яё-]{0,61}[a-z0-9а-яё])?\.)+[a-zа-яё]{2,}$")
_HOST_RE = re.compile(
    r"^(?:[A-Za-z0-9А-Яа-яЁё](?:[A-Za-z0-9А-Яа-яЁё-]{0,61}[A-Za-z0-9А-Яа-яЁё])?\.)+[A-Za-zА-Яа-яЁё]{2,}$"
)


def squeeze(value: str) -> str:
    """Убрать пробелы по краям и схлопнуть внутренние."""
    return _SPACES_RE.sub(" ", value).strip()


def optional_text(value: str | None) -> str | None:
    """Пустая строка и строка из пробелов означают «не задано»."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def person_name(value: str, *, required: bool) -> str | None:
    """Имя, фамилия, отчество: 1–60 знаков; буквы, дефис, апостроф, пробел."""
    value = squeeze(value.replace("’", "'").replace("`", "'"))
    if not value:
        if required:
            raise PydanticCustomError("required", "Обязательное поле")
        return None
    if len(value) > NAME_MAX:
        raise PydanticCustomError("name_too_long", f"Не больше {NAME_MAX} знаков")
    if not any(ch.isalpha() for ch in value) or any(not (ch.isalpha() or ch in _NAME_EXTRA) for ch in value):
        raise PydanticCustomError("name_invalid", "Допустимы буквы, дефис, апостроф и пробел")
    return value


def city(value: str | None) -> str | None:
    value = optional_text(value)
    if value is None:
        return None
    value = squeeze(value)
    if len(value) > CITY_MAX:
        raise PydanticCustomError("city_too_long", f"Не больше {CITY_MAX} знаков")
    return value


def phone(value: str | None) -> str | None:
    """Телефон в E.164: `+` и 8–15 цифр; `8XXXXXXXXXX` → `+7XXXXXXXXXX`."""
    value = optional_text(value)
    if value is None:
        return None
    normalized = normalize_phone(value)
    if normalized is None:
        raise PydanticCustomError("phone_invalid", "Укажите телефон: от 8 до 15 цифр")
    return normalized


def telegram(value: str | None) -> str | None:
    """Имя в Telegram: `@` и 5–32 знака (латиница, цифры, `_`); `@` добавляется, ссылка `t.me/имя` приводится."""
    value = optional_text(value)
    if value is None:
        return None
    if not value.startswith("@") and "/" not in value:
        value = "@" + value
    normalized = normalize_telegram(value)
    if normalized is None:
        raise PydanticCustomError("telegram_invalid", "Укажите имя в Telegram: @ и 5–32 знака (латиница, цифры, _)")
    return normalized


def link(value: str | None) -> str | None:
    """Ссылка: только `https`, не длиннее 200 знаков; без схемы — добавляется `https://`."""
    value = optional_text(value)
    if value is None:
        return None
    if "://" not in value:
        value = "https://" + value
    if len(value) > LINK_MAX:
        raise PydanticCustomError("link_too_long", f"Не больше {LINK_MAX} знаков")
    try:
        parts = urlsplit(value)
        host = parts.hostname or ""
    except ValueError:
        parts, host = None, ""
    bad_chars = any(ch.isspace() or ch in "<>\"'`\\" or ord(ch) < 0x20 for ch in value)
    if parts is None or parts.scheme.lower() != "https" or bad_chars or parts.username or not _HOST_RE.match(host):
        raise PydanticCustomError("link_invalid", "Укажите ссылку вида https://example.com/…")
    return value


def experience_years(value: float | None) -> float | None:
    """Стаж: 0–40 лет с шагом 0,5."""
    if value is None:
        return None
    if value < 0 or value > EXPERIENCE_MAX_YEARS:
        raise PydanticCustomError("experience_out_of_range", f"От 0 до {EXPERIENCE_MAX_YEARS} лет")
    doubled = value / EXPERIENCE_STEP
    if abs(doubled - round(doubled)) > 1e-9:
        raise PydanticCustomError("experience_step", "Шаг — полгода: 0, 0,5, 1, 1,5…")
    return round(doubled) * EXPERIENCE_STEP


def about(value: str | None) -> str | None:
    value = optional_text(value)
    if value is not None and len(value) > ABOUT_MAX:
        raise PydanticCustomError("about_too_long", f"Не больше {ABOUT_MAX} знаков")
    return value


def custom_label(value: str) -> str:
    """Свой тег навыка: 1–40 знаков, без управляющих символов."""
    value = squeeze(value)
    if not value:
        raise PydanticCustomError("custom_label_empty", "Пустой тег")
    if len(value) > CUSTOM_LABEL_MAX:
        raise PydanticCustomError("custom_label_too_long", f"Тег не длиннее {CUSTOM_LABEL_MAX} знаков")
    if any(ord(ch) < 0x20 for ch in value):
        raise PydanticCustomError("custom_label_invalid", "Недопустимые символы в теге")
    return value


def mail_domain(value: str) -> str:
    """Домен почты для списка «не показывать компаниям» (P1): `example.com`, без `@` и схемы."""
    value = value.strip().lower().removeprefix("@")
    if not _DOMAIN_RE.match(value):
        raise PydanticCustomError("domain_invalid", "Укажите домен почты, например example.com")
    return value
