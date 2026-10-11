"""Семейство «Трассировка словарей и списков»: подсчёт, множества, ссылки и поверхностная копия."""

from __future__ import annotations

import copy
from collections.abc import Callable
from random import Random

from app.modules.assessment.families._lib import names
from app.modules.assessment.families._lib.contract import AnswerSpec, CodeBlock, InputHint, Reject, Variant
from app.modules.assessment.families._lib.miniprog import ProgramError, run_source
from app.modules.assessment.families.registry import family_meta

META = family_meta(
    "code.trace_collections",
    version=1,
    feature_bounds={
        1: {"code_lines": (5, 5), "trace_steps": (10, 60), "nesting_depth": (1, 1), "concepts": (2, 2),
            "answer_abs": (2, 40), "trap": (1, 1)},
        2: {"code_lines": (6, 7), "trace_steps": (10, 60), "nesting_depth": (2, 2), "concepts": (3, 3),
            "answer_abs": (1, 80), "trap": (1, 1)},
        3: {"code_lines": (5, 8), "trace_steps": (4, 40), "nesting_depth": (0, 1), "concepts": (3, 4),
            "answer_abs": (2, 80), "trap": (1, 1)},
    },
    # Реестр знает только `copy_instead_of_alias` (уровень 3); для уровней 1 и 2 добавлены свои модели ошибок.
    misconceptions=("copy_instead_of_alias", "overwrite_instead_of_count", "dup_in_set"),
)  # fmt: skip

Model = Callable[[str | None], int]


def _level1(rng: Random, cnt: str, key_var: str) -> tuple[str, Model, int]:
    """Подсчёт в словаре: `counts[k] = counts.get(k, 0) + w`; вопрос — значение по ключу."""
    letters = list("abcd")[: rng.randint(3, 4)]
    size = rng.randint(6, 7)
    pairs = [(rng.choice(letters), rng.randint(1, 4)) for _ in range(size)]
    repeated = sorted({k for k, _ in pairs if sum(1 for q, _ in pairs if q == k) >= 2})
    if not repeated:
        raise Reject("no_repeated_key")
    target = rng.choice(repeated)
    items = ", ".join(f'("{k}", {w})' for k, w in pairs)
    src = (
        f"data = [{items}]\n{cnt} = {{}}\nfor {key_var}, w in data:\n"
        f"    {cnt}[{key_var}] = {cnt}.get({key_var}, 0) + w\n"
        f'print({cnt}["{target}"])'
    )

    def model(flag: str | None) -> int:
        out = 0
        for k, w in pairs:
            if k == target:
                out = w if flag == "overwrite_instead_of_count" else out + w
        return out

    return src, model, 2


def _level2(rng: Random, seen: str) -> tuple[str, Model, int]:
    """Множество остатков по элементам, прошедшим фильтр; вопрос — размер или сумма множества."""
    size = rng.randint(7, 9)
    m = rng.randint(5, 9)
    data = [rng.randint(1, 40) for _ in range(size)]
    flt_kind = rng.choice(["gt", "parity"])
    if flt_kind == "gt":
        t = rng.randint(5, 20)
        flt_text, flt = f"x > {t}", lambda x: x > t
    else:
        p = rng.randint(0, 1)
        flt_text, flt = f"x % 2 == {p}", lambda x: x % 2 == p
    ask = rng.choice(["len", "sum"])
    lit = "[" + ", ".join(map(str, data)) + "]"
    src = (
        f"nums = {lit}\n{seen} = set()\nfor x in nums:\n    if {flt_text}:\n        {seen}.add(x % {m})\n"
        f"print({'len' if ask == 'len' else 'sum'}({seen}))"
    )

    def model(flag: str | None) -> int:
        passed = [x % m for x in data if flt(x)]
        pool = passed if flag == "dup_in_set" else sorted(set(passed))
        return len(pool) if ask == "len" else sum(pool)

    return src, model, 3


