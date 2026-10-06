"""Приёмка семейства `svc.race_interleaving` (B21c)."""

from __future__ import annotations

from app.modules.assessment.families import svc_race_interleaving as mod
from tests.assessment.families._b21c_checks import assert_accepted, assert_deterministic


def test_accepted() -> None:
    assert_accepted("svc.race_interleaving")


def test_deterministic_and_selfcheck() -> None:
    assert_deterministic("svc.race_interleaving")


def test_lost_update_and_lock() -> None:
    plain = [mod.thread_ops(1, 1, "none"), mod.thread_ops(1, 1, "none")]
    assert mod.all_finals(plain, 0) == {1, 2}
    assert mod.run_order(plain, 0, [0, 1, 0, 1, 0, 1]) == 1
    locked = [mod.thread_ops(1, 1, "all"), mod.thread_ops(1, 1, "all")]
    assert mod.all_finals(locked, 0) == {2}
    # замок покрывает только чтение и изменение: запись вне замка по-прежнему допускает потерю
    half = [mod.thread_ops(1, 1, "rw"), mod.thread_ops(1, 1, "all")]
    assert mod.all_finals(half, 0) == {1, 2}


def test_dfs_equals_brute_force_on_variants() -> None:
    for level in (2, 3):
        for seed in range(12):
            try:
                v = mod.generate(level, seed)
            except Exception:
                continue
            x0, threads = mod._parse(v.code.text)
            assert mod.all_finals(threads, x0) == mod._brute(threads, x0)
