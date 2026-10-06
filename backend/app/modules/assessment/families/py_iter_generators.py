"""Семейство `py.iter_generators`: итераторы, срезы, ленивые генераторы, `itertools` (text_input, режим tokens).

Уровень 1 — `enumerate(start)`, `zip` разной длины, срезы с шагом. Уровень 2 — исчерпание итератора (`map`, `iter`) и
ленивость генератора. Уровень 3 — `yield from`, цепочки `itertools` и выражения-генераторы, которые частично
потребляют `next`. Ответ — вывод программы, полученный настоящим исполнением текста в CPython (в реестре оракул
`builtin`). Модели ошибок исполняют изменённый текст: `iterator_reusable` (итератор можно пройти заново),
`enumerate_start_ignored`, `zip_longest_assumed` (`zip` дополняет короткий список нулями), `slice_end_inclusive`,
`generator_eager` (генератор считает всё сразу). Ответ однозначен: программы детерминированы, печатают числа и слова.
"""

from __future__ import annotations

import builtins
import contextlib
import io
import itertools
from random import Random

from app.modules.assessment.families._lib import names
from app.modules.assessment.families._lib.contract import AnswerSpec, CodeBlock, InputHint, Reject, Variant
from app.modules.assessment.families.registry import family_meta

META = family_meta(
    "py.iter_generators",
    version=1,
    feature_bounds={
        1: {"code_lines": (2, 6), "concepts": (1, 2), "nesting_depth": (0, 1)},
        2: {"code_lines": (2, 9), "concepts": (2, 3), "nesting_depth": (0, 1)},
        3: {"code_lines": (4, 12), "concepts": (3, 4), "nesting_depth": (0, 1)},
    },
    misconceptions=(
        "iterator_reusable",
        "enumerate_start_ignored",
        "zip_longest_assumed",
        "slice_end_inclusive",
        "generator_eager",
    ),
)


def _import(name: str, *args: object, **kwargs: object) -> object:
    """Единственный разрешённый импорт в программах семейства — `itertools`."""
    if name != "itertools":
        raise ImportError(name)
    return __import__(name, *args, **kwargs)  # type: ignore[arg-type]


_BUILTINS: dict[str, object] = {
    name: getattr(builtins, name)
    for name in (
        "print",
        "range",
        "len",
        "sum",
        "list",
        "enumerate",
        "zip",
        "map",
        "next",
        "iter",
        "sorted",
        "max",
        "min",
    )
}
_BUILTINS["__import__"] = _import


def run(source: str) -> str:
    """Исполнить текст программы в ограниченном пространстве имён; вернуть вывод токенами через пробел.

    Исполняются шаблоны самого генератора, а не код кандидата.
    """
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exec(compile(source, "<variant>", "exec"), {"__builtins__": _BUILTINS, "__name__": "__main__"})
    return " ".join(buffer.getvalue().split())


Template = tuple[str, dict[str, str], int]


def _nums(rng: Random, low: int, high: int) -> list[int]:
    return [rng.randint(2, 9) for _ in range(rng.randint(low, high))]


def _t_enumerate(rng: Random) -> Template:
    data, start, var = _nums(rng, 4, 5), rng.randint(1, 4), names.pick(rng, names.LIST_VARS)
    op = rng.choice(("i * x", "i + x", "x - i"))

    def render(s: int) -> str:
        return f"{var} = {data}\nprint(*[{op} for i, x in enumerate({var}, {s})])"

    return render(start), {"enumerate_start_ignored": render(0)}, 1


def _t_zip(rng: Random) -> Template:
    long, short = _nums(rng, 5, 6), _nums(rng, 3, 4)
    a, b = names.pick_many(rng, names.LIST_VARS, 2)
    op = rng.choice(("x * y", "x + y", "x - y"))

    def render(pad: bool) -> str:
        right = short + [0] * (len(long) - len(short)) if pad else short
        return f"{a} = {long}\n{b} = {right}\nprint(*[{op} for x, y in zip({a}, {b})])"

    return render(False), {"zip_longest_assumed": render(True)}, 1


def _t_slice(rng: Random) -> Template:
    data = [rng.randint(2, 9) for _ in range(rng.randint(7, 9))]
    lo, step = rng.randint(0, 2), rng.randint(2, 3)
    hi = rng.randint(lo + 4, len(data) - 1)
    var = names.pick(rng, names.LIST_VARS)

    def render(extra: int) -> str:
        return f"{var} = {data}\nprint(*{var}[{lo}:{hi + extra}:{step}])"

    return render(0), {"slice_end_inclusive": render(1)}, 1


