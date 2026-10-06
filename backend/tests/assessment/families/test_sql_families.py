"""Приёмка семейств `sql.*` (B21b): набор уровней, детерминизм, ключ против `sqlite3`, ручные примеры."""

from __future__ import annotations

import pytest

from app.modules.assessment.bank.build import BuildOptions, build_family
from app.modules.assessment.families import load_family
from app.modules.assessment.families._lib import sqlbox
from app.modules.assessment.families._lib.contract import Reject, variant_to_json
from app.modules.assessment.families._lib.sqlbox import Tbl

IDS = ["sql.group_having", "sql.join_rows", "sql.null_logic"]


def _family(family_id: str):
    return load_family(f"app.modules.assessment.families.{family_id.replace('.', '_')}")


@pytest.mark.parametrize("family_id", IDS)
def test_family_is_accepted_at_all_levels(family_id: str) -> None:
    result = build_family(_family(family_id), BuildOptions(secret="test-secret", per_level=60, time_check=False))
    assert result.errors == []
    for level in result.levels:
        assert level.ok, (family_id, level.level, level.errors)
        assert level.accepted == 60


@pytest.mark.parametrize("family_id", IDS)
@pytest.mark.parametrize("level", [1, 2, 3])
def test_key_matches_sqlite_and_models_differ(family_id: str, level: int) -> None:
    family = _family(family_id)
    checked = 0
    for seed in range(1, 120):
        try:
            v = family.generate(level, seed)
        except Reject:
            continue
        checked += 1
        assert variant_to_json(v) == variant_to_json(family.generate(level, seed))
        assert family.selfcheck(v) == []
        tables = sqlbox.tables_from_variant(v)
        assert int(sqlbox.scalar(tables, v.code.text)) == v.answer.value
        assert v.misconception_answers
        assert all(value != v.answer.value for value in v.misconception_answers.values())
        assert set(v.misconception_answers) <= set(family.meta.misconceptions)
    assert checked >= 40


def test_join_rows_hand_example() -> None:
    # Три сотрудника отдела dev и два проекта dev: 3 * 2 = 6 строк; сотрудник qa пары не имеет.
    tables = [
        Tbl("employees", ("id", "name", "dept"), ((1, "a", "dev"), (2, "b", "dev"), (3, "c", "dev"), (4, "d", "qa"))),
        Tbl("projects", ("id", "title", "dept", "budget"), ((1, "p", "dev", 50), (2, "q", "dev", 10))),
    ]
    assert sqlbox.scalar(tables, "SELECT COUNT(*) FROM employees e JOIN projects p ON p.dept = e.dept") == 6
    left = "SELECT COUNT(*) FROM employees e LEFT JOIN projects p ON p.dept = e.dept AND p.budget > 20"
    assert sqlbox.scalar(tables, left) == 3 + 1


def test_null_logic_not_in_with_null_matches_nothing() -> None:
    tables = [Tbl("a", ("id",), ((1,), (2,))), Tbl("b", ("id",), ((1,), (None,)))]
    assert sqlbox.scalar(tables, "SELECT COUNT(*) FROM a WHERE id NOT IN (SELECT id FROM b)") == 0
    assert sqlbox.scalar(tables, "SELECT COUNT(*) FROM a WHERE id NOT IN (SELECT id FROM b WHERE id IS NOT NULL)") == 1


def test_selfcheck_catches_wrong_key() -> None:
    from dataclasses import replace

    from app.modules.assessment.families._lib.contract import AnswerSpec

    family = _family("sql.join_rows")
    v = next(family.generate(1, s) for s in range(1, 50) if _ok(family, 1, s))
    broken = replace(v, answer=AnswerSpec.numeric(v.answer.value + 1))
    assert family.selfcheck(broken)


def _ok(family, level: int, seed: int) -> bool:
    try:
        family.generate(level, seed)
    except Reject:
        return False
    return True
