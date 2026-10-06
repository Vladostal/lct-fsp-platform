"""Сборка приложения FastAPI (Арх. 2.1, 9.1, 10.1, 10.10).

Здесь нет доменной логики: только обработчики ошибок, общий промежуточный слой, служебный `GET /api/v1/health`
и подключение модулей через `app.wiring`. Запуск: `uvicorn app.main:app` — один воркер, без `--proxy-headers`
(адрес клиента определяет `core.deps.client_ip`).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any, Literal

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import wiring
from app.core import background, db
from app.core.config import Settings, get_settings
from app.core.errors import ApiException, error_response, error_responses, install_error_handlers, patch_openapi_errors
from app.core.logging import setup_logging

log = logging.getLogger("app.main")
access_log = logging.getLogger("app.access")

API_VERSION = "0.1.0"
HEALTH_PATH = f"{wiring.API_PREFIX}/health"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: Заголовки ответа API (Арх. 10.10). Ставятся, только если обработчик не задал свои (callback ФСП — `no-referrer`).
SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


class HealthView(BaseModel):
    """Ответ проверки готовности."""

    status: Literal["ok"] = "ok"


class ApiGuardMiddleware:
    """Общий слой запросов API: проверка `Origin`, заголовки безопасности, журнал доступа.

    * CSRF (Арх. 10.1): cookie сессии — `SameSite=Lax`; дополнительно для `POST`, `PUT`, `PATCH`, `DELETE`
      заголовок `Origin`, когда он есть, должен совпадать с `PUBLIC_BASE_URL` (или входить в `ALLOWED_ORIGINS`),
      иначе 403 `forbidden`. Запросы без `Origin` (curl, серверные клиенты) cookie чужого сайта не несут.
    * Журнал доступа пишет метод, путь без строки параметров, статус и время: в параметрах бывают `code` и `state`
      возврата из ФСП ID, которым в журнале не место (Арх. 10.8).

    Написан как чистый ASGI-слой, без `BaseHTTPMiddleware`: тот меняет порядок выполнения фоновых задач ответа,
    а от них зависит отправка писем после фиксации.
    """

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.origins = settings.origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method: str = scope["method"]
        path: str = scope["path"]
        started = time.monotonic()
        status = 500

        async def send_with_headers(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    if name not in headers:
                        headers[name] = value
            await send(message)

        try:
            if method in UNSAFE_METHODS:
                origin = Headers(scope=scope).get("origin")
                if origin is not None and origin.lower().rstrip("/") not in self.origins:
                    await error_response(403, "forbidden", "Запрос с чужого сайта отклонён")(
                        scope, receive, send_with_headers
                    )
                    return
            await self.app(scope, receive, send_with_headers)
        finally:
            level = logging.DEBUG if path == HEALTH_PATH else logging.INFO
            access_log.log(level, "%s %s %s %.0f мс", method, path, status, (time.monotonic() - started) * 1000)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Старт: лимиты модулей, хуки старта, фоновый цикл. Остановка: цикл дожидается текущей задачи."""
    settings: Settings = app.state.settings
    await run_in_threadpool(wiring.publish_limits, settings)
    await run_in_threadpool(wiring.run_startup_hooks, settings)

    stop = asyncio.Event()
    loop_task: asyncio.Task[None] | None = None
    if settings.background_enabled:
        jobs = [background.purge_job()]
        for task in wiring.periodic_tasks(settings):
            jobs.append(
                background.Job(
                    name=task.name,
                    seconds=task.seconds,
                    loader=lambda spec=task.spec: wiring.try_load(spec, strict=False),  # type: ignore[misc]
                )
            )
        loop_task = asyncio.create_task(background.run_loop(jobs, stop), name="background-loop")
    try:
        yield
    finally:
        stop.set()
        if loop_task is not None:
            with suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(loop_task, timeout=30)


def _health() -> HealthView:
    """Готовность процесса и соединения с базой (Арх. 9.4): 200 `{status: "ok"}` либо 503."""
    try:
        db.ping()
    except Exception as exc:
        log.warning("health: база недоступна: %s: %s", type(exc).__name__, exc)
        raise ApiException(503, "service_unavailable") from None
    return HealthView()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Собрать приложение. Вызывается один раз при импорте модуля; тесты могут собрать своё."""
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=API_VERSION,
        description="REST API платформы подбора ИТ-специалистов с обратной механикой. Аутентификация — cookie `sid`.",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
        # Одна схема на модель: генератор клиента не плодит пары «…-Input / …-Output».
        separate_input_output_schemas=False,
    )
    app.state.settings = settings

    install_error_handlers(app)
    app.add_middleware(ApiGuardMiddleware, settings=settings)

    app.add_api_route(
        HEALTH_PATH,
        _health,
        methods=["GET"],
        response_model=HealthView,
        responses=error_responses(503),
        tags=["core"],
        name="health",
        operation_id="core-health",
        summary="Готовность процесса и соединения с БД",
    )

    included = wiring.include_routers(app, settings)
    mounted = wiring.mount_fsp_mock(app, settings)
    log.info(
        "приложение собрано: маршрутов по модулям — %s; демо-ФСП %s; WIRING_STRICT=%s",
        ", ".join(f"{name}: {count}" for name, count in included.items()) or "нет",
        "смонтирован" if mounted else "не смонтирован",
        str(settings.wiring_strict).lower(),
    )

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = get_openapi(
                title=app.title,
                version=app.version,
                description=app.description,
                routes=app.routes,
                separate_input_output_schemas=False,
            )
            app.openapi_schema = patch_openapi_errors(schema)
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]
    return app


app = create_app()
