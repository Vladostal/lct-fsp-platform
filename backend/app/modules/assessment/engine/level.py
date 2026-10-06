"""Уровень на шкале экрана и неопределённость с учётом давности (Арх. 5.6)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from app.modules.assessment.config import GRADES, AssessmentConfig, get_config

__all__ = ["LevelNumbers", "age_days", "level_numbers", "pos", "se_eff", "thresholds"]


def pos(theta: float) -> float:
    """`pos(θ) = clip(50 + θ·50/3, 0, 100)`: пороги грейдов на шкале экрана — 25, 50, 75 (Арх. 5.6)."""
    return min(100.0, max(0.0, 50.0 + theta * 50.0 / 3.0))


def age_days(last_evidence_at: datetime, now: datetime) -> int:
    """`d` — целых дней с последнего подтверждения (не меньше нуля)."""
    return max(0, (now - last_evidence_at).days)


def se_eff(se: float, days: int, cfg: AssessmentConfig | None = None) -> float:
    """`se_eff = min(sqrt(se² + DRIFT_SD_PER_180D² · d / 180), SE_EFF_MAX)` (Арх. 5.6).

    Свежесть — не прибавка к баллу, а рост неопределённости без новых подтверждений; это единственный источник
    неопределённости и для шкалы на экране, и для ранжирования.
    """
    cfg = cfg or get_config()
    return min(math.sqrt(se * se + cfg.drift_sd_per_180d**2 * max(days, 0) / 180.0), cfg.se_eff_max)


def thresholds(cfg: AssessmentConfig | None = None) -> list[tuple[str, float]]:
    """Пороги грейдов на шкале экрана: `[(junior, 25), (middle, 50), (senior, 75)]`."""
    cfg = cfg or get_config()
    return [(grade, pos(cfg.theta_cut[grade])) for grade in GRADES]


@dataclass(frozen=True)
class LevelNumbers:
    """Числа уровня: для `LevelView` (шкала экрана) и `LevelDTO` (единицы θ, только для подбора)."""

    point: float
    lower: float
    upper: float
    se_eff: float
    age_days: int
    stale: bool
    cut: float
    cut_next: float
    width: float


def level_numbers(
    theta: float, se: float, grade: str, last_evidence_at: datetime, now: datetime, cfg: AssessmentConfig | None = None
) -> LevelNumbers:
    """Уровень кандидата (Арх. 5.6).

    `point = pos(theta)`; `lower, upper = pos(theta ∓ se_eff)`; `stale = d > STALE_AFTER_DAYS`;
    `cut = THETA_CUT[grade]`, `cut_next = cut + GRADE_WIDTH`, `width = GRADE_WIDTH`.
    """
    cfg = cfg or get_config()
    days = age_days(last_evidence_at, now)
    eff = se_eff(se, days, cfg)
    cut = cfg.theta_cut[grade]
    return LevelNumbers(
        point=pos(theta),
        lower=pos(theta - eff),
        upper=pos(theta + eff),
        se_eff=eff,
        age_days=days,
        stale=days > cfg.stale_after_days,
        cut=cut,
        cut_next=cut + cfg.grade_width,
        width=cfg.grade_width,
    )
