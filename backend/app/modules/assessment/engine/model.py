"""Модель ответа и оценка уровня на сетке (Арх. 5.5; приложение A, §5.2–5.3)."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache

from app.modules.assessment.config import AssessmentConfig, get_config

__all__ = ["Posterior", "Response", "estimate", "grid", "prob"]

_EPS = 1e-9


@dataclass(frozen=True)
class Response:
    """Учтённый ответ: сложность `b` и угадывание `c` на момент выдачи, балл 0 или 1, наклон `a` (всегда 1.0)."""

    b: float
    c: float
    score: int
    a: float = 1.0


@dataclass(frozen=True)
class Posterior:
    """Апостериорное распределение уровня на сетке `θ_k`: среднее, стандартное отклонение, веса и число ответов."""

    theta: float
    se: float
    weights: tuple[float, ...]
    points: tuple[float, ...]
    n: int

    def p_ge(self, threshold: float) -> float:
        """`p_ge(t) = Σ_{θ_k ≥ t − 1e−9} w_k` — вероятность того, что уровень не ниже порога (Арх. 5.5)."""
        return float(sum(w for w, point in zip(self.weights, self.points, strict=True) if point >= threshold - _EPS))


def prob(theta: float, b: float, c: float, a: float = 1.0) -> float:
    """`P(θ) = c + (1 − c) / (1 + exp(−a · (θ − b)))` — вероятность верного ответа (Арх. 5.5)."""
    return c + (1.0 - c) / (1.0 + math.exp(-a * (theta - b)))


@lru_cache(maxsize=8)
def _grid(low: float, high: float, step: float) -> tuple[float, ...]:
    count = round((high - low) / step)
    return tuple(round(low + step * k, 10) for k in range(count + 1))


def grid(cfg: AssessmentConfig | None = None) -> tuple[float, ...]:
    """Сетка `θ_k = −4.0 + 0.05·k, k = 0..160` (границы и шаг — из `THETA_GRID`, Арх. 5.10)."""
    cfg = cfg or get_config()
    return _grid(cfg.theta_grid_min, cfg.theta_grid_max, cfg.theta_grid_step)


@lru_cache(maxsize=4096)
def _log_terms(points: tuple[float, ...], a: float, b: float, c: float) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """`ln P(θ_k)` и `ln(1 − P(θ_k))` на сетке: считаются один раз на тройку (a, b, c)."""
    right, wrong = [], []
    for point in points:
        p = min(max(prob(point, b, c, a), 1e-12), 1.0 - 1e-12)
        right.append(math.log(p))
        wrong.append(math.log(1.0 - p))
    return tuple(right), tuple(wrong)


def estimate(responses: Iterable[Response], cfg: AssessmentConfig | None = None) -> Posterior:
    """Оценка уровня по всем учтённым ответам окна (Арх. 5.5).

    `L_k = −(θ_k − PRIOR_MEAN)² / (2·PRIOR_SD²) + Σ_i [x_i·ln P_i(θ_k) + (1 − x_i)·ln(1 − P_i(θ_k))]`;
    `w_k = softmax(L_k)`; `theta = Σ w_k·θ_k`; `se = sqrt(Σ w_k·(θ_k − theta)²)`.

    Наклон один для всех заданий, поэтому оценка монотонна: замена неверного ответа верным не уменьшает ни
    `theta`, ни `p_ge(t)` при любом пороге. Без ответов возвращается априорное распределение.
    """
    cfg = cfg or get_config()
    points = grid(cfg)
    log_like = [-((point - cfg.prior_mean) ** 2) / (2.0 * cfg.prior_sd**2) for point in points]
    counts = Counter((r.a, r.b, r.c, 1 if r.score else 0) for r in responses)
    total = 0
    for (a, b, c, score), times in counts.items():
        total += times
        terms = _log_terms(points, a, b, c)[0 if score else 1]
        log_like = [value + times * term for value, term in zip(log_like, terms, strict=True)]
    top = max(log_like)
    raw = [math.exp(value - top) for value in log_like]
    norm = sum(raw)
    weights = tuple(value / norm for value in raw)
    theta = sum(w * point for w, point in zip(weights, points, strict=True))
    variance = sum(w * (point - theta) ** 2 for w, point in zip(weights, points, strict=True))
    return Posterior(theta=theta, se=math.sqrt(max(variance, 0.0)), weights=weights, points=points, n=total)
