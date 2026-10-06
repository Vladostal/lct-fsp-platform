"""Семейство `db.constraints_effect`: что останется в таблицах после серии команд при ограничениях целостности.

Уровень 1 — внешний ключ с `ON DELETE CASCADE`, `RESTRICT` или `SET NULL`; уровень 2 — `UNIQUE` и `CHECK`.
Правило, названное в условии: команда, нарушающая ограничение, завершается ошибкой и ничего не меняет, остальные
команды выполняются. Ответ получает `sqlite3` с `PRAGMA foreign_keys = ON`; модели ошибок — тот же сценарий
без ограничений (`fk_not_enforced`, `constraints_not_enforced`) и сценарий, прерванный на первой ошибке
(`stop_at_first_error`).
"""

from __future__ import annotations

import re
import sqlite3
from random import Random

from app.modules.assessment.families._lib import names, sqlbox
from app.modules.assessment.families._lib.contract import AnswerSpec, CodeBlock, InputHint, Reject, Variant
from app.modules.assessment.families._lib.sqlbox import Tbl
from app.modules.assessment.families.registry import family_meta

META = family_meta(
    "db.constraints_effect",
    version=1,
    feature_bounds={
        1: {"tables": (2, 2), "table_rows": (6, 12), "concepts": (1, 1), "trap": (0, 1), "answer_abs": (0, 100)},
        2: {"tables": (1, 1), "table_rows": (4, 6), "concepts": (2, 2), "trap": (0, 1), "answer_abs": (0, 1000)},
    },
    misconceptions=("fk_not_enforced", "constraints_not_enforced", "stop_at_first_error"),
)  # fmt: skip

_DDL_FK = (
    "CREATE TABLE parents (id INTEGER PRIMARY KEY, name TEXT);\n"
    "CREATE TABLE children (\n"
    "  id INTEGER PRIMARY KEY,\n"
    "  parent_id INTEGER REFERENCES parents(id) ON DELETE {action},\n"
    "  note TEXT\n"
    ");"
)
_DDL_FK_PLAIN = _DDL_FK.replace(" REFERENCES parents(id) ON DELETE {action}", "")
_DDL_ACC = (
    "CREATE TABLE accounts (\n"
    "  id INTEGER PRIMARY KEY,\n"
    "  email TEXT UNIQUE,\n"
    "  balance INTEGER CHECK (balance >= 0)\n"
    ");"
)
_DDL_ACC_PLAIN = "CREATE TABLE accounts (id INTEGER PRIMARY KEY, email TEXT, balance INTEGER);"
_TOTAL_FK = "SELECT (SELECT COUNT(*) FROM parents) + (SELECT COUNT(*) FROM children)"
_TOTAL_ACC = "SELECT SUM(balance) FROM accounts"


def _run(ddl: str, tables: list[Tbl], script: list[str], total: str, *, fk: bool, stop: bool = False) -> int:
    """Выполнить сценарий в `sqlite3`: ошибка ограничения пропускает команду (или останавливает сценарий)."""
    connection = sqlite3.connect(":memory:")
    connection.isolation_level = None
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.executescript(ddl)
    for table in tables:
        marks = ", ".join("?" for _ in table.columns)
        connection.executemany(f"INSERT INTO {table.name} VALUES ({marks})", table.rows)
    connection.execute(f"PRAGMA foreign_keys = {'ON' if fk else 'OFF'}")
    for statement in script:
        try:
            connection.execute(statement)
        except sqlite3.IntegrityError:
            if stop:
                break
    value = connection.execute(total).fetchone()[0]
    connection.close()
    return int(value or 0)


