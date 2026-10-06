"""Приёмка семейств `db.*` (B21b): набор уровней, оракулы (`sqlite3`, EXPLAIN), ручные примеры моделей."""

from __future__ import annotations

import contextlib
from dataclasses import replace

import pytest

from app.modules.assessment.bank.build import BuildOptions, build_family
from app.modules.assessment.families import (
    db_constraints_effect,
    db_fd_keys,
    db_index_prefix,
    db_isolation_timeline,
    load_family,
)
from app.modules.assessment.families._lib.contract import AnswerSpec, Reject, variant_to_json

IDS = ["db.constraints_effect", "db.index_prefix", "db.fd_keys", "db.isolation_timeline"]
MODULES = {
    "db.constraints_effect": db_constraints_effect,
    "db.index_prefix": db_index_prefix,
    "db.fd_keys": db_fd_keys,
    "db.isolation_timeline": db_isolation_timeline,
}


@pytest.mark.parametrize("family_id", IDS)
def test_family_is_accepted_at_all_levels(family_id: str) -> None:
    family = load_family(f"app.modules.assessment.families.{family_id.replace('.', '_')}")
    result = build_family(family, BuildOptions(secret="test-secret", per_level=60, time_check=False))
    assert result.errors == []
    for level in result.levels:
        assert level.ok, (family_id, level.level, level.errors)
        assert level.accepted == 60


@pytest.mark.parametrize("family_id", IDS)
def test_deterministic_and_models_differ(family_id: str) -> None:
    module = MODULES[family_id]
    for level in (lv.level for lv in module.META.levels):
        count = 0
        for seed in range(1, 80):
            try:
                v = module.generate(level, seed)
            except Reject:
                continue
            count += 1
            assert variant_to_json(v) == variant_to_json(module.generate(level, seed))
            assert module.selfcheck(v) == []
            assert v.misconception_answers
            assert all(value != v.answer.correct_value() for value in v.misconception_answers.values())
            assert set(v.misconception_answers) <= set(module.META.misconceptions)
        assert count >= 30


def test_index_prefix_matches_explain_query_plan() -> None:
    checked = 0
    for level in (1, 2, 3):
        for seed in range(300):
            try:
                v = db_index_prefix.generate(level, seed)
            except Reject:
                continue
            assert db_index_prefix.oracle_check(v) == [], (level, seed)
            checked += 1
    assert checked > 600


def test_index_prefix_oracle_detects_wrong_key() -> None:
    v = db_index_prefix.generate(1, 1)
    ids = [o.id for o in v.options]
    wrong = [i for i in ids if i not in v.answer.option_ids] or ids[:1]
    broken = replace(v, answer=AnswerSpec.multi(wrong))
    assert db_index_prefix.oracle_check(broken)


def test_fd_keys_classic_examples() -> None:
    f = frozenset
    fds = [(f({"A", "B"}), "C"), (f({"C"}), "B")]
    universe = f({"A", "B", "C"})
    for closure in (db_fd_keys._closure_sets, db_fd_keys._closure_bits):
        assert closure(f({"A", "B"}), fds) == universe
        assert closure(f({"A", "C"}), fds) == universe
        assert sorted(map(sorted, db_fd_keys._keys(universe, fds, closure))) == [["A", "B"], ["A", "C"]]
        assert db_fd_keys._normal_form(universe, fds, closure) == "3НФ"
    # Ключ AB, частичная зависимость A -> C: только 1НФ; транзитивная A -> B -> C: 2НФ; A -> BC: НФБК.
    four = f({"A", "B", "C", "D"})
    partial = [(f({"A"}), "C"), (f({"A", "B"}), "D")]
    assert db_fd_keys._normal_form(four, partial, db_fd_keys._closure_sets) == "1НФ"
    chain = [(f({"A"}), "B"), (f({"B"}), "C"), (f({"A"}), "D")]
    assert db_fd_keys._normal_form(four, chain, db_fd_keys._closure_sets) == "2НФ"
    flat = [(f({"A"}), "B"), (f({"A"}), "C"), (f({"A"}), "D")]
    assert db_fd_keys._normal_form(four, flat, db_fd_keys._closure_sets) == "НФБК"


