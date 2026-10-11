"""Подключение модулей (Арх. 2.6): ленивые строки, WIRING_STRICT, проверка роутеров.

Тесты не зависят от того, какие модули уже написаны: недостающие и сломанные модули изображают подставные.
"""

from __future__ import annotations

import logging
import sys
import types

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app import wiring
from app.core.config import get_settings
from app.core.db import TxRoute
from app.main import create_app


def fake_module(monkeypatch, name: str, **attrs) -> str:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return name


def tx_router_with(path: str, name: str) -> APIRouter:
    router = APIRouter(route_class=TxRoute)

    def endpoint() -> dict[str, str]:
        return {"name": name}

    endpoint.__name__ = name
    router.add_api_route(path, endpoint, methods=["GET"])
    return router


# --- ленивые строки -------------------------------------------------------------------------------------------------


def test_all_lists_are_lazy_strings_for_every_module():
    assert tuple(f"app.modules.{name}:ROUTERS" for name in wiring.MODULES) == wiring.ROUTERS
    assert len(wiring.MODULES) == 11 and len(set(wiring.MODULES)) == 11
    specs = [*wiring.ROUTERS, *wiring.INIT_STEPS, *wiring.DEMO_HOOKS.values(), *wiring.USER_CLEANUP]
    specs += [spec for _, spec in wiring.PERIODIC] + [*wiring.PUBLIC_LIMITS, wiring.FSP_MOCK_APP]
    assert all(isinstance(spec, str) and spec.count(":") == 1 for spec in specs)
    assert [seconds for seconds, _ in wiring.PERIODIC] == [30, 60, 3600, 600, 600]
    assert set(wiring.REQUIRES) <= set(specs) | set(wiring.STARTUP)


