"""Инициализация стенда: `python -m app.scripts.init` (Арх. 13.2). Идемпотентна.

1. **Схема.** Если в `alembic/versions` есть ревизии — `alembic upgrade head`. Пока начальной миграции нет
   (до контрольной точки T2), схема создаётся из метаданных функцией `core.db.create_schema` — той же, что
   в тестах. При появлении миграции том БД пересоздаётся (`docker compose down -v`).
2. **Шаги `INIT_STEPS`** из `app.wiring`: банк заданий, демо-реестр ФСП, задания платформы, сид. Каждый шаг —
   функция без аргументов: идемпотентна, сессии открывает сама, фиксирует пакетами и пишет прогресс в журнал.
   Шаг, выключенный флагом, не вызывается. Шаг, модуля которого ещё нет, пропускается с предупреждением.
   Ошибка внутри шага: при `WIRING_STRICT=true` останавливает инициализацию (код возврата 1), при `false`
   пишется в журнал, и скрипт идёт дальше — недописанный шаг одного пакета не блокирует стенд остальных.

Запускает скрипт только сервис `migrate`; воркеры `api` схему не трогают.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

from sqlalchemy.exc import OperationalError

from app import wiring
from app.core import db
from app.core.config import BACKEND_DIR, Settings, get_settings
from app.core.logging import setup_logging

log = logging.getLogger("app.init")

ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
VERSIONS_DIR = BACKEND_DIR / "alembic" / "versions"
DB_WAIT_SECONDS = 60


def revisions() -> list[Path]:
    """Файлы ревизий Alembic; пустой список — начальной миграции ещё нет."""
    if not VERSIONS_DIR.is_dir():
        return []
    return sorted(path for path in VERSIONS_DIR.glob("*.py") if not path.name.startswith("_"))


def wait_for_db(timeout: float = DB_WAIT_SECONDS) -> None:
    """Дождаться базы: compose стартует `migrate` после healthcheck, но локальный запуск может опередить её."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            db.ping()
            return
        except OperationalError as exc:
            if time.monotonic() >= deadline:
                raise
            log.info("база ещё не отвечает, жду: %s", str(exc.orig).strip().splitlines()[0] if exc.orig else exc)
            time.sleep(1)


def init_schema() -> str:
    """Шаг 1: схема из миграций, если они есть, иначе из метаданных. Возвращает использованный способ."""
    found = revisions()
    if found:
        from alembic.config import Config

        from alembic import command

        log.info("схема: alembic upgrade head (ревизий: %s)", len(found))
        config = Config(str(ALEMBIC_INI))
        config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        config.attributes["configure_logger"] = False  # журнал уже настроен приложением (alembic/env.py)
        command.upgrade(config, "head")
        return "alembic"
    log.info("схема: миграций ещё нет — создаю из метаданных (core.db.create_schema)")
    db.create_schema()
    return "metadata"


def run_steps(settings: Settings) -> dict[str, str]:
    """Шаг 2: `INIT_STEPS`. Возвращает исход по каждому шагу: `done`, `disabled`, `missing`, `failed`."""
    outcome: dict[str, str] = {}
    total = len(wiring.INIT_STEPS)
    for number, spec in enumerate(wiring.INIT_STEPS, start=1):
        label = f"шаг {number}/{total} {spec}"
        if not wiring.enabled(spec, settings):
            log.info("%s: выключен флагом %s", label, wiring.REQUIRES[spec])
            outcome[spec] = "disabled"
            continue
        try:
            step = wiring.load(spec)
        except wiring.WiringError as exc:
            if getattr(exc, "absent", False):
                log.warning("%s: пропущен — модуля ещё нет", label)
                outcome[spec] = "missing"
                continue
            if settings.wiring_strict:
                raise
            log.warning("%s: пропущен — %s", label, exc)
            outcome[spec] = "failed"
            continue
        started = time.monotonic()
        log.info("%s: начат", label)
        try:
            step()
        except Exception:
            if settings.wiring_strict:
                log.exception("%s: ошибка, инициализация остановлена", label)
                raise
            log.exception("%s: ошибка, шаг пропущен (WIRING_STRICT=false)", label)
            outcome[spec] = "failed"
            continue
        log.info("%s: готов за %.1f с", label, time.monotonic() - started)
        outcome[spec] = "done"
    return outcome


def main() -> int:
    settings = get_settings()
    setup_logging(settings.log_level)
    started = time.monotonic()
    log.info("инициализация стенда: APP_ENV=%s, DEMO_MODE=%s", settings.app_env, str(settings.demo).lower())
    try:
        wait_for_db()
        init_schema()
        outcome = run_steps(settings)
    except Exception:
        log.exception("инициализация не завершена")
        return 1
    finally:
        db.dispose_engine()
    summary = ", ".join(f"{spec.removeprefix('app.')} — {state}" for spec, state in outcome.items())
    log.info("инициализация завершена за %.1f с: %s", time.monotonic() - started, summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
