"""Учебное семейство «сумма в цикле»: трассировка короткой программы, ответ — напечатанное число.

Образец семейства вида `numeric_input` с кодом в условии. Что здесь показано:

* паспорт строится `family_meta`: уровни и `b` приходят из реестра, автор задаёт версию и границы признаков;
* единственный источник случайности — `random.Random(seed)`;
* верный ответ и ответы моделей ошибок считает одна модель `_run` с разными флагами;
* вырожденные параметры — `raise Reject("причина")`;
* `selfcheck` перепроверяет ответ вторым способом, `oracle_check` исполняет текст программы в CPython.
"""

from __future__ import annotations

import contextlib
import io
from random import Random

from app.modules.assessment.families._lib import names
from app.modules.assessment.families._lib.contract import AnswerSpec, CodeBlock, InputHint, Reject, Variant
from app.modules.assessment.families.registry import family_meta
from tests.assessment.fake_families import FAKE_SPECS

META = family_meta(
    "code.fake_sum",
    version=1,
    feature_bounds={
        1: {"code_lines": (5, 5), "trace_steps": (10, 40), "nesting_depth": (2, 2), "answer_abs": (2, 200)},
        2: {"code_lines": (8, 8), "trace_steps": (5, 70), "nesting_depth": (2, 2), "answer_abs": (2, 800)},
    },
    spec=FAKE_SPECS["code.fake_sum"],
)


def _run(p: dict[str, int], *, inclusive: bool = False, ignore_break: bool = False) -> tuple[int, int]:
    """Модель программы: (напечатанное значение, число выполненных операторов).

    `inclusive` — ошибка `off_by_one`: кандидат считает, что `range(a, b)` включает `b`.
    `ignore_break` — кандидат не замечает `break` и доводит цикл до конца.
    """
    total, steps = 0, 1
    for i in range(p["start"], p["stop"] + (1 if inclusive else 0)):
        steps += 2
        if p["level"] == 1:
            if i % p["mod"] == p["rem"]:
                total += i
                steps += 1
            continue
        if i % p["mod"] == p["rem"]:
            steps += 1
            continue
        total += i * p["factor"]
        steps += 2
        if total > p["limit"] and not ignore_break:
            steps += 1
            break
    return total, steps + 1


def _render(p: dict[str, int], total: str, i: str) -> str:
    if p["level"] == 1:
        return (
            f"{total} = 0\n"
            f"for {i} in range({p['start']}, {p['stop']}):\n"
            f"    if {i} % {p['mod']} == {p['rem']}:\n"
            f"        {total} += {i}\n"
            f"print({total})"
        )
    return (
        f"{total} = 0\n"
        f"for {i} in range({p['start']}, {p['stop']}):\n"
        f"    if {i} % {p['mod']} == {p['rem']}:\n"
        f"        continue\n"
        f"    {total} += {i} * {p['factor']}\n"
        f"    if {total} > {p['limit']}:\n"
        f"        break\n"
        f"print({total})"
    )


def _params(level: int, rng: Random) -> dict[str, int]:
    start = rng.randint(1, 6)
    stop = start + rng.randint(5, 9)
    mod = rng.randint(2, 4)
    if level == 1:
        # Остаток подобран так, чтобы правая граница подходила под условие: тогда ошибка off_by_one меняет ответ.
        return {"level": level, "start": start, "stop": stop, "mod": mod, "rem": stop % mod}
    return {
        "level": level, "start": start, "stop": stop, "mod": mod, "rem": rng.randrange(mod),
        "factor": rng.randint(2, 4), "limit": rng.randrange(10, 45, 5),
    }  # fmt: skip


def generate(level: int, seed: int) -> Variant:
    """Вариант: программа с одним циклом; вопрос — что она напечатает.

    Уровень 1 — сумма чисел диапазона с заданным остатком от деления. Уровень 2 — пропуск через `continue`,
    умножение и выход по `break` при превышении порога. Ответ вычисляет модель `_run`. Модели ошибок:
    `off_by_one` (правая граница `range` включена) и `ignore_break` (цикл доходит до конца). Ответ однозначен:
    программа детерминирована и печатает одно целое число; варианты, где ошибка не меняет ответ, отбрасываются.
    """
    if level not in (1, 2):
        raise ValueError(f"нет уровня {level}")
    rng = Random(seed)
    p = _params(level, rng)
    total_var = names.pick(rng, names.NUM_VARS[:6])
    loop_var = names.pick(rng, names.LOOP_VARS)

    answer, steps = _run(p)
    models = {"off_by_one": _run(p, inclusive=True)[0]}
    if level == 2:
        models["ignore_break"] = _run(p, ignore_break=True)[0]
    # Модель ошибки, которая в этом варианте не меняет ответ, в вариант не попадает; главная модель уровня обязана
    # его менять, иначе вариант не отличает знание от заблуждения.
    wrong = {code: value for code, value in models.items() if value != answer}
    if ("off_by_one" if level == 1 else "ignore_break") not in wrong:
        raise Reject("misconception_equals_answer")
    if answer < 2:
        raise Reject("trivial_answer")

    code = _render(p, total_var, loop_var)
    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt="Что напечатает программа? Ответ — целое число.",
        code=CodeBlock(language="python", text=code),
        input=InputHint(placeholder="целое число", max_length=8),
        answer=AnswerSpec.numeric(answer),
        misconception_answers=wrong,
        features={
            "code_lines": code.count("\n") + 1,
            "trace_steps": steps,
            "nesting_depth": 2,
            "answer_abs": abs(answer),
        },
        explanation=(
            f"Цикл проходит значения от {p['start']} до {p['stop'] - 1}: правая граница range не входит. "
            f"Итог: {answer}. Ответы моделей ошибок: {wrong}."
        ),
    )


def _exec_output(code: str) -> str:
    """Исполнить текст программы в пустом пространстве имён и вернуть напечатанное. Это наш код, не код кандидата."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exec(code, {"__builtins__": {"range": range, "print": print}})
    return buffer.getvalue().strip()


def selfcheck(v: Variant) -> list[str]:
    """Перепроверка: исполнение отрендеренного текста даёт тот же ответ, что и модель (приложение A, §2.5)."""
    assert v.code is not None
    problems = []
    if _exec_output(v.code.text) != str(v.answer.value):
        problems.append("исполнение текста программы расходится с ответом модели")
    if v.code.text.count("\n") + 1 != v.features["code_lines"]:
        problems.append("признак code_lines не равен числу строк кода")
    return problems


def oracle_check(v: Variant) -> list[str]:
    """Сверка ключа с независимым оракулом (Арх. 5.3): здесь оракул — CPython, исполняющий тот же текст."""
    assert v.code is not None
    printed = _exec_output(v.code.text)
    return [] if printed == str(v.answer.value) else [f"CPython напечатал {printed}, ключ {v.answer.value}"]