def test_wiring_does_not_import_modules_statically():
    """Файл подключения не тянет за собой модули: иначе их нельзя было бы писать и подключать по отдельности."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(wiring))
    imported = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    imported += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    assert not [name for name in imported if name.startswith(("app.modules", "app.seed", "app.fsp_mock", "app.eval"))]


def test_stub_facades_resolve_for_every_module():
    for spec in wiring.ROUTERS:
        assert isinstance(wiring.load(spec), list)
    assert callable(wiring.load("app.modules.fsp.service:on_user_delete"))
    assert [handler.__name__ for handler in wiring.user_cleanup_handlers()] == ["on_user_delete"]


def test_absent_module_and_attribute_are_reported_as_absent():
    for spec in ("app.modules.nowhere:ROUTERS", "app.modules.identity:NO_SUCH_NAME", "app.nopackage.deep.mod:fn"):
        with pytest.raises(wiring.WiringError) as error:
            wiring.load(spec)
        assert error.value.absent is True, spec
    with pytest.raises(wiring.WiringError):
        wiring.load("без-двоеточия")


def test_broken_module_is_not_treated_as_absent(tmp_path, monkeypatch):
    (tmp_path / "broken_wiring_mod.py").write_text("import module_that_does_not_exist_anywhere\n", "utf-8")
    monkeypatch.syspath_prepend(tmp_path)
    with pytest.raises(wiring.WiringError) as error:
        wiring.load("broken_wiring_mod:ROUTERS")
    assert error.value.absent is False
    # optional=True прощает только отсутствие, а не поломку.
    with pytest.raises(wiring.WiringError):
        wiring.try_load("broken_wiring_mod:ROUTERS", strict=True, optional=True)


def test_try_load_follows_strict_flag(caplog):
    spec = "app.modules.nowhere:ROUTERS"
    with caplog.at_level(logging.WARNING, logger="app.wiring"):
        assert wiring.try_load(spec, strict=False) is None
    assert "подключение пропущено" in caplog.text and spec in caplog.text
    with pytest.raises(wiring.WiringError):
        wiring.try_load(spec, strict=True)
    assert wiring.try_load(spec, strict=True, optional=True) is None


# --- приложение целиком ---------------------------------------------------------------------------------------------


def test_app_starts_with_warning_when_module_is_missing_and_fails_when_strict(
    engine, monkeypatch, override_settings, caplog
):
    """Приёмка: при отсутствии модуля приложение стартует с предупреждением (WIRING_STRICT=false) и падает при true."""
    # Только подставная строка: тест не должен зависеть от состояния настоящих модулей соседних пакетов.
    monkeypatch.setattr(wiring, "ROUTERS", ("app.modules.not_written_yet:ROUTERS",))

    override_settings(wiring_strict=False)
    with caplog.at_level(logging.WARNING, logger="app.wiring"):
        application = create_app(get_settings())
    assert "app.modules.not_written_yet:ROUTERS" in caplog.text
    with TestClient(application) as client:  # старт: лимиты, хуки — тоже без падения
        assert client.get("/api/v1/health").json() == {"status": "ok"}

    override_settings(wiring_strict=True)
    with pytest.raises(wiring.WiringError) as error:
        create_app(get_settings())
    assert "not_written_yet" in str(error.value)


def test_health_is_503_api_error_when_database_is_down(client, monkeypatch):
    from app.core import db as core_db

    def down(engine=None) -> None:
        raise ConnectionError("база недоступна")

    monkeypatch.setattr(core_db, "ping", down)
    response = client.get("/api/v1/health")
    assert response.status_code == 503
    assert response.json()["code"] == "service_unavailable"


def test_session_app_runs_on_stubs(client):
    assert client.get("/api/v1/health").status_code == 200
    docs = client.get("/api/docs")
    assert docs.status_code == 200 and "swagger" in docs.text.lower()
    schema = client.get("/api/openapi.json").json()
    assert "/api/v1/health" in schema["paths"]


def test_every_operation_has_a_human_summary(client):
    """В Swagger у каждого метода своё название, а не автоматическое «Get Survey» из имени функции."""
    import re

    schema = client.get("/api/openapi.json").json()
    auto = re.compile(r"[A-Z][a-z]+( [A-Z][a-z]+)*")
    bad = [
        f"{method.upper()} {path}: {operation.get('summary')!r}"
        for path, methods in schema["paths"].items()
        for method, operation in methods.items()
        if not operation.get("summary") or auto.fullmatch(operation["summary"])
    ]
    assert bad == []
    assert max(len(op["summary"]) for methods in schema["paths"].values() for op in methods.values()) <= 90


@pytest.mark.parametrize(
    ("doc", "summary"),
    [
        ("Начать тест. 409: `session_active`, `cooldown_active`.", "Начать тест"),
        ("Схема опроса и сохранённые ответы.", "Схема опроса и сохранённые ответы"),
        ("  Многострочное\n    описание метода.\n\n    Подробности ниже.", "Многострочное описание метода"),
        ("Без точки в конце", "Без точки в конце"),
        ("Версия 1.2 подборки; подробности.", "Версия 1.2 подборки; подробности"),
        (
            "Очень длинное название метода, которое не помещается в отведённые девяносто знаков: дальше идут "
            "подробности, которые в название не нужны.",
            "Очень длинное название метода, которое не помещается в отведённые девяносто знаков",
        ),
        (None, None),
        ("   ", None),
    ],
)  # fmt: skip
def test_summary_from_doc(doc, summary):
    assert wiring.summary_from_doc(doc) == summary


def test_explicit_summary_is_kept(monkeypatch, override_settings):
    from fastapi import FastAPI

    router = APIRouter(route_class=TxRoute)

    @router.get("/beta/a", summary="Своё название")
    def with_summary() -> dict[str, str]:
        """Описание, которое в название попасть не должно."""
        return {}

    @router.get("/beta/b")
    def from_doc() -> dict[str, str]:
        """Название из описания. Остальное — в описание."""
        return {}

    name = fake_module(monkeypatch, "app.modules.fakebeta", ROUTERS=[router])
    monkeypatch.setattr(wiring, "ROUTERS", (f"{name}:ROUTERS",))
    override_settings(wiring_strict=True)
    application = FastAPI()
    wiring.include_routers(application)
    paths = application.openapi()["paths"]
    assert paths["/api/v1/beta/a"]["get"]["summary"] == "Своё название"
    assert paths["/api/v1/beta/b"]["get"]["summary"] == "Название из описания"


# --- роутеры --------------------------------------------------------------------------------------------------------


def test_routers_get_prefix_module_tag_and_operation_id(monkeypatch, override_settings):
    name = fake_module(monkeypatch, "app.modules.fakealpha", ROUTERS=[tx_router_with("/alpha/items", "list_items")])
    monkeypatch.setattr(wiring, "ROUTERS", (f"{name}:ROUTERS",))
    override_settings(wiring_strict=True)

    from fastapi import FastAPI

    application = FastAPI()
    assert wiring.include_routers(application) == {"fakealpha": 1}
    operation = application.openapi()["paths"]["/api/v1/alpha/items"]["get"]
    assert operation["tags"] == ["fakealpha"]
    assert operation["operationId"] == "fakealpha-list_items"


def test_router_without_txroute_is_rejected(monkeypatch, override_settings, caplog):
    plain = APIRouter()

    def plain_endpoint() -> dict[str, str]:
        return {}

    plain.add_api_route("/plain", plain_endpoint, methods=["POST"])
    name = fake_module(monkeypatch, "app.modules.fakeplain", ROUTERS=[plain])
    monkeypatch.setattr(wiring, "ROUTERS", (f"{name}:ROUTERS",))

    from fastapi import FastAPI

    override_settings(wiring_strict=True)
    with pytest.raises(wiring.WiringError) as error:
        wiring.include_routers(FastAPI())
    assert "TxRoute" in str(error.value)

    # Без строгого режима модуль с такой ошибкой не подключается вовсе: маршрут без фиксации хуже, чем его отсутствие.
    override_settings(wiring_strict=False)
    application = FastAPI()
    with caplog.at_level(logging.ERROR, logger="app.wiring"):
        assert wiring.include_routers(application) == {}
    assert "/api/v1/plain" not in application.openapi()["paths"]


def test_routers_must_be_a_list_of_api_routers(monkeypatch, override_settings):
    name = fake_module(monkeypatch, "app.modules.fakebad", ROUTERS="не список")
    monkeypatch.setattr(wiring, "ROUTERS", (f"{name}:ROUTERS",))
    override_settings(wiring_strict=True)

    from fastapi import FastAPI

    with pytest.raises(wiring.WiringError):
        wiring.include_routers(FastAPI())


def test_demo_routers_exist_only_in_demo_mode(monkeypatch, override_settings):
    """Арх. 10.3: демо-эндпоинты существуют только при DEMO_MODE=true."""
    router = tx_router_with("/demo/login", "demo_login")
    monkeypatch.setattr(sys.modules["app.modules.demo"], "ROUTERS", [router])

    from fastapi import FastAPI

    override_settings(demo_mode=True)
    assert wiring.include_routers(FastAPI()).get("demo") == 1
    override_settings(demo_mode=False)
    assert "demo" not in wiring.include_routers(FastAPI())


def test_flags_switch_periodic_tasks_and_fsp_mock(override_settings):
    override_settings(demo_mode=True)
    assert [task.name for task in wiring.periodic_tasks()][3:] == [
        "demo.service:purge_clones",
        "demo.service:refresh_scenario",
    ]
    override_settings(demo_mode=False)
    assert [task.name for task in wiring.periodic_tasks()] == [
        "contact.service:settle_all",
        "assessment.service:close_expired_sessions",
        "profile.service:purge_resume_results",
    ]
    override_settings(fsp_mock_enabled=False)
    assert wiring.enabled(wiring.FSP_MOCK_APP) is False
    from fastapi import FastAPI

    assert wiring.mount_fsp_mock(FastAPI()) is False


# --- лимиты, хуки старта, хуки демо ---------------------------------------------------------------------------------


def test_public_limits_are_collected_and_published(monkeypatch, override_settings):
    from app.shared.salary import PUBLIC_SALARY_LIMITS

    received: dict[str, float] = {}
    first = fake_module(monkeypatch, "fake_limits_one", PUBLIC_LIMITS={"need_must_max": 8, "salary_min": 10_000})
    second = fake_module(monkeypatch, "fake_limits_two", PUBLIC_LIMITS={"slots": 5, "decline_step": 5000})
    catalog = fake_module(monkeypatch, "fake_catalog_service", publish_limits=lambda **limits: received.update(limits))
    specs = (f"{first}:PUBLIC_LIMITS", f"{second}:PUBLIC_LIMITS", "fake_absent:PUBLIC_LIMITS")
    monkeypatch.setattr(wiring, "PUBLIC_LIMITS", specs)
    monkeypatch.setattr(wiring, "PUBLISH_LIMITS", f"{catalog}:publish_limits")

    override_settings(wiring_strict=False)
    expected = {**PUBLIC_SALARY_LIMITS, "need_must_max": 8, "slots": 5, "decline_step": 5000}
    assert wiring.publish_limits() == expected  # общие правила вилки публикуются всегда
    assert received == expected
    assert received["salary_max_ratio"] == 1.5 and received["min_salary_step"] == 20_000

    override_settings(wiring_strict=True)
    with pytest.raises(wiring.WiringError):
        wiring.publish_limits()  # недостающий constants.py в строгом режиме — ошибка


def test_conflicting_public_limit_is_an_error(monkeypatch, override_settings, caplog):
    first = fake_module(monkeypatch, "fake_limits_one", PUBLIC_LIMITS={"slots": 5})
    second = fake_module(monkeypatch, "fake_limits_two", PUBLIC_LIMITS={"slots": 7})
    same = fake_module(monkeypatch, "fake_limits_same", PUBLIC_LIMITS={"slots": 5})
    monkeypatch.setattr(wiring, "PUBLISH_LIMITS", "fake_absent:publish_limits")

    # Одинаковое значение у двух модулей — не конфликт.
    monkeypatch.setattr(wiring, "PUBLIC_LIMITS", (f"{first}:PUBLIC_LIMITS", f"{same}:PUBLIC_LIMITS"))
    override_settings(wiring_strict=False)
    assert wiring.publish_limits()["slots"] == 5

    monkeypatch.setattr(wiring, "PUBLIC_LIMITS", (f"{first}:PUBLIC_LIMITS", f"{second}:PUBLIC_LIMITS"))
    with caplog.at_level(logging.ERROR, logger="app.wiring"):
        assert wiring.publish_limits()["slots"] == 5  # остаётся первое значение, в журнале — ошибка
    assert "slots" in caplog.text

    monkeypatch.setattr(wiring, "PUBLISH_LIMITS", "app.modules.catalog.service:publish_limits")
    override_settings(wiring_strict=True)
    with pytest.raises(wiring.WiringError) as error:
        wiring.publish_limits()
    assert "slots" in str(error.value)


def test_stand_on_stubs_publishes_salary_limits(app):
    """Интерфейс получает из каталога правила вилки и лестницу минимума."""
    from app.modules.catalog import service as catalog_stub

    if hasattr(catalog_stub, "_limits"):
        assert catalog_stub._limits["salary_min"] == 10_000
        assert catalog_stub._limits["min_salary_high"] == 600_000


def test_startup_hooks_are_optional(monkeypatch, override_settings, caplog):
    calls: list[str] = []
    good = fake_module(monkeypatch, "fake_hook_good", on_startup=lambda: calls.append("good"))
    bad = fake_module(monkeypatch, "fake_hook_bad", on_startup=lambda: 1 / 0)
    silent = fake_module(monkeypatch, "fake_hook_none")
    monkeypatch.setattr(wiring, "STARTUP", (f"{good}:on_startup", f"{silent}:on_startup", f"{bad}:on_startup"))

    override_settings(wiring_strict=False)
    with caplog.at_level(logging.WARNING, logger="app.wiring"):
        assert wiring.run_startup_hooks() == [f"{good}:on_startup"]
    assert calls == ["good"]
    assert "fake_hook_none" not in caplog.text  # отсутствие хука — не предупреждение
    assert "fake_hook_bad" in caplog.text

    override_settings(wiring_strict=True)
    with pytest.raises(ZeroDivisionError):
        wiring.run_startup_hooks()


def test_demo_hook_resolves_lazily(monkeypatch):
    fake_module(monkeypatch, "fake_seed_demo", reset_all=lambda: "reset")
    monkeypatch.setitem(wiring.DEMO_HOOKS, "reset_all", "fake_seed_demo:reset_all")
    assert wiring.demo_hook("reset_all")() == "reset"
    monkeypatch.setitem(wiring.DEMO_HOOKS, "restart_scenario", "fake_seed_missing:restart_scenario")
    with pytest.raises(wiring.WiringError):
        wiring.demo_hook("restart_scenario")
    with pytest.raises(wiring.WiringError):
        wiring.demo_hook("no_such_hook")
