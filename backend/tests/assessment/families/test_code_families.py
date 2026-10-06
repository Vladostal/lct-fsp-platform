"""Приёмка семейств `code.*` (B21a): ключ против CPython, детерминизм, поиск строки, набор уровней."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.modules.assessment.bank.build import BuildOptions, build_family
from app.modules.assessment.families import load_family
from app.modules.assessment.families._lib.contract import (
    AnswerSpec,
    ItemKind,
    Reject,
    raw_answer_for,
    variant_answer_json,
    variant_to_json,
)
from app.modules.assessment.families.registry import CORE_P0, module_name
from app.modules.assessment.grading import grade


def _family(family_id: str):
    return load_family(f"app.modules.assessment.families.{module_name(family_id)}")


def _variants(family_id: str, level: int, want: int = 25):
    family = _family(family_id)
    found = []
    for seed in range(1, 400):
        try:
            found.append(family.generate(level, seed))
        except Reject:
            continue
        if len(found) == want:
            break
    return family, found


def _corrupt(v):
    """Вариант с заведомо неверным ключом: ответ сдвинут на единицу или заменён другим вариантом."""
    kind = v.answer.kind
    if kind is ItemKind.NUMERIC_INPUT:
        return replace(v, answer=AnswerSpec.numeric(v.answer.value + 1))
    if kind is ItemKind.TEXT_INPUT:
        words = str(v.answer.value).split()
        changed = words[::-1] if words[::-1] != words else [*words, "0"]
        return replace(v, answer=AnswerSpec.text(" ".join(changed), mode="tokens"))
    if kind is ItemKind.PICK_LINE:
        return replace(v, answer=AnswerSpec.line(v.answer.lines[0] % len(v.code.text.split("\n")) + 1))
    other = next(o.id for o in v.options if o.id != v.answer.option_id)
    return replace(v, answer=AnswerSpec.choice(other))


def _check_family(family_id: str) -> None:
    family = _family(family_id)
    assert family.oracle_check is not None
    assert family_id in CORE_P0
    assert family.meta.id == family_id
    for level in (lvl.level for lvl in family.meta.levels):
        _, variants = _variants(family_id, level)
        assert len(variants) >= 20, (family_id, level)
        for v in variants:
            assert variant_to_json(v) == variant_to_json(family.generate(level, v.seed))
            assert family.selfcheck(v) == [], (family_id, level, v.seed)
            assert family.oracle_check(v) == [], (family_id, level, v.seed)
            correct = v.answer.correct_value()
            assert grade(v.kind, variant_answer_json(v), raw_answer_for(v.kind, correct)).score == 1
            assert v.misconception_answers
            assert set(v.misconception_answers) <= set(family.meta.misconceptions)
            for value in v.misconception_answers.values():
                assert value != correct
                assert grade(v.kind, variant_answer_json(v), raw_answer_for(v.kind, value)).score == 0
            # Независимая проверка должна ловить испорченный ключ: иначе она ничего не проверяет.
            bad = _corrupt(v)
            assert family.selfcheck(bad) or family.oracle_check(bad), (family_id, level, v.seed)
    with pytest.raises((ValueError, KeyError)):
        family.generate(9, 1)


def _check_accepted(family_id: str) -> None:
    result = build_family(_family(family_id), BuildOptions(secret="test-secret", per_level=60, time_check=False))
    assert result.errors == []
    for level in result.levels:
        assert level.ok, (family_id, level.level, level.errors)
        assert level.accepted == 60


IDS = [
    "code.trace_loops", "code.trace_collections", "code.trace_recursion", "code.bug_boundary", "code.bug_logic",
]  # fmt: skip


@pytest.mark.parametrize("family_id", IDS)
def test_variants_pass_selfcheck_and_oracle(family_id: str) -> None:
    _check_family(family_id)


@pytest.mark.parametrize("family_id", IDS)
def test_family_is_accepted_at_all_levels(family_id: str) -> None:
    _check_accepted(family_id)


@pytest.mark.parametrize("family_id", ["code.bug_boundary", "code.bug_logic"])
@pytest.mark.parametrize("level", [1, 2, 3])
def test_bug_variants_have_single_broken_line(family_id: str, level: int) -> None:
    from app.modules.assessment.families._lib.miniprog import parse_bug

    _, variants = _variants(family_id, level, 15)
    for v in variants:
        _key, _fname, line, ref, _args, got, expected = parse_bug(v.prompt, v.explanation)
        lines = v.code.text.split("\n")
        assert got != expected
        assert v.answer.lines == (line,)
        assert lines[line - 1] != ref
        assert len(lines) >= 8
        assert v.features["trap"] == (1 if level == 3 else v.features["trap"])


def test_bug_selfcheck_rejects_wrong_line() -> None:
    family, variants = _variants("code.bug_boundary", 2, 5)
    for v in variants:
        wrong_line = v.answer.lines[0] % len(v.code.text.split("\n")) + 1
        broken = replace(v, answer=AnswerSpec.line(wrong_line))
        assert family.selfcheck(broken)


def test_trace_loops_off_by_one_hand_example() -> None:
    from random import Random

    from app.modules.assessment.families import code_trace_loops as tl
    from app.modules.assessment.families._lib.miniprog import run_source

    src, model, _ = tl._level1(Random(3), "total", "i")
    assert model(None) != model("off_by_one")
    assert run_source(src).printed == str(model(None))


def test_trace_recursion_memo_counts_distinct_arguments() -> None:
    from app.modules.assessment.families import code_trace_recursion as tr

    fib = tr.CALLS[0]
    total, leaves = tr._calls(fib, 2, 5)
    assert (total, leaves) == (15, 8)
    seen: set[int] = set()
    tr._memo_calls(fib, 2, 5, seen)
    assert seen == {0, 1, 2, 3, 4, 5}
