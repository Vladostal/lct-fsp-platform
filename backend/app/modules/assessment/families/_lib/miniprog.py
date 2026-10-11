"""Мини-программы для семейств `code`, `algo`, `ds` (приложение A, §2.2, §2.5).

Здесь не интерпретатор общего назначения, а две вещи, которые нужны всем генераторам трассировки:

* `run_source` — исполнение отрендеренного текста программы в пустом пространстве имён с урезанными встроенными
  функциями, ограничением числа строк и подсчётом выполненных строк (`trace_steps`). Это наш код, не код
  кандидата: кандидатский код не исполняется нигде (приложение A, §2.3);
* `render_list`, `tokens` — единый формат вывода списков и чисел, чтобы условие и ключ совпадали символ в символ.

Модель ответа в семействе пишется отдельно, обычными функциями Python в другом стиле, чем текст программы; `run_source`
служит перепроверкой (`selfcheck`) и независимым оракулом (`oracle_check`).
"""

from __future__ import annotations

import builtins
import contextlib
import copy
import io
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from random import Random
from typing import Any

from app.modules.assessment.families._lib.contract import Reject

__all__ = [
    "BATTERY_SIZE",
    "SAFE_BUILTINS",
    "BugCase",
    "BugTemplate",
    "ProgramError",
    "RunResult",
    "assemble_bug",
    "battery",
    "bug_explanation",
    "bug_misconceptions",
    "bug_prompt",
    "call_function",
    "check_bug_variant",
    "fast_call",
    "oracle_bug",
    "parse_bug",
    "render_list",
    "render_template",
    "run_call",
    "run_source",
    "tokens",
]

#: Встроенные функции, доступные программам банка. Ни `open`, ни `import`, ни `eval`.
SAFE_BUILTINS: dict[str, Any] = {
    name: getattr(builtins, name)
    for name in (
        "range", "len", "print", "sum", "min", "max", "abs", "sorted", "list", "set", "dict", "tuple",
        "enumerate", "zip", "reversed", "int", "str", "bool", "isinstance", "any", "all",
    )
}  # fmt: skip

#: Предел выполненных строк: защита от зависшей мутации (программа банка не должна исполняться дольше).
DEFAULT_MAX_STEPS = 200_000


class ProgramError(Exception):
    """Программа не завершилась штатно: исключение, превышение числа шагов или запрещённая конструкция."""


@dataclass
class RunResult:
    """Итог исполнения: напечатанное, пространство имён и число выполненных строк."""

    printed: str
    namespace: dict[str, Any]
    steps: int
    line_hits: Counter[int] = field(default_factory=Counter)


def _execute(source: str, namespace: dict[str, Any], max_steps: int) -> tuple[int, Counter[int], str]:
    """Исполнить `source` в `namespace` под трассировкой; вернуть число строк, попадания и напечатанное."""
    buffer = io.StringIO()
    hits: Counter[int] = Counter()
    code = compile(source, "<program>", "exec")
    total = 0

    def tracer(frame: Any, event: str, _arg: Any) -> Any:
        nonlocal total
        if frame.f_code.co_filename != "<program>":
            return None
        if event == "line":
            total += 1
            hits[frame.f_lineno] += 1
            if total > max_steps:
                raise ProgramError("превышено число шагов")
        return tracer

    previous = sys.gettrace()
    try:
        sys.settrace(tracer)
        with contextlib.redirect_stdout(buffer):
            exec(code, namespace)
    except ProgramError:
        raise
    except Exception as exc:
        raise ProgramError(f"{type(exc).__name__}: {exc}") from exc
    finally:
        sys.settrace(previous)
    return total, hits, buffer.getvalue().strip()


def run_source(source: str, *, max_steps: int = DEFAULT_MAX_STEPS) -> RunResult:
    """Исполнить текст программы; вернуть напечатанное, имена и число выполненных строк.

    `steps` — число событий «выполняется строка» внутри исполняемого кода (определения функций считаются
    по одной строке). `line_hits` — сколько раз выполнена каждая строка (нумерация с 1).
    """
    namespace: dict[str, Any] = {"__builtins__": dict(SAFE_BUILTINS)}
    total, hits, printed = _execute(source, namespace, max_steps)
    return RunResult(printed, namespace, total, hits)


def call_function(source: str, name: str, *args: Any, max_steps: int = DEFAULT_MAX_STEPS) -> Any:
    """Определить функции из `source` и вызвать `name(*args)`; результат возвращается, а не печатается.

    Аргументы изменяются на месте, как в обычном вызове: вызывающий передаёт свежие списки.
    """
    namespace: dict[str, Any] = {"__builtins__": dict(SAFE_BUILTINS), "_args": args}
    _execute(f"{source}\n_result = {name}(*_args)\n", namespace, max_steps)
    return namespace["_result"]


def fast_call(source: str, name: str, *args: Any) -> Any:
    """Вызвать функцию из `source` без трассировки (для подсчёта операций на больших входах).

    Защиты от зависания нет: вызывать только для программ, построенных генератором (они всегда завершаются).
    """
    namespace: dict[str, Any] = {"__builtins__": dict(SAFE_BUILTINS)}
    exec(compile(source, "<program>", "exec"), namespace)
    return namespace[name](*args)


