"""Приёмка семейства `py.iter_generators` (B21c)."""

from __future__ import annotations

import contextlib
import io

from app.modules.assessment.families import py_iter_generators as mod
from tests.assessment.families._b21c_checks import assert_accepted, assert_deterministic


def test_accepted() -> None:
    assert_accepted("py.iter_generators")


def test_deterministic_and_selfcheck() -> None:
    assert_deterministic("py.iter_generators")


def test_known_programs() -> None:
    assert mod.run("it = iter([1, 2, 3])\nprint(sum(it), sum(it))") == "6 0"
    assert mod.run("print(*[i * x for i, x in enumerate([4, 5], 1)])") == "4 10"
    lazy = 'def g():\n    for i in range(3):\n        print("make", i)\n        yield i\nx = g()\nprint(next(x))'
    assert mod.run(lazy) == "make 0 0"


def test_every_variant_answer_equals_real_python_output() -> None:
    for level in (1, 2, 3):
        for seed in range(15):
            try:
                v = mod.generate(level, seed)
            except Exception:
                continue
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                exec(v.code.text, {"__name__": "__main__"})
            assert " ".join(buffer.getvalue().split()) == v.answer.value
