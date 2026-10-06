"""Линтер вариантов: каждое правило L01–L10 ловит своё нарушение (приложение A, §2.7)."""

from __future__ import annotations

import contextlib
from dataclasses import replace

import pytest

from app.modules.assessment.bank.linter import AnswerBalance, lint_variant
from app.modules.assessment.families._lib.contract import (
    AnswerSpec,
    CodeBlock,
    Family,
    ItemKind,
    Option,
    Reject,
    Table,
    Variant,
    content_hash,
)
from tests.assessment.fake_families import FAKE_SPECS

LEVELS = [(family_id, level.level) for family_id, spec in FAKE_SPECS.items() for level in spec.levels]


def variants(family: Family, level: int, count: int) -> list[Variant]:
    found: list[Variant] = []
    seed = 0
    while len(found) < count:
        with contextlib.suppress(Reject):
            found.append(family.generate(level, seed))
        seed += 1
    return found


def codes(family: Family, variant: Variant, **kwargs: object) -> set[str]:
    return {issue.code for issue in lint_variant(family, variant, regenerate=lambda level, seed: variant, **kwargs)}


@pytest.fixture
def code_family(fake_families: dict[str, Family]) -> Family:
    return fake_families["code.fake_sum"]


@pytest.fixture
def code_variant(code_family: Family) -> Variant:
    return variants(code_family, 1, 1)[0]


@pytest.fixture
def choice_family(fake_families: dict[str, Family]) -> Family:
    return fake_families["http.fake_status"]


@pytest.fixture
def choice_variant(choice_family: Family) -> Variant:
    return variants(choice_family, 1, 1)[0]


@pytest.mark.parametrize(("family_id", "level"), LEVELS)
def test_fake_variants_are_clean(fake_families: dict[str, Family], family_id: str, level: int) -> None:
    family = fake_families[family_id]
    for variant in variants(family, level, 15):
        assert lint_variant(family, variant) == []


def test_l01_schema_and_sizes(
    code_family: Family, code_variant: Variant, choice_family: Family, choice_variant: Variant
) -> None:
    assert code_variant.code is not None and choice_variant.options is not None
    broken = [
        replace(code_variant, prompt="я" * 601),
        replace(code_variant, prompt="  "),
        replace(code_variant, prompt="Что выведет ```print(1)```?"),
        replace(code_variant, explanation=""),
        replace(code_variant, family_version=99),
        replace(code_variant, level=7),
        replace(code_variant, code=CodeBlock("python", "\n".join(["x = 1"] * 31))),
        replace(code_variant, code=CodeBlock("python", "x = " + "1" * 90)),
        replace(code_variant, options=(Option("o1", "a"), Option("o2", "b"))),
        replace(code_variant, answer=AnswerSpec.text("42")),
        replace(code_variant, tables=tuple(Table("t", ("a",), (("1",),)) for _ in range(4))),
        replace(code_variant, tables=(Table("t", ("a",), tuple(("1",) for _ in range(9))),)),
        replace(code_variant, tables=(Table("t", ("a", "b"), (("1",),)),)),
        replace(code_variant, tables=(Table("t", tuple("abcdefg"), ()),)),
        replace(code_variant, answer=AnswerSpec.numeric(float("inf"), integer=False)),
    ]
    for variant in broken:
        assert codes(code_family, variant) == {"L01"}, variant

    same_text = (Option("o1", "200"), Option("o2", "200 "), *choice_variant.options[2:])
    renumbered = tuple(Option(f"x{i}", o.text) for i, o in enumerate(choice_variant.options))
    broken_choice = [
        replace(choice_variant, options=None),
        replace(choice_variant, options=choice_variant.options[:1]),
        replace(choice_variant, options=same_text),
        replace(choice_variant, options=renumbered),
        replace(choice_variant, answer=AnswerSpec.choice("o9")),
        replace(choice_variant, code=None, answer=AnswerSpec.line(3)),
    ]
    for variant in broken_choice:
        assert codes(choice_family, variant) == {"L01"}, variant


def test_l01_pick_line_needs_eight_lines(code_family: Family, code_variant: Variant) -> None:
    family = replace(code_family, meta=replace(code_family.meta, kind=ItemKind.PICK_LINE))
    short = replace(code_variant, input=None, answer=AnswerSpec.line(2), misconception_answers={"off_by_one": 3})
    assert codes(family, short) == {"L01"}
    long_code = CodeBlock("python", "\n".join(f"x{i} = {i}" for i in range(8)))
    assert "L01" not in codes(family, replace(short, code=long_code))
    assert codes(family, replace(short, code=long_code, answer=AnswerSpec.line(9))) == {"L01"}


