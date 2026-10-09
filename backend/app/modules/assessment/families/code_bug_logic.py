"""Семейство «Поиск логической ошибки»: в эталоне испорчена одна строка мутацией логики (приложение A, §3.1)."""

from __future__ import annotations

import itertools
from random import Random

from app.modules.assessment.families._lib import names
from app.modules.assessment.families._lib.contract import AnswerSpec, CodeBlock, Reject, Variant
from app.modules.assessment.families._lib.miniprog import (
    BugTemplate,
    assemble_bug,
    bug_explanation,
    bug_misconceptions,
    bug_prompt,
    check_bug_variant,
    oracle_bug,
    parse_bug,
)
from app.modules.assessment.families.registry import family_meta

META = family_meta(
    "code.bug_logic",
    version=2,
    feature_bounds={
        1: {"code_lines": (8, 17), "options_count": (8, 17), "trap": (0, 0)},
        2: {"code_lines": (8, 17), "options_count": (8, 17), "trap": (0, 1)},
        3: {"code_lines": (8, 17), "options_count": (8, 17), "trap": (1, 1)},
    },
    # Для выбора строки реестр моделей ошибок не называет: кандидат указывает последний `return` или строку рядом.
    misconceptions=("blame_return_line", "blame_neighbor_line"),
)


def _range_args(rng: Random) -> tuple[list[int], int, int]:
    lo = rng.randint(-2, 4)
    return [rng.randint(-4, 12) for _ in range(rng.randint(6, 8))], lo, lo + rng.randint(2, 6)


def _run_args(rng: Random) -> tuple[list[int]]:
    return ([rng.randint(1, 3) for _ in range(rng.randint(7, 10))],)


def _mean_args(rng: Random) -> tuple[list[int]]:
    return ([rng.randint(-4, 9) for _ in range(rng.randint(5, 8))],)


def _negative_args(rng: Random) -> tuple[list[int]]:
    return ([rng.randint(-3, 9) for _ in range(rng.randint(6, 8))],)


def _first_negative(a: list[int]) -> int:
    return next((i for i, x in enumerate(a) if x < 0), -1)


def _longest_run(a: list[int]) -> int:
    return max(len(list(group)) for _, group in itertools.groupby(a))


def _mean_positive(a: list[int]) -> int:
    positive = [x for x in a if x > 0]
    return sum(positive) // len(positive) if positive else 0


def _percent(a: list[int], lo: int, hi: int) -> int:
    good = sum(1 for x in a if lo <= x <= hi)
    return good * 100 // len(a)


TEMPLATES: dict[str, BugTemplate] = {
    "clipped_sum": BugTemplate(
        "clipped_sum",
        (
            "def $F($A, lo, hi):",
            "    total = 0",
            "    for x in $A:",
            "        if x < lo:",
            "            continue",
            "        if x > hi:",
            "            continue",
            "        total += x",
            "    return total",
        ),
        ((1, "    total = 1"), (4, "            break"), (6, "            break"), (5, "        if x < hi:"),
         (7, "        total -= x")),
        _range_args,
        lambda a, lo, hi: sum(x for x in a if lo <= x <= hi),
    ),
    "percent": BugTemplate(
        "percent",
        (
            "def $F($A, lo, hi):",
            "    good = 0",
            "    bad = 0",
            "    for x in $A:",
            "        if lo <= x and x <= hi:",
            "            good += 1",
            "        else:",
            "            bad += 1",
            "    if good + bad == 0:",
            "        return 0",
            "    return good * 100 // (good + bad)",
        ),
        ((4, "        if lo <= x or x <= hi:"), (5, "            good -= 1"), (7, "            bad -= 1"),
         (10, "    return bad * 100 // (good + bad)"), (4, "        if lo <= x and x < hi:")),
        _range_args,
        _percent,
    ),
    "first_negative": BugTemplate(
        "first_negative",
        (
            "def $F($A):",
            "    idx = -1",
            "    for i in range(len($A)):",
            "        if $A[i] < 0:",
            "            idx = i",
            "            break",
            "    return idx",
            "    # индекс первого отрицательного или -1",
        ),
        ((1, "    idx = 0"), (2, "    for i in range(1, len($A)):"), (3, "        if $A[i] <= 0:"),
         (5, "            pass")),
        _negative_args,
        _first_negative,
    ),
    "longest_run": BugTemplate(
        "longest_run",
        (
            "def $F($A):",
            "    best = 0",
            "    cur = 0",
            "    prev = None",
            "    for x in $A:",
            "        if x == prev:",
            "            cur += 1",
            "        else:",
            "            cur = 1",
            "        if cur > best:",
            "            best = cur",
            "        prev = x",
            "    return best",
        ),
        ((8, "            cur = 0"), (9, "        if cur < best:"), (10, "            best = 1"),
         (11, "        prev = cur"), (5, "        if x != prev:")),
        _run_args,
        _longest_run,
    ),
    "mean_positive": BugTemplate(
        "mean_positive",
        (
            "def $F($A):",
            "    total = 0",
            "    count = 0",
            "    for x in $A:",
            "        if x > 0:",
            "            total += x",
            "            count += 1",
            "    if count == 0:",
            "        return 0",
            "    return total // count",
        ),
        ((1, "    total = 1"), (2, "    count = 1"), (4, "        if x < 0:"), (5, "            total -= x"),
         (6, "            count = 1"), (9, "    return total // len($A)"), (7, "    if count == 1:")),
        _mean_args,
        _mean_positive,
    ),
}  # fmt: skip