def render_list(values: Iterable[Any]) -> str:
    """Список в виде литерала Python: `[3, 1, 2]`."""
    return "[" + ", ".join(repr(v) for v in values) + "]"


def tokens(values: Sequence[Any]) -> str:
    """Ответ-перечисление: числа через пробел (режим `tokens` общей проверки)."""
    return " ".join(str(v) for v in values)


# --------------------------------------------------------------------------------------------------------------------
# Поиск ошибки: эталон, мутация одной строки, пример (приложение A, §2.5, строка «Поиск ошибки»)
# --------------------------------------------------------------------------------------------------------------------

#: Размер батареи входов для оценки редкости ошибки и поиска примера, на котором она видна.
BATTERY_SIZE = 40


BUG_NOTES: tuple[str, ...] = (
    "# входные данные не изменяются",
    "# результат нужен целиком",
    "# порядок элементов важен",
    "# работаем с обычным списком",
    "# пустой ввод не рассматриваем",
)


@dataclass(frozen=True)
class BugTemplate:
    """Эталонная функция и её мутации.

    `lines` — строки эталона; `$F`, `$A`, `$B` — имена функции и списков (подставляет `render_template`).
    `mutations` — пары «индекс строки (с 0) -> строка мутанта». `make_args` строит вход по `random.Random`;
    `spec` — независимая от текста эталона спецификация (однострочник на стандартных функциях Python).
    """

    key: str
    lines: tuple[str, ...]
    mutations: tuple[tuple[int, str], ...]
    make_args: Callable[[Random], tuple[Any, ...]]
    spec: Callable[..., Any]


@dataclass(frozen=True)
class BugCase:
    """Собранное задание: текст мутанта, номер испорченной строки (с 1), пример и доля входов, где ошибка видна."""

    template: str
    fname: str
    source: str
    reference_line: str
    line: int
    args: tuple[Any, ...]
    got: Any
    expected: Any
    share: float


def render_template(text: str, fname: str, first: str, second: str) -> str:
    """Подставить имена в строку шаблона."""
    return text.replace("$F", fname).replace("$A", first).replace("$B", second)


def run_call(source: str, fname: str, args: Sequence[Any]) -> tuple[bool, Any]:
    """Вызвать функцию на копии аргументов: (завершилась ли штатно, результат)."""
    try:
        return True, call_function(source, fname, *copy.deepcopy(list(args)), max_steps=4000)
    except ProgramError:
        return False, None


def battery(template: BugTemplate, seed: int) -> list[tuple[Any, ...]]:
    """Батарея входов; детерминирована по `seed`, поэтому оракул воспроизводит её сам."""
    rng = Random(seed ^ 0x5EED)
    return [template.make_args(rng) for _ in range(BATTERY_SIZE)]


def assemble_bug(
    rng: Random,
    template: BugTemplate,
    seed: int,
    fname: str,
    first: str,
    second: str,
    *,
    share_range: tuple[float, float],
) -> BugCase:
    """Собрать мутанта и пример; `Reject`, если ни одна мутация не подходит по редкости ошибки."""
    ref_lines = [render_template(line, fname, first, second) for line in template.lines]
    # Нейтральные комментарии сдвигают номера строк: без них верный ответ принимал бы лишь несколько значений (L09).
    notes = rng.sample(BUG_NOTES, rng.randint(1, 3))
    positions = list(range(len(ref_lines)))  # где окажется каждая строка шаблона после вставки комментариев
    for note in notes:
        at = rng.randint(1, len(ref_lines))
        ref_lines.insert(at, "    " + note)
        positions = [pos + 1 if pos >= at else pos for pos in positions]
    cases = battery(template, seed)
    fails: list[tuple[tuple[Any, ...], Any]] = []
    share = 0.0
    index = 0
    source = ""
    # Мутации перебираются в случайном порядке: берётся первая, ошибка которой по редкости подходит уровню.
    for orig, mutated in rng.sample(list(template.mutations), len(template.mutations)):
        index = positions[orig]
        bad_lines = list(ref_lines)
        bad_lines[index] = render_template(mutated, fname, first, second)
        if bad_lines[index] == ref_lines[index]:
            continue
        source = "\n".join(bad_lines)
        fails = []
        for args in cases:
            expected = template.spec(*copy.deepcopy(list(args)))
            ok, got = run_call(source, fname, args)
            if not ok or got != expected:
                fails.append((args, got if ok else None))
        share = len(fails) / len(cases)
        if share_range[0] <= share <= share_range[1]:
            break
    else:
        raise Reject("rarity")
    shown = [(args, got) for args, got in fails if got is not None]
    if not shown:
        raise Reject("no_example")
    args, got = shown[0]
    return BugCase(
        template.key, fname, source, ref_lines[index], index + 1, args, got,
        template.spec(*copy.deepcopy(list(args))), share,
    )  # fmt: skip


