"""Виртуальные кандидаты и «истинные» параметры заданий (Арх. 12.1; приложение A, §10.1).

Ответы виртуальных кандидатов порождает та же логистическая модель, на которой построен движок, а истинный грейд
задан теми же порогами. Поэтому всё, что считается на этой популяции, — самосогласованность механики со своими
допущениями, а не валидность теста. Параметры по умолчанию — допущения из Арх. 12.1; анализ чувствительности
(V9) меняет их по одному.

Единственный источник случайности — переданный `random.Random`: при том же seed популяция та же.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.modules.assessment.blueprints import lang_module
from app.modules.assessment.config import GRADES, get_config
from app.modules.assessment.groups import GROUPS
from app.shared.salary import min_salary_ladder

#: Медиана ожиданий по грейду, руб. в месяц — допущение синтетического мира.
SALARY_MEDIAN: dict[str, int] = {"junior": 90_000, "middle": 190_000, "senior": 320_000}
PERSONAS: tuple[tuple[str, float], ...] = (
    ("responsive", 0.55),
    ("selective", 0.20),
    ("expensive", 0.15),
    ("silent", 0.10),
)
WORK_FORMATS: tuple[str, ...] = ("office", "hybrid", "remote")
LANGUAGES: dict[str, tuple[tuple[str, float], ...]] = {
    "backend": (("python", 0.45), ("java", 0.20), ("go", 0.10), ("nodejs", 0.10), ("csharp", 0.10), ("php", 0.05)),
    "frontend": (("javascript", 0.5), ("typescript", 0.5)),
    "fullstack": (("javascript", 0.5), ("typescript", 0.5)),
    "data_ml": (("python", 0.8), ("r", 0.1), ("sql_only", 0.1)),
}


@dataclass(frozen=True)
class PopulationParams:
    """Допущения о популяции (Арх. 12.1)."""

    theta_mean: float = 0.2
    theta_sd: float = 1.3
    #: Разброс уровня по группам навыков: уровень в группе = `theta_true + delta[group]`.
    delta_sd: float = 0.4
    #: Заявленный грейд: истинный, на грейд выше, на грейд ниже.
    claim_true: float = 0.60
    claim_up: float = 0.25
    #: Если задано, кандидаты сгущены у порогов: центры смеси — пороги грейдов ± это значение, `theta_sd` — её разброс.
    near_cuts: float | None = None


@dataclass(frozen=True)
class VirtualCandidate:
    """Виртуальный кандидат: то, что знает симулятор и чего не знает движок."""

    id: int
    specialization: str
    theta_true: float
    delta: Mapping[str, float]
    #: Истинный грейд по `THETA_CUT`; `None` — ниже Junior.
    true_grade: str | None
    claimed_grade: str
    main_language: str
    lang_module: str | None
    behavior: str = "honest"
    persona: str = "responsive"
    work_formats: tuple[str, ...] = ("remote",)
    min_salary: int | None = None

    def ability(self, group: str) -> float:
        """Уровень кандидата в группе навыков."""
        return self.theta_true + self.delta.get(group, 0.0)


def true_grade(theta: float) -> str | None:
    """Истинный грейд: старший грейд с порогом не выше `theta`; ниже −1.5 — без грейда."""
    cuts = get_config().theta_cut
    result = None
    for grade in GRADES:
        if theta >= cuts[grade]:
            result = grade
    return result


def _weighted(rng: random.Random, options: Sequence[tuple[str, float]]) -> str:
    point, acc = rng.random(), 0.0
    for value, weight in options:
        acc += weight
        if point < acc:
            return value
    return options[-1][0]


def _claimed(rng: random.Random, grade: str | None, params: PopulationParams) -> str:
    """Заявленный грейд: истинный 0.60, на грейд выше 0.25, ниже 0.15 — в границах справочника."""
    index = GRADES.index(grade) if grade is not None else -1
    point = rng.random()
    if point < params.claim_true:
        shift = 0
    elif point < params.claim_true + params.claim_up:
        shift = 1
    else:
        shift = -1
    return GRADES[min(max(index + shift, 0), len(GRADES) - 1)]


def _min_salary(rng: random.Random, grade: str) -> int | None:
    """Минимум ожиданий: у 30 % не задан, у остальных — ступень лестницы у медианы грейда × exp(N(0, 0.2))."""
    if rng.random() < 0.30:
        rng.gauss(0, 1)  # число обращений к датчику не зависит от ветки
        return None
    target = SALARY_MEDIAN[grade] * math.exp(rng.gauss(0, 0.2))
    return min(min_salary_ladder(), key=lambda step: (abs(step - target), step))


def generate(
    n: int,
    specializations: Sequence[str],
    rng: random.Random,
    params: PopulationParams | None = None,
    *,
    first_id: int = 0,
) -> list[VirtualCandidate]:
    """`n` виртуальных кандидатов, поровну по специализациям (по кругу).

    `theta_true ~ N(0.2, 1.3²)`; `delta[group] ~ N(0, 0.4²)`; истинный грейд по `THETA_CUT`; заявленный грейд,
    персона демо-ответчика, форматы работы и минимум ожиданий — по Арх. 12.1.
    """
    params = params or PopulationParams()
    cuts = get_config().theta_cut
    result = []
    for index in range(n):
        spec = specializations[index % len(specializations)]
        if params.near_cuts is None:
            theta = rng.gauss(params.theta_mean, params.theta_sd)
        else:
            center = cuts[rng.choice(GRADES)] + rng.choice((-1.0, 1.0)) * params.near_cuts
            theta = rng.gauss(center, params.theta_sd)
        delta = {group: rng.gauss(0.0, params.delta_sd) for group in GROUPS}
        grade = true_grade(theta)
        claimed = _claimed(rng, grade, params)
        language = _weighted(rng, LANGUAGES.get(spec, (("other", 1.0),)))
        formats = tuple(f for f in WORK_FORMATS if rng.random() < 0.5) or (rng.choice(WORK_FORMATS),)
        result.append(
            VirtualCandidate(
                id=first_id + index,
                specialization=spec,
                theta_true=theta,
                delta=delta,
                true_grade=grade,
                claimed_grade=claimed,
                main_language=language,
                lang_module=lang_module(spec, language) if spec in LANGUAGES else None,
                behavior="honest",
                persona=_weighted(rng, PERSONAS),
                work_formats=formats,
                min_salary=_min_salary(rng, grade or GRADES[0]),
            )
        )
    return result


# --------------------------------------------------------------------------------------------------------------------
# «Истинные» параметры заданий
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class WorldParams:
    """Допущения о заданиях, которых движок не знает (Арх. 12.1)."""

    #: Наклон: `a_true ~ LogNormal(ln a_mean, a_sd)`, обрезан до [0.5, 2.2].
    a_mean: float = 1.1
    a_sd: float = 0.25
    #: Ошибка назначенной сложности: `b_true = b + N(0, b_error_sd²)`.
    b_error_sd: float = 0.4
    #: Дрейф варианта: `N(0, drift_sd²)` на каждую выдачу.
    drift_sd: float = 0.25
    #: Намеренно испорченные семейства (V6): у них `a_true = broken_a`.
    broken: tuple[str, ...] = ()
    broken_a: float = 0.15


@dataclass(frozen=True)
class ItemWorld:
    """Истинные параметры заданий одного прогона."""

    params: WorldParams
    a_true: Mapping[str, float]
    b_true: Mapping[tuple[str, int], float]
    extra: Mapping[str, Any] = field(default_factory=dict)


def item_world(families: Iterable[Any], rng: random.Random, params: WorldParams | None = None) -> ItemWorld:
    """Разыграть истинные наклоны семейств и истинные сложности уровней.

    `families` — объекты с `id` и `levels` (у уровня — `level` и `b`): строки реестра, паспорта, семейства банка.
    """
    params = params or WorldParams()
    a_true: dict[str, float] = {}
    b_true: dict[tuple[str, int], float] = {}
    for family in sorted(families, key=lambda item: item.id):
        a = math.exp(rng.gauss(math.log(params.a_mean), params.a_sd))
        a_true[family.id] = params.broken_a if family.id in params.broken else min(2.2, max(0.5, a))
        for level in family.levels:
            b_true[(family.id, level.level)] = float(level.b) + rng.gauss(0.0, params.b_error_sd)
    return ItemWorld(params=params, a_true=a_true, b_true=b_true)


def p_correct(
    candidate: VirtualCandidate,
    world: ItemWorld,
    family_id: str,
    group: str,
    level: int,
    c: float,
    rng: random.Random,
    *,
    shift: float = 0.0,
) -> float:
    """`P(верно) = c + (1 − c) / (1 + exp(−(a_true · (θ_true + δ[group] − b_true − дрейф) + shift)))`.

    `shift` — сдвиг знакомства с заданием в логитах (повторные попытки, утечка): положительный облегчает.
    Задания не «решаются»: моделируется только факт верного ответа.
    """
    drift = rng.gauss(0.0, world.params.drift_sd)
    logit = world.a_true[family_id] * (candidate.ability(group) - world.b_true[(family_id, level)] - drift) + shift
    return c + (1.0 - c) / (1.0 + math.exp(-logit))