DESCRIPTIONS = {
    "clipped_sum": "Функция должна вернуть сумму элементов списка, лежащих в отрезке от lo до hi включительно.",
    "percent": "Функция должна вернуть, сколько процентов элементов списка лежит в отрезке от lo до hi "
    "включительно (целая часть).",
    "first_negative": "Функция должна вернуть индекс первого отрицательного элемента или -1, если таких нет.",
    "longest_run": "Функция должна вернуть длину самой длинной серии подряд идущих одинаковых элементов.",
    "mean_positive": "Функция должна вернуть целую часть среднего арифметического положительных элементов "
    "(0, если их нет).",
}
LEVEL_RULES = {
    1: (("clipped_sum", "mean_positive"), (0.4, 1.0)),
    2: (("clipped_sum", "percent", "mean_positive", "longest_run", "first_negative"), (0.05, 1.0)),
    # `longest_run` на уровне 3 не участвует: ни одна его мутация не даёт редкой ошибки (доля неверных входов
    # 66–100 %), и каждый выпавший на него сид уходил в брак `rarity`. С ним брак уровня доходил до 52 % при
    # пороге 50 %, то есть приёмка семейства зависела от значения `ASSESSMENT_SECRET`.
    3: (("first_negative", "mean_positive", "percent"), (0.02, 0.35)),
}


def generate(level: int, seed: int) -> Variant:
    """Вариант: эталон с одной строкой, испорченной мутацией логики; вопрос — номер этой строки.

    Мутации: `and` на `or`, `+` на `-`, неверная начальная инициализация, сброс счётчика внутри цикла, `break`
    вместо `continue`, перепутанные переменные. Эталоны: сумма в отрезке, доля в отрезке, самая длинная серия,
    среднее положительных. Уровень 1 — короткие функции и ошибка, видная на большинстве входов; уровень 3 —
    ошибка видна на редком входе (доля входов не больше 35 %, признак `trap`). Условие содержит вызов, на котором
    мутант неверен, и ожидаемое значение из спецификации. Ответ однозначен: мутант отличается от эталона ровно
    одной строкой (самопроверка возвращает эталонную строку и сверяет функцию со спецификацией на батарее).
    Модели ошибок: `blame_return_line` (указан последний `return`) и `blame_neighbor_line` (соседняя строка).
    """
    if level not in LEVEL_RULES:
        raise ValueError(f"нет уровня {level}")
    rng = Random(seed)
    keys, share_range = LEVEL_RULES[level]
    template = TEMPLATES[rng.choice(keys)]
    fname = names.pick(rng, names.FUNC_NAMES)
    first, second = rng.sample(("data", "nums", "items", "values", "xs", "ys"), 2)
    case = assemble_bug(rng, template, seed, fname, first, second, share_range=share_range)
    lines = case.source.split("\n")
    wrong = bug_misconceptions(lines, case.line, ["blame_return_line", "blame_neighbor_line"])
    if not wrong:
        raise Reject("no_misconception")
    rare = case.share <= 0.35
    if level == 1 and rare:
        raise Reject("rarity")
    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt=bug_prompt(DESCRIPTIONS[template.key], case),
        code=CodeBlock(language="python", text=case.source),
        answer=AnswerSpec.line(case.line),
        misconception_answers=wrong,
        features={"code_lines": len(lines), "options_count": len(lines), "trap": 1 if rare else 0},
        explanation=bug_explanation(case),
    )


def selfcheck(v: Variant) -> list[str]:
    """Перепроверка (§2.5): возврат эталонной строки чинит функцию, мутант неверен, ответ — одна строка."""
    assert v.code is not None
    key, fname, line, ref, _args, _got, _expected = parse_bug(v.prompt, v.explanation)
    problems = check_bug_variant(TEMPLATES, v.code.text, line, ref, key, v.seed, fname)
    if v.answer.lines != (line,):
        problems.append("ответ не равен номеру испорченной строки из разбора")
    return problems


def oracle_check(v: Variant) -> list[str]:
    """Оракул CPython: настоящий `exec` проверяет пример из условия и исправленную функцию на батарее входов."""
    return oracle_bug(TEMPLATES, v)
