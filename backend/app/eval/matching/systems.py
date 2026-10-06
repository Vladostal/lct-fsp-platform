"""Системы упорядочивания для сравнения: наша, бейзлайны и абляции (приложение B, §9.7; Арх. 12.3).

Все системы получают один пул и одинаковые фильтры доступности и формата — различается только порядок внутри
раздела категории. Наша система и абляции — это `rank_need` с параметрами; бейзлайны переставляют её разделы.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from itertools import pairwise
from uuid import UUID

from app.eval.matching.relevance import relevance
from app.eval.matching.world import CUTS, GRADES, WIDTH, EvalNeed, Observed, World, closure
from app.modules.matching.dto import ShortlistQuery
from app.modules.matching.features import CandidateFeatures
from app.modules.matching.ranking import (
    DEFAULT_KEY_ORDER,
    KEY_ORDER_V10,
    KEY_ORDER_V11,
    RankedItem,
    rank_need,
)
from app.modules.matching.scoring import DEFAULT_PARAMS, ScoringParams, tie_hash


@dataclass(slots=True)
class Case:
    """Одна потребность в одном мире: пул её специализации и метки релевантности из латентной истины."""

    world: World
    need: EvalNeed
    pool: list[Observed]
    rels: dict[UUID, int] = field(default_factory=dict)
    by_id: dict[UUID, Observed] = field(default_factory=dict)

    @property
    def seed(self) -> str:
        return str(self.need.need_id)

    def features(self) -> list[CandidateFeatures]:
        return [item.features for item in self.pool]


def make_cases(world: World) -> list[Case]:
    cases = []
    for need in world.needs:
        query = need.query
        pool = [item for item in world.observed if item.latent.spec == query.specialization_code]
        case = Case(world=world, need=need, pool=pool, by_id={item.latent.candidate_id: item for item in pool})
        for item in pool:
            case.rels[item.latent.candidate_id] = relevance(
                same_specialization=True,
                theta_true=item.latent.theta_true,
                cut=CUTS[query.grade_code],
                width=WIDTH,
                skills=item.latent.skills,
                must_skills=query.must_skills,
                nice_skills=query.nice_skills,
            )
        cases.append(case)
    return cases


def ranked(
    case: Case,
    *,
    params: ScoringParams = DEFAULT_PARAMS,
    key_order: Sequence[str] = DEFAULT_KEY_ORDER,
    query: ShortlistQuery | None = None,
    pool: Sequence[CandidateFeatures] | None = None,
    seed: str | None = None,
) -> list[RankedItem]:
    """Наша система либо её абляция: боевой `rank_need` без обрезки разделов."""
    result = rank_need(
        query or case.need.query,
        case.features() if pool is None else pool,
        seed or case.seed,
        grades=GRADES,
        closure=closure,
        params=params,
        key_order=key_order,
        section_limits={},
    )
    return result.items


def ids(items: Sequence[RankedItem]) -> list[UUID]:
    return [item.candidate_id for item in items]


def reorder(items: Sequence[RankedItem], key: Callable[[RankedItem], tuple[float, ...] | float]) -> list[UUID]:
    """Переставить кандидатов внутри разделов по ключу бейзлайна (меньше — выше); разделы не смешиваются."""
    return [
        item.candidate_id
        for item in sorted(items, key=lambda item: (item.key[0], key(item), tie_hash("base", item.candidate_id)))
    ]


def declared_order(
    case: Case, items: Sequence[RankedItem], declared: dict[UUID, frozenset[str]] | None = None
) -> list[UUID]:
    """B1: `2·|must ∩ declared| + |nice ∩ declared|` — аналог подбора по совпадению заявленного стека."""
    must, nice = set(case.need.query.must_skills), set(case.need.query.nice_skills)

    def key(item: RankedItem) -> float:
        own = declared[item.candidate_id] if declared else case.by_id[item.candidate_id].declared
        return -(2 * len(must & own) + len(nice & own))

    return reorder(items, key)


def random_order(items: Sequence[RankedItem], rng: random.Random) -> list[UUID]:
    """B0: случайная перестановка внутри раздела."""
    noise = {item.candidate_id: rng.random() for item in items}
    return reorder(items, lambda item: noise[item.candidate_id])


def oracle_order(case: Case, items: Sequence[RankedItem]) -> list[UUID]:
    """Оракул: сортировка по латентной релевантности — верхняя граница при тех же фильтрах."""
    return reorder(items, lambda item: -case.rels[item.candidate_id])


def _vector(text: str, idf: dict[str, float]) -> dict[str, float]:
    tokens = text.split()
    terms = Counter(tokens)
    terms.update(f"{a} {b}" for a, b in pairwise(tokens))
    weights = {term: count * idf.get(term, 0.0) for term, count in terms.items()}
    norm = math.sqrt(sum(value * value for value in weights.values())) or 1.0
    return {term: value / norm for term, value in weights.items()}


def tfidf_scores(query_text: str, documents: dict[UUID, str]) -> dict[UUID, float]:
    """B2: косинус TF-IDF между текстом потребности и текстом кандидата; слова и биграммы,
    `idf = ln((1 + N) / (1 + df)) + 1`, L2-нормировка.
    """
    df: Counter[str] = Counter()
    for text in documents.values():
        tokens = text.split()
        df.update({*tokens, *(f"{a} {b}" for a, b in pairwise(tokens))})
    n = len(documents)
    idf = {term: math.log((1 + n) / (1 + count)) + 1 for term, count in df.items()}
    query = _vector(query_text, idf)
    scores = {}
    for cid, text in documents.items():
        vector = _vector(text, idf)
        scores[cid] = sum(weight * vector.get(term, 0.0) for term, weight in query.items())
    return scores


def tfidf_order(case: Case, items: Sequence[RankedItem]) -> list[UUID]:
    scores = tfidf_scores(case.need.text, {item.latent.candidate_id: item.text for item in case.pool})
    return reorder(items, lambda item: -scores[item.candidate_id])


#: Абляции нашей системы: каждая отключает одно решение (Арх. 12.3).
ABLATIONS: dict[str, tuple[str, dict[str, object]]] = {
    "order_v11": ("порядок версии 1.1: подтверждённое покрытие → сила", {"key_order": KEY_ORDER_V11}),
    "order_v10": ("порядок версии 1.0: покрытие с заявленным → сила", {"key_order": KEY_ORDER_V10}),
    "strength3": (
        "сила в трёх полосах по подписи (high / medium / base)",
        {"key_order": ("strength_label", "confirmed", "coverage")},
    ),
    "confirmed3": ("confirmed_band из трёх ступеней", {"key_order": ("strength", "confirmed3", "coverage")}),
    "no_bands": ("без полос (сырые значения)", {"key_order": ("strength_raw", "confirmed_raw", "coverage_raw")}),
    "additive": ("аддитивная сумма покрытия, силы и свежести", {"key_order": ("additive",)}),
    "no_gradation": (
        "без градации доказательств (все веса 1)",
        {"params": replace(DEFAULT_PARAMS, e_test_single=1.0, e_pulse=1.0, e_fsp=1.0, e_declared=1.0)},
    ),
    "no_single": (
        "без доказательства за одно задание (0.7 → 0)",
        {"params": replace(DEFAULT_PARAMS, e_test_single=0.0)},
    ),
    "declared_05": ("вес заявленного 0.5", {"params": replace(DEFAULT_PARAMS, e_declared=0.5)}),
    "declared_0": ("вес заявленного 0", {"params": replace(DEFAULT_PARAMS, e_declared=0.0)}),
    "point": ("точка вместо нижней границы (Z_LOWER = 0)", {"params": replace(DEFAULT_PARAMS, z_lower=0.0)}),
    "no_fsp": ("без ФСП (W_FSP = 0)", {"params": replace(DEFAULT_PARAMS, w_fsp=0.0, w_test=1.0)}),
    "no_drift": (
        "без роста неопределённости (se вместо se_eff)",
        {"params": replace(DEFAULT_PARAMS, use_se_eff=False)},
    ),
    "no_adjacent": ("без смежных разделов", {"exact_only": True}),
}

#: Возмущения констант на ±20 % для проверки устойчивости порядка (RBO@10).
SENSITIVITY: dict[str, ScoringParams] = {
    "E_DECLARED ×0.8": replace(DEFAULT_PARAMS, e_declared=DEFAULT_PARAMS.e_declared * 0.8),
    "E_DECLARED ×1.2": replace(DEFAULT_PARAMS, e_declared=DEFAULT_PARAMS.e_declared * 1.2),
    "E_PULSE, E_FSP ×0.8": replace(DEFAULT_PARAMS, e_pulse=0.56, e_fsp=0.56),
    "E_PULSE, E_FSP ×1.2": replace(DEFAULT_PARAMS, e_pulse=0.84, e_fsp=0.84),
    "W_FSP ×0.8": replace(DEFAULT_PARAMS, w_fsp=0.24, w_test=0.76),
    "W_FSP ×1.2": replace(DEFAULT_PARAMS, w_fsp=0.36, w_test=0.64),
    "Z_LOWER ×0.8": replace(DEFAULT_PARAMS, z_lower=0.8),
    "Z_LOWER ×1.2": replace(DEFAULT_PARAMS, z_lower=1.2),
}


def ablation(case: Case, name: str) -> list[UUID]:
    options = dict(ABLATIONS[name][1])
    if options.pop("exact_only", False):
        query = case.need.query.model_copy(update={"grade_codes": [case.need.query.grade_code]})
        return ids(ranked(case, query=query))
    return ids(ranked(case, **options))  # type: ignore[arg-type]
