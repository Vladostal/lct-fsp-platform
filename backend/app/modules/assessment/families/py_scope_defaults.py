"""Семейство `py.scope_defaults`: значения по умолчанию, замыкания, `global` и `nonlocal` (text_input, режим tokens).

Уровень 1 — изменяемый аргумент по умолчанию (список, словарь). Уровень 2 — позднее связывание переменной цикла в
замыканиях и привязка через значение по умолчанию. Уровень 3 — `global`/`nonlocal` и присваивание без объявления.
Ответ — напечатанные значения через пробел: его даёт настоящее исполнение текста программы в CPython (ограниченное
пространство имён, в реестре оракул `builtin`). Ответ модели ошибки — исполнение изменённого текста, который
воспроизводит заблуждение: `fresh_default_each_call` (значение по умолчанию создаётся заново при каждом вызове),
`early_binding_closure` (замыкание фиксирует значение в момент создания), `global_nonlocal_confused` (`global` и
`nonlocal` перепутаны), `local_assign_is_global` (присваивание в функции меняет глобальную переменную).
"""

from __future__ import annotations

import builtins
import contextlib
import io
from random import Random

from app.modules.assessment.families._lib import names
from app.modules.assessment.families._lib.contract import AnswerSpec, CodeBlock, InputHint, Reject, Variant
from app.modules.assessment.families.registry import family_meta

META = family_meta(
    "py.scope_defaults",
    version=1,
    feature_bounds={
        1: {"code_lines": (5, 9), "concepts": (1, 2), "nesting_depth": (1, 1)},
        2: {"code_lines": (2, 9), "concepts": (2, 3), "nesting_depth": (1, 2)},
        3: {"code_lines": (7, 14), "concepts": (2, 3), "nesting_depth": (1, 2)},
    },
    misconceptions=(
        "fresh_default_each_call",
        "early_binding_closure",
        "global_nonlocal_confused",
        "local_assign_is_global",
    ),
)

_BUILTINS = {
    name: getattr(builtins, name)
    for name in ("print", "range", "len", "sum", "list", "dict", "str", "int", "max", "min", "enumerate", "zip")
}


def run(source: str) -> str:
    """Исполнить текст программы в ограниченном пространстве имён; вернуть напечатанное токенами через пробел.

    Это исполнение собственных шаблонов генератора, а не кода кандидата.
    """
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exec(compile(source, "<variant>", "exec"), {"__builtins__": _BUILTINS, "__name__": "__main__"})
    return " ".join(buffer.getvalue().split())


Template = tuple[str, dict[str, str], int]  # (текст, {код ошибки: изменённый текст}, число концепций)


def _t_default_list(rng: Random) -> Template:
    fn, var = names.pick(rng, names.FUNC_NAMES), names.pick(rng, ("acc", "buf", "items", "seen"))
    k = rng.randint(1, 3)
    values = [rng.randint(2, 9) for _ in range(rng.randint(3, 4))]
    ret = rng.choice((f"sum({var})", f"len({var})", f"sum({var}) - {k}"))
    explicit = rng.randrange(len(values)) if rng.random() < 0.5 else None
    calls = [f"{fn}({x}, [])" if i == explicit else f"{fn}({x})" for i, x in enumerate(values)]

    def render(fresh: bool) -> str:
        head = (
            f"def {fn}(x, {var}=None):\n    if {var} is None:\n        {var} = []\n"
            if fresh
            else f"def {fn}(x, {var}=[]):\n"
        )
        return f"{head}    {var}.append(x * {k})\n    return {ret}\n\nprint({', '.join(calls)})"

    return render(False), {"fresh_default_each_call": render(True)}, 1 + (explicit is not None)


def _t_default_dict(rng: Random) -> Template:
    fn = names.pick(rng, ("count", "tally", "hit", "visit"))
    keys = [names.pick(rng, ("a", "b", "c")) for _ in range(rng.randint(4, 6))]
    step = rng.randint(1, 4)

    def render(fresh: bool) -> str:
        sig = "key, seen=None" if fresh else "key, seen={}"
        init = "    if seen is None:\n        seen = {}\n" if fresh else ""
        body = f"    seen[key] = seen.get(key, 0) + {step}\n    return seen[key]\n"
        calls = ", ".join(f'{fn}("{k}")' for k in keys)
        return f"def {fn}({sig}):\n{init}{body}\nprint({calls})"

    return render(False), {"fresh_default_each_call": render(True)}, 1


