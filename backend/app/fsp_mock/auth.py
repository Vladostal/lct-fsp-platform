"""Проверка вызывающего реестр (Арх. 7.3, 7.11; приложение D, §2.6).

`FSPMOCK_AUTH=none` (режим `mock`): платформа ходит в реестр внутри процесса, а HTTP-ручки R3 и R4 принимают только
`X-Admin-Token` (та же зависимость `core.deps.require_admin`, что у служебных действий платформы); вызывающий считается
сервисным клиентом `talent-platform`. Словари и календарь открыты.

`FSPMOCK_AUTH=keycloak` (проверка настоящих JWT по JWKS) — вторая очередь (P1) и в этой сборке не реализован:
ручки отвечают 503, а не пропускают вызов без проверки.
"""

from __future__ import annotations

from fastapi import Request

from app.core.config import get_settings
from app.core.deps import require_admin
from app.core.errors import ApiException
from app.fsp_mock.registry_service import Caller, RegistryError


def resolve_caller(request: Request) -> Caller:
    """Вызывающий HTTP-ручки R3/R4. Нет прав — `RegistryError` (401/403/503)."""
    mode = get_settings().fspmock_auth
    if mode == "none":
        try:
            require_admin(request)
        except ApiException as exc:
            raise RegistryError(403, "insufficient_scope", "нужен заголовок X-Admin-Token") from exc
        return Caller(kind="service")
    raise RegistryError(503, "registry_unavailable", "FSPMOCK_AUTH=keycloak в этой сборке не реализован")
