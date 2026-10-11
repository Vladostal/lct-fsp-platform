"""Семейство «Класс сложности по коду»: асимптотика функции с циклами или рекурсией (приложение A, §3.1)."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from fractions import Fraction
from random import Random

from app.modules.assessment.families._lib import names
from app.modules.assessment.families._lib.contract import AnswerSpec, CodeBlock, Option, Reject, Variant
from app.modules.assessment.families._lib.miniprog import fast_call
from app.modules.assessment.families.registry import family_meta

META = family_meta(
    "algo.bigo_loops",
    version=1,
    feature_bounds={
        1: {"code_lines": (4, 11), "nesting_depth": (0, 3), "concepts": (1, 5), "options_count": (8, 8),
            "trap": (1, 1)},
        2: {"code_lines": (5, 14), "nesting_depth": (0, 3), "concepts": (1, 5), "options_count": (8, 8),
            "trap": (1, 1)},
        3: {"code_lines": (4, 14), "nesting_depth": (0, 3), "concepts": (1, 5), "options_count": (8, 8),
            "trap": (1, 1)},
    },
    # Реестр моделей ошибок для выбора класса не называет; ниже пять типичных способов ошибиться в оценке.
    misconceptions=("add_nested", "linear_for_log", "const_as_linear", "multiply_sequential", "ignore_recursion"),
)  # fmt: skip

#: Восемь классов в фиксированном порядке реестра; порядок показа перемешивает генератор.
CLASSES: tuple[tuple[str, str], ...] = (
    ("1", "O(1)"), ("log", "O(log n)"), ("sqrt", "O(√n)"), ("n", "O(n)"),
    ("nlogn", "O(n log n)"), ("n2", "O(n²)"), ("n3", "O(n³)"), ("exp", "O(2ⁿ)"),
)  # fmt: skip
GROWTH = {  # (степень n, степень log n) -> ключ класса
    (Fraction(0), 0): "1", (Fraction(0), 1): "log", (Fraction(1, 2), 0): "sqrt", (Fraction(1), 0): "n",
    (Fraction(1), 1): "nlogn", (Fraction(2), 0): "n2", (Fraction(3), 0): "n3",
}  # fmt: skip
LEVEL_CLASSES = {
    1: ("1", "log", "sqrt", "n", "n2", "n3"),
    2: ("log", "sqrt", "n", "nlogn", "n2", "n3"),
    3: ("log", "sqrt", "n", "nlogn", "n2", "n3", "exp"),
}
VARS = ("i", "j", "k")


@dataclass(frozen=True)
class Loop:
    """Цикл вида `kind` с телом `body` (None — один оператор счётчика)."""

    kind: str  # n, const, tri, log, halve, sqrt
    body: Loop | Seq | None = None
    count: int = 0


@dataclass(frozen=True)
class Seq:
    """Блоки, идущие один за другим."""

    parts: tuple[Loop | Seq | None, ...]


@dataclass(frozen=True)
class Rec:
    """Рекурсивная функция: `calls` вызовов от n // base (или от n - 1, если base == 0) и работа порядка n^work."""

    calls: int
    base: int
    work: int


Node = Loop | Seq | Rec | None
Growth = tuple[Fraction, int]


def _factor(kind: str, mode: str) -> Growth:
    if kind == "const":
        return (Fraction(1), 0) if mode == "const_as_linear" else (Fraction(0), 0)
    if kind in ("n", "tri"):
        return Fraction(1), 0
    if mode == "linear_for_log":
        return Fraction(1), 0
    return (Fraction(0), 1) if kind in ("log", "halve") else (Fraction(1, 2), 0)


def _add(a: Growth, b: Growth) -> Growth:
    return a[0] + b[0], a[1] + b[1]


