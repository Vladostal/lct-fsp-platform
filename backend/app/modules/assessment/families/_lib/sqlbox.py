"""Случайные таблицы и выполнение запросов в `sqlite3` для семейств групп `sql` и `db` (приложение A, §2.2, 2.5).

Ответ семейств `sql.*` — результат запроса в `sqlite3` в памяти: это независимая от генератора реализация SQL.
Здесь же проверка из §2.5: запрос даёт тот же ответ при обратном порядке вставки строк и при перестановке столбцов.
Ячейки таблицы условия — строки, `NULL` пишется словом; обратный разбор возвращает числа и `None`.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.modules.assessment.families._lib.contract import Table, Variant

__all__ = ["Tbl", "connect", "order_problems", "scalar", "tables_from_variant", "to_table"]

_INT = re.compile(r"-?\d+")


@dataclass(frozen=True)
class Tbl:
    """Таблица со значениями Python: `None` — SQL `NULL`."""

    name: str
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]


def to_table(table: Tbl) -> Table:
    """Таблица для условия: ячейки — строки, пустое значение — «NULL»."""
    return Table(
        title=table.name,
        columns=table.columns,
        rows=tuple(tuple("NULL" if cell is None else str(cell) for cell in row) for row in table.rows),
    )


def _cell(text: str) -> Any:
    if text == "NULL":
        return None
    return int(text) if _INT.fullmatch(text) else text


def tables_from_variant(v: Variant) -> list[Tbl]:
    """Обратный разбор таблиц условия в значения Python (для `selfcheck`)."""
    return [
        Tbl(t.title, tuple(t.columns), tuple(tuple(_cell(c) for c in row) for row in t.rows)) for t in v.tables or ()
    ]


def connect(
    tables: Sequence[Tbl], *, reverse_rows: bool = False, reverse_columns: bool = False, foreign_keys: bool = False
) -> sqlite3.Connection:
    """Соединение с базой в памяти; таблицы созданы без типов, строки вставлены в прямом или обратном порядке."""
    connection = sqlite3.connect(":memory:")
    connection.execute(f"PRAGMA foreign_keys = {'ON' if foreign_keys else 'OFF'}")
    for table in tables:
        order = list(range(len(table.columns)))
        if reverse_columns:
            order.reverse()
        columns = [table.columns[i] for i in order]
        connection.execute(f"CREATE TABLE {table.name} ({', '.join(columns)})")
        rows = table.rows[::-1] if reverse_rows else table.rows
        marks = ", ".join("?" for _ in columns)
        connection.executemany(
            f"INSERT INTO {table.name} ({', '.join(columns)}) VALUES ({marks})",
            [tuple(row[i] for i in order) for row in rows],
        )
    return connection


def scalar(tables: Sequence[Tbl], query: str, **kwargs: bool) -> Any:
    """Единственное значение результата запроса (`None` для `NULL`)."""
    connection = connect(tables, **kwargs)
    try:
        return connection.execute(query).fetchone()[0]
    finally:
        connection.close()


def order_problems(tables: Sequence[Tbl], query: str, expected: Any) -> list[str]:
    """Перепроверка §2.5: ответ не зависит от порядка вставки строк и порядка столбцов в таблицах."""
    problems = []
    for name, kwargs in (
        ("обратный порядок строк", {"reverse_rows": True}),
        ("обратный порядок столбцов", {"reverse_columns": True}),
        ("оба", {"reverse_rows": True, "reverse_columns": True}),
    ):
        if scalar(tables, query, **kwargs) != expected:
            problems.append(f"ответ зависит от порядка данных ({name})")
    return problems