def test_fd_keys_normal_form_levels_are_balanced() -> None:
    forms = {}
    for seed in range(1, 200):
        try:
            v = db_fd_keys.generate(3, seed)
        except Reject:
            continue
        text = next(o.text for o in v.options if o.id == v.answer.option_id)
        forms[text] = forms.get(text, 0) + 1
    assert set(forms) == {"1НФ", "2НФ", "3НФ", "НФБК"}


def test_isolation_lost_update_and_write_skew() -> None:
    init = {"x": 100, "y": 50}
    steps = [
        ("T1", "BEGIN", None, None, None),
        ("T2", "BEGIN", None, None, None),
        ("T1", "READ", "x", "a", None),
        ("T2", "READ", "x", "b", None),
        ("T1", "WRITE", "x", None, "a + 10"),
        ("T1", "COMMIT", None, None, None),
        ("T2", "WRITE", "x", None, "b + 20"),
        ("T2", "COMMIT", None, None, None),
    ]
    for sim in (db_isolation_timeline._simulate, db_isolation_timeline._simulate_versions):
        assert sim(steps, init, db_isolation_timeline.SNAPSHOT)[1]["x"] == 110  # T2 откатилась
        assert sim(steps, init, db_isolation_timeline.Mode(snapshot=True))[1]["x"] == 120  # потерянное обновление
    skew = [
        ("T1", "BEGIN", None, None, None),
        ("T2", "BEGIN", None, None, None),
        ("T1", "READ", "y", "a", None),
        ("T2", "READ", "x", "b", None),
        ("T1", "WRITE", "x", None, "a - 30"),
        ("T2", "WRITE", "y", None, "b - 40"),
        ("T1", "COMMIT", None, None, None),
        ("T2", "COMMIT", None, None, None),
    ]
    for sim in (db_isolation_timeline._simulate, db_isolation_timeline._simulate_versions):
        _, snap = sim(skew, init, db_isolation_timeline.SNAPSHOT)
        _, ser = sim(skew, init, db_isolation_timeline.SERIALIZABLE)
        assert snap["x"] == 20 and snap["y"] == 60  # обе зафиксированы
        assert ser["x"] == 20 and ser["y"] == 50  # вторая отклонена


def test_isolation_read_committed_hides_uncommitted() -> None:
    steps = [
        ("T1", "BEGIN", None, None, None),
        ("T2", "BEGIN", None, None, None),
        ("T2", "WRITE", "x", None, "7"),
        ("T1", "READ", "x", "a", None),
        ("T2", "COMMIT", None, None, None),
        ("T1", "READ", "x", "b", None),
    ]
    for sim in (db_isolation_timeline._simulate, db_isolation_timeline._simulate_versions):
        reads, _ = sim(steps, {"x": 1, "y": 2}, db_isolation_timeline.RC)
        assert [v for _, v in reads] == [1, 7]
        reads, _ = sim(steps, {"x": 1, "y": 2}, db_isolation_timeline.Mode(dirty=True))
        assert [v for _, v in reads] == [7, 7]


def test_constraints_cascade_restrict_set_null() -> None:
    import sqlite3

    for action, expected in (("CASCADE", 1), ("SET NULL", 2), ("RESTRICT", 2)):
        connection = sqlite3.connect(":memory:")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            "CREATE TABLE parents (id INTEGER PRIMARY KEY);"
            f"CREATE TABLE children (id INTEGER PRIMARY KEY, p INTEGER REFERENCES parents(id) ON DELETE {action});"
            "INSERT INTO parents VALUES (1), (2); INSERT INTO children VALUES (1, 1), (2, 2);"
        )
        with contextlib.suppress(sqlite3.IntegrityError):
            connection.execute("DELETE FROM parents WHERE id = 1")
        children = connection.execute("SELECT COUNT(*) FROM children").fetchone()[0]
        assert children == expected
