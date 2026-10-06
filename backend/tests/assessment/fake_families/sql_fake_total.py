"""Учебное семейство «сумма по условию»: запрос к случайной таблице, ответ считает `sqlite3`.

Образец семейства с таблицей в условии. Что здесь показано:

* данные и запрос строятся из seed, ответ — результат выполнения запроса в `sqlite3` в памяти;
* ответ модели ошибки — результат «неправильно прочитанного» запроса, выполненного там же;
* `selfcheck` проверяет независимость ответа от порядка вставки строк и пересчитывает его на чистом Python;
* ячейки таблицы условия — строки; столбцы и имена берутся из общего словаря `names`.
"""

from __future__ import annotations

import sqlite3
from random import Random

from app.modules.assessment.families._lib import names
from app.modules.assessment.families._lib.contract import AnswerSpec, CodeBlock, InputHint, Reject, Table, Variant
from app.modules.assessment.families.registry import family_meta
from tests.assessment.fake_families import FAKE_SPECS

META = family_meta(
    "sql.fake_total",
    version=1,
    feature_bounds={
        1: {"tables": (1, 1), "table_rows": (6, 8), "concepts": (1, 1), "answer_abs": (10, 2000)},
        2: {"tables": (1, 1), "table_rows": (7, 8), "concepts": (2, 2), "answer_abs": (10, 2000)},
    },
    spec=FAKE_SPECS["sql.fake_total"],
)

Row = tuple[int, str, int, str]
COLUMNS = ("id", "city", "amount", "status")


def _execute(rows: list[Row], query: str) -> int | None:
    """Выполнить запрос к таблице `orders` в `sqlite3` в памяти и вернуть единственное значение."""
    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, city TEXT, amount INTEGER, status TEXT)")
        connection.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)", rows)
        value = connection.execute(query).fetchone()[0]
    return None if value is None else int(value)


def _queries(level: int, threshold: int, status: str) -> tuple[str, str, str]:
    """Запрос условия, код модели ошибки и запрос, который «исполняет» кандидат с этой ошибкой."""
    if level == 1:
        where = f"amount > {threshold} {{op}} status = '{status}'"
        template = f"SELECT SUM(amount)\nFROM orders\nWHERE {where}"
        return template.format(op="AND"), "or_instead_of_and", template.format(op="OR")
    inner = "SELECT city, SUM(amount) AS total\n  FROM orders\n  GROUP BY city{having}\n"
    template = f"SELECT MIN(total)\nFROM (\n  {inner})"
    return template.format(having="\n  HAVING COUNT(*) >= 2"), "having_ignored", template.format(having="")


def generate(level: int, seed: int) -> Variant:
    """Вариант: таблица заказов и запрос с агрегатом; вопрос — какое число он вернёт.

    Уровень 1 — `SUM` с двумя условиями через `AND`; модель ошибки `or_instead_of_and`. Уровень 2 — наименьшая
    сумма среди городов, у которых не меньше двух заказов (`GROUP BY` и `HAVING`); модель ошибки `having_ignored`.
    Ответ считает `sqlite3`. Он однозначен: запрос возвращает одну строку с одним числом и не зависит от порядка
    строк таблицы; варианты с пустым результатом и с ответом, равным ответу модели ошибки, отбрасываются.
    """
    if level not in (1, 2):
        raise ValueError(f"нет уровня {level}")
    rng = Random(seed)
    cities = names.pick_many(rng, names.CITIES, 3 if level == 1 else 5)
    statuses = names.pick_many(rng, names.STATUSES, 2)
    count = rng.randint(6, 8) if level == 1 else rng.randint(7, 8)
    rows: list[Row] = [
        (i, names.pick(rng, cities), rng.randrange(10, 200, 10), names.pick(rng, statuses)) for i in range(1, count + 1)
    ]
    threshold = rng.randrange(40, 140, 10)
    query, code, wrong_query = _queries(level, threshold, statuses[0])

    answer, wrong = _execute(rows, query), _execute(rows, wrong_query)
    if answer is None or wrong is None:
        raise Reject("empty_result")
    if answer == wrong:
        raise Reject("misconception_equals_answer")

    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt="Какое число вернёт запрос к таблице orders? Ответ — целое число.",
        code=CodeBlock(language="sql", text=query),
        tables=(Table(title="orders", columns=COLUMNS, rows=tuple(tuple(str(cell) for cell in row) for row in rows)),),
        input=InputHint(placeholder="целое число", max_length=8),
        answer=AnswerSpec.numeric(answer),
        misconception_answers={code: wrong},
        features={"tables": 1, "table_rows": len(rows), "concepts": level, "answer_abs": abs(answer)},
        explanation=f"Запрос возвращает {answer}. Ошибка {code} дала бы {wrong}.",
    )


def _python_answer(level: int, rows: list[Row], query: str) -> int | None:
    """Второй способ вычисления: тот же смысл запроса на чистом Python, без `sqlite3`."""
    if level == 1:
        condition = query.rsplit("WHERE ", 1)[1]
        threshold = int(condition.split(" ")[2])
        status = condition.rsplit("'", 2)[1]
        picked = [amount for _, _, amount, row_status in rows if amount > threshold and row_status == status]
        return sum(picked) if picked else None
    totals: dict[str, list[int]] = {}
    for _, city, amount, _ in rows:
        totals.setdefault(city, []).append(amount)
    sums = [sum(amounts) for amounts in totals.values() if len(amounts) >= 2]
    return min(sums) if sums else None


def selfcheck(v: Variant) -> list[str]:
    """Перепроверка (приложение A, §2.5): обратный порядок вставки строк и расчёт на чистом Python."""
    assert v.tables is not None and v.code is not None
    rows: list[Row] = [(int(r[0]), r[1], int(r[2]), r[3]) for r in v.tables[0].rows]
    problems = []
    if _execute(rows[::-1], v.code.text) != v.answer.value:
        problems.append("ответ зависит от порядка вставки строк")
    if _python_answer(v.level, rows, v.code.text) != v.answer.value:
        problems.append("расчёт на чистом Python расходится с sqlite3")
    return problems