def bug_misconceptions(lines: Sequence[str], answer: int, kinds: Sequence[str]) -> dict[str, int]:
    """Ответы моделей ошибок для задания «найди строку»: указать не ту строку.

    `blame_loop_header` — заголовок первого цикла; `blame_return_line` — последний `return`;
    `blame_neighbor_line` — соседняя с испорченной строка. Совпавшие с верной строкой не возвращаются.
    """
    out: dict[str, int] = {}
    for kind in kinds:
        if kind == "blame_loop_header":
            guess = next((i for i, text in enumerate(lines, 1) if text.strip().startswith(("for ", "while "))), None)
        elif kind == "blame_return_line":
            guess = max((i for i, text in enumerate(lines, 1) if text.strip().startswith("return")), default=None)
        else:
            guess = answer + 1 if answer < len(lines) else answer - 1
        if guess is not None and guess != answer:
            out[kind] = guess
    return out


def check_bug_variant(
    templates: dict[str, BugTemplate], text: str, line: int, reference_line: str, key: str, seed: int, fname: str
) -> list[str]:
    """Общая перепроверка заданий «найди строку»: возврат эталонной строки чинит мутанта, мутант падает на примере.

    Эталон проходит батарею входов против `spec`; замена любой другой строки на эталонную ничего не меняет, потому
    что мутант отличается от эталона ровно одной строкой.
    """
    template = templates[key]
    lines = text.split("\n")
    problems: list[str] = []
    if not 1 <= line <= len(lines):
        return ["номер строки вне кода"]
    fixed = list(lines)
    fixed[line - 1] = reference_line
    cases = battery(template, seed)
    for args in cases:
        expected = template.spec(*copy.deepcopy(list(args)))
        ok, got = run_call("\n".join(fixed), fname, args)
        if not ok or got != expected:
            problems.append(f"после возврата эталонной строки функция неверна на входе {args!r}")
            break
    if all(run_call(text, fname, args) == (True, template.spec(*copy.deepcopy(list(args)))) for args in cases):
        problems.append("мутант проходит всю батарею: ошибки нет")
    return problems


def bug_prompt(description: str, case: BugCase) -> str:
    """Условие задания «найди строку»: описание, неверный вызов, вопрос. Формат разбирают `selfcheck` и оракул."""
    shown = ", ".join(repr(arg) for arg in case.args)
    return (
        f"{description} Вызов {case.fname}({shown}) возвращает {case.got!r}, а должен вернуть {case.expected!r}. "
        "В какой строке кода ошибка? Укажите номер строки (нумерация с 1)."
    )


def bug_explanation(case: BugCase) -> str:
    """Разбор для эксперта; из него `selfcheck` берёт ключ шаблона и эталонную строку."""
    return (
        f"Шаблон {case.template}. Испорчена строка {case.line}; эталон: {case.reference_line!r}. "
        f"Ошибка видна на {case.share:.0%} входов батареи."
    )


def parse_bug(prompt: str, explanation: str) -> tuple[str, str, int, str, tuple[Any, ...], Any, Any]:
    """Разобрать вариант: (ключ шаблона, имя функции, строка, эталонная строка, вход, получено, ожидалось)."""
    import ast
    import re

    call = re.search(r"Вызов (\w+)\((.*)\) возвращает (.+?), а должен вернуть (.+?)\. В какой", prompt, re.S)
    info = re.search(r"Шаблон (\w+)\. Испорчена строка (\d+); эталон: (.+?)\. Ошибка видна", explanation, re.S)
    if call is None or info is None:
        raise ValueError("не удалось разобрать условие или разбор задания «найди строку»")
    args = ast.literal_eval(f"({call.group(2)},)")
    return (
        info.group(1), call.group(1), int(info.group(2)), ast.literal_eval(info.group(3)), args,
        ast.literal_eval(call.group(3)), ast.literal_eval(call.group(4)),
    )  # fmt: skip


def oracle_bug(templates: dict[str, BugTemplate], v: Any) -> list[str]:
    """Оракул CPython для заданий «найди строку»: настоящий `exec` без урезанных встроенных и без трассировки.

    Проверяется: мутант на примере из условия возвращает названное значение, а спецификация — ожидаемое;
    с возвращённой эталонной строкой функция совпадает со спецификацией на всей батарее.
    """
    key, fname, line, ref, args, got, expected = parse_bug(v.prompt, v.explanation)
    template = templates[key]
    problems: list[str] = []

    def call(source: str, call_args: Sequence[Any]) -> Any:
        scope: dict[str, Any] = {}
        exec(source, scope)
        return scope[fname](*copy.deepcopy(list(call_args)))

    if call(v.code.text, args) != got:
        problems.append("CPython на примере из условия вернул другое значение, чем названо в условии")
    if template.spec(*copy.deepcopy(list(args))) != expected:
        problems.append("спецификация на примере дала не то значение, что названо как ожидаемое")
    lines = v.code.text.split("\n")
    lines[line - 1] = ref
    fixed = "\n".join(lines)
    for case_args in battery(template, v.seed):
        if call(fixed, case_args) != template.spec(*copy.deepcopy(list(case_args))):
            problems.append(f"с эталонной строкой функция неверна на входе {case_args!r}")
            break
    return problems
