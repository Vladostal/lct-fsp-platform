"""Приёмка семейства `git.reset_restore` (B21c): три дерева против `git status --porcelain`."""

from __future__ import annotations

import pytest

from app.modules.assessment.families._lib.contract import OracleUnavailable
from app.modules.assessment.families._lib.gitsim import RealGit, ThreeTrees
from tests.assessment.families._b21c_checks import assert_accepted, assert_deterministic, assert_oracle_detects_tamper

BASE = [
    "echo v1 > a.py", "echo v2 > b.py", "echo v3 > c.py", "git add .", 'git commit -m "first"',
    "echo v4 >> a.py", "git add a.py", 'git commit -m "second"',
    "echo v5 >> b.py", "echo v6 >> a.py", "git add a.py", "echo v7 > new.py",
]  # fmt: skip


def status(extra: list[str], flags: tuple[str, ...] = ()) -> tuple[set[str], set[str], set[str]]:
    return ThreeTrees(flags).run([*BASE, *extra]).status()


def test_accepted() -> None:
    assert_accepted("git.reset_restore", per_level=20)


def test_deterministic_and_selfcheck() -> None:
    assert_deterministic("git.reset_restore")


def test_oracle_detects_tampered_key() -> None:
    assert_oracle_detects_tamper("git.reset_restore")


@pytest.mark.parametrize(
    "extra",
    [
        [], ["git reset --soft HEAD~1"], ["git reset --mixed HEAD~1"], ["git reset --hard HEAD~1"],
        ["git restore b.py"], ["git restore --staged a.py"], ["git stash"], ["git stash -u"],
        ["git restore --staged a.py", "git stash"],
    ],
)  # fmt: skip
def test_simulator_matches_real_git(extra: list[str]) -> None:
    sim = status(extra)
    try:
        with RealGit("files") as git:
            git.run([*BASE, *extra])
            assert git.porcelain_sets() == sim
    except OracleUnavailable:
        pytest.skip("нет git")


def test_known_states() -> None:
    staged, unstaged, untracked = status([])
    assert (staged, unstaged, untracked) == ({"a.py"}, {"b.py"}, {"new.py"})
    # Модели ошибок меняют ответ: --hard не трогает неотслеживаемые файлы, но кандидат думает иначе.
    assert status(["git reset --hard HEAD~1"])[2] == {"new.py"}
    assert status(["git reset --hard HEAD~1"], ("hard_cleans_untracked",))[2] == set()
    assert status(["git stash"], ("stash_takes_untracked",))[2] == set()
