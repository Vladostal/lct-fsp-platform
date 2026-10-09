"""Подключение модулей к приложению — единственное место (Арх. 2.6).

Все точки подключения записаны строками «модуль:атрибут» и загружаются лениво, поэтому файл не импортирует ни одного
модуля статически и не нарушает слои, а пакетам модулей править его не нужно. Модуль подключается тем, что
экспортирует нужные имена:

* **Роутеры.** `app/modules/<m>/__init__.py`: `ROUTERS: list[APIRouter]`, каждый роутер создан как
  `APIRouter(route_class=TxRoute)`. Подключаются с префиксом `/api/v1`, тегом OpenAPI, равным имени модуля,
  и `operationId = "<модуль>-<имя функции>"`.
* **Публичные лимиты.** `app/modules/<m>/constants.py`: `PUBLIC_LIMITS: dict[str, int | float]`. При старте
  передаются в `catalog.service.publish_limits(**limits)` вместе с общими правилами вилки (`shared.salary`).
* **Хук старта (необязательно).** `app/modules/<m>/__init__.py`: `on_startup() -> None`. Вызывается при старте
  процесса `api`, по слоям снизу вверх; сессию открывает сам (`core.db.session_scope`).
* **Фоновые задачи.** Функция фасада `(db, now) -> None | int`. `core.background` даёт ей отдельную сессию
  и время сервиса и фиксирует транзакцию после возврата.
* **Обработчики удаления аккаунта.** Функция фасада `(db, user_id) -> None`. `identity.delete_user` получает их
  через `user_cleanup_handlers()` и вызывает до каскадного удаления.
* **Шаги инициализации.** Функция без аргументов: идемпотентна, сессии открывает сама, фиксирует пакетами, пишет
  прогресс в журнал. Вызывает `python -m app.scripts.init` после создания схемы (Арх. 13.2).
* **Функции сида для модуля `demo`.** `app/seed/demo.py`; модуль `demo` берёт их через `demo_hook("reset_all")`
  и не импортирует `app.seed`.
* **Демо-ФСП.** `app/fsp_mock/app.py`: `app` — отдельное ASGI-приложение; монтируется в `/api/fsp-mock`
  при `FSP_MOCK_ENABLED=true`.

Пока модуля или атрибута нет: при `WIRING_STRICT=false` строка пропускается с предупреждением, при `true` запуск
падает с понятной ошибкой. Отсутствующий шаг инициализации пропускается с предупреждением в обоих режимах.
"""

from __future__ import annotations

import importlib
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute

from app.core.config import Settings, get_settings
from app.core.db import TxRoute
from app.shared.salary import PUBLIC_SALARY_LIMITS

log = logging.getLogger("app.wiring")

API_PREFIX = "/api/v1"
FSP_MOCK_PREFIX = "/api/fsp-mock"

#: Модули по слоям снизу вверх (Арх. 2.3): в этом порядке подключаются роутеры и вызываются хуки старта.
MODULES: tuple[str, ...] = (
    "identity",
    "catalog",
    "reports",
    "company",
    "textparse",
    "assessment",
    "profile",
    "fsp",
    "matching",
    "contact",
    "demo",
)

#: Роутеры: по одной строке на модуль.
ROUTERS: tuple[str, ...] = tuple(f"app.modules.{name}:ROUTERS" for name in MODULES)

#: Необязательные хуки старта процесса (например, `assessment` публикует доступные пары «специализация — грейд»).
STARTUP: tuple[str, ...] = tuple(f"app.modules.{name}:on_startup" for name in MODULES)

#: Шаги инициализации после создания схемы (Арх. 13.2), по порядку.
INIT_STEPS: tuple[str, ...] = (
    "app.modules.assessment.bank:build_if_empty",
    "app.fsp_mock.generator:seed_if_empty",
    "app.seed:seed_if_empty",
)

#: Функции сида, которые вызывает модуль `demo`, не импортируя `app.seed`.
DEMO_HOOKS: dict[str, str] = {
    "reset_all": "app.seed.demo:reset_all",
    "restart_scenario": "app.seed.demo:restart_scenario",
    "spawn_nina": "app.seed.demo:spawn_nina",
}