def growth(node: Node, mode: str = "correct") -> Growth | str:
    """Порядок роста дерева; `mode` — правило модели ошибки. Для рекурсии с двумя ветвями без деления — «exp»."""
    if node is None:
        return Fraction(0), 0
    if isinstance(node, Rec):
        if mode == "ignore_recursion":
            return Fraction(node.work), 0
        if node.base == 0:
            return "exp" if node.calls >= 2 else (Fraction(node.work + 1), 0)
        crit = round(math.log(node.calls) / math.log(node.base))
        if node.work < crit:
            return Fraction(crit), 0
        return (Fraction(crit), 1) if node.work == crit else (Fraction(node.work), 0)
    if isinstance(node, Seq):
        parts = [growth(p, mode) for p in node.parts]
        if mode == "multiply_sequential":
            total: Growth = (Fraction(0), 0)
            for part in parts:
                total = _add(total, part)  # type: ignore[arg-type]
            return total
        return max(parts)
    own, body = _factor(node.kind, mode), growth(node.body, mode)
    if mode == "add_nested":
        return max(own, body)
    return _add(own, body)  # type: ignore[arg-type]


def class_key(value: Growth | str) -> str | None:
    """Ключ класса среди восьми или None, если порядок роста не входит в список."""
    return value if isinstance(value, str) else GROWTH.get(value)


def _render_loop(node: Loop, depth: int, indent: str, parent: str | None, n: str) -> list[str]:
    var = VARS[min(depth, 2)]
    inner = indent + "    "
    body = _render(node.body, depth + 1, inner, var, n) if node.body is not None else [inner + "count += 1"]
    if node.kind == "n":
        return [f"{indent}for {var} in range({n}):", *body]
    if node.kind == "const":
        return [f"{indent}for {var} in range({node.count}):", *body]
    if node.kind == "tri":
        return [f"{indent}for {var} in range({parent or n}):", *body]
    if node.kind == "log":
        return [f"{indent}{var} = 1", f"{indent}while {var} < {n}:", *body, f"{inner}{var} *= 2"]
    if node.kind == "halve":
        return [f"{indent}{var} = {n}", f"{indent}while {var} > 1:", *body, f"{inner}{var} //= 2"]
    return [f"{indent}{var} = 1", f"{indent}while {var} * {var} <= {n}:", *body, f"{inner}{var} += 1"]


def _render(node: Loop | Seq | None, depth: int, indent: str, parent: str | None, n: str) -> list[str]:
    if node is None:
        return [indent + "count += 1"]
    if isinstance(node, Seq):
        return [line for part in node.parts for line in _render(part, depth, indent, parent, n)]
    return _render_loop(node, depth, indent, parent, n)


def render_function(node: Node, fname: str, counter: str) -> str:
    """Текст функции `fname(n)`, возвращающей число операций счётчика."""
    if isinstance(node, Rec):
        call = f"{fname}(n // {node.base})" if node.base else f"{fname}(n - 1)"
        body = f"{counter} += 1"
        work = {
            0: [],
            1: ["    for i in range(n):", f"        {body}"],
            2: ["    for i in range(n):", "        for j in range(n):", f"            {body}"],
        }[node.work]
        lines = [f"def {fname}(n):", "    if n <= 1:", "        return 1", f"    {counter} = 1", *work]
        lines += [f"    for r in range({node.calls}):", f"        {counter} += {call}", f"    return {counter}"]
        return "\n".join(lines)
    lines = [f"def {fname}(n):", f"    {counter} = 0", *_render(node, 0, "    ", None, "n"), f"    return {counter}"]
    return "\n".join(lines).replace("count", counter)


def _loop(kind: str, body: Loop | Seq | None = None, count: int = 0) -> Loop:
    return Loop(kind, body, count)


