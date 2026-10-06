"""Сценарии эндпоинтов `/auth/*` (Арх. 10.1, 10.2, 10.5): регистрация, подтверждение адреса, вход, пароли.

Главное правило регистрации — **заявки не перезаписывают друг друга**. Каждая регистрация на неподтверждённый
адрес создаёт свою строку `email_token` с собственными паролем, ролью, согласием и привязкой к браузеру (cookie
`reg`). Аккаунт получает данные той заявки, чью ссылку открыли, и только если запрос доказывает, что его шлёт сам
регистрировавшийся: в браузере есть cookie `reg` этой заявки либо в теле передан её пароль. Посторонний, знающий
чужой адрес, не может ни испортить незавершённую регистрацию владельца, ни получить аккаунт с известным ему паролем.

Ответы эндпоинтов без входа одинаковы для существующего и несуществующего адреса; различие — только в письмах.
Всё время здесь — реальное (`clock.real_now()`): демо-сдвиг часов на вход и токены не действует.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, exists, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core import clock, mail, security
from app.core.config import get_settings
from app.core.errors import ApiException, field_error
from app.core.security import CurrentUser
from app.modules.identity import emails, legal, limits, service
from app.modules.identity.constants import (
    FORGOT_IP_LIMIT_PER_HOUR,
    IP_WINDOW_S,
    KIND_ACCOUNT_DELETED,
    KIND_ALREADY_REGISTERED_MAIL,
    KIND_LOGIN,
    KIND_PASSWORD_CHECK,
    KIND_PASSWORD_FORGOT,
    KIND_PASSWORD_RESET_MAIL,
    KIND_REREGISTER_COOLDOWN_MAIL,
    KIND_RESEND_VERIFICATION,
    KIND_SIGNUP,
    KIND_VERIFY_MAIL,
    LOGIN_MAX_FAILURES_PER_EMAIL,
    LOGIN_MAX_FAILURES_PER_IP,
    LOGIN_PENDING_APPLICATIONS_CHECKED,
    LOGIN_WINDOW,
    MAIL_WINDOW,
    MAILS_PER_ADDRESS_PER_HOUR,
    PASSWORD_CHECK_MAX_FAILURES,
    PASSWORD_CHECK_WINDOW,
    RESEND_IP_LIMIT_PER_HOUR,
    RESET_TOKEN_TTL,
    UNVERIFIED_ACCOUNT_TTL,
    VERIFY_MAIL_MIN_INTERVAL,
    VERIFY_TOKEN_TTL,
)
from app.modules.identity.models import (
    CONSENT_SOURCE_USER,
    PURPOSE_RESET_PASSWORD,
    PURPOSE_VERIFY_EMAIL,
    AppUser,
    AuthSession,
    EmailToken,
    LoginAttempt,
)
from app.shared.enums import ConsentKind, Role

log = logging.getLogger("app.identity")

MESSAGES: dict[str, str] = {
    "token_invalid": "Ссылка недействительна или уже использована",
    "token_expired": "Ссылка устарела. Запросите новое письмо",
    "invalid_credentials": "Неверный e-mail или пароль",
    "email_not_verified": "Адрес не подтверждён. Отправьте письмо ещё раз",
    "password_required": "Введите пароль, который вы указали при регистрации",
    "password_mismatch": "Пароль не подошёл",
    "current_password_invalid": "Текущий пароль не подошёл",
    "demo_account_readonly": "Это демо-аккаунт: пароль и удаление для него недоступны",
    "consent_version_outdated": "Текст согласия обновился. Обновите страницу и прочитайте его ещё раз",
}

# Хеш, с которым сверяется пароль несуществующего адреса: вход тратит то же время, что и для существующего,
# и по времени ответа нельзя узнать, зарегистрирован ли адрес. Считается один раз на процесс.
_dummy_hash: str | None = None


def _error(status: int, code: str, *, commit: bool = False) -> ApiException:
    return ApiException(status, code, MESSAGES[code], commit=commit)


def _demo_readonly() -> ApiException:
    return _error(403, "demo_account_readonly")


def _find_user(db: Session, email: str) -> AppUser | None:
    return db.scalar(select(AppUser).where(AppUser.email == email))


def _link(path: str, token: str | None = None) -> str:
    """Ссылка для письма от `PUBLIC_BASE_URL` (Арх. 10.2); маршруты — Арх. 11.2."""
    base = get_settings().public_base_url
    return f"{base}{path}?token={token}" if token else f"{base}{path}"


def _format_moment(moment: datetime) -> str:
    """Момент для текста письма в часовом поясе `APP_TZ`: «05.11.2026 14:30 MSK»."""
    return moment.astimezone(get_settings().tz).strftime("%d.%m.%Y %H:%M %Z").strip()


# --------------------------------------------------------------------------------------------------------------------
# Регистрация
# --------------------------------------------------------------------------------------------------------------------


def reregister_available_at(db: Session, email: str, now: datetime) -> datetime | None:
    """Когда адрес выйдет из карантина после удаления аккаунта; `None` — карантина нет (Арх. 10.5).

    Карантин действует, пока существует отметка `account_deleted` с хэшем адреса моложе
    `REREGISTER_COOLDOWN_DAYS`: `available_at = at + cooldown`. Хэш считается от канонической формы адреса,
    поэтому алиасы того же ящика (`name+1@…`) карантин не обходят.
    """
    cooldown = timedelta(days=get_settings().reregister_cooldown_days)
    if cooldown <= timedelta(0):
        return None
    deleted_at = db.scalar(
        select(LoginAttempt.at)
        .where(
            LoginAttempt.kind == KIND_ACCOUNT_DELETED,
            LoginAttempt.email_sha256 == emails.email_hash(email),
            LoginAttempt.at > now - cooldown,
        )
        .order_by(LoginAttempt.at.desc())
        .limit(1)
    )
    return deleted_at + cooldown if deleted_at is not None else None


def _purge_stale_unverified(db: Session, now: datetime) -> None:
    """Удалить заготовки аккаунтов, адрес которых так и не подтвердили.

    Условие: адрес не подтверждён, пароля у аккаунта нет (значит, он создан регистрацией, а не сидом), аккаунту
    больше `UNVERIFIED_ACCOUNT_TTL` и у него нет ни одной непросроченной заявки. Адрес почты — персональные данные:
    держать его бессрочно ради незавершённой регистрации незачем.
    """
    has_live_token = exists().where(EmailToken.user_id == AppUser.id, EmailToken.expires_at > now)
    db.execute(
        delete(AppUser).where(
            AppUser.email_verified_at.is_(None),
            AppUser.password_hash.is_(None),
            AppUser.is_demo.is_(False),
            AppUser.created_at < now - UNVERIFIED_ACCOUNT_TTL,
            ~has_live_token,
        )
    )


def _ensure_user_stub(db: Session, email: str, role: Role, now: datetime) -> AppUser:
    """Заготовка аккаунта для неподтверждённого адреса: без пароля, роль — из первой заявки.

    `ON CONFLICT DO NOTHING`: две одновременные регистрации на один адрес не падают на уникальности, а получают
    одну и ту же строку.
    """
    db.execute(
        pg_insert(AppUser)
        .values(
            email=email,
            password_hash=None,
            role=role.value,
            email_verified_at=None,
            is_adult_confirmed=False,
            is_demo=False,
            demo_key=None,
            created_at=now,
            last_login_at=None,
        )
        .on_conflict_do_nothing(index_elements=[AppUser.email])
    )
    user = _find_user(db, email)
    if user is None:  # строку успели удалить между вставкой и чтением — повтор запроса создаст её заново
        raise ApiException(503, "service_unavailable")
    return user


def _send_verification(db: Session, user: AppUser, application: EmailToken, now: datetime) -> None:
    """Выпустить токен заявки и поставить письмо подтверждения в очередь транзакции."""
    token = security.new_token()
    application.user_id = user.id
    application.purpose = PURPOSE_VERIFY_EMAIL
    application.token_hash = security.hash_token(token)
    application.created_at = now
    application.expires_at = now + VERIFY_TOKEN_TTL
    db.add(application)
    db.flush()
    mail.enqueue(
        db,
        "verify_email",
        to=user.email,
        context={
            "link": _link("/verify-email", token),
            "expires_hours": int(VERIFY_TOKEN_TTL.total_seconds() // 3600),
        },
    )


def signup(
    db: Session, *, email: str, password: str, role: Role, consent_version: str, ip: str, binding_hash: str
) -> None:
    """`POST /auth/signup`: создать заявку на регистрацию и отправить письмо подтверждения (Арх. 10.1).

    Клиент во всех ветках получает один и тот же ответ 202. Ветки:

    1. адрес в карантине после удаления аккаунта — аккаунт не создаётся, уходит письмо с датой (10.5);
    2. адрес занят подтверждённым аккаунтом — письмо «у вас уже есть аккаунт»;
    3. иначе — новая заявка (заготовка аккаунта создаётся при первой) и письмо со ссылкой.

    Письма каждой ветки ограничены по адресу; сверх лимита письмо не уходит, ответ тот же. Число регистраций
    с одного IP ограничено `SIGNUP_IP_LIMIT_PER_HOUR` — это единственный случай ответа 429.
    """
    settings = get_settings()
    consent = legal.consent_text(ConsentKind.PROCESSING)
    if consent_version != consent.version:
        code = "consent_version_outdated"
        raise ApiException(422, "validation_error", fields=[field_error("consent_version", code, MESSAGES[code])])
    limits.throttle(db, KIND_SIGNUP, ip=ip, limit=settings.signup_ip_limit_per_hour, window_s=IP_WINDOW_S)

    now = clock.real_now()
    # Хеш считается во всех ветках, а не только при создании заявки: иначе занятый адрес отвечал бы заметно быстрее.
    password_hash = security.hash_password(password)
    address_hash = emails.email_hash(email)
    _purge_stale_unverified(db, now)

    available_at = reregister_available_at(db, email, now)
    if available_at is not None:
        if _mail_allowed(db, KIND_REREGISTER_COOLDOWN_MAIL, address_hash):
            mail.enqueue(db, "reregister_cooldown", to=email, context={"available_at": _format_moment(available_at)})
        return

    user = _find_user(db, email)
    if user is not None and user.email_verified_at is not None:
        # Демо-аккаунтам письма не шлём: их адреса на demo.test никому не принадлежат.
        if not user.is_demo and _mail_allowed(db, KIND_ALREADY_REGISTERED_MAIL, address_hash):
            mail.enqueue(
                db,
                "already_registered",
                to=user.email,
                context={"login_link": _link("/login"), "reset_link": _link("/password/forgot")},
            )
        return

    if not _mail_allowed(db, KIND_VERIFY_MAIL, address_hash, min_interval=VERIFY_MAIL_MIN_INTERVAL):
        return
    if user is None:
        user = _ensure_user_stub(db, email, role, now)
    application = EmailToken(
        binding_hash=binding_hash,
        pending_password_hash=password_hash,
        pending_role=role.value,
        pending_consent_version=consent.version,
        pending_consent_sha256=consent.sha256,
        pending_consented_at=now,
        pending_is_adult=True,
    )
    _send_verification(db, user, application, now)
    service.audit(db, "signup", target_user_id=user.id, params={"role": role.value})


def _mail_allowed(db: Session, kind: str, address_hash: str, *, min_interval: timedelta | None = None) -> bool:
    return limits.mail_allowed(
        db,
        kind,
        address_hash,
        per_window=MAILS_PER_ADDRESS_PER_HOUR,
        window=MAIL_WINDOW,
        min_interval=min_interval,
    )


def resend_verification(db: Session, *, email: str, ip: str, reg_cookie: str | None) -> None:
    """`POST /auth/resend-verification`: новая ссылка для неподтверждённого адреса; ответ всегда 202 (Арх. 10.2).

    Новый токен повторяет заявку целиком — пароль, роль, согласие и привязку к браузеру. Берётся последняя заявка,
    поданная из этого же браузера (совпала cookie `reg`), а если такой нет — последняя заявка вообще. Привязка
    не переносится на браузер, запросивший повтор: иначе чужая заявка, выпущенная повторно по просьбе владельца
    адреса, подтвердилась бы у него без пароля и дала бы аккаунт с паролем постороннего.
    """
    limits.throttle(db, KIND_RESEND_VERIFICATION, ip=ip, limit=RESEND_IP_LIMIT_PER_HOUR, window_s=IP_WINDOW_S)
    now = clock.real_now()
    user = _find_user(db, email)
    if user is None or user.email_verified_at is not None:
        return
    applications = db.scalars(
        select(EmailToken)
        .where(
            EmailToken.user_id == user.id,
            EmailToken.purpose == PURPOSE_VERIFY_EMAIL,
            EmailToken.used_at.is_(None),
            EmailToken.pending_password_hash.is_not(None),
        )
        .order_by(EmailToken.created_at.desc())
        .limit(20)
    ).all()
    if not applications:
        return
    source = applications[0]
    if reg_cookie:
        cookie_hash = security.hash_token(reg_cookie)
        source = next(
            (row for row in applications if row.binding_hash and _same(row.binding_hash, cookie_hash)), source
        )
    if not _mail_allowed(db, KIND_VERIFY_MAIL, emails.email_hash(email), min_interval=VERIFY_MAIL_MIN_INTERVAL):
        return
    application = EmailToken(
        binding_hash=source.binding_hash,
        pending_password_hash=source.pending_password_hash,
        pending_role=source.pending_role,
        pending_consent_version=source.pending_consent_version,
        pending_consent_sha256=source.pending_consent_sha256,
        pending_consented_at=source.pending_consented_at,
        pending_is_adult=source.pending_is_adult,
    )
    _send_verification(db, user, application, now)


def _same(left: str, right: str) -> bool:
    return security.constant_time_equals(left, right)


# --------------------------------------------------------------------------------------------------------------------
# Подтверждение адреса
# --------------------------------------------------------------------------------------------------------------------


def _take_token(db: Session, token: str, purpose: str, now: datetime) -> EmailToken:
    """Найти и заблокировать токен письма; 400 `token_invalid` (нет, использован) или `token_expired`.

    Блокировка строки делает токен одноразовым и при двух одновременных запросах: второй дождётся первого
    и увидит `used_at`.
    """
    row = db.scalar(
        select(EmailToken)
        .where(EmailToken.token_hash == security.hash_token(token), EmailToken.purpose == purpose)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None or row.used_at is not None:
        raise _error(400, "token_invalid")
    if row.expires_at <= now:
        raise _error(400, "token_expired")
    return row


def _lock_user(db: Session, user_id: UUID) -> AppUser | None:
    statement = select(AppUser).where(AppUser.id == user_id).with_for_update(key_share=True)
    return db.scalar(statement.execution_options(populate_existing=True))


def verify_email(
    db: Session, *, token: str, password: str | None, reg_cookie: str | None, user_agent: str | None
) -> tuple[AppUser, str]:
    """`POST /auth/verify-email`: подтвердить адрес и открыть сессию (Арх. 10.2). Возвращает аккаунт и токен `sid`.

    Правило допуска: запрос шлёт сам регистрировавшийся, если хэш cookie `reg` равен `binding_hash` заявки
    **или** пароль из тела совпал с паролем заявки. Нет ни того, ни другого — 409 `password_required`
    (экран попросит пароль); пароль не совпал — 401 `invalid_credentials`.

    При успехе аккаунт получает пароль, роль, согласие на обработку и отметку 18+ именно этой заявки, а остальные
    токены подтверждения адреса гасятся. Строка `consent` создаётся только здесь: согласие того, кто заявку
    не подтвердил, нигде не остаётся (поправка R3-data-api-security-2).
    """
    now = clock.real_now()
    application = _take_token(db, token, PURPOSE_VERIFY_EMAIL, now)
    user = _lock_user(db, application.user_id)
    if user is None or user.email_verified_at is not None or not application.pending_password_hash:
        raise _error(400, "token_invalid")

    by_cookie = bool(
        reg_cookie and application.binding_hash and _same(security.hash_token(reg_cookie), application.binding_hash)
    )
    if not by_cookie:
        if password is None:
            raise _error(409, "password_required")
        if not security.verify_password(password, application.pending_password_hash):
            raise ApiException(401, "invalid_credentials", MESSAGES["password_mismatch"])

    user.password_hash = application.pending_password_hash
    user.role = application.pending_role or user.role
    user.email_verified_at = now
    user.is_adult_confirmed = bool(application.pending_is_adult)
    application.used_at = now
    db.execute(
        update(EmailToken)
        .where(
            EmailToken.user_id == user.id,
            EmailToken.purpose == PURPOSE_VERIFY_EMAIL,
            EmailToken.used_at.is_(None),
            EmailToken.id != application.id,
        )
        .values(used_at=now)
    )
    db.flush()
    if application.pending_consent_version and application.pending_consent_sha256:
        service.grant_consent(
            db,
            user.id,
            ConsentKind.PROCESSING,
            application.pending_consent_version,
            application.pending_consent_sha256,
            CONSENT_SOURCE_USER,
            application.pending_consented_at or now,
        )
    service.audit(db, "email_verified", actor_user_id=user.id, target_user_id=user.id, params={"role": user.role})
    return user, service.open_session(db, user.id, user_agent=user_agent)


# --------------------------------------------------------------------------------------------------------------------
# Вход и выход
# --------------------------------------------------------------------------------------------------------------------


def _burn_time(password: str) -> None:
    """Сверить пароль с заведомо чужим хешем: время ответа не зависит от того, есть ли такой адрес."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = security.hash_password(security.new_token())
    security.verify_password(password, _dummy_hash)


