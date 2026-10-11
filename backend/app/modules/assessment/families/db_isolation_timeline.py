"""Семейство `db.isolation_timeline`: две транзакции по шагам при заданном уровне изоляции (приложение A, §3.3).

Правила уровня целиком названы в условии, поэтому ответ однозначен. Уровень 1 — READ COMMITTED (сумма
прочитанного первой транзакцией); уровень 2 — SNAPSHOT (потерянное обновление, итоговая сумма x + y);
уровень 3 — перекос записи при SNAPSHOT или SERIALIZABLE. Ключ считает симулятор со снимками значений
(`_simulate`); `selfcheck` пересчитывает сценарий, разобранный из текста, вторым способом — списками версий
со штампами времени (`_simulate_versions`). Модели ошибок — тот же сценарий при искажённых правилах.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from random import Random

from app.modules.assessment.families._lib.contract import AnswerSpec, CodeBlock, InputHint, Reject, Variant
from app.modules.assessment.families._lib.sqlbox import Tbl, to_table
from app.modules.assessment.families.registry import family_meta

META = family_meta(
    "db.isolation_timeline",
    version=1,
    feature_bounds={
        1: {"timeline_events": (7, 9), "tables": (1, 1), "table_rows": (2, 2), "trap": (0, 1), "answer_abs": (0, 1000)},
        2: {"timeline_events": (8, 8), "tables": (1, 1), "table_rows": (2, 2), "trap": (0, 1), "answer_abs": (0, 1000)},
        3: {"timeline_events": (10, 10), "tables": (1, 1), "table_rows": (2, 2), "trap": (0, 1),
            "answer_abs": (0, 1000)},
    },
    misconceptions=(
        "sees_uncommitted", "rc_instead_of_snapshot", "lost_update_allowed", "write_skew_ignored",
        "serializable_assumed",
    ),
)  # fmt: skip


@dataclass(frozen=True)
class Mode:
    """Правила чтения и коммита: снимок или последнее зафиксированное; грязное чтение; проверки при коммите."""

    snapshot: bool = False
    dirty: bool = False
    fcw: bool = False  # «первый зафиксировавший выигрывает» по записанным строкам
    ssi: bool = False  # откат, если записывающая транзакция читала строку, изменённую после её снимка


RC = Mode()
SNAPSHOT = Mode(snapshot=True, fcw=True)
SERIALIZABLE = Mode(snapshot=True, fcw=True, ssi=True)
_MODES = {"READ COMMITTED": RC, "SNAPSHOT": SNAPSHOT, "SERIALIZABLE": SERIALIZABLE}

#: Шаг сценария: (транзакция, операция, ключ, переменная чтения, выражение записи)
Step = tuple[str, str, str | None, str | None, str | None]


def _eval(expr: str, env: dict[str, int]) -> int:
    """Выражение записи: число, переменная, `v + N` или `v - N`."""
    tokens = expr.split()
    value = env[tokens[0]] if tokens[0].isalpha() else int(tokens[0])
    if len(tokens) == 3:
        value += int(tokens[2]) if tokens[1] == "+" else -int(tokens[2])
    return value


def _simulate(steps: list[Step], init: dict[str, int], mode: Mode) -> tuple[list[tuple[str, int]], dict[str, int]]:
    """Основной симулятор: у транзакции копия снимка; возвращает прочитанное (по порядку) и итоговые значения."""
    db = dict(init)
    clock = 0
    last: dict[str, int] = {}
    tx: dict[str, dict] = {}
    pending: dict[str, int] = {}  # последняя незафиксированная запись по ключу (для грязного чтения)
    env: dict[str, int] = {}
    reads: list[tuple[str, int]] = []
    for name, op, key, var, expr in steps:
        if op == "BEGIN":
            tx[name] = {"snap": dict(db), "ts": clock, "w": {}, "r": set()}
            continue
        t = tx[name]
        if op == "READ":
            assert key and var
            if key in t["w"]:
                value = t["w"][key]
            elif mode.dirty and key in pending:
                value = pending[key]
            else:
                value = t["snap"][key] if mode.snapshot else db[key]
            t["r"].add(key)
            env[var] = value
            reads.append((name, value))
        elif op == "WRITE":
            assert key and expr
            t["w"][key] = _eval(expr, env)
            pending[key] = t["w"][key]
        elif op == "ROLLBACK":
            _drop(t, pending)
        else:  # COMMIT
            conflict = mode.fcw and any(last.get(k, 0) > t["ts"] for k in t["w"])
            skew = mode.ssi and t["w"] and any(last.get(k, 0) > t["ts"] for k in t["r"])
            if conflict or skew:
                _drop(t, pending)
                continue
            clock += 1
            for k, val in t["w"].items():
                db[k] = val
                last[k] = clock
            _drop(t, pending)
    return reads, db


def _drop(t: dict, pending: dict[str, int]) -> None:
    """Снять незафиксированные записи транзакции (после коммита или отката)."""
    for k in t["w"]:
        pending.pop(k, None)


def _simulate_versions(
    steps: list[Step], init: dict[str, int], mode: Mode
) -> tuple[list[tuple[str, int]], dict[str, int]]:
    """Второй симулятор: версии строк со штампами; снимок — выбор версии по штампу `begin`, без копий."""
    versions: dict[str, list[tuple[int, int, str]]] = {k: [(0, v, "init")] for k, v in init.items()}
    time = 0
    begin: dict[str, int] = {}
    wrote: dict[str, dict[str, int]] = {}
    read: dict[str, set[str]] = {}
    env: dict[str, int] = {}
    reads: list[tuple[str, int]] = []
    dirty: list[tuple[str, str, int]] = []  # (транзакция, ключ, значение) в порядке записи
    for name, op, key, var, expr in steps:
        time += 1
        if op == "BEGIN":
            begin[name], wrote[name], read[name] = time, {}, set()
        elif op == "READ":
            assert key and var
            read[name].add(key)
            if key in wrote[name]:
                value = wrote[name][key]
            elif mode.dirty and any(k == key for _, k, _ in dirty):
                value = [val for _, k, val in dirty if k == key][-1]
            elif mode.snapshot:
                value = [val for ts, val, _ in versions[key] if ts < begin[name]][-1]
            else:
                value = versions[key][-1][1]
            env[var] = value
            reads.append((name, value))
        elif op == "WRITE":
            assert key and expr
            wrote[name][key] = _eval(expr, env)
            dirty.append((name, key, wrote[name][key]))
        else:
            dirty = [d for d in dirty if d[0] != name]
            if op == "ROLLBACK":
                continue
            started = begin[name]
            if mode.fcw and any(versions[k][-1][0] > started for k in wrote[name]):
                continue
            if mode.ssi and wrote[name] and any(versions[k][-1][0] > started for k in read[name]):
                continue
            for k, val in wrote[name].items():
                versions[k].append((time, val, name))
    return reads, {k: v[-1][1] for k, v in versions.items()}


def _line(step: Step) -> str:
    name, op, key, var, expr = step
    if op == "READ":
        return f"{name}: {var} = READ {key}"
    if op == "WRITE":
        return f"{name}: WRITE {key} = {expr}"
    return f"{name}: {op}"


_LINE = re.compile(r"(T\d): (?:(\w) = READ (\w)|WRITE (\w) = (.+)|(BEGIN|COMMIT|ROLLBACK))")


def _parse(text: str) -> tuple[Mode, list[Step]]:
    """Разобрать сценарий из блока кода."""
    mode = RC
    steps: list[Step] = []
    for line in text.split("\n"):
        if line.startswith("-- "):
            mode = _MODES[line[3:].strip()]
            continue
        m = _LINE.fullmatch(line)
        if not m:
            raise ValueError(f"не разобрана строка: {line}")
        if m.group(2):
            steps.append((m.group(1), "READ", m.group(3), m.group(2), None))
        elif m.group(4):
            steps.append((m.group(1), "WRITE", m.group(4), None, m.group(5)))
        else:
            steps.append((m.group(1), m.group(6), None, None, None))
    return mode, steps


def _merge(rng: Random, first: list[Step], second: list[Step]) -> list[Step]:
    """Случайное чередование двух последовательностей с сохранением порядка внутри каждой."""
    a, b, out = list(first), list(second), []
    while a or b:
        pick = a if (a and (not b or rng.random() < len(a) / (len(a) + len(b)))) else b
        out.append(pick.pop(0))
    return out


_RULES = {
    "READ COMMITTED": (
        "READ COMMITTED: каждое чтение видит последнее зафиксированное значение и собственные записи; "
        "чужие незафиксированные записи не видны. ROLLBACK отменяет записи транзакции."
    ),
    "SNAPSHOT": (
        "SNAPSHOT: транзакция видит данные, зафиксированные к её BEGIN, и свои записи. Если другая транзакция уже "
        "зафиксировала запись той же строки после BEGIN этой, COMMIT отклоняется и транзакция откатывается целиком."
    ),
    "SERIALIZABLE": (
        "SERIALIZABLE: как SNAPSHOT, но COMMIT отклоняется и тогда, когда транзакция что-то записывала, а прочитанную "
        "ею строку после её BEGIN зафиксировала другая транзакция."
    ),
}


def generate(level: int, seed: int) -> Variant:
    """Вариант: таблица acc(x, y), сценарий двух транзакций и вопрос об итоге.

    Уровень 1 — READ COMMITTED: транзакция T1 читает строку несколько раз, пока T2 пишет и фиксирует или откатывает;
    вопрос — сумма прочитанного T1. Уровень 2 — SNAPSHOT: обе транзакции читают и пишут (одну строку — потерянное
    обновление — или разные); вопрос — x + y в конце. Уровень 3 — перекос записи: T1 пишет x, T2 пишет y,
    обе прочитали обе строки; SNAPSHOT пропускает обе, SERIALIZABLE отклоняет вторую; вопрос — x + y в конце.
    Ответ вычисляет симулятор по правилам из условия; модели ошибок: `sees_uncommitted`, `rc_instead_of_snapshot`,
    `lost_update_allowed`, `write_skew_ignored`, `serializable_assumed` — тот же сценарий при искажённых правилах.
    Ответ однозначен: правила уровня названы в условии. Варианты, где ни одна модель ошибки не меняет ответ,
    и тривиальные ответы отбрасываются.
    """
    rng = Random(seed)
    init = {"x": rng.randrange(20, 90, 5), "y": rng.randrange(20, 90, 5)}
    letters = iter("abcdef")
    begin: list[Step] = [
        ("T1", "BEGIN", None, None, None), ("T2", "BEGIN", None, None, None)
    ]
    if level == 1:
        mode_name, mode = "READ COMMITTED", RC
        key = rng.choice("xy")
        reads: list[Step] = [
            ("T1", "READ", key, next(letters), None) for _ in range(rng.randint(2, 3))
        ]
        writes: list[Step] = [
            ("T2", "WRITE", key, None, str(rng.randrange(10, 100, 5))) for _ in range(rng.randint(1, 2))
        ]
        end = ("T2", rng.choice(["COMMIT", "COMMIT", "ROLLBACK"]), None, None, None)
        # Чтение до первой записи, чтение сразу после неё (пока T2 не завершена), остальное — вперемешку.
        body = [reads[0], writes[0], reads[1], *_merge(rng, reads[2:], [*writes[1:], end])]
        body.append(("T1", "COMMIT", None, None, None))
        question = "Чему равна сумма значений, прочитанных транзакцией T1?"
        wrong_modes = {"sees_uncommitted": Mode(dirty=True)}
    elif level == 2:
        mode_name, mode = "SNAPSHOT", SNAPSHOT
        key2 = "x" if rng.random() < 0.9 else "y"
        a, b = next(letters), next(letters)
        t1: list[Step] = [
            ("T1", "READ", "x", a, None), ("T1", "WRITE", "x", None, f"{a} + {rng.randrange(5, 50, 5)}")
        ]
        t2: list[Step] = [
            ("T2", "READ", key2, b, None), ("T2", "WRITE", key2, None, f"{b} + {rng.randrange(5, 50, 5)}")
        ]
        t1.append(("T1", rng.choice(["COMMIT"] * 9 + ["ROLLBACK"]), None, None, None))
        t2.append(("T2", "COMMIT", None, None, None))
        shape = rng.choice(["overlap", "late_read", "late_read"])
        if shape == "overlap":  # обе читают до любых записей, затем записи и концы вперемешку
            body = [t1[0], t2[0], *_merge(rng, t1[1:], t2[1:])]
        else:  # T2 читает после конца T1: снимок прячет изменения T1, RC их показывает
            body = [*t1, *t2]
        question = "Чему равна сумма x + y в таблице после завершения обеих транзакций?"
        wrong_modes = {
            "sees_uncommitted": Mode(dirty=True, fcw=True),
            "rc_instead_of_snapshot": RC,
            "lost_update_allowed": Mode(snapshot=True),
        }
    else:
        mode_name = rng.choice(["SNAPSHOT", "SERIALIZABLE"])
        mode = _MODES[mode_name]
        a, b, c, d = (next(letters) for _ in range(4))
        t1 = [
            ("T1", "READ", "x", a, None),
            ("T1", "READ", "y", b, None),
            ("T1", "WRITE", "x", None, f"{a} - {rng.randrange(10, 60, 5)}"),
            ("T1", "COMMIT", None, None, None),
        ]
        t2 = [("T2", "READ", "x", c, None), ("T2", "READ", "y", d, None),
              ("T2", "WRITE", "y", None, f"{d} - {rng.randrange(10, 60, 5)}"),
              ("T2", "COMMIT", None, None, None)]  # fmt: skip
        body = [*_merge(rng, t1[:2], t2[:2]), *_merge(rng, t1[2:], t2[2:])]
        question = "Чему равна сумма x + y в таблице после завершения обеих транзакций?"
        wrong_modes = (
            {"write_skew_ignored": SNAPSHOT, "rc_instead_of_snapshot": RC}
            if mode_name == "SERIALIZABLE"
            else {"serializable_assumed": SERIALIZABLE, "rc_instead_of_snapshot": RC}
        )
    steps = [*begin, *body]

    def result(m: Mode) -> int:
        _, db = _simulate(steps, init, m)
        return db["x"] + db["y"]

    def reads_t1(m: Mode) -> int:
        reads, _ = _simulate(steps, init, m)
        return sum(val for name, val in reads if name == "T1")

    value = reads_t1 if level == 1 else result
    answer = value(mode)
    wrong = {code: value(m) for code, m in wrong_modes.items()}
    wrong = {code: val for code, val in wrong.items() if val != answer}
    if not wrong:
        raise Reject("no_misconception_differs")
    if answer in (0, 1, 2):
        raise Reject("trivial_answer")
    code = f"-- {mode_name}\n" + "\n".join(_line(s) for s in steps)
    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt=f"{_RULES[mode_name]} Начальные значения в таблице acc. {question} Ответ — целое число.",
        code=CodeBlock(language="text", text=code),
        tables=(to_table(Tbl("acc", ("id", "v"), (("x", init["x"]), ("y", init["y"])))),),
        input=InputHint(placeholder="целое число", max_length=6),
        answer=AnswerSpec.numeric(answer),
        misconception_answers=wrong,
        features={
            "timeline_events": len(steps), "tables": 1, "table_rows": 2, "trap": int(len(wrong) > 1),
            "answer_abs": abs(answer),
        },
        explanation=f"Ответ {answer} при {mode_name}. Неверные чтения: {wrong}.",
    )  # fmt: skip


def selfcheck(v: Variant) -> list[str]:
    """Перепроверка: сценарий разобран из текста и пересчитан вторым симулятором (версии со штампами времени)."""
    assert v.code is not None and v.tables is not None
    try:
        mode, steps = _parse(v.code.text)
    except (ValueError, KeyError) as error:
        return [str(error)]
    init = {row[0]: int(row[1]) for row in v.tables[0].rows}
    reads, db = _simulate_versions(steps, init, mode)
    value = sum(val for name, val in reads if name == "T1") if v.level == 1 else db["x"] + db["y"]
    return [] if value == v.answer.value else [f"второй симулятор даёт {value}, ключ {v.answer.value}"]