def _t_late_binding(rng: Random) -> Template:
    n, k, start = rng.randint(3, 5), rng.randint(2, 6), rng.randint(0, 3)
    form = rng.choice(("lambda", "def"))
    var = names.pick(rng, ("i", "j", "t", "m"))
    holder = names.pick(rng, ("fs", "funcs", "hooks", "ops"))
    expr = rng.choice((f"{var} * {k}", f"{var} + {k}", f"{k} - {var}", f"{var} * {var} + {k}"))
    fixed = rng.random() < 0.5  # привязка через значение по умолчанию: тогда верный ответ — «ранняя» привязка

    def render(bind: bool) -> str:
        arg = f"{var}={var}" if bind else ""
        loop = f"range({start}, {start + n})"
        if form == "lambda":
            return f"{holder} = [lambda {arg}: {expr} for {var} in {loop}]\nprint(*[f() for f in {holder}])"
        return (
            f"{holder} = []\n"
            f"for {var} in {loop}:\n"
            f"    def f({arg}):\n"
            f"        return {expr}\n"
            f"    {holder}.append(f)\n"
            f"print(*[f() for f in {holder}])"
        )

    if fixed:
        return render(True), {"fresh_default_each_call": render(False)}, 3
    return render(False), {"early_binding_closure": render(True)}, 2


def _t_nonlocal(rng: Random) -> Template:
    n0, n1, d = rng.randint(2, 9), rng.randint(2, 9), rng.randint(2, 7)
    use_nonlocal = rng.random() < 0.5
    fn = names.pick(rng, ("outer", "wrap", "scope"))

    def render(keyword: str) -> str:
        return (
            f"n = {n0}\n"
            f"def {fn}():\n"
            f"    n = {n1}\n"
            "    def inner():\n"
            f"        {keyword} n\n"
            f"        n += {d}\n"
            "        return n\n"
            "    r = inner()\n"
            "    return r, n\n"
            f"print(*{fn}(), n)"
        )

    true_kw = "nonlocal" if use_nonlocal else "global"
    other = "global" if use_nonlocal else "nonlocal"
    return render(true_kw), {"global_nonlocal_confused": render(other)}, 3


def _t_global_reset(rng: Random) -> Template:
    t, a, b = rng.randint(2, 9), rng.randint(2, 9), rng.randint(2, 9)

    def render(declare: bool) -> str:
        decl = "    global total\n" if declare else ""
        return (
            f"total = {t}\n"
            "def bump(k):\n"
            "    global total\n"
            "    total += k\n"
            "    return total\n"
            "def reset():\n"
            f"{decl}    total = 0\n"
            "    return total\n"
            f"print(bump({a}), reset(), bump({b}), total)"
        )

    return render(False), {"local_assign_is_global": render(True)}, 2


TEMPLATES: dict[int, tuple] = {
    1: (_t_default_list, _t_default_dict),
    2: (_t_late_binding,),
    3: (_t_nonlocal, _t_global_reset),
}


def generate(level: int, seed: int) -> Variant:
    """Вариант: короткая программа Python; вопрос — что она напечатает (значения через пробел).

    Ответ получается исполнением текста в CPython. Модели ошибок — исполнение того же текста с изменением,
    воспроизводящим заблуждение (см. docstring модуля); ответ ошибки, совпавший с верным, отбрасывает вариант.
    Ответ однозначен: программа детерминирована, печатает только целые числа.
    """
    rng = Random(seed)
    source, alternatives, concepts = rng.choice(TEMPLATES[level])(rng)
    answer = run(source)
    wrong = {}
    for code, alt in alternatives.items():
        try:
            value = run(alt)
        except Exception:
            continue
        if value != answer:
            wrong[code] = value
    if not wrong:
        raise Reject("misconception_equals_answer")
    lines = source.count("\n") + 1
    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt="Что напечатает программа? Укажите значения через пробел в порядке вывода.",
        code=CodeBlock(language="python", text=source),
        input=InputHint(placeholder="числа через пробел", max_length=40),
        answer=AnswerSpec.text(answer, mode="tokens"),
        misconception_answers=wrong,
        features={"code_lines": lines, "concepts": concepts, "nesting_depth": 2 if "inner" in source else 1},
        explanation=f"Исполнение даёт «{answer}»; модели ошибок: {wrong}.",
    )


def selfcheck(v: Variant) -> list[str]:
    """Перепроверка: повторное исполнение текста из условия в чистом пространстве имён даёт тот же вывод."""
    assert v.code is not None
    try:
        got = run(v.code.text)
    except Exception as exc:
        return [f"программа не исполняется: {exc!r}"]
    return [] if got == v.answer.value else [f"исполнение даёт «{got}», ключ «{v.answer.value}»"]
