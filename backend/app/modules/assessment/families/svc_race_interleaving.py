"""Семейство `svc.race_interleaving`: гонки двух потоков над общей переменной (numeric_input).

Каждый поток повторяет «прочитать x, изменить, записать x» (строки по отдельности атомарны). Уровень 1 — итог при
заданном порядке шагов; уровень 2 — наименьший или наибольший итог при любом чередовании; уровень 3 — то же, когда
замок покрывает не весь цикл (запись вне замка). Ответ — полный перебор чередований: поиск в глубину с запоминанием
состояний (`all_finals`); `selfcheck` разбирает отрисованный текст программы заново и считает ответ другим способом —
перебором всех различных последовательностей номеров потоков. Оракула нет (в реестре `manual`). Модель ошибки
`atomic_increment`: `x += n` считается неделимым, итог — сумма всех приращений.
"""

from __future__ import annotations

import re
from random import Random

from app.modules.assessment.families._lib.contract import AnswerSpec, CodeBlock, InputHint, Reject, Variant
from app.modules.assessment.families.registry import family_meta

META = family_meta(
    "svc.race_interleaving",
    version=1,
    feature_bounds={
        1: {"code_lines": (13, 13), "concepts": (1, 1)},
        2: {"code_lines": (10, 17), "concepts": (1, 2)},
        3: {"code_lines": (12, 20), "concepts": (2, 3)},
    },
    misconceptions=("atomic_increment",),
)

Op = tuple[str, int]  # ("read"|"add"|"write"|"acq"|"rel", аргумент)


def thread_ops(inc: int, reps: int, lock: str) -> list[Op]:
    """Операции потока: `lock` — "none", "all" (замок на весь цикл) или "rw" (замок на чтение и правку, запись вне)."""
    ops: list[Op] = []
    for _ in range(reps):
        if lock != "none":
            ops.append(("acq", 0))
        ops += [("read", 0), ("add", inc)]
        if lock == "rw":
            ops.append(("rel", 0))
            ops.append(("write", 0))
        else:
            ops.append(("write", 0))
            if lock == "all":
                ops.append(("rel", 0))
    return ops


def _step(op: Op, state: tuple[int, tuple[int, ...], int], t: int) -> tuple[int, tuple[int, ...], int] | None:
    """Выполнить операцию потока t; None, если замок занят. Состояние: (x, временные значения, владелец замка)."""
    x, tmps, owner = state
    kind, arg = op
    if kind == "acq":
        return None if owner != -1 else (x, tmps, t)
    if kind == "rel":
        return (x, tmps, -1)
    new = list(tmps)
    if kind == "read":
        new[t] = x
    elif kind == "add":
        new[t] += arg
    else:
        return (new[t], tuple(new), owner)
    return (x, tuple(new), owner)


def all_finals(threads: list[list[Op]], x0: int) -> set[int]:
    """Все возможные итоговые значения x: поиск в глубину по чередованиям с запоминанием состояний."""
    seen: set[tuple] = set()
    finals: set[int] = set()
    stack = [((0,) * len(threads), (x0, (0,) * len(threads), -1))]
    while stack:
        key = stack.pop()
        if key in seen:
            continue
        seen.add(key)
        pcs, state = key
        if all(pc == len(ops) for pc, ops in zip(pcs, threads, strict=True)):
            finals.add(state[0])
            continue
        for t, ops in enumerate(threads):
            if pcs[t] < len(ops):
                nxt = _step(ops[pcs[t]], state, t)
                if nxt is not None:
                    stack.append(((*pcs[:t], pcs[t] + 1, *pcs[t + 1 :]), nxt))
    return finals


def run_order(threads: list[list[Op]], x0: int, order: list[int]) -> int:
    """Итог при заданном порядке (номера потоков по шагам)."""
    state, pcs = (x0, (0,) * len(threads), -1), [0] * len(threads)
    for t in order:
        nxt = _step(threads[t][pcs[t]], state, t)
        assert nxt is not None
        state, pcs[t] = nxt, pcs[t] + 1
    return state[0]


