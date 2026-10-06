"""Эксперименты V1–V10 валидации тестирования (Арх. 12.2; приложение A, §10.2).

Каждый эксперимент возвращает таблицу строк «показатель, значение, интервал, планка, выполнено». Планка считается
выполненной, если ей удовлетворяет граница 95-процентного бутстреп-интервала, а не точечная оценка. Все числа —
самосогласованность механики со своими допущениями (Арх. 12): ответы порождает та же модель, что лежит в движке.

Случайность: у каждого кандидата и каждого эксперимента свой датчик `random.Random(f"{seed}:{метка}:{id}")`,
поэтому результат не зависит от порядка обхода и при том же seed совпадает побайтно.
"""

# ruff: noqa: E501 — подписи отчёта и длинные проверки читаются лучше в одну строку

from __future__ import annotations

import math
import random
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from app.eval.testing.bank import SimBank
from app.eval.testing.pathsim import PathResult, SimSession, simulate_path, simulate_session, with_theta
from app.modules.assessment import blueprints
from app.modules.assessment.config import GRADES, get_config
from app.modules.assessment.engine import assemble
from app.modules.assessment.engine.decide import CONFIRMING
from app.modules.assessment.engine.model import estimate
from app.modules.assessment.engine.skills import SkillAnswer, group_verdicts, skill_proofs
from app.modules.assessment.groups import SKILL_GROUP_MAP
from app.shared.enums import SkillVerdict, TestOutcome
from app.simulation.population import (
    ItemWorld,
    PopulationParams,
    VirtualCandidate,
    WorldParams,
    generate,
    item_world,
)

BOOTSTRAP = 200
#: Расстояние до порога, дальше которого ошибка решения считается «вдали от порога».
FAR = 0.4
LEAK_M: tuple[int, ...] = (0, 1, 2, 3, 5, 10, 30)
LEAK_SHIFTS: tuple[float, ...] = (0.5, 1.0)
FAMILIARITY_SHIFT = 0.3
SERIES: tuple[int, ...] = (1, 2, 4, 8)
V7_SESSIONS: tuple[int, ...] = (100, 300, 1500)
V7_VARIANTS: tuple[int, ...] = (60, 200)
_DIRECT = {group: item.direct for group, item in SKILL_GROUP_MAP.items()}
_GRADE_INDEX: dict[str | None, int] = {None: 0, **{grade: index + 1 for index, grade in enumerate(GRADES)}}


def _r(value: float | None, digits: int = 4) -> float | None:
    return None if value is None or math.isnan(value) else round(value, digits)


def _rng(seed: int, label: str, key: object = "") -> random.Random:
    return random.Random(f"{seed}:{label}:{key}")


def _interval(stat: Callable[[Sequence[int]], float], n: int, rng: random.Random) -> tuple[float | None, float | None]:
    """Перцентильный 95-процентный бутстреп-интервал статистики по `n` объектам."""
    if n < 2:
        return None, None
    indexes = range(n)
    values = sorted(stat(rng.choices(indexes, k=n)) for _ in range(BOOTSTRAP))
    values = [v for v in values if not math.isnan(v)]
    if not values:
        return None, None
    return values[int(0.025 * (len(values) - 1))], values[math.ceil(0.975 * (len(values) - 1))]


def row(
    metric: str,
    label: str,
    value: float | None,
    ci: tuple[float | None, float | None] = (None, None),
    *,
    bar: float | None = None,
    op: str | None = None,
    n: int | None = None,
    unit: str = "share",
) -> dict[str, Any]:
    """Строка таблицы отчёта. `op` — «>=» или «<=»: планка сверяется с нижней или верхней границей интервала."""
    low, high = ci
    met: bool | None = None
    if bar is not None and value is not None:
        edge = (low if op == ">=" else high) if low is not None and high is not None else value
        met = edge >= bar if op == ">=" else edge <= bar
    return {
        "metric": metric,
        "label": label,
        "value": _r(value),
        "ci": [_r(low), _r(high)],
        "bar": bar,
        "op": op,
        "met": met,
        "n": n,
        "unit": unit,
    }


def share(metric: str, label: str, flags: Sequence[bool], rng: random.Random, **kw: Any) -> dict[str, Any]:
    """Доля с бутстреп-интервалом."""
    data = [1 if flag else 0 for flag in flags]
    if not data:
        return row(metric, label, None, n=0, **kw)
    return row(
        metric, label, sum(data) / len(data),
        _interval(lambda idx: sum(data[i] for i in idx) / len(idx), len(data), rng), n=len(data), **kw,
    )


def kappa(a: Sequence[Any], b: Sequence[Any]) -> float:
    """κ Коэна для двух разметок."""
    n = len(a)
    if n == 0:
        return float("nan")
    agree = sum(1 for x, y in zip(a, b, strict=True) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    chance = sum(ca[key] * cb.get(key, 0) for key in ca) / (n * n)
    return 1.0 if chance >= 1 else (agree - chance) / (1 - chance)


def pearson(x: Sequence[float], y: Sequence[float]) -> float:
    n = len(x)
    if n < 3:
        return float("nan")
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((v - mx) ** 2 for v in x)
    syy = sum((v - my) ** 2 for v in y)
    if sxx <= 0 or syy <= 0:
        return float("nan")
    return sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True)) / math.sqrt(sxx * syy)


