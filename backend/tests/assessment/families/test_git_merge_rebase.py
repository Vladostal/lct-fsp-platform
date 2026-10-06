"""Приёмка семейства `git.merge_rebase` (B21c): симулятор графа против настоящего git."""

from __future__ import annotations

import pytest

from app.modules.assessment.families._lib.contract import OracleUnavailable
from app.modules.assessment.families._lib.gitsim import GitGraph, RealGit
from tests.assessment.families._b21c_checks import assert_accepted, assert_deterministic, assert_oracle_detects_tamper

DIVERGED = [
    'git commit -m "c1"', "git checkout -b dev", 'git commit -m "c2"', 'git commit -m "c3"',
    "git checkout main", 'git commit -m "c4"',
]  # fmt: skip


def test_accepted() -> None:
    assert_accepted("git.merge_rebase", per_level=20)


def test_deterministic_and_selfcheck() -> None:
    assert_deterministic("git.merge_rebase")


def test_oracle_detects_tampered_key() -> None:
    assert_oracle_detects_tamper("git.merge_rebase")


def test_rebase_rewrites_commits_and_merge_does_not() -> None:
    rebased = GitGraph().run([*DIVERGED, "git checkout dev", "git rebase main"])
    assert len(rebased.replayed) == 2
    assert rebased.count("dev") == 4
    ff = GitGraph().run(
        ['git commit -m "c1"', "git checkout -b dev", 'git commit -m "c2"', "git checkout main", "git merge dev"]
    )
    assert ff.count("main") == 2  # перемотка: новых коммитов нет
    assert GitGraph().run([*DIVERGED, "git merge dev"]).count("main") == 5  # коммит слияния


def test_simulator_matches_real_git_for_onto_and_squash() -> None:
    onto = [
        'git commit -m "c1"', "git checkout -b t1", 'git commit -m "c2"', "git checkout -b t2", 'git commit -m "c3"',
        "git checkout main", 'git commit -m "c4"', "git rebase --onto main t1 t2",
    ]  # fmt: skip
    squash = [*DIVERGED, "git merge --squash dev", 'git commit -m "sq"']
    try:
        for script, ref in ((onto, "t2"), (squash, "main")):
            with RealGit("graph") as git:
                git.run(script)
                assert git.count(ref) == GitGraph().run(script).count(ref)
    except OracleUnavailable:
        pytest.skip("нет git")