#: Фоновые задачи: период в секундах и функция фасада `(db, now)`.
PERIODIC: tuple[tuple[int, str], ...] = (
    (30, "app.modules.contact.service:settle_all"),
    (60, "app.modules.assessment.service:close_expired_sessions"),
    (3600, "app.modules.profile.service:purge_resume_results"),
    (600, "app.modules.demo.service:purge_clones"),
)

#: Обработчики удаления аккаунта `(db, user_id)`: вызываются до каскадного удаления строки `app_user`.
USER_CLEANUP: tuple[str, ...] = ("app.modules.fsp.service:on_user_delete",)

#: Числа модулей для `Catalog.limits`.
PUBLIC_LIMITS: tuple[str, ...] = tuple(
    f"app.modules.{name}.constants:PUBLIC_LIMITS"
    for name in ("identity", "profile", "assessment", "matching", "contact")
)

#: Демо-ФСП: отдельное ASGI-приложение со своей схемой OpenAPI (Арх. 7.3).
FSP_MOCK_APP = "app.fsp_mock.app:app"

#: Куда модуль `catalog` принимает опубликованные лимиты.
PUBLISH_LIMITS = "app.modules.catalog.service:publish_limits"

#: Строка действует только при включённом флаге. Ключи — строки списков выше; значения — флаги `Settings.features`
#: и `fsp_mock`. Демо-эндпоинты без `DEMO_MODE` не существуют вовсе; роутер под другим флагом подключён
#: всегда и сам отвечает 404 `feature_disabled` (зависимость `require_feature`).
REQUIRES: dict[str, str] = {
    "app.modules.demo:ROUTERS": "demo",
    "app.modules.demo:on_startup": "demo",
    "app.modules.demo.service:purge_clones": "demo",
    "app.seed:seed_if_empty": "demo",
    "app.fsp_mock.generator:seed_if_empty": "fsp_mock",
    FSP_MOCK_APP: "fsp_mock",
}


class WiringError(RuntimeError):
    """Строка подключения не загрузилась или объявлена неверно."""


# --------------------------------------------------------------------------------------------------------------------
# Ленивая загрузка
# --------------------------------------------------------------------------------------------------------------------


def _is_absent(spec: str, exc: BaseException) -> bool:
    """Отличить «модуля или атрибута ещё нет» от «модуль есть, но сломан»."""
    module_name = spec.partition(":")[0]
    if isinstance(exc, ModuleNotFoundError):
        missing = exc.name or ""
        return module_name == missing or module_name.startswith(missing + ".")
    return (
        isinstance(exc, AttributeError) and getattr(exc, "obj", None) is not None and exc.name == spec.partition(":")[2]
    )


def load(spec: str) -> Any:
    """Загрузить объект по строке «модуль:атрибут»; любая неудача — `WiringError` с исходной причиной."""
    module_name, _, attr = spec.partition(":")
    if not module_name or not attr:
        raise WiringError(f"строка подключения должна иметь вид «модуль:атрибут»: {spec!r}")
    try:
        module = importlib.import_module(module_name)
        return getattr(module, attr)
    except Exception as exc:
        absent = _is_absent(spec, exc)
        error = WiringError(f"{spec}: {'не найдено' if absent else 'не загрузилось'} ({type(exc).__name__}: {exc})")
        error.absent = absent  # type: ignore[attr-defined]
        raise error from exc


def enabled(spec: str, settings: Settings | None = None) -> bool:
    """Действует ли строка при текущих флагах (`REQUIRES`)."""
    flag = REQUIRES.get(spec)
    if flag is None:
        return True
    settings = settings or get_settings()
    return settings.fsp_mock if flag == "fsp_mock" else settings.features[flag]


def try_load(spec: str, *, strict: bool | None = None, optional: bool = False) -> Any | None:
    """Загрузить строку с учётом `WIRING_STRICT`.

    `strict=True` — ошибка при любой неудаче; `False` — предупреждение и `None`. `optional=True` — отсутствие
    объекта не считается проблемой (тихо `None`), но сломанный модуль по-прежнему подчиняется `strict`.
    """
    if strict is None:
        strict = get_settings().wiring_strict
    try:
        return load(spec)
    except WiringError as exc:
        absent = bool(getattr(exc, "absent", False))
        if absent and optional:
            return None
        if strict:
            raise
        log.warning("подключение пропущено: %s", exc)
        return None


