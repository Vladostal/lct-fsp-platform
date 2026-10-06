"""Фасад модуля `identity` (Арх. 2.5): пользователи, согласия, аудит, сессии, общий счётчик лимитов.

Первым параметром функций, работающих с БД, идёт `db`. Сервис `commit` не вызывает: транзакцию фиксирует
`core.db.TxRoute` (Арх. 2.4, п. 4). Сессии, токены и лимиты считаются по реальному времени (`clock.real_now()`).

Сценарии эндпоинтов `/auth/*` (регистрация, подтверждение, вход, пароли) — в `accounts.py`; они пользуются этим
же фасадом.
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Mapping
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core import clock, security
from app.core.db import RETRYABLE_SQLSTATES
from app.core.errors import not_found
from app.modules.identity import emails, legal, limits
from app.modules.identity.constants import KIND_ACCOUNT_DELETED
from app.modules.identity.dto import ConsentDTO, ConsentTextDTO, UserDTO
from app.modules.identity.models import (
    CONSENT_SOURCE_SEED,
    CONSENT_SOURCES,
    AppUser,
    AuditEvent,
    AuthSession,
    Consent,
    EmailToken,
    LoginAttempt,
)
from app.shared.enums import ConsentKind, Role

log = logging.getLogger("app.identity")

_USER_AGENT_MAX_LENGTH = 300

# Хеш демо-пароля считается один раз на процесс (Арх. 13.6): сид создаёт сотни демо-аккаунтов с одним паролем,
# а каждый расчёт Argon2 — десятки миллисекунд. Пароль демо-аккаунтов публичный, общая соль ему не вредит.
# Ключ — SHA-256 пароля, чтобы сам пароль не лежал в памяти дольше вызова.
_demo_password_hashes: dict[str, str] = {}


# --------------------------------------------------------------------------------------------------------------------
# Пользователи
# --------------------------------------------------------------------------------------------------------------------


def _to_dto(user: AppUser) -> UserDTO:
    return UserDTO(
        id=user.id,
        email=user.email,
        role=Role(user.role),
        is_demo=user.is_demo,
        email_verified_at=user.email_verified_at,
        created_at=user.created_at,
    )


def get_user(db: Session, user_id: UUID) -> UserDTO:
    """Пользователь по идентификатору; нет такого — 404 `not_found`."""
    user = db.get(AppUser, user_id)
    if user is None:
        raise not_found()
    return _to_dto(user)


def users(db: Session, user_ids: Collection[UUID]) -> dict[UUID, UserDTO]:
    """Пользователи одним запросом; отсутствующие идентификаторы в ответ не попадают."""
    ids = set(user_ids)
    if not ids:
        return {}
    rows = db.scalars(select(AppUser).where(AppUser.id.in_(ids)))
    return {user.id: _to_dto(user) for user in rows}


def demo_user_ids(db: Session, keys: Collection[str] | None = None) -> list[UUID]:
    """Демо-аккаунты целиком (`keys=None`) или по ключам сценария (`app_user.demo_key`)."""
    statement = select(AppUser.id).where(AppUser.is_demo.is_(True))
    if keys is not None:
        wanted = set(keys)
        if not wanted:
            return []
        statement = statement.where(AppUser.demo_key.in_(wanted))
    return list(db.scalars(statement.order_by(AppUser.created_at, AppUser.id)))


def _lock_user(db: Session, user_id: UUID) -> AppUser | None:
    """Заблокировать строку пользователя на время транзакции.

    `FOR NO KEY UPDATE`: параллельные изменения того же аккаунта выстраиваются в очередь, а вставки в таблицы
    других модулей с внешним ключом на `app_user` (им нужен `FOR KEY SHARE`) не ждут.
    """
    statement = select(AppUser).where(AppUser.id == user_id).with_for_update(key_share=True)
    return db.scalar(statement.execution_options(populate_existing=True))


def create_user(
    db: Session, email: str, password: str, role: Role, *, verified: bool, is_demo: bool, demo_key: str | None
) -> UUID:
    """Создать пользователя напрямую — только для сида и демо-режима (обычный путь — регистрация с письмом).

    Адрес приводится к нижнему регистру и не проверяется на доставляемость: демо-аккаунты живут на `demo.test`.
    Аккаунт получает согласие на обработку действующей версии с источником `seed` и отметку 18+: без них он
    отличался бы от зарегистрированного. Занятый адрес или ключ — `ValueError`.
    """
    normalized = email.strip().lower()
    if "@" not in normalized.strip("@"):
        raise ValueError(f"create_user: не адрес почты: {email!r}")
    taken = db.scalar(select(AppUser.id).where(AppUser.email == normalized))
    if taken is not None:
        raise ValueError(f"create_user: адрес уже занят: {normalized}")
    if demo_key is not None and db.scalar(select(AppUser.id).where(AppUser.demo_key == demo_key)) is not None:
        raise ValueError(f"create_user: ключ демо-аккаунта уже занят: {demo_key}")

    now = clock.real_now()
    user = AppUser(
        email=normalized,
        password_hash=_hash_for_new_user(password, is_demo=is_demo),
        role=Role(role).value,
        email_verified_at=now if verified else None,
        is_adult_confirmed=True,
        is_demo=is_demo,
        demo_key=demo_key,
        created_at=now,
    )
    db.add(user)
    db.flush()
    text = legal.consent_text(ConsentKind.PROCESSING)
    grant_consent(db, user.id, ConsentKind.PROCESSING, text.version, text.sha256, CONSENT_SOURCE_SEED, now)
    return user.id


def _hash_for_new_user(password: str, *, is_demo: bool) -> str:
    if not is_demo:
        return security.hash_password(password)
    key = security.hash_token(password)
    if key not in _demo_password_hashes:
        _demo_password_hashes[key] = security.hash_password(password)
    return _demo_password_hashes[key]


# --------------------------------------------------------------------------------------------------------------------
# Сессии
# --------------------------------------------------------------------------------------------------------------------


def open_session(db: Session, user_id: UUID, *, user_agent: str | None = None) -> str:
    """Открыть сессию входа и вернуть значение cookie `sid`; в базе остаётся только SHA-256 токена (Арх. 10.1)."""
    token = security.new_token()
    now = clock.real_now()
    db.add(
        AuthSession(
            user_id=user_id,
            token_hash=security.hash_token(token),
            created_at=now,
            expires_at=now + security.session_ttl(),
            last_seen_at=now,
            user_agent=(user_agent or "")[:_USER_AGENT_MAX_LENGTH] or None,
        )
    )
    db.execute(update(AppUser).where(AppUser.id == user_id).values(last_login_at=now))
    db.flush()
    return token


def create_session(db: Session, user_id: UUID) -> str:
    """Открыть сессию и вернуть значение cookie `sid` (демо-вход). Cookie выставляет вызывающий:
    `core.security.set_session_cookie(response, token)`.
    """
    return open_session(db, user_id)


def close_sessions(db: Session, user_id: UUID, *, keep_session_id: UUID | None = None) -> int:
    """Удалить сессии пользователя — все либо все, кроме `keep_session_id`. Возвращает число удалённых."""
    statement = delete(AuthSession).where(AuthSession.user_id == user_id)
    if keep_session_id is not None:
        statement = statement.where(AuthSession.id != keep_session_id)
    return int(db.execute(statement).rowcount or 0)  # type: ignore[attr-defined]


# --------------------------------------------------------------------------------------------------------------------
# Согласия
# --------------------------------------------------------------------------------------------------------------------


def consents(db: Session, user_id: UUID) -> dict[ConsentKind, ConsentDTO]:
    """Последнее согласие каждого вида (действующее либо отозванное); вида нет в ответе — согласие не давалось."""
    rows = db.scalars(
        select(Consent)
        .where(Consent.user_id == user_id)
        # Действующая строка идёт последней и потому побеждает отозванную с тем же моментом выдачи.
        .order_by(Consent.granted_at, Consent.revoked_at.is_(None))
    )
    result: dict[ConsentKind, ConsentDTO] = {}
    for row in rows:
        result[ConsentKind(row.kind)] = ConsentDTO(
            version=row.version, granted_at=row.granted_at, revoked_at=row.revoked_at
        )
    return result


def grant_consent(
    db: Session, user_id: UUID, kind: ConsentKind, version: str, text_sha256: str, source: str, at: datetime
) -> None:
    """Записать согласие (`source` — `user` или `seed`).

    Действующее согласие вида одно. Повтор с той же версией и тем же текстом ничего не меняет; другая версия
    закрывает прежнюю строку (`revoked_at = at`) и создаёт новую — прежняя остаётся как доказательство (Арх. 10.5).
    Проверка, что версия действующая (409 `consent_version_outdated`), — дело вызывающего: он знает свой текст.
    """
    kind = ConsentKind(kind)
    if source not in CONSENT_SOURCES:
        raise ValueError(f"grant_consent: источник согласия — один из {CONSENT_SOURCES}, получено {source!r}")
    if _lock_user(db, user_id) is None:
        raise not_found()
    active = db.scalar(
        select(Consent).where(Consent.user_id == user_id, Consent.kind == kind.value, Consent.revoked_at.is_(None))
    )
    if active is not None:
        if active.version == version and active.text_sha256 == text_sha256:
            return
        active.revoked_at = at
        db.flush()
    db.add(
        Consent(
            user_id=user_id, kind=kind.value, version=version, text_sha256=text_sha256, source=source, granted_at=at
        )
    )
    db.flush()
    if source != CONSENT_SOURCE_SEED:  # согласия сида — не действия людей: тысячи таких записей журнал не украсят
        audit(
            db,
            "consent_granted",
            actor_user_id=user_id,
            target_user_id=user_id,
            params={"kind": kind.value, "version": version},
        )


def revoke_consent(db: Session, user_id: UUID, kind: ConsentKind, at: datetime) -> None:
    """Отозвать действующее согласие вида: ставит `revoked_at`, строка остаётся. Нет действующего — ничего не делает."""
    kind = ConsentKind(kind)
    revoked = db.execute(
        update(Consent)
        .where(Consent.user_id == user_id, Consent.kind == kind.value, Consent.revoked_at.is_(None))
        .values(revoked_at=at)
        .returning(Consent.version)
    ).all()
    for (version,) in revoked:
        audit(
            db,
            "consent_revoked",
            actor_user_id=user_id,
            target_user_id=user_id,
            params={"kind": kind.value, "version": version},
        )


def publication_consent_active(db: Session, user_ids: Collection[UUID]) -> set[UUID]:
    """У кого из пользователей действует (не отозвано) согласие на публикацию профиля."""
    ids = set(user_ids)
    if not ids:
        return set()
    rows = db.scalars(
        select(Consent.user_id).where(
            Consent.user_id.in_(ids), Consent.kind == ConsentKind.PUBLICATION.value, Consent.revoked_at.is_(None)
        )
    )
    return set(rows)


def current_consent(kind: ConsentKind) -> ConsentTextDTO:
    """Действующий текст согласия: версия, заголовок, текст, SHA-256. Тексты лежат в файлах, база не нужна.

    Виды `processing` и `publication`. Текст `fsp_data` хранит модуль `fsp` (`GET /fsp/consent`): для него —
    `LookupError`.
    """
    return legal.consent_text(kind)


# --------------------------------------------------------------------------------------------------------------------
# Аудит
# --------------------------------------------------------------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    """Привести значение параметра аудита к виду, пригодному для jsonb."""
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def audit(
    db: Session,
    code: str,
    *,
    actor_user_id: UUID | None = None,
    target_user_id: UUID | None = None,
    params: Mapping[str, Any] | None = None,
) -> None:
    """Записать событие безопасности (Арх. 10.8). В `params` — только идентификаторы и коды: ни адресов почты,
    ни имён, ни контактов, ни токенов. Запись переживает удаление аккаунта (внешних ключей нет).
    """
    db.add(
        AuditEvent(
            at=clock.real_now(),
            code=code,
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            params=_jsonable(params or {}),
        )
    )
    db.flush()


# --------------------------------------------------------------------------------------------------------------------
# Удаление аккаунта
# --------------------------------------------------------------------------------------------------------------------


def _run_cleanup_handlers(db: Session, user_id: UUID) -> list[str]:
    """Вызвать обработчики `USER_CLEANUP` (Арх. 2.6); вернуть имена тех, что завершились ошибкой.

    Сбой обработчика удаление не останавливает: право на удаление данных не должно зависеть от доступности
    внешнего реестра (поправка R3-data-api-security-7). Каждый обработчик выполняется в точке сохранения, чтобы
    его незавершённые записи откатились, а транзакция осталась рабочей. Исключение — сбой сериализации и взаимная
    блокировка: их пробрасываем, чтобы `run_in_tx` повторил удаление целиком.
    """
    from app import wiring  # лениво: wiring собирает приложение и сам загружает модули по строкам

    failed: list[str] = []
    for handler in wiring.user_cleanup_handlers():
        name = f"{handler.__module__}.{getattr(handler, '__name__', 'handler')}"
        try:
            with db.begin_nested():
                handler(db, user_id)
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) in RETRYABLE_SQLSTATES:
                raise
            log.exception("обработчик удаления аккаунта %s завершился ошибкой", name)
            failed.append(name)
        except Exception:
            log.exception("обработчик удаления аккаунта %s завершился ошибкой", name)
            failed.append(name)
    return failed


def remove_user(db: Session, user_id: UUID, *, actor_user_id: UUID | None = None) -> bool:
    """Удалить аккаунт со всеми данными (Арх. 10.5). `False` — такого пользователя нет.

    Порядок:

    1. обработчики `USER_CLEANUP` (снятие разрешения в реестре ФСП) — до каскадного удаления;
    2. запись аудита `consents_at_deletion`: по каждому согласию — вид, версия, SHA-256 текста, моменты выдачи
       и отзыва. Строки `consent` уйдут каскадом, а оператор должен уметь показать, что согласие было получено
       и отозвано; персональных данных в записи нет;
    3. для не-демо аккаунта — отметка карантина `login_attempt.kind = account_deleted` с хэшем адреса (HMAC
       с ключом сервера, без IP): пока она существует, регистрация на этот адрес аккаунт не создаёт;
    4. `DELETE FROM app_user`: каскады внешних ключей удаляют всё остальное, включая сессии (Арх. 8.1).
    """
    user = _lock_user(db, user_id)
    if user is None:
        return False
    failed = _run_cleanup_handlers(db, user_id)
    now = clock.real_now()

    consent_rows = db.scalars(
        select(Consent).where(Consent.user_id == user_id).order_by(Consent.granted_at, Consent.kind)
    ).all()
    params: dict[str, Any] = {
        "role": user.role,
        "is_demo": user.is_demo,
        "deleted_at": now,
        "consents": [
            {
                "kind": row.kind,
                "version": row.version,
                "text_sha256": row.text_sha256,
                "source": row.source,
                "granted_at": row.granted_at,
                # Удаление аккаунта — это и есть отзыв действующих согласий.
                "revoked_at": row.revoked_at or now,
            }
            for row in consent_rows
        ],
    }
    if failed:
        params["cleanup_failed"] = failed
    audit(db, "consents_at_deletion", actor_user_id=actor_user_id, target_user_id=user_id, params=params)

    if not user.is_demo:
        db.add(
            LoginAttempt(
                kind=KIND_ACCOUNT_DELETED, email_sha256=emails.email_hash(user.email), ip=None, ok=True, at=now
            )
        )
    db.flush()

    # Объекты удаляемого аккаунта убираем из сессии до DELETE: иначе после каскада в ней остались бы «призраки».
    for instance in list(db.identity_map.values()):
        if isinstance(instance, AppUser):
            owned = instance.id == user_id
        elif isinstance(instance, (AuthSession, EmailToken, Consent)):
            owned = instance.user_id == user_id
        else:
            continue  # объекты других модулей не трогаем и не читаем
        if owned:
            db.expunge(instance)
    db.execute(delete(AppUser).where(AppUser.id == user_id))
    return True


def delete_user(db: Session, user_id: UUID) -> None:
    """Обработчики `USER_CLEANUP`, запись аудита о согласиях, каскадное удаление строки `app_user`;
    для не-демо — отметка `account_deleted` с хэшем адреса (карантин повторной регистрации, Арх. 10.5).

    Проверок роли и пароля здесь нет: запрет удалять демо-аккаунт из интерфейса (403 `demo_account_readonly`)
    стоит в эндпоинте, а сид и модуль `demo` удаляют демо-аккаунты именно этой функцией. Несуществующий
    пользователь — не ошибка.
    """
    remove_user(db, user_id)


# --------------------------------------------------------------------------------------------------------------------
# Общий счётчик лимитов
# --------------------------------------------------------------------------------------------------------------------


def _user_key(db: Session, user_id: UUID) -> str:
    """Ключ счётчика по пользователю — хэш его адреса (Арх. 8.3); пользователя нет — хэш идентификатора."""
    email = db.scalar(select(AppUser.email).where(AppUser.id == user_id))
    if email is None:
        return security.keyed_hash("user", str(user_id))
    return emails.email_hash(email)


def throttle(
    db: Session, kind: str, *, ip: str | None = None, user_id: UUID | None = None, limit: int, window_s: int
) -> None:
    """Общий счётчик лимитов на таблице `login_attempt`: пишет строку и поднимает 429 `rate_limited`
    (`params.retry_after`, секунды) при превышении; без `ip` и `user_id` считает все строки `kind`.
    Вызывают `identity`, `matching` (страницы банка, Арх. 6.9) и `demo` (Арх. 13.5).

    * Считаются события за последние `window_s` секунд реального времени, совпадающие со всеми переданными
      ключами. Событие проходит, пока их меньше `limit`; отклонённая попытка не записывается.
    * `kind` — короткий идентификатор в нижнем регистре (`bank_page`, `demo_restart`); набор значений открыт.
    * Несколько вызовов с одним `kind` в одной транзакции считают одно событие (две границы одного действия:
      по IP и общая) — строка одна, порядок вызовов не важен.
    * Свой код ошибки (например, `bank_page_limit`) вызывающий получает, перехватив `ApiException` со статусом 429
      и подняв свою с теми же `params`.
    """
    email_hash = _user_key(db, user_id) if user_id is not None else None
    limits.throttle(db, kind, ip=ip, email_hash=email_hash, limit=limit, window_s=window_s)