def _build_loops(level: int, target: str, rng: Random) -> Node:
    """Дерево циклов с заданным порядком роста; всегда содержит конструкцию-ловушку для одной из моделей ошибок."""
    c = rng.randint(2, 5)
    choices: list[Loop | Seq]
    const = _loop("const", None, c)
    if target == "1":
        return _loop("const", const if rng.random() < 0.5 else None, c)
    if target == "log":
        kind = rng.choice(["log", "halve"])
        if level == 1:
            return _loop(kind, const if rng.random() < 0.4 else None)
        choices = [_loop(kind), Seq((_loop(kind), const)), Seq((const, _loop(kind)))]
        return rng.choice(choices)
    if target == "sqrt":
        if level == 3:
            choices = [_loop("sqrt"), _loop("sqrt", const), Seq((_loop("sqrt"), _loop("log")))]
            return rng.choice(choices)
        if level == 2:
            return Seq((_loop("sqrt"), _loop("log"))) if rng.random() < 0.5 else Seq((_loop("log"), _loop("sqrt")))
        return _loop("sqrt", const if rng.random() < 0.5 else None)
    if target == "n":
        if level == 1:
            return rng.choice([_loop("n", const), _loop("const", _loop("n"), c)])
        choices = [Seq((_loop("n"), _loop("log"))), Seq((_loop("log"), _loop("n"))),
                   Seq((_loop("n", const), _loop("sqrt")))]  # fmt: skip
        return rng.choice(choices)
    if target == "nlogn":
        return rng.choice([_loop("n", _loop("log")), _loop("n", _loop("halve")), _loop("log", _loop("n"))])
    if target == "n2":
        if level == 1:
            return _loop("n", _loop("n", const if rng.random() < 0.5 else None))
        choices = [_loop("n", _loop("tri")), Seq((_loop("n", _loop("tri")), _loop("n"))),
                   _loop("n", _loop("n", const))]  # fmt: skip
        return rng.choice(choices)
    if level == 1:
        return _loop("n", _loop("n", _loop("n")))
    return rng.choice([_loop("n", _loop("tri", _loop("tri"))), _loop("n", _loop("n", _loop("n")))])


#: Рекурсии по классу: (число вызовов, делитель или 0 для n - 1, порядок работы вне вызовов).
RECURSIONS: dict[str, tuple[tuple[int, int, int], ...]] = {
    "log": ((1, 2, 0),),
    "n": ((2, 2, 0), (3, 3, 0), (4, 4, 0), (1, 0, 0)),
    "nlogn": ((2, 2, 1), (3, 3, 1), (4, 4, 1)),
    "n2": ((4, 2, 0), (4, 2, 1), (2, 2, 2), (1, 0, 1)),
    "n3": ((8, 2, 0), (8, 2, 1), (8, 2, 2), (1, 0, 2)),
    "exp": ((2, 0, 0), (2, 0, 1)),
}


def _nesting(node: Node) -> int:
    if node is None or isinstance(node, Rec):
        return 0
    if isinstance(node, Seq):
        return max(_nesting(p) for p in node.parts)
    return 1 + _nesting(node.body)


def _concepts(node: Node) -> int:
    kinds: set[str] = set()

    def walk(item: Node) -> None:
        if isinstance(item, Rec):
            kinds.add("rec")
        elif isinstance(item, Seq):
            kinds.add("seq")
            for part in item.parts:
                walk(part)
        elif isinstance(item, Loop):
            kinds.add(item.kind)
            walk(item.body)

    walk(node)
    return len(kinds)


