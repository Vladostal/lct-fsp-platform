"""Семейство «Двоичная куча в массиве»: состояние min-кучи после серии операций (приложение A, §3.1)."""

from __future__ import annotations

import heapq
import re
from random import Random

from app.modules.assessment.families._lib.contract import AnswerSpec, InputHint, Reject, Variant
from app.modules.assessment.families._lib.miniprog import tokens
from app.modules.assessment.families.registry import family_meta

META = family_meta(
    "ds.heap_array",
    version=1,
    feature_bounds={
        1: {"concepts": (1, 1), "timeline_events": (6, 7), "answer_abs": (1, 60)},
        2: {"concepts": (2, 2), "timeline_events": (9, 11), "answer_abs": (1, 60)},
        3: {"concepts": (3, 3), "timeline_events": (8, 11), "answer_abs": (1, 60)},
    },
)

RULES = (
    "Min-куча хранится в массиве: потомки элемента i стоят на местах 2i+1 и 2i+2. Вставка: элемент добавляется "
    "в конец и поднимается, пока он меньше родителя. Извлечение минимума: последний элемент ставится на место "
    "корня и опускается, меняясь с меньшим из потомков, пока он больше хотя бы одного из них."
)


def _sift_up(a: list[int], i: int) -> None:
    while i > 0 and a[(i - 1) // 2] > a[i]:
        parent = (i - 1) // 2
        a[parent], a[i] = a[i], a[parent]
        i = parent


def _sift_down(a: list[int], i: int) -> None:
    n = len(a)
    while True:
        smallest = i
        for child in (2 * i + 1, 2 * i + 2):
            if child < n and a[child] < a[smallest]:
                smallest = child
        if smallest == i:
            return
        a[i], a[smallest] = a[smallest], a[i]
        i = smallest


def _push(a: list[int], x: int) -> None:
    a.append(x)
    _sift_up(a, len(a) - 1)


def _pop(a: list[int]) -> int:
    top = a[0]
    last = a.pop()
    if a:
        a[0] = last
        _sift_down(a, 0)
    return top


def _heapify(values: list[int]) -> list[int]:
    a = list(values)
    for i in range(len(a) // 2 - 1, -1, -1):
        _sift_down(a, i)
    return a


def _run(level: int, values: list[int], ops: list[str], pops: int) -> list[int]:
    """Модель: массив кучи после операций. `ops` — «+x» (вставка) и «-» (извлечение)."""
    if level == 3:
        heap = _heapify(values)
        for _ in range(pops):
            _pop(heap)
        return heap
    heap = []
    for op in ops:
        if op == "-":
            _pop(heap)
        else:
            _push(heap, int(op[1:]))
    return heap


def generate(level: int, seed: int) -> Variant:
    """Вариант: массив min-кучи после вставок, вставок с извлечениями или построения кучи и извлечений.

    Уровень 1 — 6–7 вставок. Уровень 2 — вставки вперемешку с 2–3 извлечениями. Уровень 3 — построение кучи
    снизу вверх из заданного массива и 2–3 извлечения. Ответ считает симуляция кучи; значения различны, поэтому
    результат единственный. Модель ошибки `sorted_array`: кандидат пишет элементы по возрастанию (отбрасывается
    вариант, где куча случайно отсортирована).
    """
    rng = Random(seed)
    count = {1: rng.randint(6, 7), 2: rng.randint(7, 8), 3: rng.randint(7, 8)}[level]
    values = rng.sample(range(1, 60), count)
    ops: list[str] = []
    pops = 0
    if level == 1:
        ops = [f"+{x}" for x in values]
        text = "Вставки по порядку: " + ", ".join(str(x) for x in values) + ". Какой массив получится?"
        events = count
    elif level == 2:
        pops = rng.randint(2, 3)
        ops = [f"+{x}" for x in values]
        for _ in range(pops):
            # Извлечение не раньше четвёртой вставки: иначе куча слишком мала и ответ тривиален.
            ops.insert(rng.randint(4, len(ops)), "-")
        text = "Операции по порядку: " + ", ".join(ops).replace("+", "вставить ").replace("-", "извлечь min")
        text += ". Какой массив получится в конце?"
        events = len(ops)
    else:
        pops = rng.randint(2, 3)
        text = (
            f"Массив {values} превращается в min-кучу построением снизу вверх (от последнего родителя к корню, "
            f"каждый элемент опускается). Затем {pops} раза извлекается минимум. Какой массив получится?"
        )
        events = count + pops
    final = _run(level, values, ops, pops)
    if final == sorted(final):
        raise Reject("sorted_heap")
    wrong = tokens(sorted(final))
    answer = tokens(final)
    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt=f"{RULES} {text} Числа через пробел, слева направо.",
        input=InputHint(placeholder="числа через пробел", max_length=60),
        answer=AnswerSpec.text(answer, mode="tokens"),
        misconception_answers={"sorted_array": wrong},
        features={"concepts": level, "timeline_events": events, "answer_abs": max(final)},
        explanation=f"Симуляция кучи даёт [{answer}]. Ошибка sorted_array: [{wrong}] — куча не отсортирована.",
    )


def selfcheck(v: Variant) -> list[str]:
    """Перепроверка: корректность кучи и состав элементов (инварианты, не повтор модели)."""
    final = [int(x) for x in str(v.answer.value).split()]
    problems = []
    if any(final[(i - 1) // 2] > final[i] for i in range(1, len(final))):
        problems.append("ответ не является min-кучей")
    if len(set(final)) != len(final):
        problems.append("в ответе повторяются значения")
    return problems


def oracle_check(v: Variant) -> list[str]:
    """Оракул CPython: `heapq` (вставка и `heappop` дают тот же массив при различных значениях)."""
    prompt = v.prompt
    if v.level == 1:
        part = re.search(r"Вставки по порядку: ([\d, ]+)\.", prompt)
        heap: list[int] = []
        for x in (int(t) for t in part.group(1).split(",")):  # type: ignore[union-attr]
            heapq.heappush(heap, x)
    elif v.level == 2:
        part = re.search(r"Операции по порядку: (.+?)\. Какой", prompt)
        heap = []
        for item in part.group(1).split(", "):  # type: ignore[union-attr]
            if item == "извлечь min":
                heapq.heappop(heap)
            else:
                heapq.heappush(heap, int(item.split()[1]))
    else:
        match = re.search(r"Массив \[([\d, ]+)\].*Затем (\d) раза", prompt)
        heap = [int(t) for t in match.group(1).split(",")]  # type: ignore[union-attr]
        heapq.heapify(heap)
        for _ in range(int(match.group(2))):  # type: ignore[union-attr]
            heapq.heappop(heap)
    expected = tokens(heap)
    return [] if expected == v.answer.value else [f"heapq даёт [{expected}], ключ [{v.answer.value}]"]