# --------------------------------------------------------------------------------------------------------------------
# Сборка приложения
# --------------------------------------------------------------------------------------------------------------------


def module_of(spec: str) -> str:
    """Имя модуля платформы из строки подключения: `app.modules.contact.service:settle_all` → `contact`."""
    parts = spec.partition(":")[0].split(".")
    if len(parts) > 2 and parts[:2] == ["app", "modules"]:
        return parts[2]
    return parts[-1]


def _operation_id(tag: str) -> Callable[[APIRoute], str]:
    def generate(route: APIRoute) -> str:
        return f"{tag}-{route.name}"

    return generate


#: Предел длины названия метода в схеме OpenAPI.
SUMMARY_MAX = 90
_SENTENCE_END = re.compile(r"[.!?](?:\s|$)")


def summary_from_doc(doc: str | None) -> str | None:
    """Название метода для OpenAPI из docstring обработчика: первое предложение без точки в конце.

    Слишком длинное предложение обрезается по первому `;` или `:`, а если их нет — по границе слова. Нужна
    затем, чтобы в Swagger стояло «Начать тест», а не автоматическое «Create Session» из имени функции.
    """
    text = " ".join((doc or "").split())
    if not text:
        return None
    end = _SENTENCE_END.search(text)
    sentence = text[: end.start()] if end else text.rstrip(".")
    if len(sentence) > SUMMARY_MAX:
        for mark in ("; ", ": ", " — "):
            cut = sentence.find(mark)
            if 15 <= cut <= SUMMARY_MAX:
                sentence = sentence[:cut]
                break
        else:
            sentence = sentence[:SUMMARY_MAX].rsplit(" ", 1)[0] + "…"
    return sentence.strip() or None


def _fill_summaries(routers: list[APIRouter]) -> None:
    """Проставить `summary` маршрутам, у которых оно не задано явно (до подключения роутера к приложению)."""
    for router in routers:
        for route in router.routes:
            if isinstance(route, APIRoute) and not route.summary:
                route.summary = summary_from_doc(route.endpoint.__doc__)


def _check_routers(spec: str, routers: Any) -> list[APIRouter]:
    if not isinstance(routers, (list, tuple)) or not all(isinstance(item, APIRouter) for item in routers):
        raise WiringError(f"{spec}: ожидается list[APIRouter]")
    for router in routers:
        for route in router.routes:
            # Маршрут без TxRoute не фиксирует транзакцию (Арх. 2.4, п. 4): это всегда ошибка сборки.
            if isinstance(route, APIRoute) and not isinstance(route, TxRoute):
                raise WiringError(
                    f"{spec}: маршрут {sorted(route.methods or [])} {route.path} создан не через "
                    "APIRouter(route_class=TxRoute)"
                )
    return list(routers)


def include_routers(app: FastAPI, settings: Settings | None = None) -> dict[str, int]:
    """Подключить роутеры всех модулей. Возвращает число маршрутов по модулям (для журнала и тестов)."""
    settings = settings or get_settings()
    included: dict[str, int] = {}
    for spec in ROUTERS:
        module = module_of(spec)
        if not enabled(spec, settings):
            log.info("модуль %s выключен флагом %s: роутеры не подключены", module, REQUIRES[spec])
            continue
        try:
            routers = try_load(spec, strict=settings.wiring_strict)
            if routers is None:
                continue
            checked = _check_routers(spec, routers)
        except WiringError:
            if settings.wiring_strict:
                raise
            log.exception("модуль %s не подключён", module)
            continue
        _fill_summaries(checked)
        for router in checked:
            app.include_router(
                router, prefix=API_PREFIX, tags=[module], generate_unique_id_function=_operation_id(module)
            )
        included[module] = sum(len(router.routes) for router in checked)
    return included


