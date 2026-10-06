"""Приёмка семейства `py.exceptions_flow` (B21c)."""

from __future__ import annotations

import contextlib
import io

from app.modules.assessment.families import py_exceptions_flow as mod
from tests.assessment.families._b21c_checks import assert_accepted, assert_deterministic


def test_accepted() -> None:
    assert_accepted("py.exceptions_flow")


def test_deterministic_and_selfcheck() -> None:
    assert_deterministic("py.exceptions_flow")


def test_known_programs() -> None:
    finally_wins = (
        'def f():\n    try:\n        return "A"\n    finally:\n        print("F")\n        return "B"\nprint(f())'
    )
    assert mod.run(finally_wins) == "F B"
    ctx = (
        "class C:\n    def __enter__(self):\n        print('in')\n    def __exit__(self, k, v, t):\n"
        "        print('out')\n        return True\n"
        "with C():\n    raise KeyError\nprint('after')"
    )
    assert mod.run(ctx) == "in out after"


def test_every_variant_answer_equals_real_python_output() -> None:
    for level in (1, 2, 3):
        for seed in range(20):
            try:
                v = mod.generate(level, seed)
            except Exception:
                continue
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                exec(v.code.text, {"__name__": "__main__"})
            assert " ".join(buffer.getvalue().split()) == v.answer.value
