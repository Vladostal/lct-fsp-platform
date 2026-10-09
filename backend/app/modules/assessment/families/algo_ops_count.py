"""Семейство «Число выполнений строки»: сколько раз выполнится оператор счётчика при заданном n."""

from __future__ import annotations

import contextlib
import io
from collections.abc import Callable
from random import Random

from app.modules.assessment.families._lib import names
from app.modules.assessment.families._lib.contract import AnswerSpec, CodeBlock, InputHint, Reject, Variant
from app.modules.assessment.families._lib.miniprog import ProgramError, run_source
from app.modules.assessment.families.registry import family_meta

META = family_meta(
    "algo.ops_count",
    version=1,
    feature_bounds={
        1: {"code_lines": (6, 7), "nesting_depth": (2, 3), "concepts": (1, 2), "answer_abs": (4, 400)},
        2: {"code_lines": (6, 7), "nesting_depth": (2, 2), "concepts": (2, 3), "answer_abs": (4, 400),
            "trap": (1, 1)},
        3: {"code_lines": (5, 8), "nesting_depth": (1, 2), "concepts": (2, 3), "answer_abs": (3, 3000),
            "trap": (1, 1)},
    },
    # Реестр знает только `rectangular_instead_of_triangular` (уровень 2); для уровней 1 и 3 добавлены свои.
    misconceptions=("rectangular_instead_of_triangular", "off_by_one_range", "log_as_linear", "ignore_early_exit"),
)  # fmt: skip

Model = Callable[[str | None], int]


