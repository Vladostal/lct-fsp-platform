"""Метрики ранжирования — собственная реализация на чистом Python (приложение B, §9.5), покрыта тестами."""

from __future__ import annotations

import math
import random
from collections.abc import Sequence

from app.eval.matching.relevance import RELEVANT_MIN


def precision_at(rels: Sequence[int], k: int) -> float:
    """`#{i ≤ k : rel_i ≥ 2} / k`; знаменатель `k`, даже если выдача короче."""
    return sum(1 for rel in rels[:k] if rel >= RELEVANT_MIN) / k


def mrr(rels: Sequence[int]) -> float:
    """`1 / ранг первого с rel ≥ 2`; 0, если такого нет."""
    for index, rel in enumerate(rels, start=1):
        if rel >= RELEVANT_MIN:
            return 1 / index
    return 0.0


def dcg(rels: Sequence[int], k: int) -> float:
    return sum((2**rel - 1) / math.log2(index + 1) for index, rel in enumerate(rels[:k], start=1))


def ndcg_at(rels: Sequence[int], pool_rels: Sequence[int], k: int = 10) -> float:
    """nDCG@k; идеал — лучшие `k` по всему пулу, а не по выданным."""
    ideal = dcg(sorted(pool_rels, reverse=True), k)
    return dcg(rels, k) / ideal if ideal > 0 else 0.0


def rbo(first: Sequence[object], second: Sequence[object], p: float = 0.9, k: int = 10) -> float:
    """`RBO = (1 − p) / (1 − p^k) · Σ_{d=1..k} p^(d−1) · |A[:d] ∩ B[:d]| / d`; одинаковые списки дают 1.

    Если оба списка короче `k` (в разделе мало кандидатов), глубина сравнения — длина большего из них: иначе
    одинаковые короткие списки давали бы меньше единицы.
    """
    k = min(k, max(len(first), len(second)))
    if k == 0:
        return 1.0
    total = 0.0
    for depth in range(1, k + 1):
        overlap = len(set(first[:depth]) & set(second[:depth]))
        total += p ** (depth - 1) * overlap / depth
    return (1 - p) / (1 - p**k) * total


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def bootstrap_ci(values: Sequence[float], *, repeats: int = 2000, seed: int = 1) -> tuple[float, float]:
    """95 % интервал среднего бутстрепом по потребностям (перцентили). Для разности систем на вход подаются
    попарные разности по тем же потребностям — это парный бутстреп.
    """
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(repeats))
    return (means[int(0.025 * repeats)], means[min(repeats - 1, int(0.975 * repeats))])


def gini(values: Sequence[float]) -> float:
    """Индекс Джини неотрицательных значений: 0 — поровну, 1 — всё у одного."""
    ordered = sorted(values)
    total = sum(ordered)
    if not ordered or total == 0:
        return 0.0
    n = len(ordered)
    weighted = sum((index + 1) * value for index, value in enumerate(ordered))
    return (2 * weighted) / (n * total) - (n + 1) / n


def weighted_kappa(first: Sequence[int], second: Sequence[int], levels: int = 3) -> float | None:
    """Взвешенная κ Коэна (линейные веса) между двумя разметчиками; `None`, если согласие не определено."""
    if not first or len(first) != len(second):
        return None
    n = len(first)
    observed = sum(abs(a - b) for a, b in zip(first, second, strict=True)) / n
    share_a = [sum(1 for value in first if value == level) / n for level in range(levels)]
    share_b = [sum(1 for value in second if value == level) / n for level in range(levels)]
    expected = sum(share_a[i] * share_b[j] * abs(i - j) for i in range(levels) for j in range(levels))
    return None if expected == 0 else 1 - observed / expected
