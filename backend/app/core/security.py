"""Пароли, токены и сессия входа (Арх. 10.1, 10.6).

* Пароль — Argon2id с параметрами библиотеки; одновременно считается не больше двух хешей (семафор), чтобы
  всплеск входов не исчерпал память: один хеш — около 64 МБ.
* Токены (сессия, подтверждение адреса, сброс пароля) — `secrets.token_urlsafe(32)`; в базе лежит только SHA-256.
* Сессия — cookie `sid` (`HttpOnly; SameSite=Lax; Path=/`, `Secure` при `COOKIE_SECURE=true`). Срок считается по
  реальному времени (`clock.real_now()`): демо-сдвиг часов на него не действует.

Таблицами `app_user` и `auth_session` владеет модуль `identity`. Слой `core` его не импортирует, поэтому читает
сессию по именам таблиц и колонок Арх. 8.3 (лёгкие конструкции `sqlalchemy.table`, без метаданных): это контракт
данных, а не зависимость от кода. Создаёт и удаляет строки сессий только `identity`.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from fastapi import Response
from pwdlib import PasswordHash
from sqlalchemy import column, select, table, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.shared.enums import Role

SESSION_COOKIE = "sid"
#: Cookie браузера, начавшего регистрацию: её хэш лежит в заявке (`email_token.binding_hash`, Арх. 10.2).
REGISTRATION_COOKIE = "reg"

#: Не чаще этого интервала обновляется `auth_session.last_seen_at`: обычный GET базу не меняет (Арх. 10.1).
LAST_SEEN_TOUCH_INTERVAL = timedelta(hours=1)

_MAX_PARALLEL_HASHES = 2
_hash_slots = threading.BoundedSemaphore(_MAX_PARALLEL_HASHES)
_password_hash = PasswordHash.recommended()

_app_user = table(
    "app_user",
    column("id"),
    column("email"),
    column("role"),
    column("is_demo"),
)
_auth_session = table(
    "auth_session",
    column("id"),
    column("user_id"),
    column("token_hash"),
    column("expires_at"),
    column("last_seen_at"),
)


# --------------------------------------------------------------------------------------------------------------------
# Пароли
# --------------------------------------------------------------------------------------------------------------------


def hash_password(password: str) -> str:
    """Хеш Argon2id. Вызывать вне транзакций с блокировками: расчёт занимает десятки миллисекунд."""
    with _hash_slots:
        return _password_hash.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Сверить пароль с хешем. Пустой или испорченный хеш — `False`, без исключения."""
    if not password_hash:
        return False
    with _hash_slots:
        try:
            return _password_hash.verify(password, password_hash)
        except Exception:
            return False


# --------------------------------------------------------------------------------------------------------------------
# Токены и хэши
# --------------------------------------------------------------------------------------------------------------------


def new_token() -> str:
    """Непрозрачный токен: 32 случайных байта в base64url."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 токена в hex: только это значение хранится в базе (Арх. 10.6)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def keyed_hash(purpose: str, value: str) -> str:
    """HMAC-SHA256 значения с ключом сервера — для идентификаторов, которые нельзя восстановить перебором.

    Ключ выводится из `ASSESSMENT_SECRET` отдельно для каждой цели (`purpose`), поэтому хэши разных целей не
    сопоставляются между собой. Пример: хэш адреса почты в журнале лимитов и в отметке карантина — простой
    SHA-256 адреса подбирается по словарю адресов и остаётся идентификатором человека после удаления аккаунта.
    """
    secret = get_settings().assessment_secret.encode("utf-8")
    key = hmac.new(secret, f"keyed-hash:{purpose}".encode(), hashlib.sha256).digest()
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def constant_time_equals(left: str, right: str) -> bool:
    """Сравнение секретов без утечки по времени."""
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


# --------------------------------------------------------------------------------------------------------------------
# Сессия входа
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """Пользователь текущего запроса. `id` — он же `candidate_id` или `employer_id`."""

    id: UUID
    email: str
    role: Role
    is_demo: bool
    session_id: UUID
    #: Срок сессии был продлён в этом запросе: cookie нужно выставить заново.
    session_renewed: bool = False


def session_ttl() -> timedelta:
    return timedelta(days=get_settings().session_ttl_days)


def set_session_cookie(response: Response, token: str) -> None:
    """Выставить cookie сессии на срок `SESSION_TTL_DAYS`."""
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(session_ttl().total_seconds()),
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    """Удалить cookie сессии (выход, удаление аккаунта)."""
    settings = get_settings()
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax", secure=settings.cookie_secure)


def load_session(db: Session, token: str | None, now_real: datetime) -> CurrentUser | None:
    """Найти действующую сессию по значению cookie; `None`, если её нет или срок вышел.

    Продление (Арх. 10.1): когда до конца срока осталось меньше половины `SESSION_TTL_DAYS`, срок отодвигается
    на полный TTL от текущего момента. `last_seen_at` обновляется не чаще раза в час — так обычный `GET`
    со свежей сессией ничего не пишет в базу (закрытый перечень записей при чтении, Арх. 10.1).
    """
    if not token:
        return None
    row = db.execute(
        select(
            _auth_session.c.id,
            _auth_session.c.expires_at,
            _auth_session.c.last_seen_at,
            _app_user.c.id.label("user_id"),
            _app_user.c.email,
            _app_user.c.role,
            _app_user.c.is_demo,
        )
        .select_from(_auth_session.join(_app_user, _app_user.c.id == _auth_session.c.user_id))
        .where(_auth_session.c.token_hash == hash_token(token))
    ).first()
    if row is None or row.expires_at <= now_real:
        return None

    ttl = session_ttl()
    renew = row.expires_at - now_real < ttl / 2
    if renew or now_real - row.last_seen_at >= LAST_SEEN_TOUCH_INTERVAL:
        values: dict[str, datetime] = {"last_seen_at": now_real}
        if renew:
            values["expires_at"] = now_real + ttl
        db.execute(update(_auth_session).where(_auth_session.c.id == row.id).values(**values))
    return CurrentUser(
        id=row.user_id,
        email=row.email,
        role=Role(row.role),
        is_demo=bool(row.is_demo),
        session_id=row.id,
        session_renewed=renew,
    )