def _render(x0: int, incs: list[int], reps: list[int], locks: list[str]) -> str:
    lines = [f"x = {x0}"]
    if any(lock != "none" for lock in locks):
        lines.append("lock = Lock()")
    for t, name in enumerate("ab"):
        lines += ["", f"def worker_{name}():", "    global x"]
        indent = "    "
        if reps[t] > 1:
            lines.append(f"    for _ in range({reps[t]}):")
            indent = "        "
        sign = f"+= {incs[t]}" if incs[t] >= 0 else f"-= {-incs[t]}"
        body = [f"tmp = x  # {name}1", f"tmp {sign}  # {name}2", f"x = tmp  # {name}3"]
        if locks[t] == "all":
            lines.append(f"{indent}with lock:")
            lines += [f"{indent}    {row}" for row in body]
        elif locks[t] == "rw":
            lines.append(f"{indent}with lock:")
            lines += [f"{indent}    {row}" for row in body[:2]]
            lines.append(f"{indent}{body[2]}")
        else:
            lines += [f"{indent}{row}" for row in body]
    return "\n".join(lines)


def _inc(rng: Random, allow_negative: bool) -> int:
    value = rng.randint(1, 9)
    return -value if allow_negative and rng.random() < 0.4 else value


def generate(level: int, seed: int) -> Variant:
    """Вариант: два потока над общей x; вопрос — итог при заданном порядке либо наименьший/наибольший итог.

    Что вычисляется: уровень 1 — выполнение шагов в заданном порядке; уровни 2–3 — минимум или максимум по всем
    допустимым чередованиям (`all_finals`, с учётом замка). Модель ошибки `atomic_increment` — итог при неделимом
    приращении: `x0 + сумма приращений`. Вариант, где обычный итог совпал с ней, отбрасывается. Ответ однозначен:
    шаги атомарны, потоки чередуются произвольно, порядок (уровень 1) выписан в условии.
    """
    rng = Random(seed)
    x0 = rng.randint(0, 9)
    reps = [1, 1] if level == 1 else [rng.randint(1, 2), rng.randint(1, 2) if level == 2 else 1]
    incs = [_inc(rng, level > 1), _inc(rng, level > 1)]
    locks = ["none", "none"] if level < 3 else [rng.choice(("rw", "rw", "all")), rng.choice(("all", "none", "rw"))]
    if level == 3 and locks == ["all", "all"]:
        raise Reject("lock_makes_atomic")
    threads = [thread_ops(incs[t], reps[t], locks[t]) for t in range(2)]
    atomic = x0 + incs[0] * reps[0] + incs[1] * reps[1]
    if level == 1:
        order = [0, 1, 0, 1, 0, 1]
        rng.shuffle(order)
        # порядок не должен нарушать порядок шагов внутри потока: метка шага — номер вхождения потока
        counters = [0, 0]
        steps = []
        for t in order:
            counters[t] += 1
            steps.append(f"{'ab'[t]}{counters[t]}")
        answer = run_order(threads, x0, order)
        question = f"Шаги выполняются в порядке: {', '.join(steps)}. Каждая строка атомарна. Чему равно x в конце?"
        goal = "порядок"
    else:
        goal = rng.choice(("наименьшее", "наибольшее"))
        finals = all_finals(threads, x0)
        answer = min(finals) if goal == "наименьшее" else max(finals)
        question = (
            f"Строки выполняются атомарно, потоки чередуются произвольно. Какое {goal} значение x возможно в конце?"
        )
    if answer == atomic:
        raise Reject("misconception_equals_answer")
    if answer in (0, 1):
        raise Reject("trivial_answer")
    text = _render(x0, incs, reps, locks)
    lock_note = " Замок lock блокирует вход в with, пока его держит другой поток." if level == 3 else ""
    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt=(
            f"Два потока запускают worker_a и worker_b над общей переменной x.{lock_note} {question} "
            "Ответ — целое число."
        ),
        code=CodeBlock(language="python", text=text),
        input=InputHint(placeholder="целое число", max_length=4),
        answer=AnswerSpec.numeric(answer),
        misconception_answers={"atomic_increment": atomic},
        features={
            "code_lines": text.count("\n") + 1,
            "concepts": 1 if level == 1 else 1 + (level == 3) + (goal != "порядок" and level == 3),
        },
        explanation=f"Перебор чередований даёт {answer}; при неделимом приращении было бы {atomic}.",
    )


