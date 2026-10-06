"""Эндпоинты `identity` (Арх. 9.4): `/auth/*` и `/legal/{doc}`.

Обработчики тонкие: разбор запроса, cookie и вызов сценария из `accounts.py`. Транзакцию фиксирует `TxRoute`
до отправки ответа; письма уходят после фиксации (Арх. 2.4, п. 4).

Ответы 202 и 204 — без тела (`response_class=Response`). Cookie выставляются на внедрённом объекте `response`,
а не на собственном ответе: только так к ответу добавляется и cookie продлённой сессии из `core.deps`.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Request, Response

from app.core import security
from app.core.config import get_settings
from app.core.db import TxRoute, run_in_tx
from app.core.deps import AnyUser, ClientIp, Db, Now
from app.core.errors import error_responses, not_found
from app.modules.identity import accounts, legal, service
from app.modules.identity.constants import REGISTRATION_COOKIE_PATH, REGISTRATION_COOKIE_TTL
from app.modules.identity.models import AppUser
from app.modules.identity.schemas import (
    AccountDeleteRequest,
    EmailRequest,
    LegalDocView,
    LoginRequest,
    MeView,
    PasswordChangeRequest,
    PasswordResetRequest,
    SignupRequest,
    VerifyEmailRequest,
)
from app.shared.enums import Role

router = APIRouter(route_class=TxRoute)

_REG_COOKIE_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")

_ACCEPTED: dict[int | str, dict[str, Any]] = {202: {"description": "Принято; ответ одинаков для любого адреса"}}
_NO_CONTENT: dict[int | str, dict[str, Any]] = {204: {"description": "Выполнено"}}


def _registration_cookie(request: Request) -> str | None:
    """Значение cookie `reg` из запроса, если оно похоже на выданное нами."""
    value = request.cookies.get(security.REGISTRATION_COOKIE)
    return value if value and _REG_COOKIE_RE.fullmatch(value) else None


def _set_registration_cookie(response: Response, value: str) -> None:
    response.set_cookie(
        security.REGISTRATION_COOKIE,
        value,
        max_age=int(REGISTRATION_COOKIE_TTL.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=get_settings().cookie_secure,
        path=REGISTRATION_COOKIE_PATH,
    )


def _clear_registration_cookie(response: Response) -> None:
    response.delete_cookie(
        security.REGISTRATION_COOKIE,
        path=REGISTRATION_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=get_settings().cookie_secure,
    )


def _me(user: AppUser, now: Any) -> MeView:
    return MeView(id=user.id, email=user.email, role=Role(user.role), is_demo=user.is_demo, server_now=now)


# --------------------------------------------------------------------------------------------------------------------
# Регистрация и подтверждение адреса
# --------------------------------------------------------------------------------------------------------------------


@router.post(
    "/auth/signup",
    status_code=202,
    response_class=Response,
    responses={**_ACCEPTED, **error_responses(422, 429)},
    summary="Регистрация: письмо со ссылкой подтверждения",
)
def signup(body: SignupRequest, request: Request, response: Response, db: Db, ip: ClientIp) -> None:
    """Ответ 202 одинаков для нового, занятого и недавно удалённого адреса — включая cookie `reg`."""
    # Браузер, уже начинавший регистрацию, сохраняет свою cookie: обе его заявки подтверждаются без пароля.
    reg = _registration_cookie(request) or security.new_token()
    accounts.signup(
        db,
        email=body.email,
        password=body.password,
        role=body.role,
        consent_version=body.consent_version,
        ip=ip,
        binding_hash=security.hash_token(reg),
    )
    _set_registration_cookie(response, reg)


@router.post(
    "/auth/resend-verification",
    status_code=202,
    response_class=Response,
    responses={**_ACCEPTED, **error_responses(422, 429)},
    summary="Повторная отправка письма подтверждения",
)
def resend_verification(body: EmailRequest, request: Request, db: Db, ip: ClientIp) -> None:
    accounts.resend_verification(db, email=body.email, ip=ip, reg_cookie=_registration_cookie(request))


@router.post(
    "/auth/verify-email",
    response_model=MeView,
    responses=error_responses(400, 401, 409, 422),
    summary="Подтверждение адреса: открывает сессию",
)
def verify_email(body: VerifyEmailRequest, request: Request, response: Response, db: Db, now: Now) -> MeView:
    """400 `token_invalid`, `token_expired`; 401 `invalid_credentials` — пароль заявки не подошёл;
    409 `password_required` — ссылку открыли не в браузере регистрации, нужен пароль заявки.
    """
    user, token = accounts.verify_email(
        db,
        token=body.token,
        password=body.password,
        reg_cookie=_registration_cookie(request),
        user_agent=request.headers.get("user-agent"),
    )
    security.set_session_cookie(response, token)
    _clear_registration_cookie(response)
    return _me(user, now)


# --------------------------------------------------------------------------------------------------------------------
# Вход, выход, текущий пользователь
# --------------------------------------------------------------------------------------------------------------------


@router.post(
    "/auth/login",
    response_model=MeView,
    responses=error_responses(401, 403, 422, 429),
    summary="Вход по адресу и паролю",
)
def login(body: LoginRequest, request: Request, response: Response, db: Db, now: Now, ip: ClientIp) -> MeView:
    """401 `invalid_credentials`; 403 `email_not_verified` — пароль верный, но адрес не подтверждён; 429 — лимит."""
    user, token = accounts.login(
        db, email=body.email, password=body.password, ip=ip, user_agent=request.headers.get("user-agent")
    )
    security.set_session_cookie(response, token)
    return _me(user, now)


@router.post(
    "/auth/logout",
    status_code=204,
    response_class=Response,
    responses={**_NO_CONTENT, **error_responses(401)},
    summary="Выход: удаляет сессию",
)
def logout(user: AnyUser, response: Response, db: Db) -> None:
    accounts.logout(db, user)
    security.clear_session_cookie(response)


@router.get("/auth/me", response_model=MeView, responses=error_responses(401), summary="Текущий пользователь")
def me(user: AnyUser, now: Now) -> MeView:
    return MeView(id=user.id, email=user.email, role=user.role, is_demo=user.is_demo, server_now=now)


# --------------------------------------------------------------------------------------------------------------------
# Пароли
# --------------------------------------------------------------------------------------------------------------------


@router.post(
    "/auth/password",
    status_code=204,
    response_class=Response,
    responses={**_NO_CONTENT, **error_responses(401, 403, 422, 429)},
    summary="Смена пароля; остальные сессии удаляются",
)
def change_password(body: PasswordChangeRequest, user: AnyUser, db: Db, ip: ClientIp) -> None:
    """403 `demo_account_readonly`; 422 `current_password_invalid`; 429 — слишком много неверных паролей."""
    accounts.change_password(db, user, current_password=body.current_password, new_password=body.new_password, ip=ip)


@router.post(
    "/auth/password/forgot",
    status_code=202,
    response_class=Response,
    responses={**_ACCEPTED, **error_responses(422, 429)},
    summary="Запрос ссылки сброса пароля",
)
def forgot_password(body: EmailRequest, db: Db, ip: ClientIp) -> None:
    accounts.forgot_password(db, email=body.email, ip=ip)


@router.post(
    "/auth/password/reset",
    status_code=204,
    response_class=Response,
    responses={**_NO_CONTENT, **error_responses(400, 403, 422)},
    summary="Новый пароль по ссылке из письма; все сессии удаляются",
)
def reset_password(body: PasswordResetRequest, response: Response, db: Db) -> None:
    """400 `token_invalid`, `token_expired`."""
    accounts.reset_password(db, token=body.token, new_password=body.new_password)
    security.clear_session_cookie(response)  # сессия этого браузера, если была, тоже удалена


# --------------------------------------------------------------------------------------------------------------------
# Удаление аккаунта
# --------------------------------------------------------------------------------------------------------------------


@router.post(
    "/auth/account/delete",
    status_code=204,
    response_class=Response,
    responses={**_NO_CONTENT, **error_responses(401, 403, 422, 429)},
    summary="Отзыв согласия на обработку и немедленное удаление аккаунта",
)
def delete_account(body: AccountDeleteRequest, user: AnyUser, response: Response, db: Db, ip: ClientIp) -> None:
    """403 `demo_account_readonly`; 422 `current_password_invalid`; 429 — слишком много неверных паролей."""
    accounts.authorize_account_deletion(db, user, password=body.password, ip=ip)
    user_id = user.id
    # Каскад затрагивает таблицы всех модулей; при взаимной блокировке с их операциями удаление повторяется один раз.
    run_in_tx(db, lambda session: service.remove_user(session, user_id, actor_user_id=user_id))
    security.clear_session_cookie(response)


# --------------------------------------------------------------------------------------------------------------------
# Тексты согласий
# --------------------------------------------------------------------------------------------------------------------


@router.get(
    "/legal/{doc}",
    response_model=LegalDocView,
    responses=error_responses(404),
    summary="Текст согласия или политики: processing, publication, privacy",
)
def legal_doc(doc: str) -> LegalDocView:
    text = legal.get_doc(doc)
    if text is None:
        raise not_found()
    return LegalDocView(doc=doc, version=text.version, title=text.title, text=text.text, sha256=text.sha256)
