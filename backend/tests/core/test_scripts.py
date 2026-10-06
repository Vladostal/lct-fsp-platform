"""Скрипты каркаса: инициализация стенда (Арх. 13.2) и выгрузка OpenAPI без сервера (Арх. 9.1)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import types

import pytest
from sqlalchemy import inspect

from app import wiring
from app.core import db as core_db
from app.core.config import BACKEND_DIR, get_settings
from app.scripts import init


def fake_step(monkeypatch, name: str, fn) -> str:
    module = types.ModuleType(name)
    module.run = fn  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, name, module)
    return f"{name}:run"


def test_schema_comes_from_metadata_until_first_migration(engine, monkeypatch, tmp_path):
    """До начальной миграции стенд и тесты создают схему одной функцией core.db.create_schema."""
    monkeypatch.setattr(init, "VERSIONS_DIR", tmp_path / "versions")  # ревизий нет
    assert init.revisions() == []
    assert init.init_schema() == "metadata"
    assert init.init_schema() == "metadata", "повторный запуск должен быть безвредным"
    inspector = inspect(engine)
    assert "service_clock" in inspector.get_table_names(schema="public")
    assert core_db.FSPMOCK_SCHEMA in inspector.get_schema_names()
    constraints = {item["name"] for item in inspector.get_check_constraints("service_clock")}
    assert constraints == {"ck_service_clock_single_row"}, "имена ограничений — по naming_convention"
    assert inspector.get_pk_constraint("service_clock")["name"] == "pk_service_clock"


def test_revisions_switch_schema_step_to_alembic(monkeypatch, tmp_path):
    versions = tmp_path / "versions"
    versions.mkdir()
    (versions / "__init__.py").write_text("", "utf-8")
    monkeypatch.setattr(init, "VERSIONS_DIR", versions)
    assert init.revisions() == []
    (versions / "0001_initial.py").write_text("revision = '0001'\n", "utf-8")
    assert [path.name for path in init.revisions()] == ["0001_initial.py"]

    called: list[str] = []
    monkeypatch.setattr("alembic.command.upgrade", lambda config, target: called.append(target))
    assert init.init_schema() == "alembic"
    assert called == ["head"]


def test_missing_and_disabled_steps_are_skipped_with_warning(monkeypatch, override_settings, caplog):
    """Приёмка: init.py пропускает отсутствующие шаги с предупреждением — в том числе при WIRING_STRICT=true."""
    done: list[str] = []
    present = fake_step(monkeypatch, "fake_init_present", lambda: done.append("present"))
    gated = fake_step(monkeypatch, "fake_init_gated", lambda: done.append("gated"))
    monkeypatch.setattr(wiring, "INIT_STEPS", ("app.modules.assessment.not_ready:build_if_empty", present, gated))
    monkeypatch.setitem(wiring.REQUIRES, gated, "pulse")

    override_settings(wiring_strict=True, feature_pulse=False)
    with caplog.at_level(logging.INFO, logger="app.init"):
        outcome = init.run_steps(get_settings())
    assert outcome == {"app.modules.assessment.not_ready:build_if_empty": "missing", present: "done", gated: "disabled"}
    assert done == ["present"]
    assert "пропущен — модуля ещё нет" in caplog.text
    assert "шаг 2/3" in caplog.text and "готов за" in caplog.text  # журнал прогресса


def test_failing_step_stops_strict_init_and_is_skipped_otherwise(monkeypatch, override_settings, caplog):
    done: list[str] = []
    broken = fake_step(monkeypatch, "fake_init_broken", lambda: 1 / 0)
    after = fake_step(monkeypatch, "fake_init_after", lambda: done.append("after"))
    monkeypatch.setattr(wiring, "INIT_STEPS", (broken, after))

    override_settings(wiring_strict=False)
    with caplog.at_level(logging.ERROR, logger="app.init"):
        assert init.run_steps(get_settings()) == {broken: "failed", after: "done"}
    assert done == ["after"]

    override_settings(wiring_strict=True)
    with pytest.raises(ZeroDivisionError):
        init.run_steps(get_settings())


def test_main_returns_exit_code(engine, monkeypatch, override_settings, tmp_path):
    monkeypatch.setattr(init, "VERSIONS_DIR", tmp_path / "versions")
    monkeypatch.setattr(core_db, "dispose_engine", lambda: None)  # движок запуска тестов ещё нужен
    monkeypatch.setattr(init, "setup_logging", lambda level: None)

    # Шаги подставные: настоящие (сборка банка, сид) в тесте каркаса запускать нельзя.
    done: list[str] = []
    steps = (fake_step(monkeypatch, "fake_init_ok", lambda: done.append("ok")), "app.not_written:step")
    monkeypatch.setattr(wiring, "INIT_STEPS", steps)
    override_settings(wiring_strict=False)
    assert init.main() == 0
    assert done == ["ok"]

    monkeypatch.setattr(wiring, "INIT_STEPS", (fake_step(monkeypatch, "fake_init_broken", lambda: 1 / 0),))
    override_settings(wiring_strict=True)
    assert init.main() == 1


def test_openapi_is_exported_without_server_and_database(tmp_path):
    """Приёмка Арх. 9.1: docs/api/openapi.json выгружается без запуска сервера; база для этого не нужна."""
    out, fsp_out = tmp_path / "api" / "openapi.json", tmp_path / "fsp.json"
    env = {
        **os.environ,
        "DATABASE_URL": "postgresql+psycopg://nobody:nothing@127.0.0.1:1/absent",
        "PYTHONPATH": str(BACKEND_DIR),
    }
    result = subprocess.run(
        [sys.executable, "-m", "app.scripts.export_openapi", "--out", str(out), "--fsp-out", str(fsp_out)],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    schema = json.loads(out.read_text("utf-8"))
    assert schema["info"]["title"] == "ФСП.Подбор"
    assert schema["paths"]["/api/v1/health"]["get"]["operationId"] == "core-health"
    assert "ApiError" in schema["components"]["schemas"]
    assert out.read_text("utf-8").endswith("}\n")

    # Повторная выгрузка даёт тот же файл: схема не содержит ничего случайного.
    first = out.read_bytes()
    subprocess.run(
        [sys.executable, "-m", "app.scripts.export_openapi", "--out", str(out), "--fsp-out", str(fsp_out)],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=120, check=True,
    )  # fmt: skip
    assert out.read_bytes() == first


def test_broken_models_are_reported_in_lenient_mode_and_raise_in_strict(monkeypatch, tmp_path):
    """Сломанный models.py чужого модуля не останавливает остальных, но и не пропадает молча."""
    (tmp_path / "broken_models_pkg.py").write_text("import module_that_does_not_exist_anywhere\n", "utf-8")
    monkeypatch.syspath_prepend(tmp_path)
    monkeypatch.setattr(core_db, "MODEL_MODULES", ("broken_models_pkg", "app.modules.reports.models"))
    monkeypatch.setattr(core_db, "MODEL_IMPORT_ERRORS", {})

    assert core_db.import_all_models(strict=False) == []  # у reports моделей нет — это не ошибка
    assert list(core_db.MODEL_IMPORT_ERRORS) == ["broken_models_pkg"]
    assert "module_that_does_not_exist_anywhere" in core_db.MODEL_IMPORT_ERRORS["broken_models_pkg"]

    with pytest.raises(ModuleNotFoundError):
        core_db.import_all_models(strict=True)