def generate(level: int, seed: int) -> Variant:
    """Вариант: схема, начальные данные и 3-4 команды; вопрос — число строк (уровень 1) или сумма `balance` (уровень 2).

    Уровень 1: `ON DELETE CASCADE`/`RESTRICT`/`SET NULL` и вставка дочерней строки с несуществующим родителем.
    Уровень 2: вставки с повторным `email` или `id`, `UPDATE` с нарушением `CHECK (balance >= 0)`. Ответ
    вычисляет `sqlite3` с включёнными внешними ключами; ответы моделей ошибок — тот же сценарий без ограничений
    и сценарий, остановленный на первой ошибке. Ответ однозначен: каждая команда атомарна, правило названо
    в условии. Варианты, где ни одна модель ошибки не отличается от верного ответа, где нет ни одной ошибки
    команды, а также с тривиальным ответом отбрасываются.
    """
    rng = Random(seed)
    if level == 1:
        action = rng.choice(["CASCADE", "RESTRICT", "SET NULL"])
        parent_ids = list(range(1, rng.randint(4, 5) + 1))
        parents = [(i, names.pick(rng, names.FIRST_NAMES)) for i in parent_ids]
        children = [
            (10 + i, rng.choice([*parent_ids, None]) if rng.random() < 0.85 else None, names.pick(rng, names.WORDS))
            for i in range(1, rng.randint(5, 7) + 1)
        ]
        tables = [
            Tbl("parents", ("id", "name"), tuple(parents)),
            Tbl("children", ("id", "parent_id", "note"), tuple(children)),
        ]
        pool = [
            f"DELETE FROM parents WHERE id = {rng.choice(parent_ids)};",
            f"DELETE FROM parents WHERE id = {rng.choice(parent_ids)};",
            f"INSERT INTO children VALUES ({50 + rng.randint(1, 9)}, {rng.choice([*parent_ids, 9])}, 'new');",
            f"INSERT INTO children VALUES ({60 + rng.randint(1, 9)}, 9, 'late');",
            f"DELETE FROM children WHERE id = {rng.choice(children)[0]};",
            f"INSERT INTO parents VALUES ({20 + rng.randint(1, 9)}, 'extra');",
        ]
        script = rng.sample(pool, rng.randint(3, 4))
        ddl, plain, total = _DDL_FK.format(action=action), _DDL_FK_PLAIN, _TOTAL_FK
        wrong_codes = ("fk_not_enforced", "stop_at_first_error")
    else:
        ids = rng.sample(range(1, 7), 4)
        mails = names.pick_many(rng, names.FIRST_NAMES_LATIN, 6)
        rows = [(i, f"{mails[k]}@example.com", rng.randrange(20, 120, 10)) for k, i in enumerate(ids)]
        tables = [Tbl("accounts", ("id", "email", "balance"), tuple(rows))]
        victim = rng.choice(rows)
        other = rng.choice([r for r in rows if r is not victim])
        pool = [
            "INSERT INTO accounts VALUES "
            f"({rng.choice([7, 8, 9])}, '{mails[4]}@example.com', {rng.randrange(10, 80, 10)});",
            f"INSERT INTO accounts VALUES ({rng.choice([7, 8, 9])}, '{victim[1]}', {rng.randrange(10, 80, 10)});",
            f"UPDATE accounts SET balance = balance - {rng.randrange(40, 160, 10)} WHERE id = {victim[0]};",
            f"UPDATE accounts SET balance = balance - {rng.randrange(10, 60, 10)} WHERE id = {other[0]};",
            f"UPDATE accounts SET email = '{other[1]}' WHERE id = {victim[0]};",
            f"INSERT INTO accounts VALUES ({rng.choice(ids)}, '{mails[5]}@example.com', 50);",
            f"UPDATE accounts SET balance = balance + {rng.randrange(10, 50, 10)} WHERE id = {rng.choice(ids)};",
        ]
        script = rng.sample(pool, rng.randint(3, 4))
        ddl, plain, total = _DDL_ACC, _DDL_ACC_PLAIN, _TOTAL_ACC
        wrong_codes = ("constraints_not_enforced", "stop_at_first_error")
    answer = _run(ddl, tables, script, total, fk=True)
    # Ошибка команды должна встретиться: иначе ограничения ничего не проверяют.
    if _run(ddl, tables, script, total, fk=True, stop=True) == answer and not _fails(ddl, tables, script):
        raise Reject("no_violation")
    wrong = {
        wrong_codes[0]: _run(plain, tables, script, total, fk=False),
        "stop_at_first_error": _run(ddl, tables, script, total, fk=True, stop=True),
    }
    wrong = {code: value for code, value in wrong.items() if value != answer}
    if not wrong:
        raise Reject("no_misconception_differs")
    if answer in (0, 1) or any(answer == len(t.rows) for t in tables):
        raise Reject("trivial_answer")
    code_text = ddl + "\n\n-- команды выполняются по очереди:\n" + "\n".join(script)
    question = (
        "Сколько строк всего в таблицах parents и children после сценария?"
        if level == 1
        else "Чему равна сумма balance после сценария?"
    )
    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt=(
            "Внешние ключи включены (PRAGMA foreign_keys = ON). Начальные данные показаны в таблицах. Команда, "
            "нарушающая ограничение, завершается ошибкой и ничего не меняет, следующие команды выполняются. "
            f"{question} Ответ — целое число."
        ),
        code=CodeBlock(language="sql", text=code_text),
        tables=tuple(sqlbox.to_table(t) for t in tables),
        input=InputHint(placeholder="целое число", max_length=6),
        answer=AnswerSpec.numeric(answer),
        misconception_answers=wrong,
        features={
            "tables": len(tables), "table_rows": sum(len(t.rows) for t in tables), "concepts": level,
            "trap": int(len(wrong) > 1), "answer_abs": answer,
        },
        explanation=f"После сценария {answer}. Неверные чтения: {wrong}.",
    )  # fmt: skip


