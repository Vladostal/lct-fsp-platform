"""Семейство `py.exceptions_flow`: порядок обработки исключений и очистки (text_input, режим tokens).

Уровень 1 — порядок `try/except/else/finally` при исключении и без него. Уровень 2 — `return` в `try`, `except` и
`finally`, вложенные блоки с повторным `raise`. Уровень 3 — менеджеры контекста: вход, выход, подавление исключения.
Ответ — метки в порядке вывода (и возвращаемые значения), полученные настоящим исполнением текста в CPython (в реестре
оракул `builtin`). Модели ошибок исполняют изменённый текст: `else_runs_after_except` (блок else выполняется и после
except), `finally_skipped_on_return` (finally не выполняется, если функция вернулась раньше), `finally_return_ignored`
(`return` в finally не перебивает результат), `finally_runs_last` (finally после внешнего обработчика),
`exit_not_called_on_error` (`__exit__` не вызывается при исключении). Ответ однозначен: программа детерминирована.
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
    "py.exceptions_flow",
    version=2,
    feature_bounds={
        1: {"code_lines": (10, 17), "concepts": (3, 4), "nesting_depth": (2, 2)},
        2: {"code_lines": (9, 19), "concepts": (3, 4), "nesting_depth": (2, 4)},
        3: {"code_lines": (14, 22), "concepts": (3, 5), "nesting_depth": (3, 4)},
    },
    misconceptions=(
        "else_runs_after_except",
        "finally_skipped_on_return",
        "finally_return_ignored",
        "finally_runs_last",
        "exit_not_called_on_error",
    ),
)

_BUILTINS = {
    name: getattr(builtins, name)
    for name in ("print", "ValueError", "KeyError", "ZeroDivisionError", "Exception", "object", "range")
}
_BUILTINS["__build_class__"] = __build_class__


def run(source: str) -> str:
    """Исполнить текст программы в ограниченном пространстве имён; вернуть вывод токенами через пробел.

    Исполняются шаблоны самого генератора, а не код кандидата.
    """
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exec(compile(source, "<variant>", "exec"), {"__builtins__": _BUILTINS, "__name__": "__main__"})
    return " ".join(buffer.getvalue().split())


Template = tuple[str, dict[str, str], int]
LABELS = names.LABELS


def _t_try_else(rng: Random) -> Template:
    a, b, c, d, e, f = rng.sample(LABELS, 6)
    use_else, use_finally = True, rng.random() < 0.7
    raise_first = rng.random() < 0.4
    args = [0, rng.choice((2, 3, 4, 5))]
    rng.shuffle(args)
    fn = names.pick(rng, names.FUNC_NAMES)

    def render(else_after_except: bool) -> str:
        risky = "        v = 12 // x\n"
        body = (
            f'        print("{a}")\n{risky}        print("{b}")\n'
            if not raise_first
            else f'{risky}        print("{a}")\n        print("{b}")\n'
        )
        out = f'def {fn}(x):\n    try:\n{body}    except ZeroDivisionError:\n        print("{c}")\n'
        if else_after_except and use_else:
            out += f'        print("{d}")\n'
        if use_else:
            out += f'    else:\n        print("{d}")\n'
        if use_finally:
            out += f'    finally:\n        print("{e}")\n'
        out += f'    print("{f}")\n'
        return out + f"{fn}({args[0]})\n{fn}({args[1]})"

    return render(False), {"else_runs_after_except": render(True)} if use_else else {}, 3 + use_else


def _t_return_finally(rng: Random) -> Template:
    a, b, c = rng.sample(LABELS, 3)
    x, y, z = rng.sample(("X", "Y", "Z", "W", "V"), 3)
    limit = rng.randint(2, 5)
    args = [rng.randint(0, limit - 1), rng.randint(limit + 1, limit + 4)]
    rng.shuffle(args)
    fin_return = rng.random() < 0.4
    nested = not fin_return and rng.random() < 0.4
    d, e = rng.sample([lab for lab in LABELS if lab not in (a, b, c)], 2)

    if nested:  # вложенный try: исключение заменяется в except внутреннего блока, finally стоит внутри

        def render_nested(late: bool) -> str:
            fin = f'            print("{c}")\n'
            inner = (
                "        try:\n"
                f'            print("{a}")\n'
                f"            if n > {limit}:\n"
                "                raise KeyError\n"
                f'            print("{b}")\n'
                "        except KeyError:\n"
                f'            print("{d}")\n'
                "            raise ValueError\n"
            )
            inner += "" if late else f"        finally:\n{fin}"
            tail = f'        print("{e}")\n' + (f'        print("{c}")\n' if late else "")
            return (
                "def g(n):\n    try:\n"
                + inner
                + "    except ValueError:\n"
                + tail
                + f'    print("{x}")\n'
                + f"g({args[0]})\ng({args[1]})"
            )

        return render_nested(False), {"finally_runs_last": render_nested(True)}, 4

    def render(variant: str) -> str:
        fin_ret = f'        return "{z}"\n' if fin_return and variant != "ignored" else ""
        if variant == "skipped":
            fin_block = ""
            after = f'    print("{c}")\n'
        else:
            fin_block = f'    finally:\n        print("{c}")\n{fin_ret}'
            after = ""
        return (
            "def f(n):\n    try:\n"
            f'        print("{a}")\n'
            f"        if n > {limit}:\n            raise ValueError\n"
            f'        return "{x}"\n'
            f'    except ValueError:\n        print("{b}")\n        return "{y}"\n'
            + fin_block
            + after
            + f"print(f({args[0]}), f({args[1]}))"
        )

    alt = (
        {"finally_return_ignored": render("ignored")}
        if fin_return
        else {"finally_skipped_on_return": render("skipped")}
    )
    return render("true"), alt, 3 + fin_return


def _t_context(rng: Random) -> Template:
    p, q = rng.sample(("p", "q", "r", "db", "file", "lock", "net"), 2)
    raise_inside = rng.random() < 0.8
    quiet_q = rng.random() < 0.5
    quiet_p = not quiet_q and rng.random() < 0.5
    raise_cls = rng.choice(("KeyError", "ValueError"))
    catch = raise_cls if rng.random() < 0.7 else "Exception"

    def render(skip_exit: bool) -> str:
        guard = "        if kind is None:\n    " if skip_exit else ""
        exit_body = f'        {"    " if skip_exit else ""}print("out", self.name)\n'
        if skip_exit:
            exit_body = '        if kind is None:\n            print("out", self.name)\n'
        _ = guard
        return (
            "class Ctx:\n"
            "    def __init__(self, name, quiet):\n"
            "        self.name = name\n"
            "        self.quiet = quiet\n"
            "    def __enter__(self):\n"
            '        print("in", self.name)\n'
            "        return self\n"
            "    def __exit__(self, kind, value, tb):\n"
            f"{exit_body}"
            "        return self.quiet\n"
            "try:\n"
            f'    with Ctx("{p}", {quiet_p}):\n'
            f'        with Ctx("{q}", {quiet_q}):\n'
            '            print("body")\n'
            + (f"            raise {raise_cls}\n" if raise_inside else "")
            + '        print("mid")\n'
            '    print("after")\n'
            f"except {catch}:\n"
            '    print("caught")\n'
            'print("end")'
        )

    return render(False), {"exit_not_called_on_error": render(True)}, 4 + raise_inside


TEMPLATES: dict[int, tuple] = {1: (_t_try_else,), 2: (_t_return_finally,), 3: (_t_context,)}


def generate(level: int, seed: int) -> Variant:
    """Вариант: программа с `try/except/else/finally`, `return` или менеджерами контекста; вопрос — вывод.

    Ответ получается исполнением текста в CPython. Модели ошибок — исполнение изменённого текста (см. docstring
    модуля); вариант, где ни одна не меняет вывод, отбрасывается. Ответ однозначен: программа детерминирована,
    исключения создаются и перехватываются в самой программе.
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
    depth = max((len(line) - len(line.lstrip())) // 4 for line in source.split("\n"))
    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt="Что напечатает программа? Укажите всё, что она выведет, через пробел в порядке вывода.",
        code=CodeBlock(language="python", text=source),
        input=InputHint(placeholder="метки через пробел", max_length=80),
        answer=AnswerSpec.text(answer, mode="tokens"),
        misconception_answers=wrong,
        features={"code_lines": source.count("\n") + 1, "concepts": concepts, "nesting_depth": depth},
        explanation=f"Исполнение даёт «{answer}»; модели ошибок: {wrong}.",
    )


def selfcheck(v: Variant) -> list[str]:
    """Перепроверка: повторное исполнение текста из условия даёт тот же вывод."""
    assert v.code is not None
    try:
        got = run(v.code.text)
    except Exception as exc:
        return [f"программа не исполняется: {exc!r}"]
    return [] if got == v.answer.value else [f"исполнение даёт «{got}», ключ «{v.answer.value}»"]
