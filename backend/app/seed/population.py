"""Синтетическая популяция: кандидаты `backend` трёх грейдов с результатами теста (Арх. 13.5).

Путь каждого кандидата по тесту получен прогоном настоящего движка на симулированных ответах
(`app.eval.testing.pathsim`) и записан `assessment.seed_result`; исходы, категорию, уровень и вердикты по навыкам
считает модуль `assessment`. Запись идёт пакетами с фиксацией; уже существующие ключи пропускаются.
"""

from __future__ import annotations

import os
import random
from datetime import timedelta

from app.core import clock
from app.core.db import session_scope
from app.eval.testing.bank import from_db
from app.modules.fsp import service as fsp
from app.modules.identity import service as identity
from app.seed import common as C
from app.seed import people
from app.simulation.population import WorldParams, item_world

PLAN_OFFSET = 1


def population_size() -> int:
    return int(os.environ.get("SEED_PER_SPECIALIZATION", C.DEFAULT_POPULATION))


def _grades(count: int) -> list[str]:
    grades: list[str] = []
    for grade, share in C.GRADE_SHARES:
        grades += [grade] * round(count * share)
    return (grades + ["middle"] * count)[:count]


def seed_population(count: int | None = None) -> int:
    """Создать синтетических кандидатов; вернуть число созданных сейчас."""
    count = count or population_size()
    if not C.ensure_ready():
        return 0
    available = set(C.available_grades())
    rng = C.rng_for(PLAN_OFFSET)
    with session_scope() as db:
        bank = from_db(db)
        now = clock.now(db)
        pool_history = sorted(fsp.demo_athlete_pool(with_history=True), key=lambda item: item.fsp_id)
        pool_empty = sorted(fsp.demo_athlete_pool(with_history=False), key=lambda item: item.fsp_id)
    world = item_world(bank.families, rng, WorldParams())
    rng.shuffle(pool_history)
    rng.shuffle(pool_empty)
    grades = [grade if grade in available else sorted(available)[0] for grade in _grades(count)]
    history_n, empty_n = round(count * C.FSP_HISTORY_SHARE), round(count * C.FSP_EMPTY_SHARE)
    fsp_ids = [item.fsp_id for item in pool_history[:history_n]] + [item.fsp_id for item in pool_empty[:empty_n]]
    order = list(range(count))
    random.Random(C.SEED + 2).shuffle(order)
    fsp_by_index = dict(zip(order, fsp_ids, strict=False))

    people_list: list[people.Person] = []
    for index in range(1, count + 1):
        finished_at = now - timedelta(days=rng.uniform(40, 90))
        candidate, path, sessions = people.simulate(bank, world, rng, index, grades[index - 1], finished_at)
        person = people.build_person(
            C.population_key(index),
            index,
            candidate,
            path,
            sessions,
            rng,
            finished_at,
            claimed=candidate.claimed_grade,
            publish=index % 16 != 0,
        )
        person.fsp_id = fsp_by_index.get(index - 1)
        people_list.append(person)

    created = 0
    for start in range(0, count, C.BATCH):
        with session_scope() as db:
            for person in people_list[start : start + C.BATCH]:
                if identity.demo_user_ids(db, [person.key]):
                    continue
                people.create_candidate(db, person)
                created += 1
        C.log.info("сид: кандидаты %d/%d", min(start + C.BATCH, count), count)
    return created
