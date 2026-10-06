"""Контракт семейства заданий (Арх. 5.3; приложение A, §2.2–2.4, 2.6).

Семейство — один файл `families/{group}_{name}.py` с тремя обязательными именами и одним необязательным::

    META: FamilyMeta                                  # строится функцией registry.family_meta(...)
    def generate(level: int, seed: int) -> Variant    # чистая функция от random.Random(seed)
    def selfcheck(v: Variant) -> list[str]            # независимая перепроверка ответа; [] — вариант корректен
    def oracle_check(v: Variant) -> list[str]         # необязательно: сверка ключа с независимым оракулом (Арх. 5.3)

Здесь лежат только типы и чистые функции над ними. Файл ничего не знает о реестре, базе и настройках, поэтому его
можно импортировать из любого генератора без циклов импорта.

Что видит кандидат, а что нет. Из `Variant` кандидату уходит только `payload` (условие, код, таблицы, варианты,
блоки, подсказка ввода). `answer`, `misconception_answers`, `features` и `explanation` не входят ни в одну схему
ответа ролей `candidate` и `employer` (Арх. 8.5).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from app.shared.enums import ItemKind

__all__ = [
    "FEATURE_KEYS",
    "AnswerSpec",
    "Block",
    "CodeBlock",
    "Family",
    "FamilyMeta",
    "InputHint",
    "ItemKind",
    "LevelMeta",
    "Option",
    "OracleUnavailable",
    "Priority",
    "Reject",
    "Table",
    "TextMode",
    "Variant",
    "canonical_json",
    "content_hash",
    "default_time_budget",
    "guess_probability",
    "raw_answer_for",
    "variant_answer_json",
    "variant_payload",
    "variant_to_json",
]

Priority = Literal["P0", "P1", "P2"]
TextMode = Literal["exact", "tokens", "set"]
OrderMode = Literal["exact", "dag"]

#: Общий словарь признаков сложности (приложение A, §2.6). Семейство может добавлять свои ключи; любой ключ,
#: который генератор кладёт в `Variant.features`, обязан иметь границы в `LevelMeta.feature_bounds` (правило L04).
FEATURE_KEYS: tuple[str, ...] = (
    "code_lines",  # строк кода в условии
    "trace_steps",  # выполненных операторов при исполнении (L10: не больше 80)
    "nesting_depth",  # глубина вложенности
    "concepts",  # число разных конструкций из списка семейства
    "tables",  # число таблиц
    "table_rows",  # сумма строк таблиц
    "joins",  # число соединений
    "subqueries",  # число подзапросов
    "timeline_events",  # событий в ленте
    "options_count",  # число вариантов выбора
    "answer_abs",  # модуль числового ответа (L10: не больше 10^6)
    "trap",  # 1, если вариант содержит ловушку уровня
)

#: Границы шкалы сложности уровня: `b` кратна 0.5 и лежит в [-2.0, 2.0] (Арх. 5.3).
B_MIN, B_MAX, B_STEP = -2.0, 2.0, 0.5


class Reject(Exception):
    """Вырожденный набор параметров: ответ тривиален, совпал с ответом модели ошибки или неоднозначен.

    Генератор бросает исключение, сборщик берёт следующий seed (приложение A, §2.2, п. 4). `reason` — короткий
    код причины латиницей: по нему отчёт сборки считает, из-за чего теряются варианты.
    """

    def __init__(self, reason: str = "degenerate") -> None:
        super().__init__(reason)
        self.reason = reason


class OracleUnavailable(Exception):
    """Внешний оракул (git, Node.js, pandas) недоступен в этом окружении.

    Бросает `oracle_check`. В `bank build --check-only` это ошибка: сверка ключей обязательна (Арх. 5.3);
    локально её можно пропустить флагом `--skip-oracle`.
    """


def default_time_budget(b: float) -> int:
    """Бюджет времени по умолчанию, секунд (приложение A, §2.6): 75 при b ≤ −1.0; 105 при −0.5…0.5; 150 при b ≥ 1.0."""
    if b <= -1.0:
        return 75
    if b >= 1.0:
        return 150
    return 105


def guess_probability(kind: ItemKind, *, options: int = 0, lines: int = 0) -> float:
    """Вероятность угадать `c` по виду задания (приложение A, §2.3).

    Ввод ответа и порядок блоков — 0; выбор одного — `1 / число вариантов`; выбор подмножества — 0.03;
    выбор строки — `1 / число строк`.
    """
    if kind is ItemKind.SINGLE_CHOICE:
        return round(1 / options, 3) if options > 0 else 0.25
    if kind is ItemKind.MULTI_CHOICE:
        return 0.03
    if kind is ItemKind.PICK_LINE:
        return round(1 / lines, 3) if lines > 0 else 0.125
    return 0.0


# --------------------------------------------------------------------------------------------------------------------
# Метаданные
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LevelMeta:
    """Уровень семейства: набор структурных признаков одной сложности."""

    #: Номер уровня, 1..3.
    level: int
    #: Сложность на шкале θ: кратна 0.5, в [-2.0, 2.0]. Назначается уровню, не варианту; берётся из реестра.
    b: float
    #: Расчётное время решения, секунд.
    time_budget_s: int
    #: Границы признаков сложности: ключ -> (минимум, максимум), обе границы включены.
    feature_bounds: Mapping[str, tuple[float, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class FamilyMeta:
    """Паспорт семейства. Создаётся функцией `registry.family_meta`: уровни и `b` приходят из реестра."""

    #: «sql.join_rows»: группа, точка, имя. Имя файла — тот же идентификатор с подчёркиванием вместо точки.
    id: str
    #: Увеличивается на единицу при любом изменении `generate`: старые варианты банка остаются при своей версии.
    version: int
    #: Название для отчётов и служебных экранов.
    title: str
    group: str
    #: Коды навыков каталога.
    skill_tags: tuple[str, ...]
    #: Основной вид задания.
    kind: ItemKind
    #: Специализации; `("*",)` — у языковых групп `py` и `js`.
    specializations: tuple[str, ...]
    levels: tuple[LevelMeta, ...]
    #: Коды моделей типичных ошибок, для которых генератор вычисляет ответ.
    misconceptions: tuple[str, ...]
    priority: Priority
    #: Другие виды заданий, допустимые на отдельных уровнях (в банке MVP — `algo.graph_traversal` и `ds.bst_ops`).
    extra_kinds: tuple[ItemKind, ...] = ()

    @property
    def kinds(self) -> tuple[ItemKind, ...]:
        """Все виды заданий, которые вправе выдать семейство."""
        return (self.kind, *self.extra_kinds)

    def level(self, level: int) -> LevelMeta:
        """Метаданные уровня по номеру; `KeyError`, если такого уровня у семейства нет."""
        for item in self.levels:
            if item.level == level:
                return item
        raise KeyError(f"{self.id}: нет уровня {level}")


# --------------------------------------------------------------------------------------------------------------------
# Части условия
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CodeBlock:
    """Код в условии: язык подсветки и текст. До 30 строк и 88 колонок (L01)."""

    language: str
    text: str


@dataclass(frozen=True)
class Table:
    """Таблица в условии: до 8 строк и 6 столбцов (L01). Ячейки — строки; пустое значение пишется как «NULL»."""

    title: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "columns", tuple(self.columns))
        object.__setattr__(self, "rows", tuple(tuple(row) for row in self.rows))


@dataclass(frozen=True)
class Option:
    """Вариант выбора: `id` — «o1», «o2», … в порядке показа (порядок перемешивает генератор)."""

    id: str
    text: str


@dataclass(frozen=True)
class Block:
    """Блок для задания на порядок: `id` — «b1», «b2», …"""

    id: str
    text: str


@dataclass(frozen=True)
class InputHint:
    """Подсказка поля ввода. `unit` — единица измерения: проверка ответа отбрасывает её в конце строки."""

    placeholder: str | None = None
    unit: str | None = None
    max_length: int | None = None


# --------------------------------------------------------------------------------------------------------------------
# Ответ
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AnswerSpec:
    """Верный ответ варианта (приложение A, §2.4). Создаётся одним из методов-конструкторов по виду задания.

    Проверяет ответ кандидата одна общая функция `assessment.grading.grade`; семейства свою проверку не пишут.
    """

    kind: ItemKind
    #: `numeric_input` — число; `text_input` — строка.
    value: int | float | str | None = None
    integer: bool = True
    tolerance_abs: float = 0.0
    tolerance_rel: float = 0.0
    #: Режим сравнения текста: `exact`, `tokens`, `set`; для порядка блоков — `exact` или `dag`.
    mode: str = "exact"
    case_sensitive: bool = False
    option_id: str | None = None
    option_ids: tuple[str, ...] = ()
    lines: tuple[int, ...] = ()
    order: tuple[str, ...] = ()
    precedence: tuple[tuple[str, str], ...] = ()

    @classmethod
    def numeric(
        cls,
        value: int | float,
        *,
        decimals: int | None = None,
        tolerance_abs: float = 0.0,
        tolerance_rel: float = 0.0,
        integer: bool | None = None,
    ) -> AnswerSpec:
        """Числовой ответ.

        Целое число без допуска — точное совпадение, дробная часть в ответе кандидата запрещена. `decimals=k` —
        ответ с округлением до k знаков: значение округляется, допуск не меньше `10^(−k)` (правило N1).
        `tolerance_rel` — относительный допуск (например, 0.02 у расчётов надёжности). Формат ответа («целое
        число», «округлите до двух знаков») обязан быть назван в условии. `integer` задаётся явно, только если
        правило по умолчанию не подходит.
        """
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise TypeError("числовой ответ должен быть int или float")
        if decimals is not None:
            if decimals < 0:
                raise ValueError("decimals не может быть отрицательным")
            if decimals == 0:
                value = round(value)
            else:
                value = round(float(value), decimals)
                tolerance_abs = max(tolerance_abs, 10.0 ** (-decimals))
        if integer is None:
            integer = isinstance(value, int) and tolerance_abs == 0 and tolerance_rel == 0
        return cls(
            kind=ItemKind.NUMERIC_INPUT,
            value=value,
            integer=integer,
            tolerance_abs=tolerance_abs,
            tolerance_rel=tolerance_rel,
        )

    @classmethod
    def text(cls, value: str, *, mode: TextMode = "exact", case_sensitive: bool = False) -> AnswerSpec:
        """Текстовый ответ. `exact` — строка целиком; `tokens` — список через пробел или запятую; `set` — множество."""
        if mode not in ("exact", "tokens", "set"):
            raise ValueError(f"неизвестный режим текста: {mode}")
        return cls(kind=ItemKind.TEXT_INPUT, value=str(value), mode=mode, case_sensitive=case_sensitive)

    @classmethod
    def choice(cls, option_id: str) -> AnswerSpec:
        """Выбор одного варианта: идентификатор верного (`"o3"`)."""
        return cls(kind=ItemKind.SINGLE_CHOICE, option_id=option_id)

    @classmethod
    def multi(cls, option_ids: Iterable[str]) -> AnswerSpec:
        """Выбор подмножества: идентификаторы всех верных вариантов; частичного зачёта нет."""
        return cls(kind=ItemKind.MULTI_CHOICE, option_ids=tuple(sorted(set(option_ids), key=_option_sort_key)))

    @classmethod
    def line(cls, *lines: int) -> AnswerSpec:
        """Выбор строки кода: номера строк, каждая из которых засчитывается (нумерация с 1)."""
        return cls(kind=ItemKind.PICK_LINE, lines=tuple(sorted(set(lines))))

    @classmethod
    def blocks(
        cls, order: Sequence[str], *, mode: OrderMode = "exact", precedence: Iterable[tuple[str, str]] = ()
    ) -> AnswerSpec:
        """Порядок блоков: `exact` — одна перестановка; `dag` — любая, где в каждой паре (a, b) блок a раньше b."""
        if mode not in ("exact", "dag"):
            raise ValueError(f"неизвестный режим порядка: {mode}")
        pairs = tuple((str(a), str(b)) for a, b in precedence)
        return cls(kind=ItemKind.ORDER_BLOCKS, order=tuple(order), mode=mode, precedence=pairs)

    def to_json(self) -> dict[str, Any]:
        """Словарь в том виде, в каком ответ хранится в `assessment_variant.answer` (приложение A, §2.4)."""
        if self.kind is ItemKind.NUMERIC_INPUT:
            return {
                "value": self.value,
                "integer": self.integer,
                "tolerance_abs": self.tolerance_abs,
                "tolerance_rel": self.tolerance_rel,
            }
        if self.kind is ItemKind.TEXT_INPUT:
            return {"value": self.value, "mode": self.mode, "case_sensitive": self.case_sensitive}
        if self.kind is ItemKind.SINGLE_CHOICE:
            return {"option_id": self.option_id}
        if self.kind is ItemKind.MULTI_CHOICE:
            return {"option_ids": list(self.option_ids)}
        if self.kind is ItemKind.PICK_LINE:
            return {"lines": list(self.lines)}
        return {"order": list(self.order), "mode": self.mode, "precedence": [list(pair) for pair in self.precedence]}

    def correct_value(self) -> Any:
        """Верный ответ «голым» значением — в том же виде, в каком пишутся `misconception_answers`."""
        if self.kind in (ItemKind.NUMERIC_INPUT, ItemKind.TEXT_INPUT):
            return self.value
        if self.kind is ItemKind.SINGLE_CHOICE:
            return self.option_id
        if self.kind is ItemKind.MULTI_CHOICE:
            return list(self.option_ids)
        if self.kind is ItemKind.PICK_LINE:
            return self.lines[0] if self.lines else None
        return list(self.order)


def _option_sort_key(option_id: str) -> tuple[int, str]:
    """«o2» раньше «o10»: сортировка идентификаторов по числовой части."""
    digits = re.sub(r"\D", "", option_id)
    return (int(digits) if digits else 0, option_id)


def raw_answer_for(kind: ItemKind, value: Any) -> dict[str, Any]:
    """Тело ответа кандидата (`answer` в `POST …/answers`) для «голого» значения.

    Так линтер превращает верный ответ и ответы моделей ошибок в то, что проверяет `grading.grade`:
    число или строка → `{"value": "42"}`; вариант → `{"option_id": "o3"}`; подмножество → `{"option_ids": [...]}`;
    строка кода → `{"line": 7}`; порядок → `{"order": [...]}`.
    """
    if kind is ItemKind.NUMERIC_INPUT:
        return {"value": format_number(value)}
    if kind is ItemKind.TEXT_INPUT:
        return {"value": str(value)}
    if kind is ItemKind.SINGLE_CHOICE:
        return {"option_id": value}
    if kind is ItemKind.MULTI_CHOICE:
        return {"option_ids": list(value)}
    if kind is ItemKind.PICK_LINE:
        return {"line": value}
    return {"order": list(value)}


def format_number(value: Any) -> str:
    """Число так, как его набрал бы кандидат: без экспоненты и без хвоста «.0» у целых значений."""
    if isinstance(value, bool):
        raise TypeError("логическое значение не является числовым ответом")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        text = format(value, ".10f").rstrip("0")
        return text.rstrip(".")
    return str(value)


# --------------------------------------------------------------------------------------------------------------------
# Вариант
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Variant:
    """Конкретное задание, полученное из `(family, level, seed)`."""

    family_id: str
    family_version: int
    level: int
    seed: int
    #: Условие: до 600 знаков, без разметки кода (код — в `code`).
    prompt: str
    #: Верный ответ; кандидату не отдаётся.
    answer: AnswerSpec
    #: Код модели ошибки -> ответ, который она даёт, «голым» значением: число, строка, идентификатор варианта,
    #: список идентификаторов, номер строки. Нужен хотя бы один, и каждый обязан отличаться от верного (L07).
    misconception_answers: Mapping[str, Any]
    #: Признаки сложности (§2.6): каждый ключ обязан иметь границы в `LevelMeta.feature_bounds`.
    features: Mapping[str, float]
    #: Разбор для эксперта и ручной проверки ключа; кандидату не отдаётся.
    explanation: str
    code: CodeBlock | None = None
    tables: tuple[Table, ...] | None = None
    #: Варианты выбора; порядок уже перемешан генератором.
    options: tuple[Option, ...] | None = None
    blocks: tuple[Block, ...] | None = None
    input: InputHint | None = None

    def __post_init__(self) -> None:
        for name in ("tables", "options", "blocks"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, tuple):
                object.__setattr__(self, name, tuple(value))

    @property
    def kind(self) -> ItemKind:
        """Вид задания варианта — вид его ответа."""
        return self.answer.kind


def variant_payload(v: Variant) -> dict[str, Any]:
    """То, что видит кандидат (`assessment_variant.payload`): из него собирается `TestItemView`. Ответа здесь нет."""
    return {
        "kind": v.kind.value,
        "prompt": v.prompt,
        "code": None if v.code is None else {"language": v.code.language, "text": v.code.text},
        "tables": None
        if v.tables is None
        else [{"title": t.title, "columns": list(t.columns), "rows": [list(row) for row in t.rows]} for t in v.tables],
        "options": None if v.options is None else [{"id": o.id, "text": o.text} for o in v.options],
        "blocks": None if v.blocks is None else [{"id": b.id, "text": b.text} for b in v.blocks],
        "input": None
        if v.input is None
        else {"placeholder": v.input.placeholder, "unit": v.input.unit, "max_length": v.input.max_length},
    }


def variant_answer_json(v: Variant) -> dict[str, Any]:
    """Ответ для хранения и проверки: `AnswerSpec.to_json()`, у числового ответа — ещё и единица из `input.unit`.

    Единица нужна функции проверки (правило N1 отбрасывает её в конце строки), а та получает только `answer`.
    """
    data = v.answer.to_json()
    if v.kind is ItemKind.NUMERIC_INPUT and v.input is not None and v.input.unit:
        data["unit"] = v.input.unit
    return data


def variant_to_json(v: Variant) -> dict[str, Any]:
    """Полное представление варианта: по нему проверяется детерминизм `generate` (L06) и пишется строка банка."""
    return {
        "family_id": v.family_id,
        "family_version": v.family_version,
        "level": v.level,
        "seed": v.seed,
        "payload": variant_payload(v),
        "answer": variant_answer_json(v),
        "misconception_answers": {code: _plain(value) for code, value in sorted(v.misconception_answers.items())},
        "features": {key: v.features[key] for key in sorted(v.features)},
        "explanation": v.explanation,
    }


def canonical_json(data: Any) -> str:
    """Каноническая запись JSON: ключи отсортированы, без лишних пробелов, кириллица как есть."""
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _plain(value: Any) -> Any:
    """Кортежи и множества → списки: значение должно одинаково выглядеть до и после записи в JSON."""
    if isinstance(value, set | frozenset):
        return sorted(value)
    if isinstance(value, tuple | list):
        return [_plain(item) for item in value]
    return value


_WS = re.compile(r"\s+")


def content_hash(v: Variant) -> str:
    """Отпечаток содержания варианта (L05): sha256 от нормализованных условия, кода, таблиц и вариантов выбора.

    Нормализация: пробельные последовательности схлопнуты, у строк кода срезаны хвостовые пробелы, варианты
    и блоки отсортированы по тексту — перестановка тех же вариантов не делает задание новым. Ответ и seed
    в отпечаток не входят.
    """
    payload = variant_payload(v)
    normalized = {
        "prompt": _WS.sub(" ", payload["prompt"]).strip().lower(),
        "code": None if v.code is None else "\n".join(line.rstrip() for line in v.code.text.strip("\n").split("\n")),
        "tables": payload["tables"],
        "options": None if v.options is None else sorted(_WS.sub(" ", o.text).strip() for o in v.options),
        "blocks": None if v.blocks is None else sorted(_WS.sub(" ", b.text).strip() for b in v.blocks),
    }
    return hashlib.sha256(canonical_json(normalized).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------------------------------------------------
# Семейство как объект
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Family:
    """Загруженное семейство: паспорт и функции модуля. Собирает `families.discover`; в тестах создаётся напрямую."""

    meta: FamilyMeta
    generate: Callable[[int, int], Variant]
    selfcheck: Callable[[Variant], list[str]]
    #: Сверка ключа с независимым оракулом (Арх. 5.3); `None` — модуль её не экспортирует.
    oracle_check: Callable[[Variant], list[str]] | None = None
    #: Имя модуля, из которого загружено семейство.
    module: str = ""
