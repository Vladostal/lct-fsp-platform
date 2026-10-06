"""Проверка ответа кандидата — одна функция на все виды заданий (Арх. 5.3; приложение A, §2.4).

Семейства свою проверку не пишут: они задают `AnswerSpec`, а сравнение делает `grade`. Балл бинарный.
Чистые функции без базы: тот же код вызывают сессия теста, линтер банка (правило L03) и симуляция.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.modules.assessment.dto import GradeResult
from app.modules.assessment.families._lib.contract import AnswerSpec, ItemKind

__all__ = ["grade", "normalize_number", "normalize_text"]

_NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")
_SPACES = re.compile(r"[\s   ]+")
_SPLIT = re.compile(r"[\s,;]+")
_BRACKETS = "[](){}"
_QUOTES = "\"'`«»"
#: Запас на погрешность двоичной записи: 0.1 + 0.2 не должно проигрывать допуску 0.01 на последнем бите.
_EPS = 1e-9


def normalize_number(raw: Any, unit: str | None = None) -> float | None:
    """Правило N1: строка кандидата -> число либо `None`, если это не число.

    Убираются пробелы (включая неразрывные) и единица измерения в конце; запятая заменяется точкой; типографский
    минус — дефисом. Строка обязана совпасть с `^[+-]?(\\d+(\\.\\d*)?|\\.\\d+)$`: дроби вида `1/3`, экспонента
    и слова не принимаются.
    """
    if isinstance(raw, bool) or raw is None:
        return None
    text = str(raw) if isinstance(raw, int | float) else raw
    if not isinstance(text, str):
        return None
    text = _SPACES.sub("", text)
    if unit:
        compact_unit = _SPACES.sub("", unit)
        if compact_unit and text.lower().endswith(compact_unit.lower()):
            text = text[: -len(compact_unit)]
    text = text.replace(",", ".").replace("−", "-")
    if not _NUMBER.match(text):
        return None
    return float(text)


def normalize_text(raw: Any, mode: str, case_sensitive: bool) -> str | list[str] | None:
    """Правило T1: `exact` -> строка со схлопнутыми пробелами; `tokens` и `set` -> список элементов.

    В режимах `tokens` и `set` снимаются внешние скобки и кавычки, строка режется по пробелам, запятым и точкам
    с запятой; у каждого элемента снимаются кавычки. Для `set` список отсортирован и без повторов.
    """
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not case_sensitive:
        text = text.lower()
    if mode == "exact":
        return _SPACES.sub(" ", text)
    text = text.strip(_BRACKETS + _QUOTES + " ")
    tokens = [token.strip(_QUOTES + _BRACKETS) for token in _SPLIT.split(text)]
    tokens = [token for token in tokens if token]
    return sorted(set(tokens)) if mode == "set" else tokens


def _normalize(kind: ItemKind, spec: Mapping[str, Any], raw: Mapping[str, Any]) -> Any:
    """Нормализованный ответ кандидата либо `None`, если тело ответа не разобрано."""
    if kind is ItemKind.NUMERIC_INPUT:
        return normalize_number(raw.get("value"), spec.get("unit"))
    if kind is ItemKind.TEXT_INPUT:
        return normalize_text(raw.get("value"), spec.get("mode", "exact"), bool(spec.get("case_sensitive")))
    if kind is ItemKind.SINGLE_CHOICE:
        value = raw.get("option_id")
        return value if isinstance(value, str) else None
    if kind is ItemKind.MULTI_CHOICE:
        value = raw.get("option_ids")
        if not isinstance(value, list | tuple) or not all(isinstance(item, str) for item in value):
            return None
        return sorted(set(value))
    if kind is ItemKind.PICK_LINE:
        value = raw.get("line")
        return value if isinstance(value, int) and not isinstance(value, bool) else None
    value = raw.get("order")
    if not isinstance(value, list | tuple) or not all(isinstance(item, str) for item in value):
        return None
    return list(value)


def _is_correct(kind: ItemKind, spec: Mapping[str, Any], normalized: Any) -> bool:
    if kind is ItemKind.NUMERIC_INPUT:
        target = float(spec["value"])
        if spec.get("integer") and normalized != int(normalized):
            return False
        tolerance = max(float(spec.get("tolerance_abs") or 0.0), float(spec.get("tolerance_rel") or 0.0) * abs(target))
        return bool(abs(normalized - target) <= tolerance + _EPS)
    if kind is ItemKind.TEXT_INPUT:
        expected = normalize_text(str(spec["value"]), spec.get("mode", "exact"), bool(spec.get("case_sensitive")))
        return bool(normalized == expected)
    if kind is ItemKind.SINGLE_CHOICE:
        return bool(normalized == spec["option_id"])
    if kind is ItemKind.MULTI_CHOICE:
        return bool(normalized == sorted(set(spec["option_ids"])))
    if kind is ItemKind.PICK_LINE:
        return normalized in spec["lines"]
    order = list(spec["order"])
    if spec.get("mode", "exact") == "exact":
        return bool(normalized == order)
    if sorted(normalized) != sorted(order):
        return False
    position = {block: index for index, block in enumerate(normalized)}
    return all(position[a] < position[b] for a, b in spec.get("precedence", ()))


def _spec_for_value(kind: ItemKind, spec: Mapping[str, Any], value: Any) -> dict[str, Any]:
    """Тот же формат ответа, но «верным» считается ответ модели ошибки: так определяется `error_tag`."""
    alt = dict(spec)
    if kind in (ItemKind.NUMERIC_INPUT, ItemKind.TEXT_INPUT):
        alt["value"] = value
    elif kind is ItemKind.SINGLE_CHOICE:
        alt["option_id"] = value
    elif kind is ItemKind.MULTI_CHOICE:
        alt["option_ids"] = list(value)
    elif kind is ItemKind.PICK_LINE:
        alt["lines"] = [value]
    else:
        alt.update(order=list(value), mode="exact")
    return alt


def grade(
    kind: ItemKind | str,
    answer_spec: AnswerSpec | Mapping[str, Any],
    raw_answer: object,
    *,
    misconceptions: Mapping[str, Any] | None = None,
) -> GradeResult:
    """Проверить ответ: `score ∈ {0, 1}` (Арх. 5.3; приложение A, §2.4).

    * `answer_spec` — `AnswerSpec` либо его JSON из `assessment_variant.answer` (у числового ответа с ключом `unit`);
    * `raw_answer` — тело `answer` из запроса; `None` — «не знаю, пропустить»: балл 0, `parse_ok = True`;
    * `misconceptions` — `misconception_answers` варианта: если неверный ответ совпал с ответом модели ошибки,
      её код пишется в `error_tag`. Это диагностика, на балл она не влияет.

    Число: `abs(x − value) ≤ max(tolerance_abs, tolerance_rel · abs(value))`, при `integer` дробная часть ответа
    обязана быть нулевой. Неразобранный ответ — балл 0 и `parse_ok = False`.
    """
    kind = ItemKind(kind)
    spec: Mapping[str, Any] = answer_spec.to_json() if isinstance(answer_spec, AnswerSpec) else answer_spec
    if raw_answer is None:
        return GradeResult(score=0, parse_ok=True, normalized=None)
    if not isinstance(raw_answer, Mapping):
        return GradeResult(score=0, parse_ok=False, normalized=None)
    normalized = _normalize(kind, spec, raw_answer)
    if normalized is None:
        return GradeResult(score=0, parse_ok=False, normalized=None)
    if _is_correct(kind, spec, normalized):
        return GradeResult(score=1, parse_ok=True, normalized=normalized)
    error_tag = None
    for code, value in sorted((misconceptions or {}).items()):
        try:
            if _is_correct(kind, _spec_for_value(kind, spec, value), normalized):
                error_tag = code
                break
        except (TypeError, ValueError, KeyError):
            continue
    return GradeResult(score=0, parse_ok=True, normalized=normalized, error_tag=error_tag)