def _password_matches(db: Session, user: AppUser | None, password: str, now: datetime) -> bool:
    """Совпал ли пароль с паролем аккаунта, а для неподтверждённого адреса — с паролем действующей заявки.

    До подтверждения у аккаунта своего пароля нет (Арх. 10.2), поэтому сверяются последние
    `LOGIN_PENDING_APPLICATIONS_CHECKED` непросроченных заявок. Число ограничено: каждая сверка — расчёт Argon2,
    и регистрации на чужой адрес не должны превращать его вход в дорогую операцию.
    """
    if user is None:
        _burn_time(password)
        return False
    if user.email_verified_at is not None:
        return security.verify_password(password, user.password_hash)
    hashes: list[str] = [user.password_hash] if user.password_hash else []
    hashes += [
        value
        for value in db.scalars(
            select(EmailToken.pending_password_hash)
            .where(
                EmailToken.user_id == user.id,
                EmailToken.purpose == PURPOSE_VERIFY_EMAIL,
                EmailToken.used_at.is_(None),
                EmailToken.expires_at > now,
            )
            .order_by(EmailToken.created_at.desc())
            .limit(LOGIN_PENDING_APPLICATIONS_CHECKED)
        )
        if value
    ]
    if not hashes:
        _burn_time(password)
        return False
    return any(security.verify_password(password, value) for value in hashes)


