"""Семейство «Поиск ошибки в границах»: в эталоне испорчена одна строка мутацией границы (приложение A, §3.1)."""

from __future__ import annotations

import bisect
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
    "code.bug_boundary",
    version=2,
    feature_bounds={
        1: {"code_lines": (8, 17), "options_count": (8, 17), "trap": (0, 0)},
        2: {"code_lines": (8, 17), "options_count": (8, 17), "trap": (0, 1)},
        3: {"code_lines": (8, 17), "options_count": (8, 17), "trap": (1, 1)},
    },
    # Для выбора строки реестр моделей ошибок не называет: кандидат, не найдя ошибку, указывает заголовок цикла
    # или строку рядом с испорченной.
    misconceptions=("blame_loop_header", "blame_neighbor_line"),
)


def _window_args(rng: Random) -> tuple[list[int], int]:
    size = rng.randint(5, 8)
    return [rng.randint(1, 9) for _ in range(size)], rng.randint(2, 4)


def _search_args(rng: Random) -> tuple[list[int], int]:
    data = sorted(rng.sample(range(1, 40), rng.randint(5, 9)))
    return data, rng.choice(data) if rng.random() < 0.7 else rng.randint(1, 40)


def _insert_args(rng: Random) -> tuple[list[int], int]:
    return sorted(rng.sample(range(1, 40), rng.randint(5, 9))), rng.randint(0, 41)


def _merge_args(rng: Random) -> tuple[list[int], list[int]]:
    return (
        sorted(rng.randint(1, 20) for _ in range(rng.randint(2, 5))),
        sorted(rng.randint(1, 20) for _ in range(rng.randint(2, 5))),
    )


def _chunk_args(rng: Random) -> tuple[list[int], int]:
    return [rng.randint(1, 9) for _ in range(rng.randint(5, 9))], rng.randint(2, 4)


TEMPLATES: dict[str, BugTemplate] = {
    "window": BugTemplate(
        "window",
        (
            "def $F($A, k):",
            "    best = None",
            "    for i in range(len($A) - k + 1):",
            "        s = 0",
            "        for j in range(i, i + k):",
            "            s += $A[j]",
            "        if best is None or s > best:",
            "            best = s",
            "    return best",
        ),
        ((2, "    for i in range(len($A) - k):"), (2, "    for i in range(1, len($A) - k + 1):"),
         (4, "        for j in range(i, i + k - 1):"),
         (4, "        for j in range(i + 1, i + k):")),
        _window_args,
        lambda a, k: max(sum(a[i : i + k]) for i in range(len(a) - k + 1)),
    ),
    "search": BugTemplate(
        "search",
        (
            "def $F($A, x):",
            "    lo = 0",
            "    hi = len($A) - 1",
            "    while lo <= hi:",
            "        mid = (lo + hi) // 2",
            "        if $A[mid] == x:",
            "            return mid",
            "        if $A[mid] < x:",
            "            lo = mid + 1",
            "        else:",
            "            hi = mid - 1",
            "    return -1",
        ),
        ((1, "    lo = 1"), (2, "    hi = len($A) - 2"), (3, "    while lo < hi:"), (10, "            hi = mid - 2")),
        _search_args,
        lambda a, x: a.index(x) if x in a else -1,
    ),
    "insert_pos": BugTemplate(
        "insert_pos",
        (
            "def $F($A, x):",
            "    lo = 0",
            "    hi = len($A)",
            "    while lo < hi:",
            "        mid = (lo + hi) // 2",
            "        if $A[mid] < x:",
            "            lo = mid + 1",
            "        else:",
            "            hi = mid",
            "    return lo",
        ),
        ((1, "    lo = 1"), (2, "    hi = len($A) - 1"), (6, "            lo = mid + 2"),
         (8, "            hi = mid - 1")),
        _insert_args,
        lambda a, x: bisect.bisect_left(a, x),
    ),
    "merge": BugTemplate(
        "merge",
        (
            "def $F($A, $B):",
            "    out = []",
            "    i = 0",
            "    j = 0",
            "    while i < len($A) and j < len($B):",
            "        if $A[i] <= $B[j]:",
            "            out.append($A[i])",
            "            i += 1",
            "        else:",
            "            out.append($B[j])",
            "            j += 1",
            "    out.extend($A[i:])",
            "    out.extend($B[j:])",
            "    return out",
        ),
        ((3, "    j = 1"), (4, "    while i < len($A) - 1 and j < len($B):"), (11, "    out.extend($A[i + 1:])"),
         (12, "    out.extend($B[j + 1:])")),
        _merge_args,
        lambda a, b: sorted(a + b),
    ),
    "chunks": BugTemplate(
        "chunks",
        (
            "def $F($A, n):",
            "    out = []",
            "    i = 0",
            "    while i < len($A):",
            "        s = 0",
            "        for x in $A[i:i + n]:",
            "            s += x",
            "        out.append(s)",
            "        i += n",
            "    return out",
        ),
        ((2, "    i = 1"), (3, "    while i < len($A) - 1:"), (5, "        for x in $A[i:i + n - 1]:"),
         (8, "        i += n - 1")),
        _chunk_args,
        lambda a, n: [sum(a[i : i + n]) for i in range(0, len(a), n)],
    ),
}  # fmt: skip

DESCRIPTIONS = {
    "window": "Функция должна вернуть наибольшую сумму k подряд идущих элементов списка.",
    "search": "Функция должна вернуть индекс числа x в отсортированном списке или -1, если числа нет.",
    "insert_pos": "Функция должна вернуть позицию, на которую нужно вставить x в отсортированный список, "
    "чтобы порядок сохранился (слева от равных).",
    "merge": "Функция должна слить два отсортированных списка в один отсортированный.",
    "chunks": "Функция должна разбить список на куски по n элементов и вернуть сумму каждого куска.",
}
#: Какие шаблоны допустимы на уровне и в каком диапазоне доли входов, на которых ошибка видна.
LEVEL_RULES = {
    1: (("chunks", "window"), (0.4, 1.0)),
    2: (("window", "search", "insert_pos", "merge", "chunks"), (0.05, 1.0)),
    3: (("search", "insert_pos", "window"), (0.02, 0.35)),
}


def generate(level: int, seed: int) -> Variant:
    """Вариант: эталон с одной строкой, испорченной мутацией границы; вопрос — номер этой строки.

    Эталоны: сумма окна, бинарный поиск, слияние, разбиение на куски; мутации: `<` вместо `<=`, `n` вместо `n - 1`,
    неверный начальный индекс. Уровень 1 — короткие функции и ошибка, видная на большинстве входов; уровень 3 —
    длинные функции и редкий вход (доля входов с ошибкой не больше 35 %, признак `trap`). Условие содержит
    вызов, на котором мутант неверен, и ожидаемое значение из спецификации. Ответ — номер испорченной строки:
    мутант отличается от эталона ровно одной строкой, поэтому ответ однозначен (самопроверка возвращает эталонную
    строку и сверяет функцию со спецификацией на батарее входов). Модели ошибок: `blame_loop_header` (указан
    заголовок цикла) и `blame_neighbor_line` (указана соседняя строка).
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
    wrong = bug_misconceptions(lines, case.line, ["blame_loop_header", "blame_neighbor_line"])
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