def _t_exhaust(rng: Random) -> Template:
    data, k = _nums(rng, 4, 6), rng.randint(2, 9)
    kind = rng.choice(("map", "iter"))
    expr = rng.choice((f"x * {k}", f"x + {k}", f"x * x - {k}"))
    reads = rng.choice(("sum(it), sum(it)", "sum(it), len(list(it))", "max(it), sum(it)"))

    def render(reusable: bool) -> str:
        if kind == "map":
            make = f"list(map(lambda x: {expr}, {data}))" if reusable else f"map(lambda x: {expr}, {data})"
        else:
            make = f"{data}" if reusable else f"iter({data})"
        return f"it = {make}\nprint({reads})"

    return render(False), {"iterator_reusable": render(True)}, 2


def _t_lazy(rng: Random) -> Template:
    n, k, takes = rng.randint(3, 6), rng.randint(2, 9), rng.randint(2, 3)
    word = names.pick(rng, ("make", "step", "load", "calc", "read", "emit"))
    expr = rng.choice((f"i * {k}", f"i + {k}", f"{k} - i"))

    def render(eager: bool) -> str:
        source = f'def gen(n):\n    for i in range(n):\n        print("{word}", i)\n        yield {expr}\n'
        make = f"iter(list(gen({n})))" if eager else f"gen({n})"
        pulls = "\n".join(f"v{j} = next(g)" for j in range(takes))
        shown = ", ".join(f"v{j}" for j in range(takes))
        return f"{source}g = {make}\n{pulls}\nprint({shown})"

    return render(False), {"generator_eager": render(True)}, 2


def _t_yield_from(rng: Random) -> Template:
    c = rng.randint(2, 4)
    pulls = rng.randint(c, c + 1)  # при pulls = c + 1 успевает напечататься метка после yield from
    word_in, word_done = rng.sample(("in", "item", "got", "tick", "done", "end", "after", "stop"), 2)
    shift = rng.randint(0, 5)

    def render(eager: bool) -> str:
        pull = "iter(list(outer()))" if eager else "outer()"
        return (
            "def inner(n):\n"
            "    for i in range(n):\n"
            f'        print("{word_in}", i)\n'
            f"        yield i + {shift}\n"
            "def outer():\n"
            f"    yield from inner({c})\n"
            f'    print("{word_done}")\n'
            "    yield 99\n"
            f"g = {pull}\n"
            f"vals = [next(g) for _ in range({pulls})]\n"
            "print(*vals)"
        )

    return render(False), {"generator_eager": render(True)}, 3


def _t_pipeline(rng: Random) -> Template:
    xs, ys = _nums(rng, 3, 4), _nums(rng, 3, 4)
    k = rng.randint(2, 4)
    cond = rng.choice(("x % 2 == 0", "x > 4", "x % 3 != 0"))
    if not any(eval(cond, {"x": x}) for x in xs + ys):
        return _t_pipeline(rng)
    gen = f"x * {k} for x in itertools.chain({xs}, {ys}) if {cond}"

    def render(fresh: bool) -> str:
        total = f"sum({gen})" if fresh else "sum(g)"
        return f"import itertools\ng = ({gen})\na = next(g, 0)\nb = next(g, 0)\nprint(a, b, {total})"

    return render(False), {"iterator_reusable": render(True)}, 4


TEMPLATES: dict[int, tuple] = {
    1: (_t_enumerate, _t_zip, _t_slice),
    2: (_t_exhaust, _t_lazy),
    3: (_t_yield_from, _t_pipeline),
}


def generate(level: int, seed: int) -> Variant:
    """Вариант: короткая программа с итераторами; вопрос — что она напечатает (токены через пробел).

    Ответ получается исполнением текста в CPython. Модели ошибок — исполнение того же текста с изменением,
    воспроизводящим заблуждение (см. docstring модуля); вариант, где ошибка не меняет вывод, отбрасывается.
    Ответ однозначен: программа детерминирована, итераторы потребляются в порядке строк.
    """
    rng = Random(seed)
    source, alternatives, concepts = rng.choice(TEMPLATES[level])(rng)
    answer = run(source)
    wrong = {}
    for code, alt in alternatives.items():
        value = run(alt)
        if value != answer:
            wrong[code] = value
    if not wrong:
        raise Reject("misconception_equals_answer")
    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt="Что напечатает программа? Укажите значения через пробел в порядке вывода.",
        code=CodeBlock(language="python", text=source),
        input=InputHint(placeholder="значения через пробел", max_length=60),
        answer=AnswerSpec.text(answer, mode="tokens"),
        misconception_answers=wrong,
        features={"code_lines": source.count("\n") + 1, "concepts": concepts, "nesting_depth": int("for" in source)},
        explanation=f"Исполнение даёт «{answer}»; модели ошибок: {wrong}.",
    )


def selfcheck(v: Variant) -> list[str]:
    """Перепроверка: повторное исполнение текста из условия даёт тот же вывод; в программе нет посторонних вызовов."""
    assert v.code is not None
    try:
        got = run(v.code.text)
    except Exception as exc:
        return [f"программа не исполняется: {exc!r}"]
    return [] if got == v.answer.value else [f"исполнение даёт «{got}», ключ «{v.answer.value}»"]


_ = itertools  # импорт нужен ограниченной среде исполнения
