"""Семейство «Состояние массива при сортировке»: массив после k проходов, разбиения или k шагов пирамиды."""

from __future__ import annotations

import contextlib
import io
from collections.abc import Callable
from random import Random

from app.modules.assessment.families._lib import names
from app.modules.assessment.families._lib.contract import AnswerSpec, CodeBlock, InputHint, Reject, Variant
from app.modules.assessment.families._lib.miniprog import ProgramError, run_source, tokens
from app.modules.assessment.families.registry import family_meta

META = family_meta(
    "algo.sort_state",
    version=1,
    feature_bounds={
        1: {"code_lines": (10, 13), "concepts": (1, 1), "answer_abs": (1, 40), "trap": (1, 1)},
        2: {"code_lines": (10, 12), "concepts": (2, 2), "answer_abs": (1, 40), "trap": (1, 1)},
        3: {"code_lines": (25, 28), "concepts": (3, 3), "answer_abs": (1, 40), "trap": (1, 1)},
    },
)

BUBBLE = """def {f}(a, k):
    n = len(a)
    for p in range(k):
        for i in range(n - 1 - p):
            if a[i] > a[i + 1]:
                a[i], a[i + 1] = a[i + 1], a[i]
    return a"""
SELECTION = """def {f}(a, k):
    n = len(a)
    for p in range(k):
        m = p
        for i in range(p + 1, n):
            if a[i] < a[m]:
                m = i
        a[p], a[m] = a[m], a[p]
    return a"""
INSERTION = """def {f}(a, k):
    for p in range(1, k + 1):
        x = a[p]
        i = p - 1
        while i >= 0 and a[i] > x:
            a[i + 1] = a[i]
            i -= 1
        a[i + 1] = x
    return a"""
LOMUTO = """def {f}(a):
    pivot = a[-1]
    i = 0
    for j in range(len(a) - 1):
        if a[j] < pivot:
            a[i], a[j] = a[j], a[i]
            i += 1
    a[i], a[-1] = a[-1], a[i]
    return a"""
HEAP = """def sift(a, i, n):
    while True:
        big = i
        left, right = 2 * i + 1, 2 * i + 2
        if left < n and a[left] > a[big]:
            big = left
        if right < n and a[right] > a[big]:
            big = right
        if big == i:
            return
        a[i], a[big] = a[big], a[i]
        i = big


def {f}(a, k):
    n = len(a)
    for i in range(n // 2 - 1, -1, -1):
        sift(a, i, n)
    for step in range(k):
        n -= 1
        a[0], a[n] = a[n], a[0]
        sift(a, 0, n)
    return a"""


def _bubble(data: list[int], k: int) -> list[int]:
    a = list(data)
    for p in range(k):
        for i in range(len(a) - 1 - p):
            if a[i] > a[i + 1]:
                a[i], a[i + 1] = a[i + 1], a[i]
    return a


def _selection(data: list[int], k: int) -> list[int]:
    a = list(data)
    for p in range(k):
        m = a.index(min(a[p:]), p)
        a[p], a[m] = a[m], a[p]
    return a


def _insertion(data: list[int], k: int) -> list[int]:
    # k проходов вставки: префикс из k + 1 элемента отсортирован, хвост не тронут.
    return sorted(data[: k + 1]) + list(data[k + 1 :])


def _lomuto(data: list[int]) -> list[int]:
    a = list(data)
    pivot = a[-1]
    store = 0
    for j in range(len(a) - 1):
        if a[j] < pivot:
            a[store], a[j] = a[j], a[store]
            store += 1
    a[store], a[-1] = a[-1], a[store]
    return a


def _stable_partition(data: list[int]) -> list[int]:
    """Соседний алгоритм: разбиение с сохранением порядка вместо обменов."""
    pivot = data[-1]
    return [x for x in data[:-1] if x < pivot] + [pivot] + [x for x in data[:-1] if x > pivot]


