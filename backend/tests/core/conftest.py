"""Фикстуры тестов каркаса: пробное приложение с собственными маршрутами на общих зависимостях."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fastapi import APIRouter, FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import TxRoute
from app.core.deps import get_db
from app.core.errors import install_error_handlers
from app.main import ApiGuardMiddleware


def build_probe_app(*routers: APIRouter) -> FastAPI:
    """Мини-приложение с теми же обработчиками ошибок и промежуточным слоем, что у боевого."""
    application = FastAPI()
    install_error_handlers(application)
    application.add_middleware(ApiGuardMiddleware, settings=get_settings())
    for router in routers:
        application.include_router(router, prefix="/api/v1")
    return application


@pytest.fixture
def tx_router() -> APIRouter:
    """Пустой роутер на `TxRoute`: тест сам объявляет в нём маршруты."""
    return APIRouter(route_class=TxRoute)


@pytest.fixture
def probe(db: Session) -> Iterator[Callable[..., TestClient]]:
    """Клиент пробного приложения на сессии теста: `client = probe(router)`."""
    apps: list[FastAPI] = []

    def override(request: Request) -> Iterator[Session]:
        db.commit()
        request.state.db = db
        yield db

    def factory(*routers: APIRouter, **client_kwargs: object) -> TestClient:
        application = build_probe_app(*routers)
        application.dependency_overrides[get_db] = override
        apps.append(application)
        return TestClient(application, **client_kwargs)  # type: ignore[arg-type]

    yield factory
    for application in apps:
        application.dependency_overrides.clear()


@pytest.fixture
def build_app() -> Callable[..., FastAPI]:
    """Собрать пробное приложение без подмены сессии (для тестов с настоящей фиксацией)."""
    return build_probe_app
