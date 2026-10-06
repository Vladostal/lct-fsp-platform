"""Демо-провайдер ФСП ID: страница входа, выдача и погашение кода авторизации, PKCE (Арх. 7.3; приложение D, §2.6).

Поток — authorization code + PKCE S256. Код — случайные 32 байта, в базе только SHA-256, срок 60 секунд,
одноразовый. Пароль на странице входа не спрашивается: роль настоящего ФСП ID играет выбор персонажа.
"""

from __future__ import annotations

import base64
import hashlib
import random
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from uuid import UUID, uuid4

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.fsp_mock import reference as ref
from app.fsp_mock.models import AccessGrant, Athlete, AuthCode
from app.fsp_mock.personas import PERSONAS, persona_fsp_id
from app.fsp_mock.registry_service import (
    GRANT_SOURCE_OIDC,
    free_adult_athletes,
    purge_expired_codes,
    register_grant,
)

CALLBACK_PATH = "/api/v1/fsp/link/callback"
REQUIRED_PARAMS = ("client_id", "redirect_uri", "response_type", "state", "nonce", "code_challenge")
PICKS = ("random_free_with_history", "random_free_empty", "new_account")

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
)


class AuthorizeError(Exception):
    """Некорректный запрос авторизации: показывается страницей ошибки, редиректа нет (иначе открытый редирект)."""


class InvalidGrant(Exception):
    """Код недействителен: нет, уже использован, просрочен, другой `redirect_uri` или не сошёлся PKCE."""


@dataclass(frozen=True, slots=True)
class RedeemedCode:
    fsp_id: UUID
    nonce: str
    scope: str


def expected_redirect_uri() -> str:
    """Единственный допустимый `redirect_uri` — из настройки, никогда из запроса."""
    return get_settings().public_base_url.rstrip("/") + CALLBACK_PATH


def validate_authorize_params(params: Mapping[str, str | None]) -> dict[str, str]:
    """Проверить параметры запроса авторизации; вернуть их очищенную копию либо `AuthorizeError`."""
    missing = [name for name in REQUIRED_PARAMS if not params.get(name)]
    if missing:
        raise AuthorizeError("Не хватает параметров запроса: " + ", ".join(missing))
    if params.get("response_type") != "code":
        raise AuthorizeError("Поддерживается только response_type=code")
    if params.get("client_id") != ref.CLIENT_ID:
        raise AuthorizeError("Неизвестный клиент")
    if params.get("redirect_uri") != expected_redirect_uri():
        raise AuthorizeError("redirect_uri не совпадает с зарегистрированным")
    if params.get("code_challenge_method") != "S256":
        raise AuthorizeError("Поддерживается только code_challenge_method=S256")
    scope = params.get("scope") or ref.SCOPE
    clean = {name: str(params[name]) for name in (*REQUIRED_PARAMS, "code_challenge_method")}
    clean["scope"] = scope
    return clean


def pick_fsp_id(db: Session, pick: str) -> UUID:
    """Быстрый выбор на странице входа: случайный свободный участник с историей, без участий либо новый ФСП ID."""
    if pick == "new_account":
        return uuid4()
    candidates = [fsp_id for fsp_id, _ in free_adult_athletes(db, with_history=pick == "random_free_with_history")]
    if not candidates:
        raise AuthorizeError("Свободных участников такого вида не осталось")
    return random.SystemRandom().choice(candidates)


def persona_cards(db: Session, *, show_all: bool) -> list[dict[str, Any]]:
    """Карточки персонажей для страницы входа: имя, описание, метка «свободен» / «уже привязан»."""
    granted = set(db.scalars(select(AccessGrant.fsp_id).where(AccessGrant.revoked_at.is_(None))))
    existing = set(db.scalars(select(Athlete.fsp_id).where(Athlete.persona_key.is_not(None))))
    cards = []
    for persona in PERSONAS:
        fsp_id = persona_fsp_id(persona.key)
        if fsp_id not in existing or (persona.hidden and not show_all):
            continue
        cards.append(
            {
                "fsp_id": str(fsp_id),
                "name": f"{persona.first_name} {persona.last_name}",
                "description": persona.description,
                "busy": fsp_id in granted,
            }
        )
    return cards