def login(db: Session, *, email: str, password: str, ip: str, user_agent: str | None) -> tuple[AppUser, str]:
    """`POST /auth/login`: проверить пару и открыть сессию (Арх. 10.1). Возвращает аккаунт и токен `sid`.

    Порядок проверок: лимиты → пароль → подтверждение адреса.

    * Лимиты раздельные: `LOGIN_MAX_FAILURES_PER_EMAIL` неудач за 15 минут на адрес (с любых IP) либо
      `LOGIN_MAX_FAILURES_PER_IP` с одного IP (на любые адреса) — следующая попытка получает 429.
    * Неверная пара — 401 `invalid_credentials` с одним текстом для несуществующего адреса, неверного пароля
      и неподтверждённого адреса с чужим паролем. Попытка остаётся в `login_attempt`: ошибка поднимается
      с `commit=True`.
    * Верный пароль при неподтверждённом адресе — 403 `email_not_verified`.
    """
    address_hash = emails.email_hash(email)
    limits.failures_guard(
        db, KIND_LOGIN, email_hash=address_hash, max_failures=LOGIN_MAX_FAILURES_PER_EMAIL, window=LOGIN_WINDOW
    )
    limits.failures_guard(db, KIND_LOGIN, ip=ip, max_failures=LOGIN_MAX_FAILURES_PER_IP, window=LOGIN_WINDOW)

    now = clock.real_now()
    user = _find_user(db, email)
    if not _password_matches(db, user, password, now):
        limits.record_attempt(db, KIND_LOGIN, email_hash=address_hash, ip=ip, ok=False)
        if user is not None:
            service.audit(db, "login_failed", target_user_id=user.id)
        raise _error(401, "invalid_credentials", commit=True)
    assert user is not None
    if user.email_verified_at is None:
        raise _error(403, "email_not_verified")

    limits.record_attempt(db, KIND_LOGIN, email_hash=address_hash, ip=ip, ok=True)
    token = service.open_session(db, user.id, user_agent=user_agent)
    service.audit(db, "login", actor_user_id=user.id, target_user_id=user.id)
    return user, token


