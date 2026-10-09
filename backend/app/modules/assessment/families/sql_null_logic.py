"""Семейство `sql.null_logic`: трёхзначная логика `NULL` в условиях, `NOT IN` и соединениях (приложение A, §3.1).

Ответ считает `sqlite3`. Модели ошибок выполняет он же на искажённом запросе: `null_equals_null` — `NULL`
считается обычным значением (`IS` и `IS NOT` вместо `=` и `<>`); `not_in_ignores_null` — `NULL` в подзапросе
`NOT IN` не учитывается.
"""

from __future__ import annotations

import re
from random import Random

from app.modules.assessment.families._lib import names, sqlbox
from app.modules.assessment.families._lib.contract import AnswerSpec, CodeBlock, InputHint, Reject, Variant
from app.modules.assessment.families._lib.sqlbox import Tbl
from app.modules.assessment.families.registry import family_meta

META = family_meta(
    "sql.null_logic",
    version=1,
    feature_bounds={
        1: {"tables": (1, 1), "table_rows": (8, 8), "subqueries": (0, 0), "trap": (1, 1), "answer_abs": (0, 1000)},
        2: {"tables": (2, 2), "table_rows": (11, 14), "subqueries": (1, 1), "trap": (1, 1), "answer_abs": (0, 1000)},
        3: {"tables": (2, 2), "table_rows": (11, 14), "joins": (1, 1), "subqueries": (0, 0), "trap": (1, 1),
            "answer_abs": (0, 1000)},
    },
)  # fmt: skip


def _nullsafe(query: str) -> str:
    """Тот же запрос с `NULL` как обычным значением: `<>` -> `IS NOT`, `=` -> `IS`."""
    return query.replace("<>", "IS NOT").replace(" = ", " IS ")


