"""Константы модуля `identity`: сроки токенов и лимиты (Арх. 10.1, 10.2, 10.5).

Все сроки и окна считаются по реальному времени (`clock.real_now()`): демо-сдвиг часов на вход, токены и лимиты
не действует (Арх. 2.4, п. 5).
"""

from __future__ import annotations

from datetime import timedelta

from app.core.config import get_settings

# --- пароль и адрес -------------------------------------------------------------------------------------------------
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
EMAIL_MAX_LENGTH = 254

# --- токены ---------------------------------------------------------------------------------------------------------
VERIFY_TOKEN_TTL = timedelta(hours=24)
RESET_TOKEN_TTL = timedelta(hours=1)
#: Срок cookie `reg` браузера, начавшего регистрацию: не меньше срока ссылки подтверждения.
REGISTRATION_COOKIE_TTL = VERIFY_TOKEN_TTL
#: Cookie `reg` нужна только эндпоинтам `/auth/*`; на остальные запросы браузер её не шлёт.
REGISTRATION_COOKIE_PATH = "/api/v1/auth"

# --- виды строк журнала лимитов `login_attempt.kind` ----------------------------------------------------------------
KIND_LOGIN = "login"
KIND_SIGNUP = "signup"
KIND_VERIFY_MAIL = "verify_mail"
KIND_ALREADY_REGISTERED_MAIL = "already_registered_mail"
KIND_PASSWORD_RESET_MAIL = "password_reset_mail"
KIND_REREGISTER_COOLDOWN_MAIL = "reregister_cooldown_mail"
KIND_ACCOUNT_DELETED = "account_deleted"
KIND_RESEND_VERIFICATION = "resend_verification"
KIND_PASSWORD_FORGOT = "password_forgot"
KIND_PASSWORD_CHECK = "password_check"

# --- вход (Арх. 10.1) -----------------------------------------------------------------------------------------------
LOGIN_WINDOW = timedelta(minutes=15)
#: Столько неудачных попыток на адрес (с любых IP) допускается за окно; следующая попытка — 429.
LOGIN_MAX_FAILURES_PER_EMAIL = 10
#: Столько неудачных попыток с одного IP (на любые адреса) допускается за окно.
LOGIN_MAX_FAILURES_PER_IP = 30
#: С паролями скольких последних заявок сверяется вход неподтверждённого адреса: каждая сверка — расчёт Argon2.
LOGIN_PENDING_APPLICATIONS_CHECKED = 5

# --- проверка текущего пароля в сессии (смена пароля, удаление аккаунта) ---------------------------------------------
PASSWORD_CHECK_WINDOW = timedelta(minutes=15)
PASSWORD_CHECK_MAX_FAILURES = 10

# --- письма (Арх. 10.1, 10.2) ---------------------------------------------------------------------------------------
MAIL_WINDOW = timedelta(hours=1)
MAILS_PER_ADDRESS_PER_HOUR = 3
#: Письма подтверждения на один адрес — не чаще этого интервала (регистрация и повторная отправка вместе).
VERIFY_MAIL_MIN_INTERVAL = timedelta(seconds=60)

# --- лимиты по IP для эндпоинтов без входа (ответ 429) ---------------------------------------------------------------
IP_WINDOW_S = 3600
RESEND_IP_LIMIT_PER_HOUR = 30
FORGOT_IP_LIMIT_PER_HOUR = 30

# --- неподтверждённые адреса ----------------------------------------------------------------------------------------
#: Заготовка аккаунта без подтверждения адреса и без действующих заявок удаляется через этот срок: адрес почты —
#: персональные данные, держать его бессрочно незачем. Срок равен хранению технических журналов (Арх. 10.5).
UNVERIFIED_ACCOUNT_TTL = timedelta(days=30)

# --- что видит интерфейс --------------------------------------------------------------------------------------------
#: Числа для `Catalog.limits` (Арх. 2.6): срок карантина адреса называет диалог удаления аккаунта (C14, E10).
PUBLIC_LIMITS: dict[str, int | float] = {
    "reregister_cooldown_days": get_settings().reregister_cooldown_days,
}