def mount_fsp_mock(app: FastAPI, settings: Settings | None = None) -> bool:
    """Смонтировать демо-ФСП в `/api/fsp-mock` при `FSP_MOCK_ENABLED=true` (Арх. 7.3)."""
    settings = settings or get_settings()
    if not enabled(FSP_MOCK_APP, settings):
        return False
    mock_app = try_load(FSP_MOCK_APP, strict=settings.wiring_strict)
    if mock_app is None:
        return False
    app.mount(FSP_MOCK_PREFIX, mock_app)
    return True


def publish_limits(settings: Settings | None = None) -> dict[str, int | float]:
    """Собрать числа для `Catalog.limits` и передать их в `catalog`.

    В набор входят общие правила вилки и лестницы минимума (`shared.salary`) и `PUBLIC_LIMITS` модулей.
    Один и тот же ключ с одним значением у двух модулей допустим; с разными — ошибка сборки
    (при `WIRING_STRICT=false` остаётся первое значение и пишется запись в журнал).
    """
    settings = settings or get_settings()
    limits: dict[str, int | float] = dict(PUBLIC_SALARY_LIMITS)
    for spec in PUBLIC_LIMITS:
        values = try_load(spec, strict=settings.wiring_strict)
        if values is None:
            continue
        if not isinstance(values, dict):
            raise WiringError(f"{spec}: ожидается dict[str, int | float]")
        conflicts = sorted(key for key, value in values.items() if key in limits and limits[key] != value)
        if conflicts:
            message = f"{spec}: лимиты уже опубликованы с другим значением: {conflicts}"
            if settings.wiring_strict:
                raise WiringError(message)
            log.error(message)
        for key, value in values.items():
            limits.setdefault(key, value)
    publish = try_load(PUBLISH_LIMITS, strict=settings.wiring_strict)
    if publish is not None:
        try:
            publish(**limits)
        except NotImplementedError:
            if settings.wiring_strict:
                raise
            log.warning("лимиты не опубликованы: catalog.service.publish_limits ещё не реализована")
    return limits


def run_startup_hooks(settings: Settings | None = None) -> list[str]:
    """Вызвать необязательные `on_startup()` модулей. Возвращает имена выполненных хуков."""
    settings = settings or get_settings()
    done: list[str] = []
    for spec in STARTUP:
        if not enabled(spec, settings):
            continue
        hook = try_load(spec, strict=settings.wiring_strict, optional=True)
        if hook is None:
            continue
        try:
            hook()
        except Exception:
            if settings.wiring_strict:
                raise
            log.exception("хук старта %s завершился ошибкой", spec)
        else:
            done.append(spec)
    return done


@dataclass(frozen=True)
class PeriodicTask:
    """Фоновая задача: период и строка подключения; функция загружается при первом запуске."""

    seconds: int
    spec: str

    @property
    def name(self) -> str:
        return self.spec.removeprefix("app.modules.")


def periodic_tasks(settings: Settings | None = None) -> list[PeriodicTask]:
    """Фоновые задачи, действующие при текущих флагах."""
    settings = settings or get_settings()
    return [PeriodicTask(seconds, spec) for seconds, spec in PERIODIC if enabled(spec, settings)]


def user_cleanup_handlers(settings: Settings | None = None) -> list[Callable[..., None]]:
    """Обработчики удаления аккаунта `(db, user_id)` — для `identity.delete_user` (Арх. 10.5)."""
    settings = settings or get_settings()
    handlers: list[Callable[..., None]] = []
    for spec in USER_CLEANUP:
        handler = try_load(spec, strict=settings.wiring_strict)
        if handler is not None:
            handlers.append(handler)
    return handlers


def demo_hook(name: str) -> Callable[..., Any]:
    """Функция сида для модуля `demo`. Сида ещё нет — `WiringError` (модуль `demo` отвечает на неё сам)."""
    try:
        spec = DEMO_HOOKS[name]
    except KeyError:
        raise WiringError(f"неизвестный хук демо-режима: {name}") from None
    hook = load(spec)
    if not callable(hook):
        raise WiringError(f"{spec}: ожидается функция")
    return hook