def auc(negative: Sequence[float], positive: Sequence[float]) -> float:
    """Площадь под ROC: вероятность того, что оценка у «старшего» выше, чем у «младшего»."""
    if not negative or not positive:
        return float("nan")
    ranked = sorted([(v, 0) for v in negative] + [(v, 1) for v in positive])
    rank_sum, i = 0.0, 0
    while i < len(ranked):
        j = i
        while j < len(ranked) and ranked[j][0] == ranked[i][0]:
            j += 1
        mean_rank = (i + j + 1) / 2
        rank_sum += mean_rank * sum(1 for k in range(i, j) if ranked[k][1])
        i = j
    return (rank_sum - len(positive) * (len(positive) + 1) / 2) / (len(negative) * len(positive))


# --------------------------------------------------------------------------------------------------------------------
# Общий прогон: одна сессия, вторая независимая, полный путь дважды
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Scenario:
    """Набор допущений: популяция, «истинные» параметры заданий, знает ли их движок."""

    key: str
    label: str
    population: PopulationParams = field(default_factory=PopulationParams)
    world: WorldParams = field(default_factory=WorldParams)
    omniscient: bool = False


@dataclass
class Core:
    """Сырые результаты общего прогона одного сценария."""

    scenario: Scenario
    candidates: list[VirtualCandidate]
    world: ItemWorld
    first: list[SimSession]
    second: list[SimSession]
    path_a: list[PathResult]
    path_b: list[PathResult]


def population(bank: SimBank, seed: int, n: int, params: PopulationParams, label: str = "pop") -> list[VirtualCandidate]:
    """Популяция сценария: поровну по специализациям с доступным тестом; заявленный грейд — только из доступных пар."""
    pairs = bank.pairs()
    specs = sorted({spec for spec, _ in pairs}, key=lambda s: [p[0] for p in pairs].index(s))
    result = []
    for candidate in generate(n, specs, _rng(seed, label), params):
        grades = [grade for spec, grade in pairs if spec == candidate.specialization]
        if candidate.claimed_grade not in grades:
            nearest = min(grades, key=lambda g: abs(GRADES.index(g) - GRADES.index(candidate.claimed_grade)))
            candidate = with_theta(candidate, candidate.theta_true, claimed=nearest)
        result.append(candidate)
    return result


def run_core(bank: SimBank, seed: int, n: int, scenario: Scenario) -> Core:
    """V1–V4 одного сценария: сессия на заявленный грейд, вторая независимая сессия, полный путь дважды."""
    people = population(bank, seed, n, scenario.population, f"pop:{scenario.key}")
    world = item_world(bank.families, _rng(seed, f"world:{scenario.key}"), scenario.world)
    first: list[SimSession] = []
    second: list[SimSession] = []
    path_a: list[PathResult] = []
    path_b: list[PathResult] = []
    omni = scenario.omniscient
    for person in people:
        first.append(
            simulate_session(person, bank, world, _rng(seed, f"s1:{scenario.key}", person.id), person.claimed_grade, omniscient=omni)
        )
        second.append(
            simulate_session(
                person, bank, world, _rng(seed, f"s2:{scenario.key}", person.id), person.claimed_grade,
                seed_tag="#b", omniscient=omni,
            )
        )
        path_a.append(simulate_path(person, bank, _rng(seed, f"pa:{scenario.key}", person.id), world=world, omniscient=omni))
        path_b.append(
            simulate_path(person, bank, _rng(seed, f"pb:{scenario.key}", person.id), world=world, seed_tag="#b", omniscient=omni)
        )
    return Core(scenario, people, world, first, second, path_a, path_b)


def _confirmed(session: SimSession) -> bool:
    return session.outcome in CONFIRMING


def v1(core: Core, seed: int) -> dict[str, Any]:
    """V1 — одна сессия на заявленный грейд: исходы, длина, точность среди решённых."""
    cuts = get_config().theta_cut
    rng = _rng(seed, f"boot:v1:{core.scenario.key}")
    decided: list[bool] = []
    far: list[bool] = []
    false_confirm: list[bool] = []
    false_reject: list[bool] = []
    for person, session in zip(core.candidates, core.first, strict=True):
        truth = person.theta_true >= cuts[session.grade]
        if session.outcome is TestOutcome.BORDERLINE:
            continue
        correct = _confirmed(session) == truth
        decided.append(correct)
        if abs(person.theta_true - cuts[session.grade]) > FAR:
            far.append(not correct)
        (false_reject if truth else false_confirm).append(_confirmed(session) != truth)
    n = len(core.first)
    outcomes = Counter(session.outcome.value for session in core.first)
    lengths = Counter(session.length for session in core.first)
    return {
        "rows": [
            share("v1_accuracy", "Точность среди решённых (исход против истинного уровня)", decided, rng, bar=0.88, op=">="),
            share("v1_far_errors", f"Ошибки дальше {FAR} от порога", far, rng, bar=0.04, op="<="),
            share("v1_false_confirm", "Ложное подтверждение (уровень ниже порога)", false_confirm, rng),
            share("v1_false_reject", "Ложный отказ (уровень не ниже порога)", false_reject, rng),
            row("v1_mean_length", "Средняя длина теста, заданий", sum(s.length for s in core.first) / n, n=n, unit="items"),
        ],
        "outcomes": {outcome.value: _r(outcomes.get(outcome.value, 0) / n) for outcome in TestOutcome},
        "lengths": {str(length): _r(count / n) for length, count in sorted(lengths.items())},
    }


