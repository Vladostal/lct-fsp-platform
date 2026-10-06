"""Линтер вариантов: правила L01–L10 (Арх. 5.3; приложение A, §2.7).

Линтер проверяет то, что одинаково для всех семейств, чтобы авторы не писали это каждый сам:

* `lint_variant` — правила одного варианта: L01 схема и размеры, L02 `selfcheck`, L03 проверка ответа общей
  функцией `grade`, L04 признаки в границах уровня, L05 уникальность содержания, L06 детерминизм, L07 различимость,
  L08 однозначность числового ответа с допуском, L10 пределы трассы и величины ответа;
* `AnswerBalance` — правило L09 о распределении ответов по уровню. Оно применяется при наборе уровня: вариант,
  который довёл бы долю одного ответа выше предела, отбрасывается с кодом L09 и сборка берёт следующий seed.
  Так уровень с перекосом ответов либо выравнивается, либо не набирает квоту и не принимается.

Чистые функции без базы и настроек.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.modules.assessment.families._lib.contract import (
    Family,
    FamilyMeta,
    ItemKind,
    LevelMeta,
    Variant,
    canonical_json,
    content_hash,
    raw_answer_for,
    variant_answer_json,
    variant_to_json,
)
from app.modules.assessment.grading import grade

__all__ = ["LIMITS", "AnswerBalance", "LintIssue", "lint_variant"]

#: Пределы правил L01, L09, L10 — единственное место, где они записаны числами.
LIMITS: dict[str, float] = {
    "prompt_chars": 600,
    "code_lines": 30,
    "code_columns": 88,
    "tables": 3,
    "table_rows": 8,
    "table_columns": 6,
    "options_min": 2,
    "options_max": 8,
    "pick_line_min_lines": 8,
    "trace_steps": 80,
    "answer_abs": 1_000_000,
    "top_answer_share": 0.25,
    "position_share_margin": 0.10,
    "trivial_share": 0.10,
}


@dataclass(frozen=True)
class LintIssue:
    """Нарушение правила: код `L01`…`L10` и пояснение для автора семейства."""

    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


def _schema(meta: FamilyMeta, v: Variant, level: LevelMeta | None) -> list[str]:
    """L01: поля соответствуют виду задания, размеры условия в пределах."""
    out: list[str] = []
    kind = v.kind
    if level is None:
        out.append(f"у семейства нет уровня {v.level}")
    if (v.family_id, v.family_version) != (meta.id, meta.version):
        out.append("family_id или family_version варианта не совпадают с META")
    if kind not in meta.kinds:
        out.append(f"вид {kind.value} не разрешён семейству ({', '.join(k.value for k in meta.kinds)})")
    prompt = v.prompt.strip()
    if not prompt or len(v.prompt) > LIMITS["prompt_chars"]:
        out.append(f"условие пустое или длиннее {int(LIMITS['prompt_chars'])} знаков ({len(v.prompt)})")
    if "```" in v.prompt:
        out.append("в условии разметка кода: код передаётся полем code")
    if not v.explanation.strip():
        out.append("нет разбора (explanation): он нужен эксперту для ручной проверки ключа")
    code_lines = v.code.text.split("\n") if v.code is not None else []
    if v.code is not None:
        if not v.code.text.strip() or len(code_lines) > LIMITS["code_lines"]:
            out.append(f"код пустой или длиннее {int(LIMITS['code_lines'])} строк ({len(code_lines)})")
        widest = max((len(line) for line in code_lines), default=0)
        if widest > LIMITS["code_columns"]:
            out.append(f"строка кода шире {int(LIMITS['code_columns'])} колонок ({widest})")
    for table in v.tables or ():
        if len(table.rows) > LIMITS["table_rows"] or not 1 <= len(table.columns) <= LIMITS["table_columns"]:
            out.append(f"таблица {table.title}: больше 8 строк или 6 столбцов")
        if any(len(row) != len(table.columns) for row in table.rows):
            out.append(f"таблица {table.title}: длина строки не равна числу столбцов")
        if any(not isinstance(cell, str) for row in table.rows for cell in row):
            out.append(f"таблица {table.title}: ячейки должны быть строками")
    if v.tables is not None and len(v.tables) > LIMITS["tables"]:
        out.append(f"таблиц больше {int(LIMITS['tables'])}")

    choice = kind in (ItemKind.SINGLE_CHOICE, ItemKind.MULTI_CHOICE)
    if choice:
        options = v.options or ()
        ids = [option.id for option in options]
        if not LIMITS["options_min"] <= len(options) <= LIMITS["options_max"]:
            out.append(f"вариантов выбора должно быть от 2 до 8 ({len(options)})")
        if ids != [f"o{i}" for i in range(1, len(ids) + 1)]:
            out.append("идентификаторы вариантов — «o1», «o2», … в порядке показа")
        if len({" ".join(option.text.split()) for option in options}) != len(options):
            out.append("тексты вариантов выбора повторяются")
        if kind is ItemKind.SINGLE_CHOICE and v.answer.option_id not in ids:
            out.append("верный вариант отсутствует среди вариантов выбора")
        if kind is ItemKind.MULTI_CHOICE and (not v.answer.option_ids or not set(v.answer.option_ids) <= set(ids)):
            out.append("верное подмножество пусто или содержит неизвестный вариант")
    elif v.options is not None:
        out.append("варианты выбора заданы у задания другого вида")
    if kind is ItemKind.ORDER_BLOCKS:
        ids = [block.id for block in v.blocks or ()]
        if len(ids) < 2 or sorted(v.answer.order) != sorted(ids) or len(set(ids)) != len(ids):
            out.append("порядок блоков должен быть перестановкой всех блоков задания")
    elif v.blocks is not None:
        out.append("блоки заданы у задания другого вида")
    if kind is ItemKind.PICK_LINE:
        if v.code is None or len(code_lines) < LIMITS["pick_line_min_lines"]:
            out.append(f"для выбора строки нужен код не короче {int(LIMITS['pick_line_min_lines'])} строк")
        if not v.answer.lines or any(not 1 <= line <= len(code_lines) for line in v.answer.lines):
            out.append("номер верной строки вне кода")
    if kind is ItemKind.NUMERIC_INPUT and (
        isinstance(v.answer.value, bool)
        or not isinstance(v.answer.value, int | float)
        or not math.isfinite(v.answer.value)
    ):
        out.append("числовой ответ должен быть конечным числом")
    if kind is ItemKind.TEXT_INPUT and (not isinstance(v.answer.value, str) or not v.answer.value.strip()):
        out.append("текстовый ответ пуст")
    if v.input is not None and kind not in (ItemKind.NUMERIC_INPUT, ItemKind.TEXT_INPUT):
        out.append("подсказка поля ввода задана у задания без поля ввода")
    return out


def _tolerance(v: Variant) -> float:
    value = v.answer.value
    if not isinstance(value, int | float):
        return 0.0
    return max(v.answer.tolerance_abs, v.answer.tolerance_rel * abs(value))


def lint_variant(
    family: Family,
    v: Variant,
    *,
    seen_hashes: set[str] | None = None,
    regenerate: Callable[[int, int], Variant] | None = None,
) -> list[LintIssue]:
    """Проверить вариант по правилам L01–L08 и L10; пустой список — вариант принят.

    * `seen_hashes` — отпечатки уже принятых вариантов той же пары «семейство, уровень» (L05). Множество
      не изменяется: отпечаток принятого варианта добавляет вызывающий;
    * `regenerate` — функция повторной генерации для L06; по умолчанию `family.generate`.

    При нарушении схемы (L01) остальные правила не проверяются: их выводы на сломанном варианте бессмысленны.
    """
    meta = family.meta
    level = next((item for item in meta.levels if item.level == v.level), None)
    issues = [LintIssue("L01", text) for text in _schema(meta, v, level)]
    if issues or level is None:
        return issues

    # L02: независимая перепроверка ответа самим семейством.
    try:
        problems = list(family.selfcheck(v))
    except Exception as exc:
        problems = [f"selfcheck упал: {type(exc).__name__}: {exc}"]
    issues += [LintIssue("L02", str(text)) for text in problems]

    # L07: без модели ошибки вариант не отличает знание от типичного заблуждения.
    answers = dict(v.misconception_answers)
    if not answers:
        issues.append(LintIssue("L07", "нет ни одного ответа модели ошибки (misconception_answers пуст)"))
    unknown = sorted(set(answers) - set(meta.misconceptions))
    if unknown:
        issues.append(LintIssue("L07", f"коды моделей ошибок не объявлены в META.misconceptions: {unknown}"))

    # L03: верный ответ проходит общую проверку, ответы моделей ошибок и прочие варианты выбора — нет.
    spec = variant_answer_json(v)
    kind = v.kind
    correct = v.answer.correct_value()
    try:
        if grade(kind, spec, raw_answer_for(kind, correct)).score != 1:
            issues.append(LintIssue("L03", "верный ответ не проходит общую проверку grade"))
        for code, value in sorted(answers.items()):
            if grade(kind, spec, raw_answer_for(kind, value)).score != 0:
                issues.append(LintIssue("L07", f"ответ модели ошибки {code} засчитывается как верный"))
        if kind is ItemKind.SINGLE_CHOICE:
            for option in v.options or ():
                if option.id != v.answer.option_id and grade(kind, spec, {"option_id": option.id}).score != 0:
                    issues.append(LintIssue("L03", f"неверный вариант {option.id} засчитывается"))
            stray = sorted(str(value) for value in answers.values() if value not in {o.id for o in v.options or ()})
            if stray:
                issues.append(LintIssue("L03", f"ответ модели ошибки — не идентификатор варианта: {stray}"))
    except Exception as exc:
        issues.append(LintIssue("L03", f"ответ не проверяется функцией grade: {type(exc).__name__}: {exc}"))

    # L04: признаки сложности объявлены и лежат в границах уровня.
    for key, value in sorted(v.features.items()):
        bounds = level.feature_bounds.get(key)
        if bounds is None:
            issues.append(LintIssue("L04", f"признак {key} не имеет границ в feature_bounds уровня {v.level}"))
        elif not bounds[0] <= value <= bounds[1]:
            issues.append(LintIssue("L04", f"признак {key}={value} вне границ {bounds[0]}…{bounds[1]}"))

    # L05: то же содержание под другим seed — не новый вариант.
    if seen_hashes is not None and content_hash(v) in seen_hashes:
        issues.append(LintIssue("L05", "содержание повторяет уже принятый вариант уровня"))

    # L06: повторный вызов даёт побайтно тот же JSON.
    try:
        again = (regenerate or family.generate)(v.level, v.seed)
        if canonical_json(variant_to_json(again)) != canonical_json(variant_to_json(v)):
            issues.append(LintIssue("L06", "повторный generate(level, seed) дал другой вариант"))
    except Exception as exc:
        issues.append(LintIssue("L06", f"повторный generate упал: {type(exc).__name__}: {exc}"))

    # L08: ответ модели ошибки не должен попадать в допуск верного ответа и стоять вплотную к нему.
    tolerance = _tolerance(v)
    if kind is ItemKind.NUMERIC_INPUT and tolerance > 0:
        for code, value in sorted(answers.items()):
            if isinstance(value, int | float) and abs(value - float(correct)) <= 2 * tolerance:
                issues.append(LintIssue("L08", f"ответ модели ошибки {code} ближе двух допусков к верному"))

    # L10: задание решается в уме за отведённое время.
    if v.features.get("trace_steps", 0) > LIMITS["trace_steps"]:
        issues.append(LintIssue("L10", f"trace_steps больше {int(LIMITS['trace_steps'])}"))
    answer_abs = max(
        v.features.get("answer_abs", 0),
        abs(correct) if kind is ItemKind.NUMERIC_INPUT else 0,
    )
    if answer_abs > LIMITS["answer_abs"]:
        issues.append(LintIssue("L10", "модуль числового ответа больше 10^6"))
    return issues


def answer_key(v: Variant) -> str:
    """Значение ответа для подсчёта распределения (L09): то, что кандидат мог бы запомнить и передать другому.

    У выбора одного варианта это текст верного варианта, а не его позиция: позицию считает отдельное условие.
    """
    if v.kind is ItemKind.SINGLE_CHOICE:
        text = next((o.text for o in v.options or () if o.id == v.answer.option_id), "")
        return " ".join(text.split())
    value: Any = v.answer.correct_value()
    if v.kind is ItemKind.TEXT_INPUT:
        value = grade(v.kind, variant_answer_json(v), {"value": value}).normalized
    return canonical_json(value)


def is_trivial(v: Variant) -> bool:
    """Тривиальный числовой ответ: 0, 1 или число строк одной из таблиц условия."""
    if v.kind is not ItemKind.NUMERIC_INPUT:
        return False
    value = v.answer.value
    return value in (0, 1) or any(value == len(table.rows) for table in v.tables or ())


@dataclass
class AnswerBalance:
    """Правило L09 при наборе уровня из `quota` вариантов.

    Пределы — доли от квоты, а не от уже набранного: иначе первый же вариант нарушал бы правило.

    * доля самого частого ответа — не выше 0.25; у выбора одного варианта из k предел для текста верного варианта
      и для его позиции — `1/k + 0.10` (при четырёх вариантах предел 0.25 недостижим арифметически);
    * тривиальные числовые ответы (0, 1, число строк таблицы) — не чаще 10 %.
    """

    quota: int
    values: Counter[str] = field(default_factory=Counter)
    positions: Counter[str] = field(default_factory=Counter)
    trivial: int = 0

    def _cap(self, share: float) -> int:
        return max(1, math.floor(share * self.quota + 1e-9))

    def check(self, v: Variant) -> list[LintIssue]:
        """Нарушит ли приём варианта распределение ответов уровня."""
        issues = []
        share = LIMITS["top_answer_share"]
        if v.kind is ItemKind.SINGLE_CHOICE:
            share = 1 / max(1, len(v.options or ())) + LIMITS["position_share_margin"]
            if self.positions[str(v.answer.option_id)] >= self._cap(share):
                issues.append(LintIssue("L09", f"верный вариант слишком часто стоит на месте {v.answer.option_id}"))
        if self.values[answer_key(v)] >= self._cap(share):
            issues.append(LintIssue("L09", f"ответ повторяется чаще, чем в {share:.0%} вариантов уровня"))
        if is_trivial(v) and self.trivial >= self._cap(LIMITS["trivial_share"]):
            issues.append(LintIssue("L09", "тривиальный ответ (0, 1, число строк таблицы) чаще, чем в 10 % вариантов"))
        return issues

    def add(self, v: Variant) -> None:
        """Учесть принятый вариант."""
        self.values[answer_key(v)] += 1
        if v.kind is ItemKind.SINGLE_CHOICE:
            self.positions[str(v.answer.option_id)] += 1
        if is_trivial(v):
            self.trivial += 1
