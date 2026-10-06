"""Семейство `sql.join_rows`: сколько строк вернёт соединение таблиц (приложение A, §3.1).

Ключ соединения неуникален (отдел), поэтому строки размножаются. Ответ считает `sqlite3`; модели ошибок —
`inner_instead_of_left` (LEFT прочитан как INNER) и `no_fanout` (размножение строк не учтено): неверные запросы
тоже выполняет `sqlite3`.
"""

from __future__ import annotations

import re
from random import Random

from app.modules.assessment.families._lib import names, sqlbox
from app.modules.assessment.families._lib.contract import AnswerSpec, CodeBlock, InputHint, Reject, Variant
from app.modules.assessment.families._lib.sqlbox import Tbl
from app.modules.assessment.families.registry import family_meta

META = family_meta(
    "sql.join_rows",
    version=1,
    feature_bounds={
        1: {"tables": (2, 2), "table_rows": (9, 12), "joins": (1, 1), "trap": (1, 1), "answer_abs": (0, 100)},
        2: {"tables": (2, 2), "table_rows": (12, 13), "joins": (1, 1), "trap": (1, 1), "answer_abs": (0, 100)},
        3: {"tables": (3, 3), "table_rows": (14, 20), "joins": (2, 2), "trap": (1, 1), "answer_abs": (0, 100)},
    },
)  # fmt: skip


def _queries(level: int, t: int) -> tuple[str, dict[str, str]]:
    """Запрос условия и искажённые запросы моделей ошибок."""
    base = "SELECT COUNT(*)\nFROM employees e\n"
    if level == 1:
        return (
            base + "JOIN projects p ON p.dept = e.dept",
            {"no_fanout": "SELECT COUNT(DISTINCT e.id)\nFROM employees e\nJOIN projects p ON p.dept = e.dept"},
        )
    if level == 2:
        return (
            base + f"LEFT JOIN projects p ON p.dept = e.dept AND p.budget > {t}",
            {
                "inner_instead_of_left": base + f"JOIN projects p ON p.dept = e.dept AND p.budget > {t}",
                "no_fanout": "SELECT COUNT(DISTINCT e.id)\nFROM employees e\n"
                f"LEFT JOIN projects p ON p.dept = e.dept AND p.budget > {t}",
            },
        )
    main = base + "JOIN projects p ON p.dept = e.dept\n"
    return (
        main + "LEFT JOIN reviews r ON r.project_id = p.id",
        {
            "inner_instead_of_left": main + "JOIN reviews r ON r.project_id = p.id",
            "no_fanout": main.rstrip("\n"),
        },
    )


def generate(level: int, seed: int) -> Variant:
    """Вариант: две-три таблицы и `COUNT(*)` после соединения; вопрос — число строк результата.

    Уровень 1 — `INNER JOIN` по неуникальному отделу (размножение строк); уровень 2 — `LEFT JOIN` с условием
    на правую таблицу в `ON`; уровень 3 — два соединения, последнее `LEFT` по таблице отзывов. Модели ошибок:
    `inner_instead_of_left` и `no_fanout`; их ответы вычисляет `sqlite3`. Ответ однозначен: результат — одно число;
    ответы 0, 1 и совпадающие с числом строк таблицы отбрасываются, как и варианты, где ни одна модель ошибки
    не отличается от верного ответа.
    """
    rng = Random(seed)
    depts = names.pick_many(rng, names.DEPARTMENTS, 4 if level == 1 else 3)
    emp_names = names.pick_many(rng, names.FIRST_NAMES, (5 if level == 2 else rng.randint(5, 6)))
    employees = [(i, n, names.pick(rng, depts)) for i, n in enumerate(emp_names, start=1)]
    titles = names.pick_many(rng, names.WORDS, (rng.randint(7, 8) if level == 2 else rng.randint(4, 5)))
    # Отделы проектов берутся из подмножества отделов: часть сотрудников остаётся без пары.
    project_depts = depts[:-1] if level < 3 else depts
    projects = [
        (i, t, names.pick(rng, project_depts), rng.randrange(10, 100, 10)) for i, t in enumerate(titles, start=1)
    ]
    tables = [
        Tbl("employees", ("id", "name", "dept"), tuple(employees)),
        Tbl("projects", ("id", "title", "dept", "budget"), tuple(projects)),
    ]
    if level == 3:
        reviews = [(i, rng.randint(1, len(projects)), rng.randint(1, 5)) for i in range(1, rng.randint(5, 8) + 1)]
        tables.append(Tbl("reviews", ("id", "project_id", "score"), tuple(reviews)))
    t = rng.randrange(20, 60, 10)
    query, wrong_queries = _queries(level, t)
    answer = int(sqlbox.scalar(tables, query))
    wrong = {code: int(sqlbox.scalar(tables, text)) for code, text in wrong_queries.items()}
    wrong = {code: value for code, value in wrong.items() if value != answer}
    if not wrong:
        raise Reject("no_misconception_differs")
    if answer in (0, 1) or any(answer == len(table.rows) for table in tables):
        raise Reject("trivial_answer")
    rows_total = sum(len(table.rows) for table in tables)
    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt="Сколько строк вернёт запрос? Ответ — целое число.",
        code=CodeBlock(language="sql", text=query),
        tables=tuple(sqlbox.to_table(table) for table in tables),
        input=InputHint(placeholder="целое число", max_length=6),
        answer=AnswerSpec.numeric(answer),
        misconception_answers=wrong,
        features={
            "tables": len(tables), "table_rows": rows_total, "joins": len(tables) - 1, "trap": 1,
            "answer_abs": answer,
        },
        explanation=f"Запрос возвращает {answer} строк. Неверные чтения: {wrong}.",
    )  # fmt: skip


def selfcheck(v: Variant) -> list[str]:
    """Перепроверка: порядок данных не меняет ответ; счёт соединения циклами на чистом Python совпадает."""
    assert v.code is not None
    tables = sqlbox.tables_from_variant(v)
    problems = sqlbox.order_problems(tables, v.code.text, v.answer.value)
    employees, projects = tables[0].rows, tables[1].rows
    if v.level == 3:
        reviews = tables[2].rows
        count = sum(
            max(1, sum(1 for r in reviews if r[1] == p[0])) for e in employees for p in projects if p[2] == e[2]
        )
    else:
        limit = int(m.group(1)) if (m := re.search(r"budget > (\d+)", v.code.text)) else None
        count = 0
        for e in employees:
            pairs = sum(1 for p in projects if p[2] == e[2] and (limit is None or p[3] > limit))
            count += pairs if v.level == 1 else max(1, pairs)
    if count != v.answer.value:
        problems.append("счёт соединения на чистом Python расходится с sqlite3")
    return problems