def _level3(rng: Random) -> tuple[str, Model, int]:
    """Два имени на один список или поверхностная копия вложенного списка."""
    if rng.random() < 0.5:
        data = [rng.randint(1, 9) for _ in range(rng.randint(4, 5))]
        ops = []
        for _ in range(rng.randint(2, 3)):
            ops.append(rng.choice(["append", "set", "pop"]))
        args = [rng.randint(1, 9) for _ in ops]
        idx = [rng.randrange(len(data) - 1) for _ in ops]
        lines = []
        for op, arg, ix in zip(ops, args, idx, strict=True):
            lines.append({"append": f"b.append({arg})", "set": f"b[{ix}] = {arg}", "pop": "b.pop()"}[op])
        src = f"a = {data}\nb = a\n" + "\n".join(lines) + "\nprint(sum(a))"

        def apply(a: list[int], b: list[int]) -> None:
            for op, arg, ix in zip(ops, args, idx, strict=True):
                if op == "append":
                    b.append(arg)
                elif op == "set":
                    b[ix] = arg
                else:
                    b.pop()

        def _alias_model(flag: str | None) -> int:
            a = list(data)
            b = list(a) if flag == "copy_instead_of_alias" else a
            apply(a, b)
            return sum(a)

        return src, _alias_model, 3
    rows = [[rng.randint(1, 9) for _ in range(rng.randint(1, 3))] for _ in range(3)]
    extra, add = rng.randint(1, 9), rng.randint(1, 9)
    row = rng.randrange(3)
    copier = rng.choice(["a[:]", "list(a)", "a.copy()"])
    src = f"a = {rows}\nb = {copier}\nb[{row}].append({add})\nb.append([{extra}])\nprint(sum(a[{row}]) + len(a))"

    def _shallow_copy_model(flag: str | None) -> int:
        a = copy.deepcopy(rows)
        b = copy.deepcopy(a) if flag == "copy_instead_of_alias" else list(a)
        b[row].append(add)
        b.append([extra])
        return sum(a[row]) + len(a)

    return src, _shallow_copy_model, 4


def generate(level: int, seed: int) -> Variant:
    """Вариант: программа над словарями, множествами и списками; вопрос — напечатанное целое число.

    Уровень 1 — подсчёт со взвешиванием в словаре (ошибка `overwrite_instead_of_count`: значение перезаписывается,
    а не накапливается). Уровень 2 — множество остатков элементов, прошедших фильтр; печатается размер или сумма
    (ошибка `dup_in_set`: дубли считаются). Уровень 3 — два имени на один список или поверхностная копия
    вложенного списка (ошибка `copy_instead_of_alias`: кандидат считает, что присваивание или срез копируют
    всё). Ответ даёт модель на объектах Python с явной семантикой ссылок; вариант, где ошибка не меняет ответ,
    отбрасывается. Ответ однозначен: программа детерминирована.
    """
    rng = Random(seed)
    cnt = names.pick(rng, names.DICT_VARS[:4])
    seen_name = names.pick(rng, ("seen", "found", "uniq", "marks"))
    key_var = names.pick(rng, ("k", "key", "name"))
    if level == 1:
        src, model, concepts = _level1(rng, cnt, key_var)
        depth, main = 1, "overwrite_instead_of_count"
    elif level == 2:
        src, model, concepts = _level2(rng, seen_name)
        depth, main = 2, "dup_in_set"
    elif level == 3:
        src, model, concepts = _level3(rng)
        depth, main = 0, "copy_instead_of_alias"
    else:
        raise ValueError(f"нет уровня {level}")
    answer = model(None)
    bad = model(main)
    if bad == answer:
        raise Reject("misconception_equals_answer")
    if answer < 2:
        raise Reject("trivial_answer")
    try:
        steps = run_source(src).steps
    except ProgramError as exc:
        raise Reject("program_error") from exc
    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt="Что напечатает программа? Ответ — целое число.",
        code=CodeBlock(language="python", text=src),
        input=InputHint(placeholder="целое число", max_length=8),
        answer=AnswerSpec.numeric(answer),
        misconception_answers={main: bad},
        features={
            "code_lines": src.count("\n") + 1,
            "trace_steps": steps,
            "nesting_depth": depth,
            "concepts": concepts,
            "answer_abs": abs(answer),
            "trap": 1,
        },
        explanation=f"Модель программы даёт {answer}. Ответ модели ошибки {main}: {bad}.",
    )


def selfcheck(v: Variant) -> list[str]:
    """Перепроверка: исполнение отрендеренного текста в пустом пространстве имён даёт ответ модели (§2.5)."""
    assert v.code is not None
    problems = []
    try:
        if run_source(v.code.text).printed != str(v.answer.value):
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