def generate(level: int, seed: int) -> Variant:
    """Вариант: таблицы с пропусками `NULL` и запрос-ловушка; вопрос — сумма, которую вернёт запрос.

    Уровень 1 — сравнение столбца с `NULL`-ами константой (`<>` или `= ... OR <>`); уровень 2 — `NOT IN` по подзапросу,
    содержащему `NULL`, внутри `OR`; уровень 3 — соединение по ключу, который пуст с обеих сторон, и условие
    по правой таблице `LEFT JOIN`. Модели ошибок `null_equals_null` и `not_in_ignores_null` вычисляет `sqlite3`.
    Ответ однозначен: одно число; пустой результат, 0, 1 и ответ, равный числу строк таблицы, отбрасываются,
    как и варианты, где модель ошибки не меняет ответ.
    """
    rng = Random(seed)
    wrong_queries: dict[str, str] = {}
    orders: list[tuple[object, ...]]
    if level == 1:
        rows = [
            (i, rng.randrange(10, 100, 5), rng.choice([None, 5, 10, 15]), names.pick(rng, names.STATUSES))
            for i in range(1, 9)
        ]
        tables = [Tbl("orders", ("id", "amount", "discount", "status"), tuple(rows))]
        d = rng.choice([5, 10, 15])
        if rng.random() < 0.5:
            query = f"SELECT SUM(amount)\nFROM orders\nWHERE discount <> {d}"
        else:
            query = f"SELECT SUM(amount)\nFROM orders\nWHERE discount = {d} OR discount <> {d}"
        wrong_queries["null_equals_null"] = _nullsafe(query)
    elif level == 2:
        orders = [(i, rng.randrange(10, 100, 5), rng.choice(["paid", "new", "cancelled"])) for i in range(1, 9)]
        refunded = rng.sample(range(1, 9), rng.randint(2, 3))
        refunds = [(i, oid) for i, oid in enumerate(refunded, start=1)] + [(len(refunded) + 1, None)]
        tables = [
            Tbl("orders", ("id", "amount", "status"), tuple(orders)),
            Tbl("refunds", ("id", "order_id"), tuple(refunds)),
        ]
        query = "SELECT SUM(amount)\nFROM orders\nWHERE status = 'paid'\n   OR id NOT IN (SELECT order_id FROM refunds)"
        wrong_queries["not_in_ignores_null"] = query.replace(
            "FROM refunds)", "FROM refunds\n                 WHERE order_id IS NOT NULL)"
        )
    else:
        refs = rng.sample(range(1, 7), 4)
        accounts = [(r, rng.choice(["gold", "basic", "basic"])) for r in refs] + [(None, rng.choice(["gold", "basic"]))]
        orders = [
            (i, rng.choice([*refs, None, None]) if rng.random() < 0.9 else rng.randint(7, 9), rng.randrange(10, 100, 5))
            for i in range(1, 9)
        ]
        tables = [
            Tbl("orders", ("id", "ref", "amount"), tuple(orders)),
            Tbl("accounts", ("ref", "tier"), tuple(accounts)),
        ]
        query = "SELECT SUM(o.amount)\nFROM orders o\nLEFT JOIN accounts a ON o.ref = a.ref\nWHERE a.tier <> 'gold'"
        wrong_queries["null_equals_null"] = _nullsafe(query)
    raw = sqlbox.scalar(tables, query)
    if raw is None:
        raise Reject("empty_result")
    answer = int(raw)
    wrong = {}
    for code, text in wrong_queries.items():
        value = sqlbox.scalar(tables, text)
        value = 0 if value is None else int(value)
        if value != answer:
            wrong[code] = value
    if not wrong:
        raise Reject("no_misconception_differs")
    if answer in (0, 1) or any(answer == len(t.rows) for t in tables):
        raise Reject("trivial_answer")
    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt="Какое число вернёт запрос (NULL — отсутствующее значение)? Ответ — целое число.",
        code=CodeBlock(language="sql", text=query),
        tables=tuple(sqlbox.to_table(t) for t in tables),
        input=InputHint(placeholder="целое число", max_length=8),
        answer=AnswerSpec.numeric(answer),
        misconception_answers=wrong,
        features={
            "tables": len(tables), "table_rows": sum(len(t.rows) for t in tables), "trap": 1,
            "subqueries": 1 if level == 2 else 0, "answer_abs": answer,
            **({"joins": 1} if level == 3 else {}),
        },
        explanation=f"Запрос возвращает {answer}. Неверные чтения: {wrong}.",
    )  # fmt: skip


def selfcheck(v: Variant) -> list[str]:
    """Перепроверка: порядок данных не меняет ответ; трёхзначная логика, написанная вручную на Python, совпадает."""
    assert v.code is not None
    tables = sqlbox.tables_from_variant(v)
    problems = sqlbox.order_problems(tables, v.code.text, v.answer.value)
    text = v.code.text
    total = 0
    if v.level == 1:
        d = int(re.search(r"discount <> (\d+)", text).group(1))  # type: ignore[union-attr]
        # Сравнение с NULL даёт UNKNOWN: строка не проходит ни `<>`, ни `=`.
        either = "discount = " in text  # `= d OR <> d`: истинно для любого не-NULL значения
        total = sum(r[1] for r in tables[0].rows if r[2] is not None and (either or r[2] != d))
    elif v.level == 2:
        ids = [r[1] for r in tables[1].rows]
        has_null = None in ids
        for oid, amount, status in tables[0].rows:
            # `id NOT IN (...)` истинно, только если id нет в списке и в списке нет NULL.
            if status == "paid" or (oid not in ids and not has_null):
                total += amount
    else:
        gold = {r[0]: r[1] for r in tables[1].rows if r[0] is not None}
        for _, ref, amount in tables[0].rows:
            tier = gold.get(ref) if ref is not None else None  # NULL = NULL не истинно: пары нет, tier = NULL
            if tier is not None and tier != "gold":
                total += amount
    if total != v.answer.value:
        problems.append("расчёт трёхзначной логики на Python расходится с sqlite3")
    return problems