def _heap_steps(data: list[int], k: int) -> list[int]:
    """Пирамидальная сортировка: построение max-кучи и k извлечений; рекурсивный спуск вместо цикла."""
    a = list(data)

    def sift(i: int, n: int) -> None:
        children = [c for c in (2 * i + 1, 2 * i + 2) if c < n]
        top = max([i, *children], key=lambda c: a[c])
        if top != i:
            a[i], a[top] = a[top], a[i]
            sift(top, n)

    for i in range(len(a) // 2 - 1, -1, -1):
        sift(i, len(a))
    end = len(a)
    for _ in range(k):
        end -= 1
        a[0], a[end] = a[end], a[0]
        sift(0, end)
    return a


def _selection_from_right(data: list[int], k: int) -> list[int]:
    """Соседний алгоритм: k проходов выбора, переносящих наибольшее в конец."""
    a = list(data)
    for p in range(k):
        end = len(a) - 1 - p
        m = a.index(max(a[: end + 1]))
        a[m], a[end] = a[end], a[m]
    return a


def generate(level: int, seed: int) -> Variant:
    """Вариант: программа сортировки, вызванная с k проходами; вопрос — какой массив она напечатает.

    Уровень 1 — k проходов пузырька, выбора или вставок. Уровень 2 — разбиение Ломуто с опорным элементом в конце.
    Уровень 3 — пирамидальная сортировка: построение max-кучи и k извлечений. Ответ — эталонная модель на Python
    (отдельно от текста программы). Модель ошибки `neighbor_algorithm`: результат соседнего алгоритма с теми же
    данными (пузырёк, выбор, вставки по кругу; для разбиения — устойчивое разбиение; для пирамиды — выбор
    наибольшего). Вариант отбрасывается, если ошибка совпала с ответом или массив уже полностью отсортирован.
    Значения различны, поэтому ответ однозначен.
    """
    rng = Random(seed)
    fname = names.pick(rng, names.FUNC_NAMES)
    if level == 1:
        size = rng.randint(6, 8)
        data = rng.sample(range(1, 40), size)
        algo = rng.choice(["bubble", "selection", "insertion"])
        k = rng.randint(1, 3)
        table: dict[str, tuple[str, Callable[[list[int], int], list[int]], Callable[[list[int], int], list[int]]]] = {
            "bubble": (BUBBLE, _bubble, _selection),
            "selection": (SELECTION, _selection, _insertion),
            "insertion": (INSERTION, _insertion, _bubble),
        }
        template, model, neighbor = table[algo]
        answer, wrong = model(data, k), neighbor(data, k)
        call = f"print({fname}(data, {k}))"
    elif level == 2:
        data = rng.sample(range(1, 40), rng.randint(7, 8))
        template, answer, wrong = LOMUTO, _lomuto(data), _stable_partition(data)
        call = f"print({fname}(data))"
    elif level == 3:
        data = rng.sample(range(1, 40), rng.randint(7, 8))
        k = rng.randint(1, 3)
        template, answer, wrong = HEAP, _heap_steps(data, k), _selection_from_right(data, k)
        call = f"print({fname}(data, {k}))"
    else:
        raise ValueError(f"нет уровня {level}")
    if answer == wrong:
        raise Reject("misconception_equals_answer")
    if answer == sorted(answer) or answer == data:
        raise Reject("trivial_state")
    src = template.format(f=fname) + f"\n\ndata = {data}\n{call}"
    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt="Что напечатает программа? Числа через пробел, слева направо; скобки и запятые не нужны.",
        code=CodeBlock(language="python", text=src),
        input=InputHint(placeholder="числа через пробел", max_length=40),
        answer=AnswerSpec.text(tokens(answer), mode="tokens"),
        misconception_answers={"neighbor_algorithm": tokens(wrong)},
        features={"code_lines": src.count("\n") + 1, "concepts": level, "answer_abs": max(answer), "trap": 1},
        explanation=f"Эталонная модель даёт [{tokens(answer)}]; соседний алгоритм — [{tokens(wrong)}].",
    )


def _printed_tokens(text: str) -> str:
    return " ".join(text.strip().strip("[]").replace(",", " ").split())


def selfcheck(v: Variant) -> list[str]:
    """Перепроверка: исполнение отрендеренного текста (с трассировкой строк) даёт ответ модели (§2.5)."""
    assert v.code is not None
    try:
        printed = _printed_tokens(run_source(v.code.text).printed)
    except ProgramError as exc:
        return [f"программа не исполняется: {exc}"]
    return [] if printed == v.answer.value else ["исполнение текста программы расходится с ответом модели"]


def oracle_check(v: Variant) -> list[str]:
    """Оракул CPython: тот же текст исполняется обычным `exec` с полными встроенными функциями."""
    assert v.code is not None
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exec(v.code.text, {})
    printed = _printed_tokens(buffer.getvalue())
    return [] if printed == v.answer.value else [f"CPython напечатал {printed}, ключ {v.answer.value}"]
