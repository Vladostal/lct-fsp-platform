"""Приёмка семейства `git.log_reach` (B21c): симулятор графа против настоящего git."""

from __future__ import annotations

import pytest

from app.modules.assessment.families._lib.contract import OracleUnavailable
from app.modules.assessment.families._lib.gitsim import GitError, GitGraph, RealGit
from tests.assessment.families._b21c_checks import assert_accepted, assert_deterministic, assert_oracle_detects_tamper

SCRIPT = [
    'git commit -m "c1"', 'git commit -m "c2"', "git checkout -b dev", 'git commit -m "c3"',
    "git checkout main", 'git commit -m "c4"', "git merge dev", "git revert HEAD~1",
    "git reset --hard HEAD~1", "git checkout main~1", 'git commit -m "c5"', "git checkout main",
]  # fmt: skip


def test_accepted() -> None:
    assert_accepted("git.log_reach", per_level=20)


def test_deterministic_and_selfcheck() -> None:
    assert_deterministic("git.log_reach")


def test_oracle_detects_tampered_key() -> None:
    assert_oracle_detects_tamper("git.log_reach")


def test_simulator_matches_real_git() -> None:
    sim = GitGraph().run(SCRIPT)
    try:
        with RealGit("graph") as git:
            git.run(SCRIPT)
            assert sim.count("main") == git.count("main")
            assert sim.count_range("dev", "main") == git.count_range("dev", "main")
    except OracleUnavailable:
        pytest.skip("нет git")


def test_misconception_flags_change_the_answer() -> None:
    base = GitGraph().run(SCRIPT).count("main")
    assert GitGraph(["first_parent"]).run(SCRIPT).count("main") != base
    assert GitGraph(["reset_keeps_history"]).run(SCRIPT).count("main") != base


def test_invalid_commands_are_errors() -> None:
    with pytest.raises(GitError):
        GitGraph().run(['git commit -m "c1"', "git revert HEAD", "git revert HEAD~1"])
