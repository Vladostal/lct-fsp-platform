"""Приёмка семейства `svc.async_order` (B21c): симулятор цикла против настоящего asyncio."""

from __future__ import annotations

from app.modules.assessment.families import svc_async_order as mod
from tests.assessment.families._b21c_checks import assert_accepted, assert_deterministic, assert_oracle_detects_tamper

GATHER = (
    "import asyncio\n\n" + mod.JOB + "\nasync def main():\n"
    '    await asyncio.gather(job("A", 3), job("B", 1))\n    print("main")\n\nasyncio.run(main())'
)


def test_accepted() -> None:
    assert_accepted("svc.async_order", per_level=20)


def test_deterministic_and_selfcheck() -> None:
    assert_deterministic("svc.async_order")


def test_oracle_detects_tampered_key() -> None:
    assert_oracle_detects_tamper("svc.async_order")


def test_gather_order_in_virtual_and_real_time() -> None:
    expected = "start A start B end B end A main"
    assert mod._execute(GATHER, virtual=True) == expected
    assert mod._execute(GATHER, virtual=False) == expected


def test_create_task_starts_only_after_main_yields() -> None:
    v = mod.generate(1, 3)
    words = v.answer.value.split()
    assert words[:2] == ["main", "1"]  # задача не начинается до первого ожидания главной корутины
    assert "task_starts_immediately" in v.misconception_answers
    assert v.misconception_answers["task_starts_immediately"].split()[:2] == ["start", words[words.index("start") + 1]]