def generate(level: int, seed: int) -> Variant:
    """Вариант: функция с циклами или рекурсией; вопрос — класс сложности по времени (один из восьми).

    Каждый блок несёт порядок роста (степень n, степень log n): вложение — сумма степеней, последовательность —
    максимум, рекурсия — основная теорема о рекуррентных соотношениях, вычитающая рекурсия с двумя ветвями — 2ⁿ.
    Уровень 1 — независимые вложенные циклы, цикл до √n и константные циклы. Уровень 2 — удвоение счётчика,
    зависимые границы, последовательные блоки. Уровень 3 — рекурсия T(n) = a·T(n/b) + f(n), вычитающая
    рекурсия, цикл до √n. Ответ — вычисленный класс; целевой класс выбирается равномерно (правило L09).
    Модели ошибок: `add_nested` (вложение считается суммой), `linear_for_log` (удвоение и √n считаются линейными),
    `const_as_linear` (цикл с константной границей считается линейным), `multiply_sequential` (блоки
    перемножаются), `ignore_recursion` (учтена только работа вне вызовов). Выбор однозначен: восемь различных
    классов, один из них равен вычисленному.
    """
    if level not in LEVEL_CLASSES:
        raise ValueError(f"нет уровня {level}")
    rng = Random(seed)
    target = rng.choice(LEVEL_CLASSES[level])
    node: Node
    if level == 3 and target in RECURSIONS and not (target == "n" and rng.random() < 0.3):
        node = Rec(*rng.choice(RECURSIONS[target]))
    else:
        node = _build_loops(level, target, rng)
    key = class_key(growth(node))
    if key != target:
        raise Reject("target_mismatch")
    fname = names.pick(rng, names.FUNC_NAMES)
    counter = names.pick(rng, ("count", "ops", "steps", "work"))
    code = render_function(node, fname, counter)
    order = list(CLASSES)
    rng.shuffle(order)
    ids = {k: f"o{i}" for i, (k, _) in enumerate(order, 1)}
    wrong: dict[str, str] = {}
    for mode in META.misconceptions:
        alt = class_key(growth(node, mode))
        if alt is not None and alt != target:
            wrong[mode] = ids[alt]
    if not wrong:
        raise Reject("no_misconception")
    by_id = {v: k for k, v in ids.items()}
    lines = code.count("\n") + 1
    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt=(
            f"Функция {fname} получает натуральное n; счётчик {counter} считает выполненные операции. "
            "Какова асимптотическая сложность функции по времени при росте n?"
        ),
        code=CodeBlock(language="python", text=code),
        options=tuple(Option(ids[k], text) for k, text in order),
        answer=AnswerSpec.choice(ids[target]),
        misconception_answers=wrong,
        features={
            "code_lines": lines,
            "nesting_depth": _nesting(node),
            "concepts": _concepts(node),
            "options_count": 8,
            "trap": 1,
        },
        explanation=(
            f"Порядок роста вычислен по дереву блоков: {dict(CLASSES)[target]}. "
            f"Ответы моделей ошибок: { {m: by_id[o] for m, o in wrong.items()} }."
        ),
    )


def selfcheck(v: Variant) -> list[str]:
    """Перепроверка выбора: восемь различных классов, верный и неверные идентификаторы существуют."""
    problems = []
    texts = [o.text for o in v.options or ()]
    if sorted(texts) != sorted(text for _, text in CLASSES):
        problems.append("варианты не равны восьми классам сложности")
    ids = {o.id for o in v.options or ()}
    if v.answer.option_id not in ids or not set(v.misconception_answers.values()) <= ids:
        problems.append("идентификаторы ответов отсутствуют среди вариантов")
    if v.answer.option_id in set(v.misconception_answers.values()):
        problems.append("ответ модели ошибки совпал с верным")
    return problems


def measure_class(source: str, fname: str) -> str:
    """Оракул: класс по числу операций на размерах 8, 16 (признак 2ⁿ), 24 и 96 (и 256, 65536 для сублинейных).

    Размеры 24 и 96 делятся на 2, 3 и 4 несколько раз подряд: у рекурсий с делителем 3 и 4 округление `n // b` на
    степенях двойки искажало бы отношение. Отношение при учетверении n: n — 3…4, n log n — 4.6…5.5, n² — 16, n³ — 64.
    """
    o8, o16 = fast_call(source, fname, 8), fast_call(source, fname, 16)
    if o16 / o8 > 30:
        return "exp"
    ratio = fast_call(source, fname, 96) / fast_call(source, fname, 24)
    if ratio < 2.5:
        far = fast_call(source, fname, 65536) / fast_call(source, fname, 256)
        return "1" if far < 1.3 else "log" if far < 5 else "sqrt"
    for bound, key in ((4.35, "n"), (9.8, "nlogn"), (32.0, "n2")):
        if ratio < bound:
            return key
    return "n3"


def oracle_check(v: Variant) -> list[str]:
    """Оракул CPython: счёт операций при росте n (приложение A, §2.5) должен дать класс верного варианта."""
    assert v.code is not None
    fname = re.search(r"def (\w+)\(n\)", v.code.text).group(1)  # type: ignore[union-attr]
    measured = measure_class(v.code.text, fname)
    expected = dict(CLASSES)[measured]
    chosen = next(o.text for o in v.options or () if o.id == v.answer.option_id)
    return [] if chosen == expected else [f"счёт операций даёт {expected}, ключ {chosen}"]
