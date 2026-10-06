"""Семейство «Трассировка рекурсии»: значение, число вызовов, число вычислений с мемоизацией."""

from __future__ import annotations

import re
from collections.abc import Callable
from random import Random

from app.modules.assessment.families._lib import names
from app.modules.assessment.families._lib.contract import AnswerSpec, CodeBlock, InputHint, Reject, Variant
from app.modules.assessment.families._lib.miniprog import ProgramError, run_source
from app.modules.assessment.families.registry import family_meta

META = family_meta(
    "code.trace_recursion",
    version=1,
    feature_bounds={
        1: {"code_lines": (5, 5), "trace_steps": (6, 40), "nesting_depth": (1, 1), "concepts": (1, 1),
            "answer_abs": (2, 400), "trap": (1, 1)},
        2: {"code_lines": (9, 9), "trace_steps": (10, 80), "nesting_depth": (2, 2), "concepts": (2, 2),
            "answer_abs": (4, 60), "trap": (1, 1)},
        3: {"code_lines": (15, 15), "trace_steps": (10, 80), "nesting_depth": (2, 2), "concepts": (3, 3),
            "answer_abs": (4, 60), "trap": (1, 1)},
    },
)  # fmt: skip

#: Пары рекурсивных вызовов: (текст аргумента, функция аргумента).
CALLS: list[tuple[tuple[str, Callable[[int], int]], tuple[str, Callable[[int], int]]]] = [
    (("n - 1", lambda n: n - 1), ("n - 2", lambda n: n - 2)),
    (("n - 1", lambda n: n - 1), ("n - 3", lambda n: n - 3)),
    (("n - 2", lambda n: n - 2), ("n - 3", lambda n: n - 3)),
    (("n // 2", lambda n: n // 2), ("n - 1", lambda n: n - 1)),
    (("n - 1", lambda n: n - 1), ("n // 2", lambda n: n // 2)),
    (("n - 1", lambda n: n - 1), ("n - 4", lambda n: n - 4)),
    (("n - 2", lambda n: n - 2), ("n // 2", lambda n: n // 2)),
    (("n - 1", lambda n: n - 1), ("n - 1", lambda n: n - 1)),
]


def _rename(src: str, rng: Random) -> str:
    """Имена функции, параметра и счётчика по `rng`: меняют текст, но не сложность (приложение A, §2.1)."""
    func = names.pick(rng, names.FUNC_NAMES)
    param = names.pick(rng, ("n", "k", "m", "t", "size"))
    counter = names.pick(rng, ("calls", "steps", "visits", "hits"))
    out = re.sub(r"\bn\b", "\x00", src)
    out = re.sub(r"\bf\b", func, out)
    out = re.sub(r"\bcalls\b", counter, out)
    return out.replace("\x00", param)


def _calls(children: tuple, base: int, n: int) -> tuple[int, int]:
    """Число вызовов без мемоизации и число из них, обработанных базой (листьев)."""
    if n < base:
        return 1, 1
    total, leaves = 1, 0
    for _, step in children:
        t, leaf = _calls(children, base, step(n))
        total += t
        leaves += leaf
    return total, leaves


def _memo_calls(children: tuple, base: int, n: int, seen: set[int]) -> None:
    if n in seen:
        return
    seen.add(n)
    if n >= base:
        for _, step in children:
            _memo_calls(children, base, step(n), seen)


def _level1(rng: Random) -> tuple[str, Callable[[str | None], int], int]:
    """Линейная рекурсия: `f(n) = a·f(n - s) + b` до базы."""
    base = rng.randint(0, 2)
    c = rng.randint(1, 3)
    step = rng.randint(1, 2)
    form = rng.choice(["add", "double", "plus_n"])
    k = rng.randint(1, 4)
    arg = base + step * rng.randint(2, 5) + rng.randint(0, step - 1)
    tail = {"add": f"f(n - {step}) + {k}", "double": f"2 * f(n - {step}) + {k}", "plus_n": f"f(n - {step}) + n"}[form]
    src = f"def f(n):\n    if n <= {base}:\n        return {c}\n    return {tail}\nprint(f({arg}))"

    def model(flag: str | None) -> int:
        def f(n: int) -> int:
            if n <= base:
                return 0 if flag == "miss_base_case" else c
            rest = f(n - step)
            return {"add": rest + k, "double": 2 * rest + k, "plus_n": rest + n}[form]

        return f(arg)

    return src, model, 1


def _level2(rng: Random) -> tuple[str, Callable[[str | None], int], int]:
    """Ветвящаяся рекурсия: сколько раз вызвана функция."""
    (t1, _), (t2, _) = children = rng.choice(CALLS)
    base = rng.randint(2, 3)
    arg = rng.randint(4, 8)
    src = (
        f"calls = 0\ndef f(n):\n    global calls\n    calls += 1\n    if n < {base}:\n        return n\n"
        f"    return f({t1}) + f({t2})\nf({arg})\nprint(calls)"
    )

    def model(flag: str | None) -> int:
        total, leaves = _calls(children, base, arg)
        return total - leaves if flag == "miss_base_case" else total

    return src, model, 2


def _level3(rng: Random) -> tuple[str, Callable[[str | None], int], int]:
    """Рекурсия с мемоизацией: сколько раз тело функции выполнено по-настоящему."""
    (t1, _), (t2, _) = children = rng.choice(CALLS)
    base = rng.randint(2, 3)
    arg = rng.randint(5, 9)
    src = (
        f"calls = 0\nmemo = {{}}\ndef f(n):\n    global calls\n    if n in memo:\n        return memo[n]\n"
        f"    calls += 1\n    if n < {base}:\n        result = n\n    else:\n"
        f"        result = f({t1}) + f({t2})\n    memo[n] = result\n    return result\nf({arg})\nprint(calls)"
    )

    def model(flag: str | None) -> int:
        if flag == "count_without_memo":
            return _calls(children, base, arg)[0]
        seen: set[int] = set()
        _memo_calls(children, base, arg, seen)
        return len(seen)

    return src, model, 3


def generate(level: int, seed: int) -> Variant:
    """Вариант: рекурсивная функция; вопрос — значение или число вызовов (целое число).

    Уровень 1 — линейная рекурсия, спрашивается значение. Уровень 2 — ветвящаяся, спрашивается число вызовов
    (глобальный счётчик). Уровень 3 — то же с мемоизацией: число вызовов, выполнивших тело. Ответ — модель на
    Python отдельно от текста программы. Модели ошибок: `miss_base_case` (на уровне 1 база вносит 0, на уровне 2
    вызовы-листья не считаются) и `count_without_memo` (уровень 3: счёт без кэша). Вариант, где главная ошибка
    уровня не меняет ответ, отбрасывается; ответ однозначен: программа детерминирована.
    """
    rng = Random(seed)
    if level == 1:
        src, model, depth = _level1(rng)
        flags, main = ["miss_base_case"], "miss_base_case"
    elif level == 2:
        src, model, depth = _level2(rng)
        flags, main = ["miss_base_case"], "miss_base_case"
    elif level == 3:
        src, model, depth = _level3(rng)
        flags, main = ["count_without_memo"], "count_without_memo"
    else:
        raise ValueError(f"нет уровня {level}")
    src = _rename(src, rng)
    answer = model(None)
    wrong = {flag: model(flag) for flag in flags if model(flag) != answer}
    if main not in wrong:
        raise Reject("misconception_equals_answer")
    if answer < 4:
        raise Reject("trivial_answer")
    try:
        steps = run_source(src).steps
    except ProgramError as exc:
        raise Reject("program_error") from exc
    if steps > 80:
        raise Reject("too_long")
    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt="Что напечатает программа? Ответ — целое число.",
        code=CodeBlock(language="python", text=src),
        input=InputHint(placeholder="целое число", max_length=8),
        answer=AnswerSpec.numeric(answer),
        misconception_answers=wrong,
        features={
            "code_lines": src.count("\n") + 1,
            "trace_steps": steps,
            "nesting_depth": 1 if level == 1 else 2,
            "concepts": depth,
            "answer_abs": abs(answer),
            "trap": 1,
        },
        explanation=f"Модель программы даёт {answer}. Ответы моделей ошибок: {wrong}.",
    )


def selfcheck(v: Variant) -> list[str]:
    """Перепроверка: исполнение отрендеренного текста в пустом пространстве имён даёт ответ модели (§2.5)."""
    assert v.code is not None
    problems = []
    try:
        if run_source(v.code.text).printed != str(v.answer.value):
            problems.append("исполнение текста программы расходится с ответом модели")
    except ProgramError as exc:
        problems.append(f"программа не исполняется: {exc}")
    if v.code.text.count("\n") + 1 != v.features["code_lines"]:
        problems.append("признак code_lines не равен числу строк кода")
    return problems


def oracle_check(v: Variant) -> list[str]:
    """Оракул CPython: тот же текст исполняется обычным `exec` с полными встроенными функциями."""
    import contextlib
    import io

    assert v.code is not None
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exec(v.code.text, {})
    printed = buffer.getvalue().strip()
    return [] if printed == str(v.answer.value) else [f"CPython напечатал {printed}, ключ {v.answer.value}"]
