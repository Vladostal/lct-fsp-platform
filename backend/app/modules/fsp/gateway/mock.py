"""Адаптер `MockFspGateway`: вызовы в процессе к демо-ФСП (Арх. 7.3; приложение D, §2.5).

Единственный файл платформы, который знает про `app.fsp_mock` (контракт import-linter). Мок ведёт себя как внешняя
система: на каждый вызов открывает собственную короткую сессию БД и не участвует в транзакции платформы. Ответы
реестра проходят тот же разбор моделями контракта, что и HTTP-ответы настоящего реестра, поэтому расхождения схемы
видны и в демонстрационном режиме.
"""

from __future__ import annotations

import hmac
import json
from collections.abc import Sequence
from contextlib import suppress
from datetime import date
from typing import Any, Literal
from urllib.parse import urlencode
from uuid import UUID

from pydantic import ValidationError

from app.core.config import get_settings
from app.fsp_mock import oidc, registry_service
from app.fsp_mock import reference as mock_ref
from app.fsp_mock.personas import persona_fsp_id
from app.fsp_mock.registry_service import Caller, RegistryError, RegistryMalformed, registry_session
from app.modules.fsp import constants as c
from app.modules.fsp.gateway.base import (
    AthleteExport,
    AuthorizationRequest,
    Competition,
    ExportNotModified,
    ExportNotRegistered,
    ExportOk,
    ExportResult,
    FspAuthError,
    FspContractError,
    FspGrantRevoked,
    FspIdentity,
    FspUnavailable,
)

TOKEN_PREFIX = "mock-user:"
_GRANT_CODES = frozenset({"grant_required", "grant_revoked"})


def _map_error(exc: RegistryError) -> Exception:
    """Ошибка контракта реестра → исключение шлюза (Арх. 7.3)."""
    if exc.status in (429, 500, 502, 503, 504):
        return FspUnavailable(exc.code, exc.retry_after)
    if exc.status == 403 and exc.code in _GRANT_CODES:
        return FspGrantRevoked(exc.code)
    if exc.status in (401, 403):
        return FspAuthError(exc.code)
    return FspContractError(f"{exc.status} {exc.code}")