def _parse(text: str) -> tuple[int, list[list[Op]]]:
    """Разобрать отрисованную программу: x0 и операции двух потоков."""
    lines = [re.sub(r"\s*#.*$", "", row) for row in text.split("\n")]
    x0 = int(re.match(r"x = (\d+)", lines[0]).group(1))  # type: ignore[union-attr]
    threads: list[list[Op]] = []
    for row_index, row in enumerate(lines):
        if not row.startswith("def worker_"):
            continue
        body = []
        for follow in lines[row_index + 1 :]:
            if follow.startswith("def worker_"):
                break
            if follow.strip():
                body.append(follow)
        reps, ops, in_lock = 1, [], False
        lock_depth = 0
        for follow in body:
            stripped = follow.strip()
            depth = len(follow) - len(follow.lstrip())
            if in_lock and depth <= lock_depth:
                ops.append(("rel", 0))
                in_lock = False
            if m := re.match(r"for _ in range\((\d+)\)", stripped):
                reps = int(m.group(1))
            elif stripped == "with lock:":
                ops.append(("acq", 0))
                in_lock, lock_depth = True, depth
            elif stripped == "tmp = x":
                ops.append(("read", 0))
            elif m := re.match(r"tmp ([+-])= (\d+)", stripped):
                ops.append(("add", int(m.group(2)) * (1 if m.group(1) == "+" else -1)))
            elif stripped == "x = tmp":
                ops.append(("write", 0))
        if in_lock:
            ops.append(("rel", 0))
        threads.append(ops * reps)
    return x0, threads


def _orders(left: list[int]) -> list[list[int]]:
    """Все различные последовательности номеров потоков с заданным числом шагов у каждого (мультимножество)."""
    if not any(left):
        return [[]]
    out = []
    for t, n in enumerate(left):
        if n:
            left[t] -= 1
            out += [[t, *rest] for rest in _orders(left)]
            left[t] += 1
    return out


def _brute(threads: list[list[Op]], x0: int) -> set[int]:
    """Другой способ перебора: все различные последовательности потоков; недопустимые по замку отбрасываются."""
    finals = set()
    for order in _orders([len(ops) for ops in threads]):
        state, pcs, ok = (x0, (0,) * len(threads), -1), [0] * len(threads), True
        for t in order:
            nxt = _step(threads[t][pcs[t]], state, t)
            if nxt is None:
                ok = False
                break
            state, pcs[t] = nxt, pcs[t] + 1
        if ok:
            finals.add(state[0])
    return finals


def selfcheck(v: Variant) -> list[str]:
    """Пересчёт: программа разбирается из текста, итог считается перебором всех последовательностей потоков."""
    assert v.code is not None
    x0, threads = _parse(v.code.text)
    if v.level == 1:
        m = re.search(r"порядке: ([ab]\d(?:, [ab]\d)*)\.", v.prompt)
        if not m:
            return ["в условии нет порядка шагов"]
        order = [("ab".index(step[0])) for step in m.group(1).split(", ")]
        got = run_order(threads, x0, order)
    else:
        if len(threads[0]) + len(threads[1]) > 16:
            return ["слишком много шагов для перебора"]
        finals = _brute(threads, x0)
        got = min(finals) if "наименьшее" in v.prompt else max(finals)
    return [] if got == v.answer.value else [f"пересчёт даёт {got}, ключ {v.answer.value}"]