def _fails(ddl: str, tables: list[Tbl], script: list[str]) -> bool:
    """Есть ли в сценарии команда, которая падает с ошибкой целостности."""
    connection = sqlite3.connect(":memory:")
    connection.isolation_level = None
    connection.executescript(ddl)
    for table in tables:
        marks = ", ".join("?" for _ in table.columns)
        connection.executemany(f"INSERT INTO {table.name} VALUES ({marks})", table.rows)
    connection.execute("PRAGMA foreign_keys = ON")
    failed = False
    for statement in script:
        try:
            connection.execute(statement)
        except sqlite3.IntegrityError:
            failed = True
    connection.close()
    return failed


def _simulate_fk(v: Variant, script: list[str]) -> int:
    """Модель уровня 1 на словарях Python: внешний ключ с действием из DDL."""
    assert v.code is not None
    action = re.search(r"ON DELETE ([A-Z ]+),", v.code.text).group(1)  # type: ignore[union-attr]
    tables = sqlbox.tables_from_variant(v)
    parents = {r[0] for r in tables[0].rows}
    children = {r[0]: r[1] for r in tables[1].rows}
    for statement in script:
        if m := re.fullmatch(r"DELETE FROM parents WHERE id = (\d+);", statement):
            pid = int(m.group(1))
            if pid not in parents:
                continue
            refs = [c for c, p in children.items() if p == pid]
            if refs and action == "RESTRICT":
                continue
            parents.discard(pid)
            for c in refs:
                if action == "CASCADE":
                    del children[c]
                else:
                    children[c] = None
        elif m := re.fullmatch(r"INSERT INTO children VALUES \((\d+), (\d+), '\w+'\);", statement):
            cid, pid = int(m.group(1)), int(m.group(2))
            if cid not in children and pid in parents:
                children[cid] = pid
        elif m := re.fullmatch(r"DELETE FROM children WHERE id = (\d+);", statement):
            children.pop(int(m.group(1)), None)
        elif m := re.fullmatch(r"INSERT INTO parents VALUES \((\d+), 'extra'\);", statement):
            parents.add(int(m.group(1)))
        else:
            raise ValueError(f"неизвестная команда: {statement}")
    return len(parents) + len(children)


def _simulate_acc(v: Variant, script: list[str]) -> int:
    """Модель уровня 2 на словарях Python: PRIMARY KEY, UNIQUE(email), CHECK(balance >= 0)."""
    accounts = {r[0]: [r[1], r[2]] for r in sqlbox.tables_from_variant(v)[0].rows}
    for statement in script:
        if m := re.fullmatch(r"INSERT INTO accounts VALUES \((\d+), '([^']+)', (\d+)\);", statement):
            aid, mail, bal = int(m.group(1)), m.group(2), int(m.group(3))
            if aid not in accounts and all(a[0] != mail for a in accounts.values()) and bal >= 0:
                accounts[aid] = [mail, bal]
        elif m := re.fullmatch(r"UPDATE accounts SET balance = balance ([+-]) (\d+) WHERE id = (\d+);", statement):
            row = accounts.get(int(m.group(3)))
            if row is not None:
                new = row[1] + (int(m.group(2)) if m.group(1) == "+" else -int(m.group(2)))
                if new >= 0:
                    row[1] = new
        elif m := re.fullmatch(r"UPDATE accounts SET email = '([^']+)' WHERE id = (\d+);", statement):
            row = accounts.get(int(m.group(2)))
            if row is not None and all(a[0] != m.group(1) for k, a in accounts.items() if k != int(m.group(2))):
                row[0] = m.group(1)
        else:
            raise ValueError(f"неизвестная команда: {statement}")
    return sum(a[1] for a in accounts.values())


def selfcheck(v: Variant) -> list[str]:
    """Перепроверка: те же команды на модели из словарей Python дают тот же ответ, что `sqlite3`."""
    assert v.code is not None
    script = [line for line in v.code.text.split("\n") if re.match(r"(INSERT|UPDATE|DELETE)", line)]
    try:
        value = _simulate_fk(v, script) if v.level == 1 else _simulate_acc(v, script)
    except ValueError as error:
        return [str(error)]
    return [] if value == v.answer.value else [f"модель на Python даёт {value}, ключ {v.answer.value}"]
