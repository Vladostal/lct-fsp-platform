"""Сценарии сида: полный прогон, сброс и перезапуск сценария (Арх. 13.5). Хуки `DEMO_HOOKS` в `app.wiring`.

`reset_all` удаляет все демо-аккаунты через `identity.delete_user` и создаёт сид заново; `restart_scenario` удаляет
и создаёт заново только именованных кандидатов (`orbita` и демо-компании остаются), чем сохраняет приглашения
демо-компаний живым кандидатам и раскрытия.
"""

from __future__ import annotations

from app.core.db import session_scope
from app.modules.identity import service as identity
from app.seed import common as C
from app.seed import companies, population, scenario


def scenario_ready() -> bool:
    """Последний аккаунт сценария на месте."""
    with session_scope() as db:
        return bool(identity.demo_user_ids(db, [C.EMPLOYER_KEY]))


def run_all() -> dict[str, int | bool]:
    """Популяция, именованные кандидаты, демо-компании, `orbita`; каждый шаг идемпотентен."""
    if not C.ensure_ready():
        return {}
    result: dict[str, int | bool] = {}
    result["population"] = population.seed_population()
    result["named"] = scenario.seed_named()
    result["companies"] = companies.seed_companies()
    result["orbita"] = scenario.seed_orbita()
    C.log.info("сид: готово %s", result)
    return result


def reset_all() -> None:
    """Удалить все демо-аккаунты и создать сид заново от текущего времени сервиса."""
    with session_scope() as db:
        for user_id in identity.demo_user_ids(db):
            identity.delete_user(db, user_id)
    run_all()


def restart_scenario() -> None:
    """Пересоздать именованных кандидатов и их историю с `orbita` с датами от текущего времени."""
    if not C.ensure_ready():
        return
    with session_scope() as db:
        for user_id in identity.demo_user_ids(db, C.CANDIDATE_KEYS):
            identity.delete_user(db, user_id)
    scenario.seed_named()
    scenario.seed_orbita()
