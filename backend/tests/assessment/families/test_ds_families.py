"""Приёмка семейств `ds.*` (B21a): ключ против независимого оракула, детерминизм, набор уровней."""

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


IDS = ["ds.heap_array", "ds.hash_probing", "ds.bst_ops"]


@pytest.mark.parametrize("family_id", IDS)
def test_variants_pass_selfcheck_and_oracle(family_id: str) -> None:
    _check_family(family_id)


@pytest.mark.parametrize("family_id", IDS)
def test_family_is_accepted_at_all_levels(family_id: str) -> None:
    _check_accepted(family_id)


def test_heap_hand_example() -> None:
    from app.modules.assessment.families import ds_heap_array as heap

    # Вставки 5, 3, 8, 1: 5 | 3 5 | 3 5 8 | 1 3 8 5; извлечение минимума даёт 3 5 8.
    assert heap._run(1, [5, 3, 8, 1], ["+5", "+3", "+8", "+1"], 0) == [1, 3, 8, 5]
    assert heap._run(2, [5, 3, 8, 1], ["+5", "+3", "+8", "+1", "-"], 0) == [3, 5, 8]
    assert heap._run(3, [9, 4, 7, 1, 8], [], 0) == [1, 4, 7, 9, 8]


def test_hash_probing_tombstone_changes_search_length() -> None:
    from app.modules.assessment.families import ds_hash_probing as hp

    cells: list[int | None] = [None] * 7
    for key in (7, 14, 21):  # все в ячейку 0: цепочка 0, 1, 2
        hp._insert(cells, key)
    cells[cells.index(14)] = hp.TOMB
    assert hp._search(cells, 21) == 3
    assert hp._search(cells, 21, stop_at_tomb=True) == 2


def test_bst_successor_and_predecessor_differ() -> None:
    from app.modules.assessment.families import ds_bst_ops as bst

    keys = [50, 30, 70, 20, 40, 60, 80]
    successor = bst._preorder(bst._delete(bst._build(keys), 50, use_pred=False))
    predecessor = bst._preorder(bst._delete(bst._build(keys), 50, use_pred=True))
    assert successor[0] == 60
    assert predecessor[0] == 40
