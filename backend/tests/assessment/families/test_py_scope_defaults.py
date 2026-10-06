"""Приёмка семейства `py.scope_defaults` (B21c)."""

from __future__ import annotations

from app.modules.assessment.families import py_scope_defaults as mod
from tests.assessment.families._b21c_checks import assert_accepted, assert_deterministic


def test_accepted() -> None:
    assert_accepted("py.scope_defaults")


def test_deterministic_and_selfcheck() -> None:
    assert_deterministic("py.scope_defaults")


def test_known_programs_match_cpython() -> None:
    mutable = "def f(x, acc=[]):\n    acc.append(x)\n    return len(acc)\nprint(f(5), f(6), f(7, []), f(8))"
    assert mod.run(mutable) == "1 2 1 3"
    late = "fs = [lambda: i for i in range(3)]\nprint(*[f() for f in fs])"
    assert mod.run(late) == "2 2 2"
    scope = (
        "n = 1\ndef f():\n    n = 5\n    def g():\n        nonlocal n\n        n += 1\n        return n\n"
        "    return g(), n\nprint(*f(), n)"
    )
    assert mod.run(scope) == "6 6 1"


def test_every_variant_answer_equals_real_python_output() -> None:
    import contextlib
    import io

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
