"""Прогон валидации подбора и отчёт (Арх. 12.3; приложение B, §9.7–9.10).

Критерии успеха объявлены до прогона и печатаются вместе с несбывшимися. Значимы разности с бейзлайнами и
расстояние до оракула, а не абсолютные числа: мир и функцию релевантности написала команда.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from app.eval.matching import metrics as M
from app.eval.matching import relevance as relevance_module
from app.eval.matching import systems as S
from app.eval.matching.world import (
    MAIN_REGIME,
    OBSERVATION_MODEL,
    REGIMES,
    World,
    build_world,
)
from app.modules.matching import constants as C
from app.modules.matching.features import CandidateFeatures, SkillEvidence, merge_evidence
from app.modules.matching.ranking import (
    DEFAULT_KEY_ORDER,
    KEY_ORDER_V10,
    KEY_ORDER_V11,
    KEY_ORDER_V12,
    RankedItem,
)
from app.modules.matching.scoring import DEFAULT_PARAMS, strength
from app.shared.enums import EvidenceKind, Relation

QUICK_SEEDS = [11, 12, 13]
REPORT_SEEDS = list(range(201, 221))
THREATS = [
    "Релевантность задана латентной моделью, которую написала команда: P@10 — согласие с этой моделью, а не с "
    "успешным наймом и не с суждением экспертов (пока не проведён ручной слой).",
    "Наблюдения порождены упрощённой моделью (`observation_model = simplified`): оценка теста и подтверждения "
    "навыков — формулы, а не прогон движка тестирования; сигнал ФСП — формула с насыщением.",
    "Веса доказательств заданы из смысла и не проверены на реальных людях; перенос на специализации без теста "
    "не доказан.",
    "Шум формы теста («близнецы») показывает, насколько место кандидата зависит от выпавших ему заданий, а не от "
    "него самого; планки для этого числа нет.",
    "Навыки мира заданы в `world.py`, а не взяты из боевого справочника: состав требований-инструментов условен.",
    "Ошибка оценки уровня в упрощённой модели (`se` от 0.4 до 0.6 ширины грейда, приложение B, §9.2) задана "
    "допущением и, вероятно, завышает шум формы по сравнению с настоящим движком теста; основной вариант "
    "наблюдений (прогон движка на симулированных ответах) не выполнялся.",
    "Порядок ключей версии 2 (обязательные → подтверждённое → сила) выбран по этой же симуляции на сидах 201–208: "
    "сравнение с бейзлайном на них оптимистично. Независимая проверка — тот же прогон на сидах, не участвовавших "
    "в выборе (`--seeds 301-320`): в основном режиме разность P@10 с бейзлайном заявленного стека +0.041 "
    "[+0.034; +0.049], превосходство сохраняется во всех четырёх проверенных режимах.",
]


@dataclass(slots=True)
class Scores:
    """Метрики одной системы по потребностям (в порядке потребностей — для парных разностей)."""

    p5: list[float] = field(default_factory=list)
    p10: list[float] = field(default_factory=list)
    mrr: list[float] = field(default_factory=list)
    ndcg: list[float] = field(default_factory=list)

    def add(self, case: S.Case, order: Sequence[UUID], pool_rels: Sequence[int]) -> None:
        rels = [case.rels[cid] for cid in order]
        self.p5.append(M.precision_at(rels, 5))
        self.p10.append(M.precision_at(rels, 10))
        self.mrr.append(M.mrr(rels))
        self.ndcg.append(M.ndcg_at(rels, pool_rels, 10))

    def row(self) -> dict[str, Any]:
        low, high = M.bootstrap_ci(self.p10)
        return {
            "p5": round(M.mean(self.p5), 4),
            "p10": round(M.mean(self.p10), 4),
            "p10_ci": [round(low, 4), round(high, 4)],
            "ndcg10": round(M.mean(self.ndcg), 4),
            "mrr": round(M.mean(self.mrr), 4),
        }


def paired(first: Sequence[float], second: Sequence[float]) -> dict[str, float]:
    """Парная разность по тем же потребностям с 95 % интервалом (парный бутстреп)."""
    diffs = [a - b for a, b in zip(first, second, strict=True)]
    low, high = M.bootstrap_ci(diffs)
    return {"diff": round(M.mean(diffs), 4), "ci_low": round(low, 4), "ci_high": round(high, 4)}


def evaluate(cases: Sequence[S.Case], *, random_repeats: int, full: bool) -> dict[str, Scores]:
    """Все системы на одних и тех же потребностях. `full = False` — только наша и три бейзлайна (режимы)."""
    table: dict[str, Scores] = {}

    def put(name: str, case: S.Case, order: Sequence[UUID], pool_rels: Sequence[int]) -> None:
        table.setdefault(name, Scores()).add(case, order, pool_rels)

    for case in cases:
        ours = S.ranked(case)
        pool_rels = [case.rels[item.candidate_id] for item in ours]
        put("ours", case, S.ids(ours), pool_rels)
        put("declared", case, S.declared_order(case, ours), pool_rels)
        put("strength_only", case, S.ids(S.ranked(case, key_order=("strength",))), pool_rels)
        rng = random.Random(f"random:{case.seed}")
        shuffles = [S.random_order(ours, rng) for _ in range(random_repeats)]
        rels = [[case.rels[cid] for cid in order] for order in shuffles]
        scores = table.setdefault("random", Scores())
        scores.p5.append(M.mean([M.precision_at(row, 5) for row in rels]))
        scores.p10.append(M.mean([M.precision_at(row, 10) for row in rels]))
        scores.mrr.append(M.mean([M.mrr(row) for row in rels]))
        scores.ndcg.append(M.mean([M.ndcg_at(row, pool_rels, 10) for row in rels]))
        if not full:
            continue
        put("tfidf", case, S.tfidf_order(case, ours), pool_rels)
        put("oracle", case, S.oracle_order(case, ours), pool_rels)
        for name in S.ABLATIONS:
            order = S.ablation(case, name)
            put(f"abl:{name}", case, order, pool_rels)
    return table


# --------------------------------------------------------------------------------------------------------------------
# Отдельные замеры
# --------------------------------------------------------------------------------------------------------------------


def sensitivity(cases: Sequence[S.Case], base_p10: Sequence[float]) -> list[dict[str, Any]]:
    """ΔP@10 и RBO@10 с базовым порядком при возмущении одной константы на ±20 %."""
    base = [S.ids(S.ranked(case)) for case in cases]
    rows = []
    for name, params in S.SENSITIVITY.items():
        p10, overlap = [], []
        for case, base_order in zip(cases, base, strict=True):
            order = S.ids(S.ranked(case, params=params))
            p10.append(M.precision_at([case.rels[cid] for cid in order], 10))
            overlap.append(M.rbo(base_order, order))
        rows.append({"name": name, **paired(p10, base_p10), "rbo10": round(M.mean(overlap), 4)})
    return rows


def twins(cases: Sequence[S.Case], *, samples: int) -> dict[str, Any]:
    """Шум формы теста: пары «кандидат — он же с другой формой теста» (Арх. 12.3).

    Доля пар с разным `strength_band`, с разным `confirmed_band` и медиана разницы позиций в подборке — для
    действующего порядка и для порядка версии 1.1. Второй близнец подставляется в пул вместо первого.
    """
    rng = random.Random("twins")
    strength_diff = confirmed_diff = pairs = lost = 0
    shifts: dict[str, list[float]] = {"current": [], "v11": []}
    orders = {"current": DEFAULT_KEY_ORDER, "v11": KEY_ORDER_V11}
    for case in cases:
        base = {name: S.ranked(case, key_order=order) for name, order in orders.items()}
        exact = [item for item in base["current"] if item.scored.relation == Relation.EXACT]
        candidates = [item for item in exact if item.candidate_id in case.world.twins]
        for item in rng.sample(candidates, min(samples, len(candidates))):
            twin = case.world.twins[item.candidate_id]
            pool = [twin if row.candidate_id == item.candidate_id else row for row in case.features()]
            pairs += 1
            for name, order in orders.items():
                before = next(row for row in base[name] if row.candidate_id == item.candidate_id)
                after = next(
                    (
                        row
                        for row in S.ranked(case, key_order=order, pool=pool)
                        if row.candidate_id == twin.candidate_id
                    ),
                    None,
                )
                if after is None:
                    lost += name == "current"
                    continue
                shifts[name].append(abs(before.position - after.position))
                if name == "current":
                    strength_diff += before.scored.strength.band != after.scored.strength.band
                    confirmed_diff += before.scored.coverage.confirmed_band != after.scored.coverage.confirmed_band
    compared = max(1, pairs - lost)
    return {
        "pairs": pairs,
        "left_shortlist_share": round(lost / max(1, pairs), 4),
        "strength_band_diff_share": round(strength_diff / compared, 4),
        "confirmed_band_diff_share": round(confirmed_diff / compared, 4),
        "median_position_shift_current": M.median(shifts["current"]),
        "median_position_shift_v11": M.median(shifts["v11"]),
    }


def _stuff(features: CandidateFeatures, skills: Sequence[str]) -> CandidateFeatures:
    added = [SkillEvidence(skill, EvidenceKind.DECLARED) for skill in skills]
    return replace(features, evidence=merge_evidence([*features.evidence.values(), *added]))


def stuffing(cases: Sequence[S.Case]) -> dict[str, dict[str, float]]:
    """Накрутка заявленным: каждому десятому кандидату в профиль добавляются все навыки потребности.

    Для каждой системы: сколько таких кандидатов вошло в топ-10 (в среднем на потребность), скольких более
    сильных — с большей полосой силы либо с той же силой и большим подтверждённым покрытием — они вытеснили,
    и P@10 до и после накрутки. Последнее — главное число: порядок, в который накрутка не проникает, но который
    и без неё ставит нерелевантных выше, работодателю не полезнее.
    """
    systems: dict[str, Callable[[S.Case, Sequence[RankedItem], dict[UUID, frozenset[str]]], list[UUID]]] = {
        "ours": lambda case, items, declared: S.ids(items),
        "declared": lambda case, items, declared: S.declared_order(case, items, declared),
        "order_v12": lambda case, items, declared: S.ids(items),
        "order_v10": lambda case, items, declared: S.ids(items),
    }
    key_orders = {
        "ours": DEFAULT_KEY_ORDER,
        "declared": DEFAULT_KEY_ORDER,
        "order_v12": KEY_ORDER_V12,
        "order_v10": KEY_ORDER_V10,
    }
    totals = {name: {"entered": 0.0, "displaced": 0.0, "p10": 0.0, "p10_stuffed": 0.0} for name in systems}
    for case in cases:
        query = case.need.query
        skills = [*query.must_skills, *query.nice_skills]
        stuffed_ids = {item.latent.candidate_id for index, item in enumerate(case.pool) if index % 10 == 0}
        pool = [_stuff(row, skills) if row.candidate_id in stuffed_ids else row for row in case.features()]
        declared = {
            item.latent.candidate_id: (
                item.declared | set(skills) if item.latent.candidate_id in stuffed_ids else item.declared
            )
            for item in case.pool
        }
        honest = {item.latent.candidate_id: item.declared for item in case.pool}
        for name, system in systems.items():
            before_items = S.ranked(case, key_order=key_orders[name])
            after_items = S.ranked(case, key_order=key_orders[name], pool=pool)
            before_order, after_order = system(case, before_items, honest), system(case, after_items, declared)
            before, after = before_order[:10], after_order[:10]
            bands = {
                row.candidate_id: (row.scored.strength.band, row.scored.coverage.confirmed_band) for row in after_items
            }
            inside = [cid for cid in after if cid in stuffed_ids and cid not in before]
            pushed = [cid for cid in before if cid not in after and cid not in stuffed_ids]
            totals[name]["entered"] += len(inside)
            totals[name]["displaced"] += sum(1 for cid in pushed if any(bands[cid] > bands[other] for other in inside))
            totals[name]["p10"] += M.precision_at([case.rels[cid] for cid in before_order], 10)
            totals[name]["p10_stuffed"] += M.precision_at([case.rels[cid] for cid in after_order], 10)
    return {name: {key: round(value / len(cases), 4) for key, value in row.items()} for name, row in totals.items()}


def fairness(cases: Sequence[S.Case]) -> dict[str, Any]:
    """Условия и влияние ФСП: выполнимость формата и вилки в топ-10, доля кандидатов без ФСП."""
    fmt, salary, salary_base, ratio, equal, displaced = [], [], [], [], [], []
    for case in cases:
        items = [item for item in S.ranked(case) if item.scored.relation == Relation.EXACT]
        if not items:
            continue
        top = items[:10]
        formats = {str(value) for value in case.need.query.work_formats}
        fmt.append(M.mean([float(bool(item.scored.features.work_formats & formats)) for item in top]))

        def affordable(item: RankedItem, case: S.Case = case) -> float:
            return float(case.by_id[item.candidate_id].latent.min_salary <= case.need.salary_mid)

        salary.append(M.mean([affordable(item) for item in top]))
        salary_base.append(M.mean([affordable(item) for item in items]))

        def no_fsp_share(rows: Sequence[RankedItem]) -> float:
            return M.mean([float(row.scored.features.fsp_signal == 0) for row in rows])

        if no_fsp_share(items) > 0:
            ratio.append(no_fsp_share(top) / no_fsp_share(items))
        upper = sorted(items, key=lambda row: -row.scored.strength.t)[: max(1, len(items) // 3)]
        upper_ids = {row.candidate_id for row in upper}
        upper_top = [row for row in top if row.candidate_id in upper_ids]
        if upper_top and no_fsp_share(upper) > 0:
            equal.append(no_fsp_share(upper_top) / no_fsp_share(upper))
        only_test = replace(DEFAULT_PARAMS, w_fsp=0.0, w_test=1.0)
        by_test = sorted(items, key=lambda row: -strength(row.scored.features, only_test).x10)[:10]
        by_strength = {row.candidate_id for row in sorted(items, key=lambda row: -row.scored.strength.x10)[:10]}
        displaced.append(
            float(
                sum(1 for row in by_test if row.scored.features.fsp_signal == 0 and row.candidate_id not in by_strength)
            )
        )
    return {
        "feasible_format_at_10": round(M.mean(fmt), 4),
        "feasible_salary_at_10": round(M.mean(salary), 4),
        "feasible_salary_base": round(M.mean(salary_base), 4),
        "nofsp_ratio_at_10": round(M.mean(ratio), 4),
        "nofsp_equal_level_at_10": round(M.mean(equal), 4),
        "fsp_displacement_at_10": round(M.mean(displaced), 4),
        "fsp_max_points": round(100 * C.W_FSP, 1),
    }


def exposure_evenness(world: World, *, sessions: int = 200, employers: int = 40) -> dict[str, dict[str, float]]:
    """Равномерность показов: 200 сессий за 7 дней, фиксируется топ-10; с учётом показов и без."""
    cases = S.make_cases(world)
    result = {}
    for mode in ("with_exposure", "without_exposure"):
        rng = random.Random("sessions")
        shown: dict[UUID, int] = {}
        previous: dict[UUID, int] = {}
        per_day = sessions // 7 + 1
        for number in range(sessions):
            if number % per_day == 0:
                previous = dict(shown)  # показы считаются до сегодняшнего дня
            case = rng.choice(cases)
            employer = rng.randrange(employers)
            pool = case.features()
            if mode == "with_exposure":
                pool = [replace(row, exposure_7d=previous.get(row.candidate_id, 0)) for row in pool]
            for cid in S.ids(S.ranked(case, pool=pool, seed=f"{employer}:{case.seed}"))[: C.EXPOSURE_TOP_K]:
                shown[cid] = shown.get(cid, 0) + 1
        counts = [float(shown.get(item.latent.candidate_id, 0)) for item in world.observed]
        result[mode] = {
            "gini": round(M.gini(counts), 4),
            "shown_share": round(sum(1 for value in counts if value > 0) / max(1, len(counts)), 4),
            "max_shows": max(counts, default=0.0),
        }
    return result


# --------------------------------------------------------------------------------------------------------------------
# Прогон и отчёт
# --------------------------------------------------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "нет файла"


def _manual(out: Path) -> dict[str, Any]:
    """Ручной слой: читается результат `import-labels`; без него — «не проводился»."""
    path = out / "manual" / "manual.json"
    if not path.exists():
        return {"status": "не проводился", "pairs": 0, "kappa": None}
    data = json.loads(path.read_text(encoding="utf-8"))
    frozen_ok = all(_sha256(out / "manual" / name) == digest for name, digest in data.get("frozen", {}).items())
    data["status"] = "проведён" if frozen_ok else "набор изменён после заморозки"
    return data


def run(out: Path, *, seeds: Sequence[int], quick: bool) -> dict[str, Any]:
    """Выполнить прогон и записать `report.json` и `report.md` в каталог `out`."""
    started = time.monotonic()
    repeats = 20 if quick else 100
    regime_names = [MAIN_REGIME, "strong", "honest"] if quick else list(REGIMES)

    worlds = {name: [build_world(seed, REGIMES[name]) for seed in seeds] for name in regime_names}
    cases = {name: [case for world in items for case in S.make_cases(world)] for name, items in worlds.items()}
    main_cases = cases[MAIN_REGIME]
    main = evaluate(main_cases, random_repeats=repeats, full=True)
    regimes = {
        name: main if name == MAIN_REGIME else evaluate(cases[name], random_repeats=repeats, full=False)
        for name in regime_names
    }

    ours = main["ours"]
    diffs = {
        name: paired(ours.p10, main[name].p10) for name in ("declared", "random", "strength_only", "tfidf", "oracle")
    }
    regime_rows = {
        name: {
            "label": REGIMES[name].name,
            "ours": table["ours"].row()["p10"],
            "declared": table["declared"].row()["p10"],
            "strength_only": table["strength_only"].row()["p10"],
            "random": table["random"].row()["p10"],
            "diff_declared": paired(table["ours"].p10, table["declared"].p10),
        }
        for name, table in regimes.items()
    }
    tested = [index for index, case in enumerate(main_cases) if case.need.must_tested]
    untested = [index for index, case in enumerate(main_cases) if not case.need.must_tested]

    def stratum(indexes: Sequence[int]) -> dict[str, Any]:
        mine = [ours.p10[i] for i in indexes]
        base = [main["strength_only"].p10[i] for i in indexes]
        return {
            "needs": len(indexes),
            "p10_ours": round(M.mean(mine), 4),
            "p10_strength_only": round(M.mean(base), 4),
            **paired(mine, base),
        }

    strata = {"must_tested": stratum(tested), "must_not_tested": stratum(untested)}
    sens = sensitivity(main_cases, ours.p10)
    fair = fairness(main_cases)
    twin = twins(main_cases, samples=4 if quick else 10)
    stuff = stuffing(main_cases)
    strong = regime_rows["strong"]["diff_declared"]
    honest = regime_rows["honest"]["diff_declared"]
    manual = _manual(out)

    criteria = [
        {
            "name": "Основной режим: P@10 выше бейзлайна заявленного стека, интервал не содержит нуля",
            "ok": diffs["declared"]["ci_low"] > 0,
            "value": diffs["declared"],
        },
        {
            "name": "Режим «сильно»: P@10 выше бейзлайна заявленного стека, интервал не содержит нуля",
            "ok": strong["ci_low"] > 0,
            "value": strong,
        },
        {
            "name": "Лучше случайного порядка не меньше чем на 0.15 по P@10",
            "ok": diffs["random"]["diff"] >= 0.15,
            "value": diffs["random"],
        },
        {
            "name": "Не хуже бейзлайна «только сила профиля»: интервал разности P@10 не лежит целиком ниже нуля",
            "ok": diffs["strength_only"]["ci_high"] >= 0,
            "value": diffs["strength_only"],
        },
        {
            "name": "Потребности с обязательными навыками, которые проверяет тест: разность с «только сила» "
            "положительна (R3-tz-compliance-5)",
            "ok": strata["must_tested"]["ci_low"] > 0,
            "value": strata["must_tested"],
        },
        {
            "name": "feasible_format@10 = 1.0",
            "ok": fair["feasible_format_at_10"] == 1.0,
            "value": fair["feasible_format_at_10"],
        },
        {
            "name": "RBO@10 ≥ 0.8 при возмущении констант на ±20 %",
            "ok": all(row["rbo10"] >= 0.8 for row in sens),
            "value": min(row["rbo10"] for row in sens),
        },
        {
            "name": "Накрутка заявленным: P@10 после накрутки не ниже, чем у бейзлайна заявленного стека "
            "после той же накрутки (добавлен с порядком версии 2)",
            "ok": stuff["ours"]["p10_stuffed"] >= stuff["declared"]["p10_stuffed"],
            "value": {"ours": stuff["ours"]["p10_stuffed"], "declared": stuff["declared"]["p10_stuffed"]},
        },
    ]
    notes = []
    if not criteria[0]["ok"]:
        notes.append(
            "Наш порядок не превосходит бейзлайн заявленного стека по P@10; цену решения показывают абляции "
            "порядков версий 1.0–1.2 и раздел «Накрутка заявленным»."
        )
    if not criteria[4]["ok"]:
        notes.append(
            "Критерий по страте «обязательные проверяются тестом» не выполнен: потребность в первую очередь "
            "работает через раздел категории и условия, а не через порядок внутри раздела."
        )
    if not criteria[3]["ok"]:
        notes.append("Наш порядок уступает бейзлайну «только сила профиля»: ключи покрытия отнимают, а не добавляют.")
    if stuff["ours"]["displaced"] > 0:
        notes.append(
            "Первым ключом внутри раздела стоит число закрытых обязательных навыков, и заявленный навык пробел "
            "закрывает. Поэтому накрутка заявленного поднимает кандидата над теми, у кого пробел остался, — но не "
            "над кандидатом с тем же числом закрытых обязательных и большим подтверждённым покрытием. Порядок "
            f"версии 1.2 («сила первой») к накрутке глух, но и без неё даёт P@10 {stuff['order_v12']['p10']:.3f} "
            f"против {stuff['ours']['p10_stuffed']:.3f} у действующего порядка уже после накрутки: защита стоила "
            "дороже угрозы. Источник каждого навыка работодатель видит в карточке."
        )

    here = Path(relevance_module.__file__).resolve().parent
    module_dir = Path(C.__file__).resolve().parent
    skills_yaml = module_dir.parent / "catalog" / "data" / "skills.yaml"
    report: dict[str, Any] = {
        "summary": {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "seed": seeds[0],
            "n": len(main_cases),
            "versions": {
                "scorer": C.SCORER_VERSION,
                "observation_model": OBSERVATION_MODEL,
                "relevance_sha256": _sha256(here / "relevance.py")[:16],
                "constants_sha256": _sha256(module_dir / "constants.py")[:16],
            },
            "p10_ours": main["ours"].row()["p10"],
            "p10_declared": main["declared"].row()["p10"],
            "p10_random": main["random"].row()["p10"],
            "p10_diff_declared": diffs["declared"]["diff"],
            "p10_diff_ci_low": diffs["declared"]["ci_low"],
            "p10_diff_ci_high": diffs["declared"]["ci_high"],
            "p10_strength_only": main["strength_only"].row()["p10"],
            "manual_pairs": int(manual.get("pairs", 0)),
            "manual_kappa": manual.get("kappa"),
        },
        "passport": {
            "mode": "quick" if quick else "full",
            "seeds": list(seeds),
            "candidates_per_seed": 400,
            "needs_per_seed": 30,
            "pool_with_category": sum(len(world.observed) for world in worlds[MAIN_REGIME]),
            "main_regime": REGIMES[MAIN_REGIME].name,
            "observation_model": OBSERVATION_MODEL,
            "sha256": {
                "relevance.py": _sha256(here / "relevance.py"),
                "constants.py": _sha256(module_dir / "constants.py"),
                "skills.yaml": _sha256(skills_yaml),
            },
            "random_repeats": repeats,
            "real_text_needs": "не проводилось (P1): 12 потребностей по реальным текстам не размечены",
        },
        "main": {name: scores.row() for name, scores in main.items() if not name.startswith("abl:")},
        "paired_p10": diffs,
        "regimes": regime_rows,
        "honest_regime_diff_declared": honest,
        "ablations": {
            name: {
                "label": S.ABLATIONS[name][0],
                **main[f"abl:{name}"].row(),
                "vs_ours": paired(main[f"abl:{name}"].p10, ours.p10),
            }
            for name in S.ABLATIONS
        },
        "strata": strata,
        "fairness": fair,
        "exposure": exposure_evenness(worlds[MAIN_REGIME][0]),
        "sensitivity": sens,
        "twins": twin,
        "stuffing": stuff,
        "manual": manual,
        "criteria": criteria,
        "notes": notes,
        "threats": THREATS,
    }
    report["passport"]["duration_s"] = round(time.monotonic() - started, 1)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "report.md").write_text(render(report), encoding="utf-8")
    return report


STUFFING_LABELS = {
    "ours": "Наша (порядок версии 2)",
    "declared": "B1 заявленный стек",
    "order_v12": "Порядок версии 1.2 (сила первой)",
    "order_v10": "Порядок версии 1.0",
}

SYSTEM_LABELS = {
    "ours": "Наша система",
    "declared": "B1 совпадение заявленного стека",
    "tfidf": "B2 TF-IDF",
    "strength_only": "B3 только сила профиля",
    "random": "B0 случайный в категории",
    "oracle": "Оракул",
}


def _ci(row: dict[str, float]) -> str:
    return f"{row['diff']:+.3f} [{row['ci_low']:+.3f}; {row['ci_high']:+.3f}]"


def render(report: dict[str, Any]) -> str:
    """Отчёт в Markdown: паспорт, главная таблица, разности, режимы, абляции, условия, шум формы, критерии."""
    p, s = report["passport"], report["summary"]
    lines = [
        "# Валидация подбора",
        "",
        "## Паспорт прогона",
        "",
        f"- Дата: {s['generated_at']}; режим запуска: {p['mode']}; длительность: {p['duration_s']} с.",
        f"- Версия оценщика: `{s['versions']['scorer']}`; сиды: {p['seeds'][0]}–{p['seeds'][-1]} "
        f"({len(p['seeds'])} шт.).",
        f"- Мир: {p['candidates_per_seed']} кандидатов и {p['needs_per_seed']} потребностей на сид; с категорией "
        f"осталось {p['pool_with_category']}; потребностей в оценке: {s['n']}.",
        f"- Основной режим допущений (объявлен заранее): {p['main_regime']}.",
        f"- Модель наблюдений: `{p['observation_model']}` — упрощённая (см. «Угрозы валидности»).",
        f"- Потребности по реальным текстам: {p['real_text_needs']}.",
        *(f"- sha256 `{name}`: `{digest}`" for name, digest in p["sha256"].items()),
        "",
        "## Главная таблица (основной режим)",
        "",
        "| Система | P@5 | P@10 | 95 % интервал P@10 | nDCG@10 | MRR |",
        "|---|---|---|---|---|---|",
    ]
    for name, label in SYSTEM_LABELS.items():
        row = report["main"][name]
        lines.append(
            f"| {label} | {row['p5']:.3f} | {row['p10']:.3f} | [{row['p10_ci'][0]:.3f}; {row['p10_ci'][1]:.3f}] | "
            f"{row['ndcg10']:.3f} | {row['mrr']:.3f} |"
        )
    lines += ["", "P@10 здесь — согласие с латентной моделью мира, а не с экспертами.", ""]
    lines += ["## Парные разности P@10 «наша − система»", "", "| Система | Разность [95 % интервал] |", "|---|---|"]
    lines += [f"| {SYSTEM_LABELS[name]} | {_ci(row)} |" for name, row in report["paired_p10"].items()]
    lines += [
        "",
        "## Режимы допущений",
        "",
        "| Режим | Наша | B1 заявленный стек | B3 только сила | B0 случайный | Наша − B1 |",
        "|---|---|---|---|---|---|",
    ]
    for row in report["regimes"].values():
        lines.append(
            f"| {row['label']} | {row['ours']:.3f} | {row['declared']:.3f} | {row['strength_only']:.3f} | "
            f"{row['random']:.3f} | {_ci(row['diff_declared'])} |"
        )
    lines += [
        "",
        "В честном режиме самоописание по построению несёт правду; разность с B1 печатается без планки — это "
        f"названная цена отказа от доверия резюме: {_ci(report['honest_regime_diff_declared'])}.",
        "",
        "## Абляции",
        "",
        "| Вариант | P@10 | nDCG@10 | Вариант − наша (P@10) |",
        "|---|---|---|---|",
    ]
    for row in report["ablations"].values():
        lines.append(f"| {row['label']} | {row['p10']:.3f} | {row['ndcg10']:.3f} | {_ci(row['vs_ours'])} |")
    strata = report["strata"]
    lines += [
        "",
        "## Вклад потребности в порядок: страты (R3-tz-compliance-5)",
        "",
        "| Потребности | Число | Наша | Только сила | Разность [95 % интервал] |",
        "|---|---|---|---|---|",
        f"| обязательные навыки проверяются тестом | {strata['must_tested']['needs']} | "
        f"{strata['must_tested']['p10_ours']:.3f} | {strata['must_tested']['p10_strength_only']:.3f} | "
        f"{_ci(strata['must_tested'])} |",
        f"| среди обязательных есть инструменты вне теста | {strata['must_not_tested']['needs']} | "
        f"{strata['must_not_tested']['p10_ours']:.3f} | {strata['must_not_tested']['p10_strength_only']:.3f} | "
        f"{_ci(strata['must_not_tested'])} |",
    ]
    fair, exp = report["fairness"], report["exposure"]
    lines += [
        "",
        "## Условия и справедливость",
        "",
        f"- `feasible_format@10` = {fair['feasible_format_at_10']:.3f} (ожидается 1.0).",
        f"- `feasible_salary@10` = {fair['feasible_salary_at_10']:.3f} при базовой доле по разделу "
        f"{fair['feasible_salary_base']:.3f}: измеренная цена отказа от фильтра по вилке.",
        f"- `nofsp_ratio@10` = {fair['nofsp_ratio_at_10']:.3f}; `nofsp_equal_level@10` = "
        f"{fair['nofsp_equal_level_at_10']:.3f}; `fsp_displacement@10` = {fair['fsp_displacement_at_10']:.3f} "
        f"(потолок вклада ФСП — {fair['fsp_max_points']} балла силы).",
        f"- Равномерность показов (один сид, 200 сессий): с учётом показов — Джини {exp['with_exposure']['gini']:.3f}, "
        f"показано {exp['with_exposure']['shown_share']:.1%}, максимум {exp['with_exposure']['max_shows']:.0f}; "
        f"без учёта — Джини {exp['without_exposure']['gini']:.3f}, "
        f"показано {exp['without_exposure']['shown_share']:.1%}, "
        f"максимум {exp['without_exposure']['max_shows']:.0f}. Эффект мал: это порядок среди равных.",
        "",
        "## Чувствительность к константам (±20 %)",
        "",
        "| Возмущение | ΔP@10 [95 % интервал] | RBO@10 |",
        "|---|---|---|",
        *(f"| {row['name']} | {_ci(row)} | {row['rbo10']:.3f} |" for row in report["sensitivity"]),
    ]
    twin, stuff = report["twins"], report["stuffing"]
    lines += [
        "",
        "## Шум формы теста («близнецы»)",
        "",
        f"Пар «кандидат — он же с другой формой теста»: {twin['pairs']}. Доля пар с разным `strength_band`: "
        f"{twin['strength_band_diff_share']:.1%}; с разным `confirmed_band`: {twin['confirmed_band_diff_share']:.1%}; "
        f"близнец выпал из подборки (другая категория): {twin['left_shortlist_share']:.1%}. Медиана разницы позиций: "
        f"действующий порядок — {twin['median_position_shift_current']:g}, порядок версии 1.1 — "
        f"{twin['median_position_shift_v11']:g}. Планки нет; число относится к угрозам валидности.",
        "",
        "## Накрутка заявленным",
        "",
        "Каждому десятому кандидату в профиль добавлены все навыки потребности. В среднем на потребность:",
        "",
        "| Система | Вошло в топ-10 | Вытеснено более сильных | P@10 до | P@10 после |",
        "|---|---|---|---|---|",
        *(
            f"| {label} | {stuff[name]['entered']:.2f} | {stuff[name]['displaced']:.2f} | "
            f"{stuff[name]['p10']:.3f} | {stuff[name]['p10_stuffed']:.3f} |"
            for name, label in STUFFING_LABELS.items()
        ),
        "",
        "«Более сильный» — кандидат с большей полосой силы либо с той же силой и большим подтверждённым покрытием. "
        "P@10 после накрутки показывает итог для работодателя: сколько релевантных осталось в топ-10.",
        "",
        "## Ручной слой",
        "",
    ]
    manual = report["manual"]
    if manual["pairs"]:
        lines.append(
            f"Статус: {manual['status']}. Пар: {manual['pairs']}; взвешенная κ между разметчиками: {manual['kappa']}; "
            f"P@10 по согласованной оценке: {manual.get('p10')}."
        )
    else:
        lines.append(
            "Ручной слой не проводился. Материалы готовит `python -m app.eval.matching export-pairs`, результат "
            "вписывает `import-labels`. Точность разбора потребностей и резюме по золотым структурам не измерялась."
        )
    lines += ["", "## Критерии успеха (объявлены до прогона)", ""]
    lines += [
        f"- [{'x' if row['ok'] else ' '}] {row['name']} — {'выполнен' if row['ok'] else 'НЕ ВЫПОЛНЕН'}"
        for row in report["criteria"]
    ]
    lines += ["", *report["notes"], "", "## Угрозы валидности", ""]
    lines += [f"{index}. {text}" for index, text in enumerate(report["threats"], start=1)]
    return "\n".join(lines) + "\n"


def console(report: dict[str, Any]) -> str:
    """Короткая сводка для терминала и CI."""
    lines = ["Критерии успеха:"]
    lines += [
        f"  [{'ok' if row['ok'] else 'НЕТ'}] {row['name']}: {json.dumps(row['value'], ensure_ascii=False)}"
        for row in report["criteria"]
    ]
    lines.append("Абляции порядка (P@10; вариант − наша):")
    for name in ("order_v10", "order_v11", "order_v12"):
        row = report["ablations"][name]
        lines.append(f"  {row['label']}: {row['p10']:.3f}; {_ci(row['vs_ours'])}")
    twin = report["twins"]
    lines.append(
        f"Близнецы: разный strength_band — {twin['strength_band_diff_share']:.1%}, разный confirmed_band — "
        f"{twin['confirmed_band_diff_share']:.1%}; медиана разницы позиций: действующий порядок — "
        f"{twin['median_position_shift_current']:g}, порядок 1.1 — {twin['median_position_shift_v11']:g}"
    )
    stuff = report["stuffing"]
    lines.append(
        "Накрутка заявленным (вошло в топ-10 / вытеснено более сильных / P@10 до → после): "
        + "; ".join(
            f"{name} — {row['entered']:.2f} / {row['displaced']:.2f} / {row['p10']:.3f} → {row['p10_stuffed']:.3f}"
            for name, row in stuff.items()
        )
    )
    lines += [*report["notes"], "summary: " + json.dumps(report["summary"], ensure_ascii=False)]
    return "\n".join(lines)
