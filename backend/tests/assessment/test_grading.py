"""Общая проверка ответа `grading.grade`: правила N1, T1 и виды заданий (приложение A, §2.4)."""

from __future__ import annotations

import pytest

from app.modules.assessment.families._lib.contract import AnswerSpec, ItemKind
from app.modules.assessment.grading import grade, normalize_number, normalize_text

NUM = ItemKind.NUMERIC_INPUT
TEXT = ItemKind.TEXT_INPUT


@pytest.mark.parametrize(
    ("raw", "unit", "expected"),
    [
        ("42", None, 42.0),
        (" 1 234 ", None, 1234.0),
        ("1 234,5", None, 1234.5),
        ("-3", None, -3.0),
        ("−3", None, -3.0),
        ("+.5", None, 0.5),
        ("7.", None, 7.0),
        ("120 мс", "мс", 120.0),
        ("15%", "%", 15.0),
        ("1/3", None, None),
        ("1e3", None, None),
        ("сорок два", None, None),
        ("", None, None),
        ("12 мс", None, None),
        (None, None, None),
    ],
)
def test_normalize_number(raw: object, unit: str | None, expected: float | None) -> None:
    assert normalize_number(raw, unit) == expected


def test_numeric_integer_and_tolerance() -> None:
    exact = AnswerSpec.numeric(42)
    assert grade(NUM, exact, {"value": "42"}).score == 1
    assert grade(NUM, exact, {"value": "42,0"}).score == 1
    assert grade(NUM, exact, {"value": "42.5"}).score == 0
    assert grade(NUM, exact, {"value": "41"}).score == 0

    rounded = AnswerSpec.numeric(0.3333, decimals=2)
    assert grade(NUM, rounded, {"value": "0,33"}).score == 1
    assert grade(NUM, rounded, {"value": "0.34"}).score == 1
    assert grade(NUM, rounded, {"value": "0.35"}).score == 0

    relative = AnswerSpec.numeric(200.0, tolerance_rel=0.02)
    assert grade(NUM, relative, {"value": "204"}).score == 1
    assert grade(NUM, relative, {"value": "205"}).score == 0


def test_numeric_unit_comes_from_stored_answer() -> None:
    stored = {**AnswerSpec.numeric(120).to_json(), "unit": "мс"}
    assert grade(NUM, stored, {"value": "120 мс"}).score == 1
    assert grade("numeric_input", stored, {"value": "120 с"}).parse_ok is False


def test_unparsed_and_skipped_answers() -> None:
    spec = AnswerSpec.numeric(5)
    skipped = grade(NUM, spec, None)
    assert (skipped.score, skipped.parse_ok) == (0, True)
    for raw in ({"value": "пять"}, {}, {"option_id": "o1"}, {"value": None}, {"value": True}):
        result = grade(NUM, spec, raw)
        assert (result.score, result.parse_ok) == (0, False)


def test_text_modes() -> None:
    assert normalize_text("  Hello   World ", "exact", False) == "hello world"
    assert normalize_text("[3, 1; 2]", "tokens", False) == ["3", "1", "2"]
    assert normalize_text("['b', 'a', 'b']", "set", False) == ["a", "b"]

    assert grade(TEXT, AnswerSpec.text("Hello World"), {"value": " hello  world"}).score == 1
    assert grade(TEXT, AnswerSpec.text("Hello", case_sensitive=True), {"value": "hello"}).score == 0
    tokens = AnswerSpec.text("A C B", mode="tokens")
    assert grade(TEXT, tokens, {"value": "a, c, b"}).score == 1
    assert grade(TEXT, tokens, {"value": "[A C B]"}).score == 1
    assert grade(TEXT, tokens, {"value": "A B C"}).score == 0
    assert grade(TEXT, AnswerSpec.text("A C B", mode="set"), {"value": "b a c"}).score == 1
    assert grade(TEXT, AnswerSpec.text("x"), {"value": 5}).parse_ok is False


def test_choice_line_and_blocks() -> None:
    assert grade(ItemKind.SINGLE_CHOICE, AnswerSpec.choice("o3"), {"option_id": "o3"}).score == 1
    assert grade(ItemKind.SINGLE_CHOICE, AnswerSpec.choice("o3"), {"option_id": "o1"}).score == 0
    multi = AnswerSpec.multi(["o1", "o4"])
    assert grade(ItemKind.MULTI_CHOICE, multi, {"option_ids": ["o4", "o1"]}).score == 1
    assert grade(ItemKind.MULTI_CHOICE, multi, {"option_ids": ["o1"]}).score == 0
    assert grade(ItemKind.MULTI_CHOICE, multi, {"option_ids": "o1"}).parse_ok is False
    assert grade(ItemKind.PICK_LINE, AnswerSpec.line(7, 8), {"line": 8}).score == 1
    assert grade(ItemKind.PICK_LINE, AnswerSpec.line(7), {"line": 6}).score == 0
    assert grade(ItemKind.PICK_LINE, AnswerSpec.line(7), {"line": "7"}).parse_ok is False

    exact = AnswerSpec.blocks(["b2", "b1", "b3"])
    assert grade(ItemKind.ORDER_BLOCKS, exact, {"order": ["b2", "b1", "b3"]}).score == 1
    assert grade(ItemKind.ORDER_BLOCKS, exact, {"order": ["b1", "b2", "b3"]}).score == 0
    dag = AnswerSpec.blocks(["b1", "b2", "b3"], mode="dag", precedence=[("b1", "b3")])
    assert grade(ItemKind.ORDER_BLOCKS, dag, {"order": ["b2", "b1", "b3"]}).score == 1
    assert grade(ItemKind.ORDER_BLOCKS, dag, {"order": ["b3", "b1", "b2"]}).score == 0
    assert grade(ItemKind.ORDER_BLOCKS, dag, {"order": ["b1", "b3"]}).score == 0


def test_error_tag_is_diagnostics_only() -> None:
    spec = AnswerSpec.numeric(12)
    wrong = {"off_by_one": 13, "ignore_break": 20}
    tagged = grade(NUM, spec, {"value": "13"}, misconceptions=wrong)
    assert (tagged.score, tagged.error_tag) == (0, "off_by_one")
    assert grade(NUM, spec, {"value": "14"}, misconceptions=wrong).error_tag is None
    assert grade(NUM, spec, {"value": "12"}, misconceptions=wrong).error_tag is None
    choice = grade(ItemKind.SINGLE_CHOICE, AnswerSpec.choice("o1"), {"option_id": "o2"}, misconceptions={"trap": "o2"})
    assert choice.error_tag == "trap"