def logout(db: Session, user: CurrentUser) -> None:
    """`POST /auth/logout`: удалить строку текущей сессии — токен из cookie после этого бесполезен."""
    db.execute(delete(AuthSession).where(AuthSession.id == user.session_id))
    service.audit(db, "logout", actor_user_id=user.id, target_user_id=user.id)


# --------------------------------------------------------------------------------------------------------------------
# Пароли
# --------------------------------------------------------------------------------------------------------------------


def check_current_password(db: Session, user: CurrentUser, password: str, *, field: str, ip: str | None) -> AppUser:
    """Сверить пароль вошедшего пользователя (смена пароля, удаление аккаунта); вернуть заблокированную строку.

    Неверный пароль — 422 `current_password_invalid` с ошибкой поля `field`. Неудачи считаются: после
    `PASSWORD_CHECK_MAX_FAILURES` за 15 минут — 429, чтобы украденная сессия не давала подбирать пароль.
    """
    address_hash = emails.email_hash(user.email)
    limits.failures_guard(
        db,
        KIND_PASSWORD_CHECK,
        email_hash=address_hash,
        max_failures=PASSWORD_CHECK_MAX_FAILURES,
        window=PASSWORD_CHECK_WINDOW,
    )
    account = _lock_user(db, user.id)
    if account is None:
        raise ApiException(401, "not_authenticated")
    if not security.verify_password(password, account.password_hash):
        limits.record_attempt(db, KIND_PASSWORD_CHECK, email_hash=address_hash, ip=ip, ok=False)
        code = "current_password_invalid"
        raise ApiException(422, code, MESSAGES[code], fields=[field_error(field, code, MESSAGES[code])], commit=True)
    return account


