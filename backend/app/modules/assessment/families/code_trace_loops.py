"""Семейство «Трассировка циклов»: что напечатает короткая программа с циклами (приложение A, §3.1)."""

from __future__ import annotations

from collections.abc import Callable
from random import Random

from app.modules.assessment.families._lib import names
from app.modules.assessment.families._lib.contract import AnswerSpec, CodeBlock, InputHint, Reject, Variant
from app.modules.assessment.families._lib.miniprog import ProgramError, run_source
from app.modules.assessment.families.registry import family_meta

META = family_meta(
    "code.trace_loops",
    version=1,
    feature_bounds={
        1: {"code_lines": (5, 5), "trace_steps": (10, 40), "nesting_depth": (1, 1), "concepts": (2, 3),
            "answer_abs": (2, 400), "trap": (1, 1)},
        2: {"code_lines": (8, 9), "trace_steps": (10, 80), "nesting_depth": (2, 2), "concepts": (4, 5),
            "answer_abs": (2, 400), "trap": (1, 1)},
        3: {"code_lines": (5, 8), "trace_steps": (10, 80), "nesting_depth": (1, 2), "concepts": (3, 5),
            "answer_abs": (2, 400), "trap": (1, 1)},
    },
)  # fmt: skip

Model = Callable[[str | None], int]


def _level1(rng: Random, total: str, i: str) -> tuple[str, Model, int]:
    """Один цикл с условием: сумма или счёт по `range(a, b)`."""
    a = rng.randint(1, 5)
    b = a + rng.randint(6, 10)
    m = rng.randint(2, 4)
    kind = rng.choice(["eq", "ne", "gt"])
    if kind == "eq":
        # Остаток правой границы: условие выполняется на b, поэтому ошибка off_by_one меняет ответ.
        r = b % m
        text, test = f"{i} % {m} == {r}", lambda x: x % m == r
    elif kind == "ne":
        r = rng.randrange(m)
        text, test = f"{i} % {m} != {r}", lambda x: x % m != r
    else:
        t = rng.randint(a + 1, b - 2)
        text, test = f"{i} > {t}", lambda x: x > t
    weight = rng.choice(["i", "one", "mul"])
    c = rng.randint(2, 4)
    inc = {"i": i, "one": "1", "mul": f"{i} * {c}"}[weight]
    wfun = {"i": lambda x: x, "one": lambda x: 1, "mul": lambda x: x * c}[weight]
    src = f"{total} = 0\nfor {i} in range({a}, {b}):\n    if {text}:\n        {total} += {inc}\nprint({total})"

    def model(flag: str | None) -> int:
        stop = b + 1 if flag == "off_by_one" else b
        return sum(wfun(x) for x in range(a, stop) if test(x))

    return src, model, 3


def _level2(rng: Random, total: str, i: str, j: str) -> tuple[str, Model, int]:
    """Два вложенных цикла с `break` и `continue`."""
    a, c = rng.randint(1, 2), rng.randint(1, 2)
    big_a, big_c = a + rng.randint(3, 4), c + rng.randint(4, 6)
    k = rng.randint(0, 2)
    m, r = rng.randint(2, 4), 0
    r = rng.randrange(m)
    brk = rng.choice(["diag", "prod"])
    if brk == "diag":
        brk_text, brk_test = f"{j} > {i} + {k}", lambda x, y: y > x + k
    else:
        limit = rng.randint(6, 14)
        brk_text, brk_test = f"{i} * {j} > {limit}", lambda x, y: x * y > limit
    inc_kind = rng.choice(["one", "j", "i"])
    inc = {"one": "1", "j": j, "i": i}[inc_kind]
    inc_fn = {"one": lambda x, y: 1, "j": lambda x, y: y, "i": lambda x, y: x}[inc_kind]
    src = (
        f"{total} = 0\nfor {i} in range({a}, {big_a}):\n    for {j} in range({c}, {big_c}):\n"
        f"        if {brk_text}:\n            break\n        if ({i} + {j}) % {m} == {r}:\n            continue\n"
        f"        {total} += {inc}\nprint({total})"
    )

    def model(flag: str | None) -> int:
        out = 0
        upper_a = big_a + 1 if flag == "off_by_one" else big_a
        upper_c = big_c + 1 if flag == "off_by_one" else big_c
        for x in range(a, upper_a):
            for y in range(c, upper_c):
                if brk_test(x, y) and flag != "ignore_break":
                    break
                if (x + y) % m == r:
                    continue
                out += inc_fn(x, y)
        return out

    return src, model, 5


