"""Семейство `db.index_prefix`: какие запросы используют составной индекс (a, b, c) (приложение A, §3.3).

Выбор подмножества. Правило ответа названо в условии: «индекс используется», если в плане запроса есть поиск
по индексу (условие на ведущий столбец, до первого столбца без условия) либо просмотр индекса без обращения
к таблице (все нужные столбцы входят в индекс). Ключ считает движок правил «левый префикс»; оракул — планы
`EXPLAIN QUERY PLAN` из `sqlite3` (`oracle_check`). Модели ошибок — тот же движок с искажённым правилом:
индекс годится для любого столбца (`any_column_order`), функция над столбцом не мешает (`function_still_sargable`),
`OR` по разным столбцам использует индекс (`or_uses_index`).
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from random import Random

from app.modules.assessment.families._lib.contract import (
    AnswerSpec,
    CodeBlock,
    Option,
    Reject,
    Variant,
)
from app.modules.assessment.families.registry import family_meta

META = family_meta(
    "db.index_prefix",
    version=2,
    feature_bounds={
        1: {"options_count": (4, 5), "concepts": (1, 1), "trap": (1, 1)},
        2: {"options_count": (5, 5), "concepts": (2, 2), "trap": (1, 1)},
        3: {"options_count": (5, 6), "concepts": (3, 3), "trap": (1, 1)},
    },
    misconceptions=("any_column_order", "function_still_sargable", "or_uses_index"),
)  # fmt: skip

_SCHEMAS = (
    ("orders", ("customer_id", "status", "day"), "note"),
    ("visits", ("user_id", "page", "day"), "agent"),
    ("tickets", ("author_id", "state", "day"), "title"),
)
_TEXT = {"status": ("new", "paid", "done"), "page": ("home", "cart", "help"), "state": ("open", "closed", "wip")}


@dataclass(frozen=True)
class _Atom:
    """Условие над столбцом индекса: `fn` — функция над столбцом (None, «abs», «+0»)."""

    col: int  # 0, 1, 2 — позиция в индексе
    op: str
    value: int | str
    fn: str | None = None


@dataclass(frozen=True)
class _Query:
    select: tuple[int, ...] | str  # позиции столбцов индекса либо «*» / «payload»
    atoms: tuple[_Atom, ...]
    disjunction: bool = False


def _used(q: _Query, *, any_order: bool = False, fn_ok: bool = False, or_ok: bool = False) -> bool:
    """Движок правил: используется ли индекс (a, b, c). Флаги — искажения моделей ошибок."""
    if isinstance(q.select, tuple):  # покрывающий: все столбцы выбора есть в индексе
        return True
    sargable = [a for a in q.atoms if a.fn is None or fn_ok]
    if q.disjunction:
        if or_ok:
            return bool(sargable)
        return all(a.col == 0 for a in q.atoms) and len(sargable) == len(q.atoms)
    if any_order:
        return bool(sargable)
    return any(a.col == 0 for a in sargable)


def _literal(schema: tuple, atom: _Atom) -> str:
    column = schema[1][atom.col]
    if atom.fn == "abs":
        column = f"abs({column})"
    elif atom.fn == "+0":
        column = f"{column} + 0"
    value = f"'{atom.value}'" if isinstance(atom.value, str) else str(atom.value)
    return f"{column} {atom.op} {value}"


def _sql(schema: tuple, q: _Query) -> str:
    if isinstance(q.select, tuple):
        select = ", ".join(schema[1][i] for i in q.select)
    else:
        select = "*" if q.select == "*" else schema[2]
    glue = " OR " if q.disjunction else " AND "
    return f"SELECT {select} FROM {schema[0]} WHERE " + glue.join(_literal(schema, a) for a in q.atoms)


def _atom(rng: Random, schema: tuple, col: int, *, ops: tuple[str, ...], fn: str | None = None) -> _Atom:
    """Случайное условие над столбцом индекса: текстовый столбец сравнивается только на равенство."""
    if col == 1:
        return _Atom(1, "=", rng.choice(_TEXT[schema[1][1]]))
    return _Atom(col, rng.choice(ops), rng.randint(2, 40), fn)


def _random_query(rng: Random, schema: tuple, level: int) -> _Query:
    """Один запрос уровня."""
    cols = [0, 1, 2]
    if level == 1:
        picked = sorted(rng.sample(cols, rng.choice([1, 2, 2, 3])))
        atoms = tuple(_atom(rng, schema, c, ops=("=",)) for c in picked)
        return _Query(rng.choice(["*", "payload"]), atoms)
    if level == 2:
        picked = sorted(rng.sample(cols, rng.choice([1, 2, 2, 3])))
        atoms = tuple(_atom(rng, schema, c, ops=("=", "=", ">", "<", ">=") if c != 1 else ("=",)) for c in picked)
        selects: list[tuple[int, ...] | str] = ["*", "payload", "payload", (0, 1), (1, 2), (0, 2), (0, 1, 2)]
        select = rng.choice(selects)
        if isinstance(select, tuple):
            select = tuple(select)
        return _Query(select, atoms)
    kind = rng.choice(["fn", "fn", "or_same", "or_diff", "or_diff", "mixed"])
    if kind == "fn":  # функция над столбцом: ключ неприменим к вычисленному выражению
        picked = sorted(rng.sample([0, 2], rng.choice([1, 2])))
        atoms = tuple(_atom(rng, schema, c, ops=("=", ">"), fn=rng.choice(["abs", "+0"])) for c in picked)
        if rng.random() < 0.4:
            atoms = (*atoms, _atom(rng, schema, 1, ops=("=",)))
        return _Query(rng.choice(["*", "payload"]), tuple(sorted(atoms, key=lambda a: a.col)))
    if kind == "or_same":
        a = _atom(rng, schema, 0, ops=("=",))
        return _Query("payload", (a, _Atom(0, "=", int(a.value) + rng.randint(1, 9))), True)
    if kind == "or_diff":
        pair = sorted(rng.sample(cols, 2))
        return _Query("payload", tuple(_atom(rng, schema, c, ops=("=",)) for c in pair), True)
    lead = _atom(rng, schema, 0, ops=("=",))
    return _Query("*", (lead, _atom(rng, schema, 2, ops=("=", ">"), fn="abs")))


def generate(level: int, seed: int) -> Variant:
    """Вариант: таблица, индекс (a, b, c) и 4-6 запросов; вопрос — какие из них используют индекс.

    Уровень 1 — только равенства по подмножеству столбцов (левый префикс); уровень 2 — диапазоны и покрывающие
    запросы; уровень 3 — функция над столбцом и `OR`. Ключ — движок правил «левый префикс»; ответы моделей ошибок —
    тот же движок с искажением (`any_column_order`, `function_still_sargable`, `or_uses_index`). Ответ однозначен:
    правило «индекс используется» названо в условии, а ключ дополнительно сверяется с планами `sqlite3`
    (`oracle_check`). Отбрасываются варианты без верных или без неверных запросов, с повторяющимися запросами
    и такие, где ни одна модель ошибки не меняет ответ.
    """
    rng = Random(seed)
    schema = _SCHEMAS[rng.randrange(len(_SCHEMAS))]
    count = {1: rng.choice([4, 5]), 2: 5, 3: rng.choice([5, 6])}[level]
    for _ in range(12):  # набор запросов пересэмплируется, пока в нём нет и верных, и неверных
        queries = [_random_query(rng, schema, level) for _ in range(count)]
        flags = [_used(q) for q in queries]
        if 0 < sum(flags) < count:
            break
    else:
        raise Reject("all_or_none")
    texts = [_sql(schema, q) for q in queries]
    if len(set(texts)) != len(texts):
        raise Reject("duplicate_query")
    ids = [f"o{i}" for i in range(1, count + 1)]
    answer = [i for i, f in zip(ids, flags, strict=True) if f]
    flawed = {
        "any_column_order": {"any_order": True},
        "function_still_sargable": {"fn_ok": True},
        "or_uses_index": {"or_ok": True},
    }
    wrong = {}
    for code, kwargs in flawed.items():
        got = [i for i, q in zip(ids, queries, strict=True) if _used(q, **kwargs)]
        if got != answer and got:
            wrong[code] = got
    if not wrong:
        raise Reject("no_misconception_differs")
    table, cols, payload = schema
    ddl = (
        f"CREATE TABLE {table} ({cols[0]} INTEGER, {cols[1]} TEXT, {cols[2]} INTEGER, {payload} TEXT);\n"
        f"CREATE INDEX idx ON {table} ({', '.join(cols)});"
    )
    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt=(
            "СУБД — SQLite. Выберите все запросы, в плане которых используется индекс idx: поиск по индексу либо "
            "просмотр индекса "
            "без обращения к таблице (все нужные столбцы входят в индекс). Таблица пуста, статистики нет."
        ),
        code=CodeBlock(language="sql", text=ddl),
        options=tuple(Option(i, t) for i, t in zip(ids, texts, strict=True)),
        answer=AnswerSpec.multi(answer),
        misconception_answers=wrong,
        features={"options_count": count, "concepts": level, "trap": 1},
        explanation=f"Используют индекс: {', '.join(answer)}. Неверные чтения: {wrong}.",
    )


def _parse(v: Variant) -> tuple[tuple, list[_Query]]:
    """Разобрать код и тексты запросов обратно в модель."""
    assert v.code is not None and v.options is not None
    m = re.search(r"CREATE TABLE (\w+) \((\w+) INTEGER, (\w+) TEXT, (\w+) INTEGER, (\w+) TEXT\)", v.code.text)
    assert m
    schema = (m.group(1), (m.group(2), m.group(3), m.group(4)), m.group(5))
    queries = []
    for option in v.options:
        select, where = re.fullmatch(r"SELECT (.+) FROM \w+ WHERE (.+)", option.text).groups()  # type: ignore[union-attr]
        disjunction = " OR " in where
        atoms = []
        for part in where.split(" OR " if disjunction else " AND "):
            m2 = re.fullmatch(r"(abs\()?(\w+)(\))?( \+ 0)? (=|<>|>=|<=|>|<) ('?)(\w+)'?", part)
            assert m2, part
            col = schema[1].index(m2.group(2))
            fn = "abs" if m2.group(1) else ("+0" if m2.group(4) else None)
            value: int | str = m2.group(7) if m2.group(6) else int(m2.group(7))
            atoms.append(_Atom(col, m2.group(5), value, fn))
        if select == "*":
            sel: tuple[int, ...] | str = "*"
        elif select == schema[2]:
            sel = "payload"
        else:
            sel = tuple(schema[1].index(c.strip()) for c in select.split(","))
        queries.append(_Query(sel, tuple(atoms), disjunction))
    return schema, queries


def selfcheck(v: Variant) -> list[str]:
    """Перепроверка: запросы разбираются из текста обратно в модель, и движок правил даёт тот же ответ."""
    assert v.options is not None
    _, queries = _parse(v)
    got = [o.id for o, q in zip(v.options, queries, strict=True) if _used(q)]
    problems = [] if got == list(v.answer.option_ids) else [f"правило «левый префикс» даёт {got}"]
    if len({o.text for o in v.options}) != len(v.options):
        problems.append("одинаковые запросы")
    return problems


def oracle_check(v: Variant) -> list[str]:
    """Оракул: `EXPLAIN QUERY PLAN` в `sqlite3` — упоминается ли индекс `idx` в плане каждого запроса."""
    assert v.code is not None and v.options is not None
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(v.code.text)
        used = []
        for option in v.options:
            plan = connection.execute("EXPLAIN QUERY PLAN " + option.text).fetchall()
            if any("idx" in str(row[-1]) for row in plan):
                used.append(option.id)
    finally:
        connection.close()
    if used != list(v.answer.option_ids):
        return [f"план sqlite3 использует индекс в {used}, ключ {list(v.answer.option_ids)}"]
    return []