def v2(core: Core, seed: int) -> dict[str, Any]:
    """V2 — две независимые сессии: согласие решения и доля противоречий."""
    cuts = get_config().theta_cut
    rng = _rng(seed, f"boot:v2:{core.scenario.key}")
    agree: list[bool] = []
    contradiction: list[bool] = []
    bins: dict[str, list[bool]] = {}
    edges = ((0.0, 0.25), (0.25, 0.5), (0.5, 1.0), (1.0, 9.0))
    for person, a, b in zip(core.candidates, core.first, core.second, strict=True):
        same = _confirmed(a) == _confirmed(b)
        agree.append(same)
        pair = {a.outcome, b.outcome}
        contradiction.append(TestOutcome.NOT_CONFIRMED in pair and bool(pair & CONFIRMING))
        distance = abs(person.theta_true - cuts[a.grade])
        for low, high in edges:
            if low <= distance < high:
                bins.setdefault(f"{low}–{high if high < 9 else '∞'}", []).append(same)
    four = [a.outcome == b.outcome for a, b in zip(core.first, core.second, strict=True)]
    return {
        "rows": [
            share("v2_agreement", "Согласие решения «подтверждён или нет»", agree, rng, bar=0.75, op=">="),
            share("v2_contradictions", "Противоречия «подтверждён ↔ не подтверждён»", contradiction, rng, bar=0.09, op="<="),
            share("v2_agreement_four", "Согласие четырёх исходов", four, rng),
            row(
                "v2_kappa", "κ Коэна по четырём исходам",
                kappa([s.outcome for s in core.first], [s.outcome for s in core.second]), n=len(four), unit="kappa",
            ),
        ],
        "by_distance": [
            {"distance": key, "agreement": _r(sum(flags) / len(flags)), "n": len(flags)} for key, flags in bins.items()
        ],
    }


def v3(core: Core, seed: int) -> dict[str, Any]:
    """V3 — полный путь по правилам грейда: итоговая категория против истинного грейда."""
    rng = _rng(seed, f"boot:v3:{core.scenario.key}")
    final = [_GRADE_INDEX[path.grade] for path in core.path_a]
    truth = [_GRADE_INDEX[person.true_grade] for person in core.candidates]
    pairs = list(zip(final, truth, strict=True))
    below = [f == 0 for f, t in pairs if t == 0]
    names = ["none", *GRADES]
    matrix = Counter((names[t], names[f]) for f, t in pairs)
    return {
        "rows": [
            share("v3_exact", "Итоговая категория совпала с истинным грейдом", [f == t for f, t in pairs], rng, bar=0.75, op=">="),
            share("v3_adjacent", "В пределах соседнего грейда", [abs(f - t) <= 1 for f, t in pairs], rng, bar=0.98, op=">="),
            share("v3_overgrade", "Завышение (категория выше истинного грейда)", [f > t for f, t in pairs], rng, bar=0.09, op="<="),
            share("v3_undergrade", "Занижение", [f < t for f, t in pairs], rng),
            share("v3_below_junior", "Кандидатов с уровнем ниже Junior в популяции", [t == 0 for t in truth], rng),
            share("v3_below_junior_no_category", "Из них остались без категории", below, rng),
            share("v3_no_category", "Всего остались без категории", [f == 0 for f in final], rng),
            row(
                "v3_mean_sessions", "Сессий на путь в среднем",
                sum(len(p.sessions) for p in core.path_a) / max(len(core.path_a), 1), n=len(core.path_a), unit="sessions",
            ),
        ],
        "confusion": [
            {"true": t, "final": f, "share": _r(matrix.get((t, f), 0) / max(len(pairs), 1))} for t in names for f in names
        ],
        # Вариант не повторяется у одного кандидата: одной паре (семейство, уровень) за путь выпадает не больше раз,
        # чем в ней вариантов.
        "max_same_level_per_candidate": max(
            (
                max(Counter((i.family_id, i.level) for s in path.sessions for i in s.items).values(), default=0)
                for path in core.path_a
            ),
            default=0,
        ),
    }


def v4(core: Core, seed: int) -> dict[str, Any]:
    """V4 — полный путь дважды: стабильность итогового грейда."""
    rng = _rng(seed, f"boot:v4:{core.scenario.key}")
    a = [_GRADE_INDEX[path.grade] for path in core.path_a]
    b = [_GRADE_INDEX[path.grade] for path in core.path_b]
    k = kappa(a, b)
    interval = _interval(lambda idx: kappa([a[i] for i in idx], [b[i] for i in idx]), len(a), rng)
    return {
        "rows": [
            share("v4_agreement", "Согласие итогового грейда двух путей", [x == y for x, y in zip(a, b, strict=True)], rng, bar=0.70, op=">="),
            row("v4_kappa", "κ Коэна итогового грейда", k, interval, bar=0.55, op=">=", n=len(a), unit="kappa"),
            share("v4_two_grades", "Расхождение на два грейда и больше", [abs(x - y) >= 2 for x, y in zip(a, b, strict=True)], rng),
        ]
    }


