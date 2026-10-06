"""Сид демо-данных (Арх. 13.2, 13.5): `python -m app.seed [catalog-check|fsp|demo|scenario|all] [--reset]`.

Сид вызывает только фасады модулей и их функции записи (Арх. 2.5); синтетические записи помечены `is_demo`.
Шаг инициализации стенда — `seed_if_empty`: ничего не делает, пока демо-данные на месте.
"""

from __future__ import annotations


def seed_if_empty() -> None:
    """Шаг `INIT_STEPS`: создать демо-данные, если последнего аккаунта сценария (`orbita`) ещё нет."""
    from app.seed.demo import run_all, scenario_ready

    if scenario_ready():
        from app.seed.common import log

        log.info("сид: демо-данные на месте, шаг пропущен")
        return
    run_all()