def test_l02_selfcheck(code_family: Family, code_variant: Variant) -> None:
    wrong_key = replace(code_variant, answer=AnswerSpec.numeric(int(code_variant.answer.value) + 1000))
    assert "L02" in codes(code_family, wrong_key)

    def boom(v: Variant) -> list[str]:
        raise RuntimeError("упал")

    issues = lint_variant(replace(code_family, selfcheck=boom), code_variant)
    assert [issue.code for issue in issues] == ["L02"] and "упал" in issues[0].message


def test_l03_l07_grading_and_misconceptions(
    code_family: Family, code_variant: Variant, choice_family: Family, choice_variant: Variant
) -> None:
    answer = code_variant.answer.value
    assert codes(code_family, replace(code_variant, misconception_answers={})) == {"L07"}
    assert codes(code_family, replace(code_variant, misconception_answers={"off_by_one": answer})) == {"L07"}
    assert codes(code_family, replace(code_variant, misconception_answers={"unknown_model": 5})) == {"L07"}
    assert codes(choice_family, replace(choice_variant, misconception_answers={"neighbor_code": "404"})) == {"L03"}


def test_l04_features_in_bounds(code_family: Family, code_variant: Variant) -> None:
    assert codes(code_family, replace(code_variant, features={**code_variant.features, "nesting_depth": 5})) == {"L04"}
    assert codes(code_family, replace(code_variant, features={**code_variant.features, "joins": 1})) == {"L04"}


def test_l05_duplicate_content(code_family: Family, code_variant: Variant) -> None:
    assert codes(code_family, code_variant, seen_hashes={content_hash(code_variant)}) == {"L05"}
    assert codes(code_family, code_variant, seen_hashes={"другой отпечаток"}) == set()


def test_l06_determinism(code_family: Family, code_variant: Variant) -> None:
    calls = iter(range(1000))

    def unstable(level: int, seed: int) -> Variant:
        return replace(code_variant, prompt=f"{code_variant.prompt} Попытка {next(calls)}.")

    issues = lint_variant(replace(code_family, generate=unstable), code_variant)
    assert [issue.code for issue in issues] == ["L06"]


def test_l08_misconception_inside_tolerance(code_family: Family, code_variant: Variant) -> None:
    close = replace(
        code_variant,
        answer=AnswerSpec.numeric(50.0, tolerance_abs=1.0),
        misconception_answers={"off_by_one": 51.5},
        features={**code_variant.features, "answer_abs": 50},
    )
    far = replace(close, misconception_answers={"off_by_one": 53})
    family = replace(code_family, selfcheck=lambda v: [])
    assert codes(family, close) == {"L08"}
    assert codes(family, far) == set()


def test_l10_limits(code_family: Family, code_variant: Variant) -> None:
    level = code_family.meta.level(1)
    wide = replace(level, feature_bounds={**level.feature_bounds, "trace_steps": (0, 500), "answer_abs": (0, 10**9)})
    family = replace(code_family, meta=replace(code_family.meta, levels=(wide,)), selfcheck=lambda v: [])
    long_trace = replace(code_variant, features={**code_variant.features, "trace_steps": 81})
    assert codes(family, long_trace) == {"L10"}
    huge = replace(
        code_variant,
        answer=AnswerSpec.numeric(2_000_000),
        features={**code_variant.features, "answer_abs": 2_000_000},
    )
    assert codes(family, huge) == {"L10"}


def test_l09_answer_balance(code_variant: Variant, choice_variant: Variant) -> None:
    balance = AnswerBalance(quota=20)
    for _ in range(5):
        assert balance.check(code_variant) == []
        balance.add(code_variant)
    assert [issue.code for issue in balance.check(code_variant)] == ["L09"]
    other = replace(code_variant, answer=AnswerSpec.numeric(int(code_variant.answer.value) + 1))
    assert balance.check(other) == []

    trivial = AnswerBalance(quota=20)
    zero, one = (replace(code_variant, answer=AnswerSpec.numeric(n)) for n in (0, 1))
    trivial.add(zero)
    trivial.add(one)
    assert [issue.code for issue in trivial.check(zero)] == ["L09"]
    rows = replace(code_variant, answer=AnswerSpec.numeric(3), tables=(Table("t", ("a",), (("1",), ("2",), ("3",))),))
    assert [issue.code for issue in trivial.check(rows)] == ["L09"]

    # Выбор одного из шести: предел для позиции и для текста верного варианта — 1/6 + 0.10 от квоты.
    positions = AnswerBalance(quota=30)
    for _ in range(8):
        assert positions.check(choice_variant) == []
        positions.add(choice_variant)
    assert {issue.code for issue in positions.check(choice_variant)} == {"L09"}