def _void_reset_tokens(db: Session, user_id: UUID, now: datetime) -> None:
    db.execute(
        update(EmailToken)
        .where(
            EmailToken.user_id == user_id,
            EmailToken.purpose == PURPOSE_RESET_PASSWORD,
            EmailToken.used_at.is_(None),
        )
        .values(used_at=now)
    )


def change_password(
    db: Session, user: CurrentUser, *, current_password: str, new_password: str, ip: str | None
) -> None:
    """`POST /auth/password`: сменить пароль; остальные сессии пользователя удаляются (Арх. 10.1).

    У демо-аккаунта пароль публичный и не меняется: 403 `demo_account_readonly` (Арх. 10.3).
    """
    if user.is_demo:
        raise _demo_readonly()
    account = check_current_password(db, user, current_password, field="current_password", ip=ip)
    now = clock.real_now()
    account.password_hash = security.hash_password(new_password)
    db.flush()
    service.close_sessions(db, user.id, keep_session_id=user.session_id)
    _void_reset_tokens(db, user.id, now)
    service.audit(db, "password_changed", actor_user_id=user.id, target_user_id=user.id)


def forgot_password(db: Session, *, email: str, ip: str) -> None:
    """`POST /auth/password/forgot`: письмо со ссылкой сброса; ответ 202 для любого адреса (Арх. 10.2).

    Письмо уходит, только если аккаунт существует, адрес подтверждён и аккаунт не демо; не больше трёх писем
    в час на адрес. Токен живёт час и срабатывает один раз.
    """
    limits.throttle(db, KIND_PASSWORD_FORGOT, ip=ip, limit=FORGOT_IP_LIMIT_PER_HOUR, window_s=IP_WINDOW_S)
    user = _find_user(db, email)
    if user is None or user.email_verified_at is None or user.is_demo:
        return
    if not _mail_allowed(db, KIND_PASSWORD_RESET_MAIL, emails.email_hash(email)):
        return
    now = clock.real_now()
    token = security.new_token()
    db.add(
        EmailToken(
            user_id=user.id,
            purpose=PURPOSE_RESET_PASSWORD,
            token_hash=security.hash_token(token),
            created_at=now,
            expires_at=now + RESET_TOKEN_TTL,
        )
    )
    db.flush()
    mail.enqueue(
        db,
        "password_reset",
        to=user.email,
        context={
            "link": _link("/password/reset", token),
            "expires_minutes": int(RESET_TOKEN_TTL.total_seconds() // 60),
        },
    )
    service.audit(db, "password_reset_requested", target_user_id=user.id)


def reset_password(db: Session, *, token: str, new_password: str) -> None:
    """`POST /auth/password/reset`: задать новый пароль по ссылке из письма (Арх. 10.2).

    Токен гасится (вместе с остальными ссылками сброса этого аккаунта), все сессии пользователя удаляются.
    """
    now = clock.real_now()
    row = _take_token(db, token, PURPOSE_RESET_PASSWORD, now)
    user = _lock_user(db, row.user_id)
    if user is None or user.email_verified_at is None:
        raise _error(400, "token_invalid")
    if user.is_demo:
        raise _demo_readonly()
    user.password_hash = security.hash_password(new_password)
    db.flush()
    _void_reset_tokens(db, user.id, now)
    service.close_sessions(db, user.id)
    service.audit(db, "password_reset", target_user_id=user.id)


# --------------------------------------------------------------------------------------------------------------------
# Удаление аккаунта
# --------------------------------------------------------------------------------------------------------------------


def authorize_account_deletion(db: Session, user: CurrentUser, *, password: str, ip: str | None) -> None:
    """Проверки перед `POST /auth/account/delete`: демо-аккаунт — 403, неверный пароль — 422 (Арх. 9.4, 10.3).

    Само удаление — `service.remove_user`; эндпоинт выполняет его через `run_in_tx`, чтобы взаимная блокировка
    с параллельной операцией над данными этого аккаунта привела к повтору, а не к ошибке.
    """
    if user.is_demo:
        raise _demo_readonly()
    check_current_password(db, user, password, field="password", ip=ip)