# --------------------------------------------------------------------------------------------------------------------
# V5 — повторные попытки
# --------------------------------------------------------------------------------------------------------------------


def _attempts(
    person: VirtualCandidate,
    bank: SimBank,
    world: ItemWorld,
    rng: random.Random,
    grade: str,
    *,
    accumulate: bool,
    familiarity: float = 0.0,
    tag: str = "",
    attempts: int = 3,
) -> bool:
    """Подтвердился ли грейд хотя бы в одной из попыток одной серии (одного аккаунта)."""
    window: list[Any] = []
    for attempt in range(1, attempts + 1):
        shift = (lambda _family: familiarity) if familiarity and attempt > 1 else None
        session = simulate_session(
            person, bank, world, rng, grade, attempt=attempt,
            window=window if accumulate else (), seen={i.family_id for i in window} if accumulate else (),
            shift=shift, seed_tag=tag,
        )
        if _confirmed(session):
            return True
        window.extend(session.items)
    return False


def v5(bank: SimBank, seed: int, n: int, world: ItemWorld) -> dict[str, Any]:
    """V5 — три попытки с накоплением и без, эффект знакомства, N независимых серий без общего накопления."""
    cuts = get_config().theta_cut
    pairs = bank.pairs()
    count = max(60, n // 10)
    base = generate(count, [pairs[0][0]], _rng(seed, "v5:pop"), first_id=10_000_000)
    rng = _rng(seed, "boot:v5")
    rows, curve = [], []
    for below in (0.3, 0.5, 0.8):
        people = []
        for index, person in enumerate(base):
            spec, grade = pairs[index % len(pairs)]
            moved = with_theta(person, cuts[grade] - below, claimed=grade)
            people.append((replace(moved, specialization=spec, lang_module=None), grade))
        accumulated = [
            _attempts(p, bank, world, _rng(seed, f"v5:acc:{below}", p.id), g, accumulate=True) for p, g in people
        ]
        independent = [
            _attempts(p, bank, world, _rng(seed, f"v5:ind:{below}", p.id), g, accumulate=False) for p, g in people
        ]
        tag = str(below).replace(".", "")
        bar = {"bar": 0.10, "op": "<="} if below == 0.5 else {}
        rows.append(
            share(f"v5_three_attempts_{tag}", f"Подтверждение за три попытки, уровень на {below} ниже порога, с накоплением", accumulated, rng, **bar)
        )
        rows.append(
            share(f"v5_three_attempts_{tag}_no_pool", f"То же без накопления (считается последняя попытка), на {below} ниже", independent, rng)
        )
        if below == 0.5:
            familiar = [
                _attempts(p, bank, world, _rng(seed, "v5:fam", p.id), g, accumulate=True, familiarity=FAMILIARITY_SHIFT)
                for p, g in people
            ]
            rows.append(
                share("v5_three_attempts_familiar", f"С эффектом знакомства +{FAMILIARITY_SHIFT} логита на повторах, на 0.5 ниже (без планки)", familiar, rng)
            )
            series = [
                [
                    _attempts(p, bank, world, _rng(seed, f"v5:series:{k}", p.id), g, accumulate=True, tag=f"#acc{k}")
                    for k in range(max(SERIES))
                ]
                for p, g in people
            ]
            for size in SERIES:
                item = share(
                    f"v5_series_{size}", f"Ложное подтверждение за {size} независимых серий (новый аккаунт), на 0.5 ниже",
                    [any(result[:size]) for result in series], rng,
                )
                rows.append(item)
                curve.append({"series": size, "value": item["value"], "ci": item["ci"]})
    return {"rows": rows, "series_curve": curve, "n_per_point": count}


# --------------------------------------------------------------------------------------------------------------------
# V6 — дискриминативность
# --------------------------------------------------------------------------------------------------------------------


def broken_families(bank: SimBank) -> tuple[str, ...]:
    """Три семейства, которые намеренно портятся в V6: по одному из трёх самых больших общих групп."""
    by_group: dict[str, list[str]] = {}
    for family in bank.families:
        if len(family.specializations) >= 3:
            by_group.setdefault(family.group, []).append(family.id)
    groups = sorted(by_group, key=lambda g: (-len(by_group[g]), g))[:3]
    return tuple(sorted(by_group[g])[0] for g in groups)


def v6(bank: SimBank, seed: int, n: int, core: Core) -> dict[str, Any]:
    """V6 — дискриминативность: корреляция оценки с истиной, AUC соседних грейдов, семейства.

    Условна по модели: наклон заданий — входной параметр симуляции. Содержательна только проверка, что три
    намеренно испорченных семейства (`a_true = 0.15`) оказываются внизу списка.
    """
    rng = _rng(seed, "boot:v6")
    hat = [session.post.theta for session in core.first]
    truth = [person.theta_true for person in core.candidates]
    correlation = pearson(hat, truth)
    interval = _interval(lambda idx: pearson([hat[i] for i in idx], [truth[i] for i in idx]), len(hat), rng)
    by_grade: dict[int, list[float]] = {}
    for person, value in zip(core.candidates, hat, strict=True):
        by_grade.setdefault(_GRADE_INDEX[person.true_grade], []).append(value)
    aucs = [auc(by_grade.get(g, []), by_grade.get(g + 1, [])) for g in range(len(GRADES))]
    aucs = [value for value in aucs if not math.isnan(value)]
    mean_auc = sum(aucs) / len(aucs) if aucs else float("nan")

    broken = broken_families(bank)
    world = item_world(bank.families, _rng(seed, "world:v6"), WorldParams(broken=broken))
    scores: dict[str, tuple[list[float], list[float]]] = {}
    for person in core.candidates[: min(n, 2500)]:
        session = simulate_session(person, bank, world, _rng(seed, "v6:s", person.id), person.claimed_grade)
        responses = [item.response() for item in session.items]
        for index, item in enumerate(session.items):
            # Оценка уровня по остальным заданиям сессии: само задание в неё не входит.
            rest = estimate(responses[:index] + responses[index + 1 :]).theta
            xs, ys = scores.setdefault(item.family_id, ([], []))
            xs.append(float(item.score))
            ys.append(rest)
    table: list[dict[str, Any]] = sorted(
        (
            {"family_id": family_id, "correlation": _r(pearson(xs, ys)), "n": len(xs), "broken": family_id in broken}
            for family_id, (xs, ys) in scores.items()
            if len(xs) >= 30 and not math.isnan(pearson(xs, ys))
        ),
        key=lambda item: (item["correlation"], item["family_id"]),
    )
    bottom = {item["family_id"] for item in table[:5]}
    values = [item["correlation"] for item in table]
    median = values[len(values) // 2] if values else None
    in_bottom = sum(1 for family_id in broken if family_id in bottom)
    return {
        "rows": [
            row("v6_correlation", "Корреляция оценки уровня с истинным уровнем", correlation, interval, bar=0.85, op=">=", n=len(hat), unit="r"),
            row("v6_auc", "AUC разделения соседних истинных грейдов (среднее)", mean_auc, bar=0.85, op=">=", n=len(hat), unit="auc"),
            row("v6_family_median", "Медиана по семействам: корреляция балла с оценкой по остальным заданиям", median, n=len(table), unit="r"),
            row(
                "v6_broken_in_bottom5", "Испорченных семейств в нижней пятёрке (из трёх)", float(in_bottom),
                bar=3.0, op=">=", n=len(broken), unit="count",
            ),
        ],
        "broken": list(broken),
        "bottom": table[:8],
        "top": table[-3:],
    }


# --------------------------------------------------------------------------------------------------------------------
# V7 — экспозиция и исчерпание пула
# --------------------------------------------------------------------------------------------------------------------


def v7(bank: SimBank, seed: int, world: ItemWorld, sessions: Sequence[int] = V7_SESSIONS) -> dict[str, Any]:
    """V7 — экспозиция семейств и исчерпание вариантов при потоке сессий одной категории.

    Кандидаты сосредоточены у порога: худший случай по длине теста. Вариант выдаётся по правилу «наименьший
    `served_count`», поэтому повтор между кандидатами начинается, когда паре (семейство, уровень) выпала
    выдача сверх числа её вариантов.
    """
    cuts = get_config().theta_cut
    top = max(sessions)
    per_pair: list[dict[str, Any]] = []
    for spec, grade in bank.pairs():
        rng = _rng(seed, "v7", f"{spec}:{grade}")
        lang = bank.lang(spec, grade, None)
        ranges = [blueprints.MAIN_RANGE[grade], blueprints.STRETCH_RANGE[grade]]
        pool = sorted(
            {f.id for rng_ in ranges if rng_ for f in blueprints.eligible(bank.pools, spec, lang, None, rng_)}
        )
        seen_in: Counter[str] = Counter()
        served: Counter[tuple[str, int]] = Counter()
        first_repeat = dict.fromkeys(V7_VARIANTS)
        with_repeat = dict.fromkeys(V7_VARIANTS, 0)
        exposure_at = {}
        crowd = generate(top, [spec], _rng(seed, "v7:pop", f"{spec}:{grade}"), first_id=20_000_000)
        for index, base_person in enumerate(crowd):
            # Языки — как в популяции: часть кандидатов идёт запасным путём без языкового модуля.
            person = replace(base_person, theta_true=cuts[grade] + rng.gauss(0.0, 0.3), claimed_grade=grade)
            session = simulate_session(person, bank, world, rng, grade, seed_tag=f"#v7:{spec}:{grade}")
            repeated = dict.fromkeys(V7_VARIANTS, False)
            for item in session.items:
                seen_in[item.family_id] += 1
                served[(item.family_id, item.level)] += 1
                for variants in V7_VARIANTS:
                    if served[(item.family_id, item.level)] > variants:
                        repeated[variants] = True
            for variants in V7_VARIANTS:
                if repeated[variants]:
                    with_repeat[variants] += 1
                    if first_repeat[variants] is None:
                        first_repeat[variants] = index + 1
            if index + 1 in sessions:
                exposure_at[index + 1] = {
                    "max": max(seen_in.values()) / (index + 1),
                    "mean": sum(seen_in.values()) / (index + 1) / max(len(pool), 1),
                    "unused": sum(1 for family_id in pool if family_id not in seen_in),
                }
        per_pair.append(
            {
                "pair": f"{spec}:{grade}",
                "pool": len(pool),
                "exposure": {str(k): {m: _r(v) if m != "unused" else v for m, v in e.items()} for k, e in exposure_at.items()},
                "first_repeat": {str(v): first_repeat[v] for v in V7_VARIANTS},
                "sessions_with_repeat": {str(v): _r(with_repeat[v] / top) for v in V7_VARIANTS},
            }
        )
    by_plan = 0.0
    for spec, grade in bank.pairs():
        for lang in blueprints.lang_scenarios(spec):
            for group, slots in blueprints.plan_slots(spec, grade, lang).items():
                size = len(blueprints.eligible(bank.pools, spec, lang, group, blueprints.MAIN_RANGE[grade]))
                if size:
                    by_plan = max(by_plan, slots / size)
    worst = max(p["exposure"][str(top)]["max"] for p in per_pair)
    unused = sum(p["exposure"][str(top)]["unused"] for p in per_pair)
    rows = [
        row("v7_max_exposure", f"Наибольшая экспозиция семейства при {top} сессиях на категорию", worst, bar=0.60, op="<=", n=top),
        row("v7_unused_families", "Неиспользуемых семейств (сумма по категориям)", float(unused), bar=0.0, op="<=", unit="count"),
    ]
    rows.append(
        row(
            "v7_exposure_by_plan",
            "Экспозиция по построению: наибольшее «слоты / пул» среди привязанных групп, включая путь без языкового модуля",
            by_plan,
        )
    )
    for variants in V7_VARIANTS:
        firsts = [p["first_repeat"][str(variants)] for p in per_pair if p["first_repeat"][str(variants)] is not None]
        rows.append(
            row(
                f"v7_first_repeat_{variants}",
                f"Сессий до первого повтора варианта между кандидатами при {variants} вариантах на уровень (худшая категория)",
                float(min(firsts)) if firsts else None, n=top, unit="sessions",
            )
        )
        rows.append(
            row(
                f"v7_sessions_with_repeat_{variants}",
                f"Доля сессий хотя бы с одним уже выдававшимся вариантом при {variants} вариантах ({top} сессий, худшая категория)",
                max(p["sessions_with_repeat"][str(variants)] for p in per_pair), n=top,
            )
        )
    return {"rows": rows, "pairs": per_pair, "sessions": list(sessions)}


# --------------------------------------------------------------------------------------------------------------------
# V8 — кривая утечки
# --------------------------------------------------------------------------------------------------------------------


def v8(bank: SimBank, seed: int, n: int, world: ItemWorld) -> dict[str, Any]:
    """V8 — ложное подтверждение слабого кандидата, получившего содержание `m` чужих сессий той же категории.

    Пулы семейств (наш банк): знакомы только семейства, встретившиеся в утёкших сессиях. Одно семейство на слот:
    при `m ≥ 1` знакомы все. Знакомство сдвигает уровень на `LEAK_SHIFT` логита. Статичный банк — справочная
    линия: 100 % у него задано допущением, а не получено.
    """
    cuts = get_config().theta_cut
    pairs = bank.pairs()
    count = max(60, n // 10)
    rng = _rng(seed, "boot:v8")
    base = generate(count, [pairs[0][0]], _rng(seed, "v8:pop"), first_id=30_000_000)
    people = []
    for index, person in enumerate(base):
        spec, grade = pairs[index % len(pairs)]
        gap = 0.8 if index % 2 == 0 else 0.4
        moved = with_theta(person, cuts[grade] - gap, claimed=grade)
        moved = replace(moved, specialization=spec, lang_module=None)
        lang = bank.lang(spec, grade, None)
        leaked: list[frozenset[str]] = []
        known: set[str] = set()
        for other in range(max(LEAK_M)):
            form_seed = assemble.session_seed("leak", f"{moved.id}:{other}", spec, grade, 1)
            form = assemble.assemble_base(bank.pools, seed=form_seed, specialization=spec, grade=grade, lang=lang)
            known |= {slot.family_id for slot in form}
            leaked.append(frozenset(known))
        people.append((moved, grade, leaked))
    curves: list[dict[str, Any]] = []
    for shift in LEAK_SHIFTS:
        for design in ("pools", "single_family"):
            points: list[dict[str, Any]] = []
            for m in LEAK_M:
                flags = []
                for person, grade, leaked in people:
                    known_now = leaked[m - 1] if m else frozenset()
                    if design == "pools":
                        fn = lambda family, known_now=known_now, shift=shift: shift if family in known_now else 0.0  # noqa: E731
                    else:
                        fn = lambda _family, m=m, shift=shift: shift if m else 0.0  # noqa: E731
                    session = simulate_session(
                        person, bank, world, _rng(seed, f"v8:{design}:{shift}:{m}", person.id), grade, shift=fn
                    )
                    flags.append(_confirmed(session))
                item = share(f"v8_{design}_{shift}_{m}", "", flags, rng)
                points.append({"m": m, "value": item["value"], "ci": item["ci"]})
            curves.append({"design": design, "shift": shift, "points": points})

    def at(design: str, shift: float, m: int) -> dict[str, Any]:
        curve = next(c for c in curves if c["design"] == design and c["shift"] == shift)
        return next(p for p in curve["points"] if p["m"] == m)

    base_point, pessimistic = at("pools", 0.5, 5), at("pools", 1.0, 5)
    rows = [
        row("leak_false_confirm_m5", "Ложное подтверждение при 5 утёкших сессиях, сдвиг 0.5 (пулы семейств)", base_point["value"], tuple(base_point["ci"]), bar=0.15, op="<=", n=count),
        row("leak_false_confirm_m5_pessimistic", "То же при сдвиге 1.0 (без планки)", pessimistic["value"], tuple(pessimistic["ci"]), n=count),
        row("leak_single_family_m5", "Одно семейство на слот, 5 утёкших сессий, сдвиг 0.5", at("single_family", 0.5, 5)["value"], tuple(at("single_family", 0.5, 5)["ci"]), n=count),
        row("leak_no_leak", "Без утечки (m = 0)", at("pools", 0.5, 0)["value"], tuple(at("pools", 0.5, 0)["ci"]), n=count),
    ]
    return {
        "rows": rows,
        "curves": curves,
        "static_bank": {"value": 1.0, "note": "справочная линия: 100 % задано допущением (те же задания у всех), а не получено"},
        "n_per_point": count,
    }


# --------------------------------------------------------------------------------------------------------------------
# V9 — чувствительность
# --------------------------------------------------------------------------------------------------------------------

SCENARIOS: tuple[Scenario, ...] = (
    Scenario("slope_low", "Наклон заданий 0.8", world=WorldParams(a_mean=0.8)),
    Scenario("slope_high", "Наклон заданий 1.4", world=WorldParams(a_mean=1.4)),
    Scenario("b_error", "Ошибка сложности 0.7", world=WorldParams(b_error_sd=0.7)),
    Scenario("skill_spread", "Разброс навыков 0.7", population=PopulationParams(delta_sd=0.7)),
    Scenario("omniscient", "«Всезнающий» движок (истинные параметры заданий)", omniscient=True),
    Scenario("narrow", "Узкая популяция (SD θ = 0.8)", population=PopulationParams(theta_sd=0.8)),
    Scenario("near_cuts", "Кандидаты сгущены у порогов (±0.3)", population=PopulationParams(near_cuts=0.3, theta_sd=0.25)),
    Scenario("drift", "Дрейф варианта SD = 0.5", world=WorldParams(drift_sd=0.5)),
)

_V9_KEYS: tuple[tuple[str, str], ...] = (
    ("v1_accuracy", "v1"),
    ("v2_agreement", "v2"),
    ("v2_contradictions", "v2"),
    ("v3_exact", "v3"),
    ("v3_overgrade", "v3"),
    ("v4_agreement", "v4"),
    ("v4_kappa", "v4"),
)
_V9_BARS: dict[str, tuple[str, float]] = {
    "v2_agreement": (">=", 0.75),
    "v2_contradictions": ("<=", 0.09),
    "v3_exact": (">=", 0.75),
    "v3_overgrade": ("<=", 0.09),
    "v4_agreement": (">=", 0.70),
    "v4_kappa": (">=", 0.55),
}


def core_numbers(core: Core, seed: int) -> dict[str, float | None]:
    tables = {"v1": v1(core, seed), "v2": v2(core, seed), "v3": v3(core, seed), "v4": v4(core, seed)}
    result = {}
    for key, table in _V9_KEYS:
        result[key] = next(item["value"] for item in tables[table]["rows"] if item["metric"] == key)
    return result


def v9(bank: SimBank, seed: int, n: int, baseline: dict[str, float | None]) -> dict[str, Any]:
    """V9 — чувствительность V1–V4 к допущениям; строки, где планки V2–V4 не выполняются по точечной оценке, выделены."""
    count = max(80, n // 4)
    table: list[dict[str, Any]] = [{"key": "baseline", "label": "Базовые допущения (полная выборка)", "n": n, **baseline, "failed": []}]
    for scenario in SCENARIOS:
        numbers = core_numbers(run_core(bank, seed, count, scenario), seed)
        failed = []
        for key, (op, bar) in _V9_BARS.items():
            value = numbers[key]
            if value is not None and not (value >= bar if op == ">=" else value <= bar):
                failed.append(key)
        table.append({"key": scenario.key, "label": scenario.label, "n": count, **numbers, "failed": failed})
    table[0]["failed"] = [
        key
        for key, (op, bar) in _V9_BARS.items()
        if baseline[key] is not None and not (baseline[key] >= bar if op == ">=" else baseline[key] <= bar)  # type: ignore[operator]
    ]
    return {"table": table, "columns": [key for key, _ in _V9_KEYS], "bars": {k: list(v) for k, v in _V9_BARS.items()}}


# --------------------------------------------------------------------------------------------------------------------
# V10 — доказательства по навыкам
# --------------------------------------------------------------------------------------------------------------------


def _proofs(session: SimSession, bank: SimBank) -> tuple[dict[str, Any], dict[str, bool]]:
    answers = [
        SkillAnswer(item.group, item.b, item.score, bank.by_id[item.family_id].skill_tags) for item in session.items
    ]
    verdicts = group_verdicts(answers, session.grade)
    return verdicts, {proof.skill: proof.full for proof in skill_proofs(verdicts.values(), _DIRECT)}


def _strength_label(session: SimSession) -> str:
    """Полоса силы профиля по формуле Арх. 6.6 без сигнала ФСП (свежий результат: `se_eff = se`)."""
    try:
        from app.modules.matching import constants as matching

        z, under, weight = matching.Z_LOWER, matching.UNDER, matching.W_TEST
    except Exception:  # модуль подбора может быть ещё не собран: берутся значения Арх. 6.15
        z, under, weight = 1.0, 0.5, 0.7
    cfg = get_config()
    lower = session.post.theta - z * session.post.se
    t = min(1.0, max(0.0, (lower - cfg.theta_cut[session.grade] + under * cfg.grade_width) / ((1 + under) * cfg.grade_width)))
    strength = 100.0 * weight * t
    return "high" if strength >= 55 else "medium" if strength >= 30 else "base"


def v10(bank: SimBank, seed: int, core: Core) -> dict[str, Any]:
    """V10 — доказательства по навыкам по правилу Арх. 5.6 (с тегами), для весов 1.0 и 0.7, и «близнецы».

    Сильный по навыку — уровень в группе выше порога грейда на 0.5 и больше; слабый — ниже на 0.5 и больше.
    «Близнецы» — один и тот же кандидат на двух формах с разными seed: чем различаются наборы подтверждённых
    навыков при одинаковых θ и навыках.
    """
    cuts = get_config().theta_cut
    rng = _rng(seed, "boot:v10")
    tagged = {(family.group, tag) for family in bank.families for tag in family.skill_tags}
    stats: dict[tuple[str, str], list[str]] = {}
    group_stats: dict[str, list[bool]] = {"strong": [], "weak": []}
    for person, session in zip(core.candidates, core.first, strict=True):
        verdicts, proofs = _proofs(session, bank)
        plan = blueprints.plan_slots(person.specialization, session.grade, session.lang)
        for group, slots in sorted(plan.items()):
            ability = person.ability(group) - cuts[session.grade]
            side = "strong" if ability >= 0.5 else "weak" if ability <= -0.5 else None
            if side is None:
                continue
            verdict = verdicts.get(group)
            group_stats[side].append(verdict is not None and verdict.verdict is SkillVerdict.CONFIRMED)
            for skill in _DIRECT.get(group, ()):
                if (group, skill) not in tagged:
                    continue
                kind = "none" if skill not in proofs else "full" if proofs[skill] else "partial"
                stats.setdefault((side, "one_slot" if slots == 1 else "multi_slot"), []).append(kind)
                stats.setdefault((side, "all"), []).append(kind)
    rows = []
    titles = {"all": "все группы", "one_slot": "группы с одним слотом", "multi_slot": "группы с двумя и более слотами"}
    for scope in ("all", "one_slot", "multi_slot"):
        for side, side_title in (("strong", "сильные по навыку"), ("weak", "слабые по навыку")):
            kinds = stats.get((side, scope), [])
            prefix = f"v10_{scope}_{side}"
            head = f"{titles[scope].capitalize()}, {side_title}"
            rows.append(share(f"{prefix}_full", f"{head}: доказательство весом 1.0", [k == "full" for k in kinds], rng))
            rows.append(share(f"{prefix}_partial", f"{head}: доказательство весом 0.7", [k == "partial" for k in kinds], rng))
            rows.append(share(f"{prefix}_any", f"{head}: любое доказательство", [k != "none" for k in kinds], rng))
    rows.append(share("v10_group_confirmed_strong", "Вердикт группы «подтверждено» среди сильных по группе", group_stats["strong"], rng))
    rows.append(share("v10_group_confirmed_weak", "Вердикт группы «подтверждено» среди слабых по группе", group_stats["weak"], rng))

    skills_differ, full_differ, band_differ, overlap = [], [], [], []
    for a, b in zip(core.first, core.second, strict=True):
        if not (_confirmed(a) and _confirmed(b)):
            continue
        pa, pb = _proofs(a, bank)[1], _proofs(b, bank)[1]
        skills_differ.append(set(pa) != set(pb))
        full_differ.append({s for s, full in pa.items() if full} != {s for s, full in pb.items() if full})
        band_differ.append(_strength_label(a) != _strength_label(b))
        union = set(pa) | set(pb)
        overlap.append(len(set(pa) & set(pb)) / len(union) if union else 1.0)
    twins = [
        share("v10_twins_skills_differ", "«Близнецы»: разный набор навыков с доказательством", skills_differ, rng),
        share("v10_twins_full_differ", "«Близнецы»: разный набор навыков с весом 1.0", full_differ, rng),
        share("v10_twins_band_differ", "«Близнецы»: разная полоса силы профиля", band_differ, rng),
        row("v10_twins_overlap", "«Близнецы»: средняя доля общих навыков (Жаккар)", sum(overlap) / len(overlap) if overlap else None, n=len(overlap)),
    ]
    return {"rows": rows + twins, "twins_pairs": len(skills_differ)}
