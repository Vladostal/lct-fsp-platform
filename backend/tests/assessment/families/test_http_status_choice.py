"""Приёмка семейства `http.status_choice` (B21c)."""

from __future__ import annotations

from app.modules.assessment.families import http_status_choice as mod
from tests.assessment.families._b21c_checks import assert_accepted, assert_deterministic


def test_accepted() -> None:
    assert_accepted("http.status_choice")


def test_deterministic_and_selfcheck() -> None:
    assert_deterministic("http.status_choice")


def test_rule_table_has_unique_answer_and_trap_in_options() -> None:
    for level in (1, 2, 3):
        for seed in range(30):
            v = mod.generate(level, seed)
            texts = [o.text for o in v.options or ()]
            assert len(texts) == 6 == len(set(texts))
            correct = next(o.text for o in v.options or () if o.id == v.answer.option_id)
            trap = next(o.text for o in v.options or () if o.id == v.misconception_answers["neighbor_code"])
            assert correct != trap


def test_selfcheck_catches_wrong_key() -> None:
    v = mod.generate(2, 5)
    other = next(o.id for o in v.options or () if o.id != v.answer.option_id)
    from dataclasses import replace

    from app.modules.assessment.families._lib.contract import AnswerSpec

    assert mod.selfcheck(replace(v, answer=AnswerSpec.choice(other))) != []
