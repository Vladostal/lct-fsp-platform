"""Семейство `sql.group_having`: GROUP BY и HAVING на случайной таблице заказов (приложение A, §3.1).

Ответ — число, которое возвращает запрос в `sqlite3`; модели ошибок — тот же запрос, «прочитанный» неверно:
условие группы перенесено в WHERE (`where_instead_of_having`) или `COUNT(столбец)` заменён на `COUNT(*)`
(`count_star_vs_column`). Обе неверные версии тоже выполняет `sqlite3`.
"""

from __future__ import annotations

import re
from random import Random

from app.modules.assessment.families._lib import names, sqlbox
from app.modules.assessment.families._lib.contract import AnswerSpec, CodeBlock, InputHint, Reject, Variant
from app.modules.assessment.families._lib.sqlbox import Tbl
from app.modules.assessment.families.registry import family_meta

META = family_meta(
    "sql.group_having",
    version=1,
    feature_bounds={
        1: {"tables": (1, 1), "table_rows": (8, 8), "subqueries": (1, 1), "concepts": (2, 2), "trap": (0, 0),
            "answer_abs": (0, 1000)},
        2: {"tables": (1, 1), "table_rows": (8, 8), "subqueries": (1, 1), "concepts": (4, 4), "trap": (1, 1),
            "answer_abs": (0, 1000)},
        3: {"tables": (1, 1), "table_rows": (8, 8), "subqueries": (1, 1), "concepts": (4, 4), "trap": (0, 1),
            "answer_abs": (0, 1000)},
    },
)  # fmt: skip

_COLUMNS = ("id", "city", "amount", "status", "discount")


def _query(level: int, p: dict, *, where: bool = False, star: bool = False) -> str:
    """Текст запроса уровня; `where` и `star` — искажения моделей ошибок."""
    count = p["count"]
    if star and count:
        count = "COUNT(*)"
    having = []
    if count:
        having.append(f"{count} >= {p['k']}")
    if not where:
        having.append(f"MAX(amount) > {p['t']}")
    if level == 1:
        inner, group = "city, SUM(amount) AS total", "city"
    elif level == 2:
        inner, group = "city, SUM(CASE WHEN status = 'paid' THEN amount ELSE 0 END) AS total", "city"
    else:
        inner, group = f"amount / {p['b']} AS bucket, SUM(amount) AS total", f"amount / {p['b']}"
    lines = ["SELECT SUM(total) FROM (", f"  SELECT {inner}", "  FROM orders"]
    if where:
        lines.append(f"  WHERE amount > {p['t']}")
    lines.append(f"  GROUP BY {group}")
    if having:
        lines.append("  HAVING " + " AND ".join(having))
    lines.append(")")
    return "\n".join(lines)


def _value(tables: list[Tbl], query: str) -> int | None:
    value = sqlbox.scalar(tables, query)
    return None if value is None else int(value)


def generate(level: int, seed: int) -> Variant:
    """Вариант: таблица `orders` из 8 строк и запрос с `GROUP BY` и `HAVING`; вопрос — сумма по подходящим группам.

    Уровень 1 — группы по городу с условием `MAX(amount) > t`; уровень 2 — условная агрегация `CASE` и
    `COUNT(discount)` при пропусках `NULL` в столбце discount; уровень 3 — группировка по выражению
    `amount / b` и `COUNT(DISTINCT city)`. Модели ошибок: условие группы как условие строки (`WHERE`) и
    `COUNT(*)` вместо `COUNT(столбец)`; их ответы вычисляет `sqlite3`. Ответ однозначен: результат — одно число,
    ничьих и зависимости от порядка строк нет; пустой результат и совпадение всех ответов моделей ошибок
    с верным отбрасываются.
    """
    rng = Random(seed)
    cities = names.pick_many(rng, names.CITIES, 3 if level > 1 else rng.randint(3, 4))
    statuses = ["paid", "new", "cancelled"]
    rows = []
    for i in range(1, 9):
        discount = rng.choice([None, 5, 10, 10]) if level == 2 else (rng.choice([None, 5, 10]) if level == 3 else None)
        rows.append((i, names.pick(rng, cities), rng.randrange(10, 100, 5), names.pick(rng, statuses), discount))
    tables = [Tbl("orders", _COLUMNS, tuple(rows))]
    params = {
        "t": rng.randrange(50, 80, 5) if level == 3 else rng.randrange(30, 75, 5),
        "k": 2,
        "b": rng.choice([40, 45, 50]),
        "count": (None, "COUNT(discount)", "COUNT(DISTINCT city)")[level - 1],
    }
    query = _query(level, params)
    answer = _value(tables, query)
    if answer is None:
        raise Reject("empty_result")
    wrong: dict[str, int] = {}
    wrong_where = _value(tables, _query(level, params, where=True)) or 0
    if wrong_where != answer:
        wrong["where_instead_of_having"] = wrong_where
    if params["count"]:
        wrong_star = _value(tables, _query(level, params, star=True)) or 0
        if wrong_star != answer:
            wrong["count_star_vs_column"] = wrong_star
    if not wrong:
        raise Reject("no_misconception_differs")
    if answer in (0, 1) or answer == len(rows):
        raise Reject("trivial_answer")
    trap = int(level == 2 or (level == 3 and "count_star_vs_column" in wrong))
    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt="Какое число вернёт запрос к таблице orders (NULL — отсутствующее значение)? Ответ — целое число.",
        code=CodeBlock(language="sql", text=query),
        tables=(sqlbox.to_table(tables[0]),),
        input=InputHint(placeholder="целое число", max_length=8),
        answer=AnswerSpec.numeric(answer),
        misconception_answers=wrong,
        features={
            "tables": 1, "table_rows": len(rows), "subqueries": 1, "concepts": 2 if level == 1 else 4,
            "trap": trap, "answer_abs": abs(answer),
        },
        explanation=f"Запрос возвращает {answer}. Неверные чтения: {wrong}.",
    )  # fmt: skip


def selfcheck(v: Variant) -> list[str]:
    """Перепроверка: порядок строк и столбцов не меняет ответ; расчёт на чистом Python совпадает с `sqlite3`."""
    assert v.tables is not None and v.code is not None
    tables = sqlbox.tables_from_variant(v)
    query = v.code.text
    problems = sqlbox.order_problems(tables, query, v.answer.value)
    rows = tables[0].rows
    t = int(re.search(r"MAX\(amount\) > (\d+)", query).group(1))  # type: ignore[union-attr]
    groups: dict[object, list[tuple]] = {}
    for row in rows:
        if v.level == 3:
            key = row[2] // int(re.search(r"amount / (\d+)", query).group(1))  # type: ignore[union-attr]
        else:
            key = row[1]
        groups.setdefault(key, []).append(row)
    total = 0
    for members in groups.values():
        if max(r[2] for r in members) <= t:
            continue
        if v.level > 1:
            k = int(re.search(r">= (\d+)", query).group(1))  # type: ignore[union-attr]
            count = len({r[1] for r in members}) if v.level == 3 else sum(1 for r in members if r[4] is not None)
            if count < k:
                continue
        total += sum(r[2] for r in members if v.level != 2 or r[3] == "paid")
    if total != v.answer.value:
        problems.append("расчёт на чистом Python расходится с sqlite3")
    return problems
