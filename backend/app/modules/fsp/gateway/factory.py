"""Выбор адаптера шлюза по `FSP_MODE` (Арх. 7.3)."""

from __future__ import annotations

from app.core.config import get_settings
from app.modules.fsp.gateway.base import FspGateway, FspUnavailable


def get_fsp_gateway() -> FspGateway:
    """Шлюз текущего процесса: `mock` — демо-провайдер в процессе; `keycloak` — вторая очередь (P1).

    Режим `keycloak` в этой сборке не реализован: вызывающий получает `FspUnavailable` (503 `fsp_unavailable`
    в `POST /fsp/link/start`), а не молчаливую подмену демо-провайдером.
    """
    mode = get_settings().fsp_mode
    if mode == "mock":
        from app.modules.fsp.gateway.mock import MockFspGateway

        return MockFspGateway()
    raise FspUnavailable("адаптер FSP_MODE=keycloak не реализован в этой сборке (P1)")