def _level3(rng: Random, total: str, i: str, j: str) -> tuple[str, Model, int, int]:
    """Зависимые границы и изменение списка по индексу; возвращает ещё глубину вложенности."""
    nums = names.pick(rng, names.LIST_VARS[:5])
    size = rng.randint(5, 6)
    data = [rng.randint(1, 9) for _ in range(size)]
    kind = rng.choice(["prefix", "pairs", "bubble"])
    lit = "[" + ", ".join(map(str, data)) + "]"
    if kind == "prefix":
        cmp_ = rng.choice([">", "<"])
        add = rng.randint(1, 3)
        src = (
            f"{nums} = {lit}\nfor {i} in range(1, len({nums})):\n    if {nums}[{i}] {cmp_} {nums}[{i} - 1]:\n"
            f"        {nums}[{i}] = {nums}[{i} - 1] + {add}\nprint(sum({nums}))"
        )

        def model(flag: str | None) -> int:
            a = list(data)
            stop = len(a) - 1 if flag == "off_by_one" else len(a)
            for x in range(1, stop):
                if (a[x] > a[x - 1]) if cmp_ == ">" else (a[x] < a[x - 1]):
                    a[x] = a[x - 1] + add
            return sum(a)

        return src, model, 1, 4
    if kind == "pairs":
        src = (
            f"{nums} = {lit}\n{total} = 0\nfor {i} in range(len({nums})):\n"
            f"    for {j} in range({i} + 1, len({nums})):\n"
            f"        if {nums}[{j}] - {nums}[{i}] > {total}:\n"
            f"            {total} = {nums}[{j}] - {nums}[{i}]\nprint({total})"
        )

        def model(flag: str | None) -> int:
            best = 0
            stop = len(data) - 1 if flag == "off_by_one" else len(data)
            for x in range(len(data)):
                for y in range(x + 1, stop):
                    best = max(best, data[y] - data[x])
            return best

        return src, model, 2, 5
    pos = rng.randint(1, size - 2)
    src = (
        f"{nums} = {lit}\nfor {i} in range(len({nums}) - 1):\n    if {nums}[{i}] > {nums}[{i} + 1]:\n"
        f"        {nums}[{i}], {nums}[{i} + 1] = {nums}[{i} + 1], {nums}[{i}]\nprint({nums}[{pos}] * 10 + {nums}[-1])"
    )

    def model(flag: str | None) -> int:
        a = list(data)
        stop = len(a) - 2 if flag == "off_by_one" else len(a) - 1
        for x in range(stop):
            if a[x] > a[x + 1]:
                a[x], a[x + 1] = a[x + 1], a[x]
        return a[pos] * 10 + a[-1]

    return src, model, 1, 4


def generate(level: int, seed: int) -> Variant:
    """Вариант: программа с циклами; вопрос — что она напечатает (целое число).

    Уровень 1 — один цикл `range(a, b)` с условием по остатку или порогу. Уровень 2 — два вложенных цикла с
    `break` и `continue`. Уровень 3 — зависимые границы (`range(i + 1, n)`) и изменение списка по индексу.
    Ответ вычисляет модель — функция на Python, написанная отдельно от текста программы. Модели ошибок:
    `off_by_one` (граница на единицу дальше; на уровне 3 — на единицу ближе, иначе индекс выйдет за список) и
    `ignore_break` (кандидат не замечает выход из цикла). Вариант, где главная ошибка уровня не меняет ответ,
    отбрасывается; ответ однозначен, потому что программа детерминирована и печатает одно целое число.
    """
    rng = Random(seed)
    total = names.pick(rng, names.NUM_VARS[:6])
    i, j = rng.sample(names.LOOP_VARS[:4], 2)
    if level == 1:
        src, model, concepts = _level1(rng, total, i)
        depth, flags, main = 1, ["off_by_one"], "off_by_one"
    elif level == 2:
        src, model, concepts = _level2(rng, total, i, j)
        depth, flags, main = 2, ["off_by_one", "ignore_break"], "ignore_break"
    elif level == 3:
        flags, main = ["off_by_one"], "off_by_one"
        # До трёх попыток с новыми данными: на коротком списке сдвиг границы часто не меняет ответ.
        for _ in range(3):
            src, model, depth, concepts = _level3(rng, total, i, j)
            if model(main) != model(None):
                break
    else:
        raise ValueError(f"нет уровня {level}")
    answer = model(None)
    wrong = {flag: model(flag) for flag in flags if model(flag) != answer}
    if main not in wrong:
        raise Reject("misconception_equals_answer")
    if answer < 2:
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
            "nesting_depth": depth,
            "concepts": concepts,
            "answer_abs": abs(answer),
            "trap": 1,
        },
        explanation=f"Модель программы даёт {answer}. Ответы моделей ошибок: {wrong}.",
    )


def _printed(v: Variant) -> str:
    assert v.code is not None
    return run_source(v.code.text).printed


def selfcheck(v: Variant) -> list[str]:
    """Перепроверка: исполнение отрендеренного текста в пустом пространстве имён даёт ответ модели (§2.5)."""
    assert v.code is not None
    problems = []
    try:
        if _printed(v) != str(v.answer.value):
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
