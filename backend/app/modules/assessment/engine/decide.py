"""Решение по тесту на грейд и ход сессии в контрольных точках (Арх. 5.5; приложение A, §5.4–5.5)."""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.assessment.config import AssessmentConfig, get_config
from app.modules.assessment.engine.model import Posterior
from app.shared.enums import TestOutcome

__all__ = ["CONFIRMING", "Decision", "checkpoint", "decide", "final_outcome"]

#: Исходы, которые подтверждают грейд.
CONFIRMING: frozenset[TestOutcome] = frozenset({TestOutcome.CONFIRMED, TestOutcome.CONFIRMED_WITH_MARGIN})


@dataclass(frozen=True)
class Decision:
    """Исход и вероятности, по которым он принят."""

    outcome: TestOutcome
    p_pass: float
    p_margin: float


def decide(post: Posterior, grade: str, cfg: AssessmentConfig | None = None) -> Decision:
    """Исход теста на грейд `t` (Арх. 5.5).

    `p_pass = p_ge(THETA_CUT[t])`, `p_margin = p_ge(THETA_CUT[t] + MARGIN_DELTA)`;
    `p_pass ≥ 0.80` и `p_margin ≥ 0.80` → `confirmed_with_margin`; `p_pass ≥ 0.80` → `confirmed`;
    `p_pass ≤ 0.20` → `not_confirmed`; иначе `borderline`.
    """
    cfg = cfg or get_config()
    cut = cfg.theta_cut[grade]
    p_pass = post.p_ge(cut)
    p_margin = post.p_ge(cut + cfg.margin_delta)
    if p_pass >= cfg.p_confirm and p_margin >= cfg.p_margin:
        outcome = TestOutcome.CONFIRMED_WITH_MARGIN
    elif p_pass >= cfg.p_confirm:
        outcome = TestOutcome.CONFIRMED
    elif p_pass <= cfg.p_reject:
        outcome = TestOutcome.NOT_CONFIRMED
    else:
        outcome = TestOutcome.BORDERLINE
    return Decision(outcome=outcome, p_pass=p_pass, p_margin=p_margin)


def checkpoint(decision: Decision, stage: int, cfg: AssessmentConfig | None = None) -> bool:
    """Нужен ли добавочный блок в контрольной точке (Арх. 5.5, шаг 5 `submit_answer`).

    Блок из `EXT_BLOCK` заданий добавляется, если исход `borderline` и `stage < MAX_EXT_BLOCKS`. Если собрать блок
    не из чего (банк исчерпан), тест завершается с текущим исходом — это решает вызывающий.
    """
    cfg = cfg or get_config()
    return decision.outcome is TestOutcome.BORDERLINE and stage < cfg.max_ext_blocks


def final_outcome(decision: Decision, *, has_not_shown: bool) -> TestOutcome:
    """Итог при закрытии сессии (Арх. 5.5, `finalize`): незавершённый тест не подтверждает грейд.

    Если остались непоказанные задания (`not_shown`), а исход подтверждающий, он заменяется на `borderline`.
    Это закрывает уловку «ответить на лёгкие задания и дождаться таймера».
    """
    if has_not_shown and decision.outcome in CONFIRMING:
        return TestOutcome.BORDERLINE
    return decision.outcome
