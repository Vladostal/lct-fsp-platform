"""Адрес почты: нормализация, каноническая форма и хэш с ключом (Арх. 10.1, 10.5; поправки третьей рецензии).

Две разные формы адреса:

* **нормализованный** (`normalize_email`) — то, что хранится в `app_user.email` и куда уходят письма: нижний регистр,
  без пробелов по краям. По нему аккаунты различаются: `name+work@example.com` и `name@example.com` — два аккаунта;
* **канонический** (`canonical_email`) — только для хэша в журнале лимитов и в отметке карантина: без суффикса
  `+…` в локальной части, а для Gmail ещё и без точек. Алиасы одного ящика дают один хэш, поэтому лимит писем и
  карантин после удаления аккаунта не обходятся дописыванием `+1` (поправка R3-mechanics-recheck-2).

Хэш — HMAC-SHA256 с ключом сервера (`core.security.keyed_hash`), а не простой SHA-256: по словарю адресов его не
восстановить, и после удаления аккаунта он не остаётся идентификатором человека (поправка R3-tz-compliance-7).
"""

from __future__ import annotations

from email_validator import EmailNotValidError, validate_email

from app.core import security
from app.modules.identity.constants import EMAIL_MAX_LENGTH

#: Домены, где точки в локальной части не значимы и оба имени ведут в один ящик.
_GMAIL_DOMAINS = frozenset({"gmail.com", "googlemail.com"})
_HASH_PURPOSE = "email"


def normalize_email(value: str) -> str | None:
    """Адрес в нижнем регистре либо `None`, если это не адрес или он длиннее 254 знаков."""
    value = value.strip()
    if not value or len(value) > EMAIL_MAX_LENGTH:
        return None
    try:
        normalized = validate_email(value, check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        return None
    return normalized if len(normalized) <= EMAIL_MAX_LENGTH else None


def canonical_email(email: str) -> str:
    """Каноническая форма адреса для хэша: нижний регистр, без `+суффикса`; для Gmail — без точек.

    Формула: `local@domain` → `local.split("+")[0]`; при домене `gmail.com` или `googlemail.com` из локальной части
    убираются точки, а домен приводится к `gmail.com`. Строка без `@` возвращается как есть в нижнем регистре.
    """
    email = email.strip().lower()
    local, at, domain = email.rpartition("@")
    if not at or not local:
        return email
    local = local.split("+", 1)[0] or local
    if domain in _GMAIL_DOMAINS:
        local = local.replace(".", "") or local
        domain = "gmail.com"
    return f"{local}@{domain}"


def email_hash(email: str) -> str:
    """Значение для `login_attempt.email_sha256`: HMAC-SHA256 канонической формы адреса с ключом сервера."""
    return security.keyed_hash(_HASH_PURPOSE, canonical_email(email))