def render_authorize(db: Session, params: dict[str, str], *, show_all: bool = False) -> str:
    return _env.get_template("authorize.html").render(
        params=params,
        personas=persona_cards(db, show_all=show_all),
        picks={
            "with_history": "random_free_with_history",
            "empty": "random_free_empty",
            "new": "new_account",
        },
    )


def render_error(message: str) -> str:
    return _env.get_template("error.html").render(message=message)


def hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def pkce_challenge(code_verifier: str) -> str:
    """`base64url(sha256(code_verifier))` без `=`."""
    digest = hashlib.sha256(code_verifier.encode("ascii", "ignore")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def issue_code(db: Session, *, fsp_id: UUID, params: Mapping[str, str], now: datetime) -> str:
    """Выдать код авторизации (32 случайных байта; в базе — SHA-256) и вернуть его значение."""
    purge_expired_codes(db, now)
    code = secrets.token_urlsafe(32)
    db.add(
        AuthCode(
            code_hash=hash_code(code),
            fsp_id=fsp_id,
            client_id=params["client_id"],
            redirect_uri=params["redirect_uri"],
            scope=params.get("scope") or ref.SCOPE,
            nonce=params["nonce"],
            code_challenge=params["code_challenge"],
            expires_at=now + timedelta(seconds=ref.AUTH_CODE_TTL_SECONDS),
        )
    )
    db.flush()
    return code


def redirect_url(redirect_uri: str, **query: str) -> str:
    return f"{redirect_uri}?{urlencode(query)}"


def redeem_code(
    db: Session, *, code: str, code_verifier: str, redirect_uri: str, client_id: str, now: datetime
) -> RedeemedCode:
    """Погасить код: существует, не использован, не истёк, `redirect_uri` совпадает, PKCE сходится.

    Код гасится атомарным `UPDATE … WHERE used_at IS NULL`, поэтому повторное предъявление (в том числе
    параллельное) не проходит. Код, предъявленный с неверным `code_verifier`, остаётся погашенным.
    """
    code_hash = hash_code(code)
    row = db.execute(select(AuthCode).where(AuthCode.code_hash == code_hash)).scalar_one_or_none()
    if row is None:
        raise InvalidGrant("код не найден")
    claimed = db.execute(
        update(AuthCode)
        .where(AuthCode.code_hash == code_hash, AuthCode.used_at.is_(None), AuthCode.expires_at > now)
        .values(used_at=now)
        .returning(AuthCode.code_hash)
        .execution_options(synchronize_session=False)
    ).first()
    if claimed is None:
        raise InvalidGrant("код уже использован или просрочен")
    # Код погашен до проверок: попытка с чужим redirect_uri или неверным code_verifier сжигает его, а не оставляет
    # для повторного подбора. Фиксируем погашение, даже если ниже поднимется ошибка.
    db.commit()
    if row.client_id != client_id or row.redirect_uri != redirect_uri:
        raise InvalidGrant("redirect_uri или клиент не совпадают с запросом авторизации")
    if not secrets.compare_digest(pkce_challenge(code_verifier), row.code_challenge):
        raise InvalidGrant("code_verifier не соответствует code_challenge")
    # Согласие дано на странице входа: разрешение «спортсмен → клиент» выдаётся в потоке входа, а не ждёт выгрузки.
    # Иначе при недоступном реестре в момент привязки следующая выгрузка сервисным токеном получила бы
    # `grant_required` и отвязала бы только что привязанного человека.
    register_grant(db, row.fsp_id, client_id, GRANT_SOURCE_OIDC, now)
    return RedeemedCode(fsp_id=row.fsp_id, nonce=row.nonce, scope=row.scope)