def _ranges_level1(rng: Random, n: int) -> tuple[list[tuple[str, tuple[int, int, int]]], int]:
    """Две-три независимые границы: (текст range, (начало, конец, шаг))."""
    c = rng.randint(1, 3)
    options = [
        ("n", (0, n, 1)),
        (f"n - {c}", (0, n - c, 1)),
        (f"{c}, n", (c, n, 1)),
        (f"{c}, n + {c}", (c, n + c, 1)),
        ("n // 2", (0, n // 2, 1)),
        (f"0, n, {rng.randint(2, 3)}", (0, n, 0)),
    ]
    picks = []
    for _ in range(rng.randint(2, 3)):
        text, spec = rng.choice(options)
        if spec[2] == 0:
            step = int(text.rsplit(" ", 1)[1])
            spec = (0, n, step)
        picks.append((text, spec))
    return picks, len(picks)


def _level1(rng: Random, n: int, counter: str, loop_vars: list[str]) -> tuple[str, Model, int, int]:
    picks, depth = _ranges_level1(rng, n)
    if depth == 3:
        # Третий цикл — малая константная граница, чтобы ответ оставался вычислимым в уме.
        small = rng.randint(2, 3)
        picks[2] = (str(small), (0, small, 1))
    lines = [f"n = {n}", f"{counter} = 0"]
    for level, (text, _) in enumerate(picks):
        lines.append("    " * level + f"for {loop_vars[level]} in range({text}):")
    lines.append("    " * depth + f"{counter} += 1")
    lines.append(f"print({counter})")

    def model(flag: str | None) -> int:
        total = 1
        for _, (start, stop, step) in picks:
            total *= len(range(start, stop + (1 if flag == "off_by_one_range" else 0), step))
        return total

    return "\n".join(lines), model, depth, 1


def _level2(rng: Random, n: int, counter: str, loop_vars: list[str]) -> tuple[str, Model, int, int]:
    """Треугольные циклы: внутренняя граница зависит от внешней переменной."""
    i, j = loop_vars[0], loop_vars[1]
    outer_start = rng.choice([0, 1])
    outer_step = rng.choice([1, 1, 2])
    outer_text = (
        "n" if outer_start == 0 and outer_step == 1 else
        f"{outer_start}, n" if outer_step == 1 else f"{outer_start}, n, {outer_step}"
    )  # fmt: skip
    kinds = [
        (f"{i}", lambda x: range(x)),
        (f"{i} + 1", lambda x: range(x + 1)),
        (f"{i}, n", lambda x: range(x, n)),
        (f"{i} + 1, n", lambda x: range(x + 1, n)),
        (f"n - {i}", lambda x: range(n - x)),
    ]
    step = rng.choice([1, 1, 2])
    text, inner = rng.choice(kinds)
    if step == 2 and ", n" in text:
        text += ", 2"
        base = inner
        inner = lambda x, base=base: range(base(x).start, base(x).stop, 2)  # type: ignore[misc]  # noqa: E731
    outer = range(outer_start, n, outer_step)
    src = (
        f"n = {n}\n{counter} = 0\nfor {i} in range({outer_text}):\n    for {j} in range({text}):\n"
        f"        {counter} += 1\nprint({counter})"
    )

    def model(flag: str | None) -> int:
        if flag == "rectangular_instead_of_triangular":
            return len(outer) * max(len(inner(x)) for x in outer)
        return sum(len(inner(x)) for x in outer)

    return src, model, 2, 2


def _level3(rng: Random, counter: str, loop_vars: list[str]) -> tuple[str, Model, int, int, int]:
    """Логарифмические циклы и циклы с ранним выходом; возвращает ещё значение n."""
    i, j = loop_vars[0], loop_vars[1]
    kind = rng.choice(["double", "halve", "sqrt_exit", "log_in_loop", "exit_third"])
    c = rng.choice([2, 2, 3])
    if kind == "double":
        n = rng.randint(20, 900)
        src = f"n = {n}\n{counter} = 0\n{i} = 1\nwhile {i} < n:\n    {counter} += 1\n    {i} *= {c}\nprint({counter})"

        def model(flag: str | None) -> int:
            if flag == "log_as_linear":
                return n - 1
            steps, x = 0, 1
            while x < n:
                steps, x = steps + 1, x * c
            return steps

        return src, model, 1, 2, n
    if kind == "halve":
        n = rng.randint(30, 1000)
        src = f"n = {n}\n{counter} = 0\n{i} = n\nwhile {i} > 1:\n    {counter} += 1\n    {i} //= {c}\nprint({counter})"

        def model(flag: str | None) -> int:
            if flag == "log_as_linear":
                return n - 1
            steps, x = 0, n
            while x > 1:
                steps, x = steps + 1, x // c
            return steps

        return src, model, 1, 2, n
    if kind == "sqrt_exit":
        n = rng.randint(30, 400)
        cmp_ = rng.choice([">", ">="])
        src = (
            f"n = {n}\n{counter} = 0\nfor {i} in range(n):\n    if {i} * {i} {cmp_} n:\n        break\n"
            f"    {counter} += 1\nprint({counter})"
        )

        def model(flag: str | None) -> int:
            if flag == "ignore_early_exit":
                return n
            steps = 0
            for x in range(n):
                if (x * x > n) if cmp_ == ">" else (x * x >= n):
                    break
                steps += 1
            return steps

        return src, model, 2, 3, n
    if kind == "exit_third":
        n = rng.randint(20, 300)
        k = rng.choice([3, 4, 5])
        src = (
            f"n = {n}\n{counter} = 0\nfor {i} in range(n):\n    {counter} += 1\n    if {i} * {k} > n:\n        break\n"
            f"print({counter})"
        )

        def model(flag: str | None) -> int:
            if flag == "ignore_early_exit":
                return n
            steps = 0
            for x in range(n):
                steps += 1
                if x * k > n:
                    break
            return steps

        return src, model, 2, 3, n
    n = rng.randint(20, 300)
    m = rng.randint(3, 6)
    src = (
        f"n = {n}\n{counter} = 0\nfor {i} in range({m}):\n    {j} = 1\n    while {j} < n:\n        {counter} += 1\n"
        f"        {j} *= 2\nprint({counter})"
    )

    def model(flag: str | None) -> int:  # type: ignore[no-redef]
        inner = 0
        x = 1
        while x < n:
            inner, x = inner + 1, x * 2
        return m * ((n - 1) if flag == "log_as_linear" else inner)

    return src, model, 2, 2, n


def generate(level: int, seed: int) -> Variant:
    """Вариант: «сколько раз выполнится строка со счётчиком при заданном n» (целое число).

    Уровень 1 — прямоугольные циклы с границами `n`, `n - c`, `c, n`, шагом (две-три независимые границы).
    Уровень 2 — треугольные циклы: внутренняя граница зависит от внешней переменной, возможен шаг. Уровень 3 —
    логарифмические циклы (удвоение, деление), цикл по `m`, внутри которого логарифм, и ранний выход по `break`.
    Ответ вычисляет модель — прямые циклы на Python отдельно от текста программы. Модели ошибок:
    `off_by_one_range` (граница включена), `rectangular_instead_of_triangular` (внутренняя граница берётся
    наибольшей), `log_as_linear` (логарифмический цикл считается линейным), `ignore_early_exit` (выход игнорируется).
    Вариант, где главная ошибка уровня не меняет ответ, отбрасывается; ответ однозначен: программа детерминирована.
    """
    rng = Random(seed)
    counter = names.pick(rng, ("count", "ops", "hits", "total"))
    # Только i, j, k: имена n и m заняты параметром и константами программы.
    loop_vars = rng.sample(list(names.LOOP_VARS[:3]), 3)
    if level == 1:
        n = rng.randint(5, 9)
        src, model, depth, concepts = _level1(rng, n, counter, loop_vars)
        main, trap = "off_by_one_range", None
    elif level == 2:
        n = rng.randint(6, 12)
        src, model, depth, concepts = _level2(rng, n, counter, loop_vars)
        main, trap = "rectangular_instead_of_triangular", 1
    elif level == 3:
        src, model, depth, concepts, n = _level3(rng, counter, loop_vars)
        main, trap = ("log_as_linear" if "while" in src else "ignore_early_exit"), 1
    else:
        raise ValueError(f"нет уровня {level}")
    answer = model(None)
    bad = model(main)
    if bad == answer:
        raise Reject("misconception_equals_answer")
    if answer < 4:
        raise Reject("trivial_answer")
    features = {
        "code_lines": src.count("\n") + 1,
        "nesting_depth": depth,
        "concepts": concepts,
        "answer_abs": answer,
    }
    if trap is not None:
        features["trap"] = trap
    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt=f"Сколько раз выполнится строка «{counter} += 1» при n = {n}? Ответ — целое число.",
        code=CodeBlock(language="python", text=src),
        input=InputHint(placeholder="целое число", max_length=8),
        answer=AnswerSpec.numeric(answer),
        misconception_answers={main: bad},
        features=features,
        explanation=f"Модель считает {answer} выполнений. Ответ модели ошибки {main}: {bad}.",
    )


def selfcheck(v: Variant) -> list[str]:
    """Перепроверка: исполнение текста под счётчиком строк даёт ответ модели (§2.5)."""
    assert v.code is not None
    problems = []
    try:
        result = run_source(v.code.text)
        if result.printed != str(v.answer.value):
            problems.append("исполнение текста программы расходится с ответом модели")
    except ProgramError as exc:
        problems.append(f"программа не исполняется: {exc}")
    if v.code.text.count("\n") + 1 != v.features["code_lines"]:
        problems.append("признак code_lines не равен числу строк кода")
    return problems


def oracle_check(v: Variant) -> list[str]:
    """Оракул CPython: тот же текст исполняется обычным `exec` с полными встроенными функциями."""
    assert v.code is not None
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exec(v.code.text, {})
    printed = buffer.getvalue().strip()
    return [] if printed == str(v.answer.value) else [f"CPython напечатал {printed}, ключ {v.answer.value}"]