class MockFspGateway:
    """Демо-провайдер ФСП ID и демо-реестр внутри процесса `api`."""

    mode: Literal["mock", "keycloak"] = "mock"

    @property
    def issuer(self) -> str:
        return c.MOCK_ISSUER

    @property
    def registry_url(self) -> str:
        return get_settings().public_base_url.rstrip("/") + "/api/fsp-mock/registry/v1"

    def authorization_url(self, req: AuthorizationRequest) -> str:
        query = urlencode(
            {
                "response_type": "code",
                "client_id": mock_ref.CLIENT_ID,
                "redirect_uri": req.redirect_uri,
                "scope": req.scope,
                "state": req.state,
                "nonce": req.nonce,
                "code_challenge": req.code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{get_settings().public_base_url.rstrip('/')}/api/fsp-mock/oidc/authorize?{query}"

    def exchange_code(self, *, code: str, code_verifier: str, redirect_uri: str, nonce: str) -> FspIdentity:
        from app.core import clock

        try:
            with registry_session() as db:
                redeemed = oidc.redeem_code(
                    db,
                    code=code,
                    code_verifier=code_verifier,
                    redirect_uri=redirect_uri,
                    client_id=mock_ref.CLIENT_ID,
                    now=clock.real_now(),
                )
        except oidc.InvalidGrant as exc:
            raise FspAuthError(str(exc)) from exc
        if not hmac.compare_digest(redeemed.nonce.encode(), nonce.encode()):
            raise FspAuthError("nonce не совпадает")
        fsp_id = str(redeemed.fsp_id)
        return FspIdentity(issuer=c.MOCK_ISSUER, subject=fsp_id, fsp_id=fsp_id, user_token=f"{TOKEN_PREFIX}{fsp_id}")

    def fetch_export(self, fsp_id: str, *, user_token: str | None = None, etag: str | None = None) -> ExportResult:
        try:
            target = UUID(fsp_id)
        except ValueError as exc:
            raise FspContractError("некорректный fsp_id") from exc
        caller = Caller(kind="service")
        if user_token is not None:
            if not user_token.startswith(TOKEN_PREFIX):
                raise FspAuthError("пользовательский токен не распознан")
            try:
                caller = Caller(kind="user", fsp_id=UUID(user_token[len(TOKEN_PREFIX) :]))
            except ValueError as exc:
                raise FspAuthError("пользовательский токен не распознан") from exc
        try:
            with registry_session() as db:
                result = registry_service.export(db, target, caller, if_none_match=etag, in_process=True)
        except RegistryMalformed as exc:
            raise FspContractError("ответ реестра не по контракту") from exc
        except RegistryError as exc:
            if exc.status == 404 and exc.code == "athlete_not_found":
                return ExportNotRegistered()
            raise _map_error(exc) from exc
        if isinstance(result, registry_service.ExportNotModified):
            return ExportNotModified()
        raw: dict[str, Any] = result.body
        if len(json.dumps(raw, ensure_ascii=False)) > c.MAX_EXPORT_BYTES:
            raise FspContractError("выгрузка больше 2 МБ")
        try:
            export = AthleteExport.model_validate(raw)
        except ValidationError as exc:
            raise FspContractError("выгрузка не проходит схему") from exc
        return ExportOk(export=export, etag=result.etag, raw=raw, api_version=mock_ref.REGISTRY_VERSION)

    def revoke_grant(self, fsp_id: str) -> None:
        from app.core import clock

        try:
            with registry_session() as db:
                # Недоступный реестр не принимает и отзыв: отвязка и удаление аккаунта от него не зависят.
                with suppress(RegistryMalformed):
                    registry_service.check_failure_mode(db, in_process=True)
                registry_service.revoke_grant(db, UUID(fsp_id), mock_ref.CLIENT_ID, clock.real_now())
        except (ValueError, RegistryError) as exc:
            raise FspUnavailable("не удалось снять разрешение") from exc

    def seed_grant(self, fsp_id: str) -> None:
        """Разрешение «спортсмен → клиент», созданное сидом платформы (`access_grant.source = 'seed'`)."""
        from app.core import clock

        with registry_session() as db:
            registry_service.register_grant(
                db, UUID(fsp_id), mock_ref.CLIENT_ID, registry_service.GRANT_SOURCE_SEED, clock.real_now()
            )

    def persona_id(self, key: str) -> str:
        """`fsp_id` персонажа: от сида не зависит, поэтому сид платформы привязывает `anna` и `olga` по ключу."""
        return str(persona_fsp_id(key))

    def athlete_pool(self, *, with_history: bool) -> list[tuple[str, float]]:
        """Свободные взрослые спортсмены демо-реестра: `(fsp_id, latent_skill)` — для раздачи кандидатам сида."""
        with registry_session() as db:
            return [
                (str(fsp_id), latent)
                for fsp_id, latent in registry_service.free_adult_athletes(db, with_history=with_history)
            ]

    def list_competitions(self, *, statuses: Sequence[str], date_from: date, limit: int = 50) -> list[Competition]:
        try:
            with registry_session() as db:
                registry_service.check_failure_mode(db, in_process=True)
                page = registry_service.list_competitions(
                    db, statuses=list(statuses), date_from=date_from, limit=min(limit, 100)
                )
        except RegistryMalformed as exc:
            raise FspContractError("ответ реестра не по контракту") from exc
        except RegistryError as exc:
            raise _map_error(exc) from exc
        try:
            return [Competition.model_validate(item.model_dump(mode="json")) for item in page.items]
        except ValidationError as exc:
            raise FspContractError("календарь не проходит схему") from exc

    def health(self) -> bool:
        with registry_session() as db:
            return registry_service.get_failure_mode(db) == "none"
