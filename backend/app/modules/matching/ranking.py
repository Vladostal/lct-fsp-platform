"""Чистое ядро подбора: порядок выдачи, разделы, банк, различия версий, контрфакты (Арх. 6.7, 6.9, 6.11, 6.12).

Файл не импортирует SQLAlchemy: `rank_need` получает готовый пул `CandidateFeatures` и возвращает порядок —
одинаково для рабочего сервиса и для валидации (Арх. 2.4, п. 6). Рабочий порядок ключей один
(`DEFAULT_KEY_ORDER`); параметр `key_order` существует только для абляций отчёта (Арх. 12.3).

Порядок версии 2: закрытые обязательные навыки → подтверждённое покрытие → сила → покрытие с заявленным.
Он выбран по отчёту валидации (`docs/validation/matching`): прежний порядок «сила первой» проигрывал бейзлайну
заявленного стека по P@10, новый превосходит его во всех режимах и сохраняет преимущество при накрутке заявленного.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from app.modules.matching import constants as C
from app.modules.matching.dto import ShortlistQuery
from app.modules.matching.features import CandidateFeatures
from app.modules.matching.scoring import (
    DEFAULT_PARAMS,
    REASON_LIMIT,
    SECTION_ORDER,
    Closure,
    Coverage,
    ScoringParams,
    Strength,
    coverage,
    exposure_bucket,
    first_failed_filter,
    fit_band,
    sections_for,
    strength,
    tie_hash,
)
from app.shared.enums import DiffMark, FitBand, Relation


@dataclass(frozen=True, slots=True)
class Scored:
    """Кандидат, прошедший фильтры-условия, с покрытием и силой — до упорядочивания."""

    features: CandidateFeatures
    relation: Relation
    coverage: Coverage
    strength: Strength
    fit_band: FitBand | None


#: Составляющие ключа порядка внутри раздела; меньшее значение — выше в выдаче.
KEY_PARTS: dict[str, Callable[[Scored], int]] = {
    # Рабочие ключи (Арх. 6.7).
    # Сколько обязательных навыков потребности осталось без единого доказательства: 0 — закрыты все.
    "must": lambda s: s.coverage.must_total - s.coverage.must_covered,
    "strength": lambda s: -s.strength.band,
    "confirmed": lambda s: -s.coverage.confirmed_band,
    "coverage": lambda s: -s.coverage.band,
    # Только для абляций отчёта (Арх. 12.3; поправка R3-tz-compliance-5 — три полосы силы по подписи).
    "strength_label": lambda s: {"high": 0, "medium": 1, "base": 2}[s.strength.label],
    "confirmed3": lambda s: -min(2, (s.coverage.confirmed_pct or 0) // 34),
    "strength_raw": lambda s: -s.strength.x10,
    "confirmed_raw": lambda s: -(s.coverage.confirmed_pct or 0),
    "coverage_raw": lambda s: -(s.coverage.pct or 0),
    "additive": lambda s: (
        -round(4.5 * (s.coverage.pct or 0) + 4.0 * s.strength.value + 15 * max(0.0, 1 - s.features.age_days / 365))
    ),
}

#: Действующий порядок (версия 2): закрытые обязательные → подтверждённое покрытие → сила → покрытие с заявленным.
DEFAULT_KEY_ORDER: tuple[str, ...] = ("must", "confirmed", "strength", "coverage")
#: Прежние порядки сравниваются с действующим в отчёте валидации: версия 1.2 — «сила первой» (Арх. 15.1, № 53),
#: версия 1.1 (Арх. 15.1, № 35) и версия 1.0.
KEY_ORDER_V12: tuple[str, ...] = ("strength", "confirmed", "coverage")
KEY_ORDER_V11: tuple[str, ...] = ("confirmed", "strength", "coverage")
KEY_ORDER_V10: tuple[str, ...] = ("coverage", "strength")


@dataclass(frozen=True, slots=True)
class RankedItem:
    """Строка подборки: позиция сквозная, 1..n по всей версии."""

    scored: Scored
    position: int
    key: tuple[int | str, ...]

    @property
    def candidate_id(self) -> UUID:
        """Идентификатор кандидата строки."""
        return self.scored.features.candidate_id


@dataclass(frozen=True, slots=True)
class RankResult:
    """Результат `rank_need`: строки версии, причины невхождения и счётчики воронки раздела `exact`."""

    items: list[RankedItem]
    #: Кандидаты пула, не вошедшие в версию: код причины первой невыполненной проверки (Арх. 6.4).
    rejected: dict[UUID, str]
    #: Раздел `exact`: в пуле, прошли формат, прошли все фильтры, из них без пробела в обязательных, показаны.
    available: int = 0
    format_ok: int = 0
    passed: int = 0
    must_ok: int = 0
    shown: int = 0
    section_counts: dict[Relation, int] = field(default_factory=dict)


def sort_key(scored: Scored, seed: str, key_order: Sequence[str] = DEFAULT_KEY_ORDER) -> tuple[int | str, ...]:
    """Ключ порядка выдачи (Арх. 6.7); сортировка по возрастанию кортежа.

    ```
    sort_key = ( section_order,                 # exact = 0, lower_with_margin = 1, higher = 2
                 must_missing,                  # обязательных навыков без единого доказательства (0 — закрыты все)
                 −confirmed_band,               # соответствие потребности по подтверждённому (0, если требований нет)
                 −strength_band,                # сила подтверждённого профиля: все ответы теста и ФСП, нижняя граница
                 −coverage_band,                # заявленное по желательным — только среди равных по ключам выше
                 exposure_bucket,               # floor(log2(1 + exposure_7d))
                 tie_hash )                     # sha256(f"{seed}:{candidate_id}")
    ```

    Выдача под потребность упорядочена по соответствию потребности: сначала те, у кого есть данные по всем
    обязательным навыкам, среди них — те, у кого больше подтверждено тестом и ФСП, а сила профиля решает среди
    равных по соответствию. Заявленный навык закрывает пробел в обязательных, но не входит в `confirmed_band`:
    кандидат с подтверждённым навыком всегда выше кандидата с тем же навыком «со слов». Карточка при этом
    показывает источник каждого навыка и риск «заявлено кандидатом, тестом не проверено».
    `key_order` меняется только в абляциях валидации.
    """
    parts = tuple(KEY_PARTS[name](scored) for name in key_order)
    features = scored.features
    return (
        SECTION_ORDER[scored.relation],
        *parts,
        exposure_bucket(features.exposure_7d),
        tie_hash(seed, features.candidate_id),
    )


def band_key(
    relation: Relation, must_missing: int, confirmed_band: int, strength_band: int, coverage_band: int
) -> tuple[int, ...]:
    """Полоса кандидата для сравнения версий: `(section_order, must_missing, −confirmed_band, −strength_band,
    −coverage_band)` (Арх. 6.11) — те же ключи и в том же порядке, что в `sort_key`. Перестановки внутри полосы —
    не изменение оценки. `must_missing` — число обязательных без доказательств, а не число закрытых: так полосы
    версий с разным списком обязательных сравнимы (перенос навыка в желательные не выглядит ухудшением).
    """
    return (SECTION_ORDER[relation], must_missing, -confirmed_band, -strength_band, -coverage_band)


def score_candidate(
    features: CandidateFeatures,
    query: ShortlistQuery,
    relation: Relation,
    closure: Closure,
    params: ScoringParams = DEFAULT_PARAMS,
) -> Scored:
    """Покрытие (Арх. 6.5), сила (Арх. 6.6) и подпись совпадения (Арх. 6.7) одного кандидата по запросу."""
    cov = coverage(features.evidence, query.must_skills, query.nice_skills, closure, params)
    return Scored(features, relation, cov, strength(features, params), fit_band(cov, params))


def rank_need(
    query: ShortlistQuery,
    pool: Sequence[CandidateFeatures],
    seed: str,
    *,
    grades: Sequence[str],
    closure: Closure,
    params: ScoringParams = DEFAULT_PARAMS,
    key_order: Sequence[str] = DEFAULT_KEY_ORDER,
    section_limits: Mapping[str, int] | None = None,
) -> RankResult:
    """Подборка под потребность (Арх. 6.3–6.7).

    Порядок работы: фильтры-условия (`first_failed_filter`, ничем не компенсируются) → раздел категории
    (`exact`, `lower_with_margin`, `higher`; разделы не смешиваются) → внутри раздела ключ `sort_key`:
    закрытые обязательные навыки → полоса подтверждённого покрытия → полоса силы → полоса покрытия с заявленным →
    реже показанные → жребий → обрезка раздела по `SECTION_LIMITS` (причина `below_limit`) → сквозная позиция 1..n.

    Фильтра по покрытию обязательных навыков нет: кандидат без данных остаётся в подборке с риском. `pool` —
    только видимые кандидаты; вилка запроса на результат не влияет. Функция детерминирована: одинаковые запрос,
    пул и сид дают одинаковый порядок.
    """
    limits = C.SECTION_LIMITS if section_limits is None else section_limits
    sections = sections_for(query, grades)
    rejected: dict[UUID, str] = {}
    by_relation: dict[Relation, list[tuple[tuple[int | str, ...], Scored]]] = {}
    available = format_ok = 0
    query_formats = {str(item) for item in query.work_formats}
    for features in pool:
        is_exact = (
            features.specialization_code == query.specialization_code
            and sections.get(features.grade_code) == Relation.EXACT
        )
        if is_exact:
            available += 1
            if features.work_formats & query_formats:
                format_ok += 1
        reason = first_failed_filter(features, query, sections)
        if reason is not None:
            rejected[features.candidate_id] = reason
            continue
        scored = score_candidate(features, query, sections[features.grade_code], closure, params)
        by_relation.setdefault(scored.relation, []).append((sort_key(scored, seed, key_order), scored))

    items: list[RankedItem] = []
    section_counts: dict[Relation, int] = {}
    exact = by_relation.get(Relation.EXACT, [])
    for relation in sorted(by_relation, key=lambda item: SECTION_ORDER[item]):
        ordered = sorted(by_relation[relation], key=lambda pair: pair[0])
        limit = limits.get(relation.value, len(ordered))
        for key, scored in ordered[:limit]:
            items.append(RankedItem(scored=scored, position=len(items) + 1, key=key))
        for _, scored in ordered[limit:]:
            rejected[scored.features.candidate_id] = REASON_LIMIT
        section_counts[relation] = min(limit, len(ordered))
    return RankResult(
        items=items,
        rejected=rejected,
        available=available,
        format_ok=format_ok,
        passed=len(exact),
        must_ok=sum(1 for _, scored in exact if not scored.coverage.must_gap),
        shown=section_counts.get(Relation.EXACT, 0),
        section_counts=section_counts,
    )


@dataclass(frozen=True, slots=True)
class BankRanked:
    """Строка банка кандидатов: категория и сила; покрытие не считается (потребности нет)."""

    features: CandidateFeatures
    strength: Strength


def rank_bank(
    pool: Sequence[CandidateFeatures],
    seed: str,
    *,
    specializations: Sequence[str],
    grades: Sequence[str],
    params: ScoringParams = DEFAULT_PARAMS,
) -> list[BankRanked]:
    """Порядок банка кандидатов (Арх. 6.9).

    Специализации — в порядке каталога, грейды — от старшего к младшему, внутри категории —
    `(−strength_band, exposure_bucket, tie_hash)`: буквально «внутри категории — по силе подтверждённого
    профиля». Навыки в банке — только фильтр «есть / нет», в порядок не входят.
    """
    spec_index = {code: index for index, code in enumerate(specializations)}
    grade_index = {code: index for index, code in enumerate(grades)}

    def key(row: BankRanked) -> tuple[int, str, int, int, int, str]:
        features = row.features
        return (
            spec_index.get(features.specialization_code, len(spec_index)),
            features.specialization_code,
            -grade_index.get(features.grade_code, -1),
            -row.strength.band,
            exposure_bucket(features.exposure_7d),
            tie_hash(seed, features.candidate_id),
        )

    return sorted((BankRanked(features, strength(features, params)) for features in pool), key=key)


# --------------------------------------------------------------------------------------------------------------------
# Различия версий
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DiffInput:
    """Строка версии для сравнения: позиция и полоса (`band_key`)."""

    candidate_id: UUID
    position: int
    band: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class DiffEntry:
    """Метка строки новой версии относительно базовой."""

    candidate_id: UUID
    mark: DiffMark
    delta: int | None
    position: int
    base_position: int | None


@dataclass(frozen=True, slots=True)
class SnapshotDiff:
    """Различия двух версий: метки строк новой версии, выпавшие и счётчики."""

    entries: dict[UUID, DiffEntry]
    dropped: list[UUID]
    added: int
    moved_up: int
    moved_down: int

    @property
    def dropped_count(self) -> int:
        """Сколько кандидатов базовой версии нет в новой."""
        return len(self.dropped)


def diff_snapshots(base: Sequence[DiffInput], new: Sequence[DiffInput]) -> SnapshotDiff:
    """Сравнить две версии подборки одной потребности (Арх. 6.11, «Различия»).

    ```
    для кандидата в обеих версиях:
        mark  = "up", если полоса новой меньше; "down", если больше; иначе "same"
        delta = base.position − new.position, если mark != "same"; иначе None
    только в новой:  mark = "new"
    только в базе:   выпавший (причину — `first_failed_filter` — подставляет вызывающий)
    ```

    Метка «выше» / «ниже» ставится по смене полосы `band_key`, а не позиции. Функция симметрична: `added`
    одной стороны равно числу выпавших другой.
    """
    base_by_id = {row.candidate_id: row for row in base}
    new_ids = {row.candidate_id for row in new}
    entries: dict[UUID, DiffEntry] = {}
    added = moved_up = moved_down = 0
    for row in new:
        old = base_by_id.get(row.candidate_id)
        if old is None:
            entries[row.candidate_id] = DiffEntry(row.candidate_id, DiffMark.NEW, None, row.position, None)
            added += 1
            continue
        if row.band < old.band:
            mark, moved_up = DiffMark.UP, moved_up + 1
        elif row.band > old.band:
            mark, moved_down = DiffMark.DOWN, moved_down + 1
        else:
            mark = DiffMark.SAME
        delta = old.position - row.position if mark != DiffMark.SAME else None
        entries[row.candidate_id] = DiffEntry(row.candidate_id, mark, delta, row.position, old.position)
    ordered_base = sorted(base, key=lambda item: item.position)
    dropped = [row.candidate_id for row in ordered_base if row.candidate_id not in new_ids]
    return SnapshotDiff(entries=entries, dropped=dropped, added=added, moved_up=moved_up, moved_down=moved_down)


# --------------------------------------------------------------------------------------------------------------------
# Подсказки-контрфакты
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Counterfactual:
    """Одно изменение запроса и его прирост (Арх. 6.12)."""

    code: str
    value: str | None
    gain: int
    query: ShortlistQuery


def exact_counts(
    query: ShortlistQuery,
    pool: Sequence[CandidateFeatures],
    *,
    grades: Sequence[str],
    closure: Closure,
    params: ScoringParams = DEFAULT_PARAMS,
) -> tuple[int, int]:
    """Сколько кандидатов раздела `exact` проходит фильтры-условия и сколько из них без пробела в обязательных
    (`must_gap = false`) — основа подсказок (Арх. 6.12). Обрезка `SECTION_LIMITS` не применяется.
    """
    sections = sections_for(query, grades)
    passed = no_gap = 0
    for features in pool:
        if sections.get(features.grade_code) != Relation.EXACT or first_failed_filter(features, query, sections):
            continue
        passed += 1
        cov = coverage(features.evidence, query.must_skills, (), closure, params)
        if not cov.must_gap:
            no_gap += 1
    return passed, no_gap


def counterfactuals(
    query: ShortlistQuery,
    pool: Sequence[CandidateFeatures],
    kinds: Collection[str],
    *,
    grades: Sequence[str],
    closure: Closure,
    all_formats: Sequence[str],
    params: ScoringParams = DEFAULT_PARAMS,
    min_gain: int = C.HINT_MIN_GAIN,
    limit: int = C.HINTS_LIMIT,
) -> list[Counterfactual]:
    """Подсказки: тот же конвейер с одним изменением запроса (Арх. 6.12).

    `gain` для `add_format` и `drop_require_fsp` — прирост числа кандидатов раздела `exact`; для
    `move_must_to_nice` — прирост числа кандидатов раздела `exact` без пробела в обязательных: перенос навыка
    состав подборки не меняет, но показывает, сколько кандидатов закрывают остальные требования. Возвращаются
    только изменения с `gain ≥ HINT_MIN_GAIN`, не больше трёх, по убыванию прироста. Подсказки по вилке не
    строятся никогда: счётчики считаются по открытым данным (навыки, форматы) и минимум не раскрывают.
    """
    base_passed, base_no_gap = exact_counts(query, pool, grades=grades, closure=closure, params=params)
    found: list[Counterfactual] = []
    if "move_must_to_nice" in kinds:
        for skill in query.must_skills:
            changed = replace_query(
                query,
                must_skills=[item for item in query.must_skills if item != skill],
                nice_skills=sorted({*query.nice_skills, skill}),
            )
            _, no_gap = exact_counts(changed, pool, grades=grades, closure=closure, params=params)
            found.append(Counterfactual("move_must_to_nice", skill, no_gap - base_no_gap, changed))
    if "add_format" in kinds:
        present = {str(item) for item in query.work_formats}
        for work_format in all_formats:
            if work_format in present:
                continue
            changed = replace_query(query, work_formats=sorted({*present, work_format}))
            passed, _ = exact_counts(changed, pool, grades=grades, closure=closure, params=params)
            found.append(Counterfactual("add_format", work_format, passed - base_passed, changed))
    if "drop_require_fsp" in kinds and query.require_fsp:
        changed = replace_query(query, require_fsp=False)
        passed, _ = exact_counts(changed, pool, grades=grades, closure=closure, params=params)
        found.append(Counterfactual("drop_require_fsp", None, passed - base_passed, changed))
    found = [item for item in found if item.gain >= min_gain]
    found.sort(key=lambda item: (-item.gain, item.code, item.value or ""))
    return found[:limit]


def replace_query(query: ShortlistQuery, **changes: object) -> ShortlistQuery:
    """Копия запроса с изменёнными полями (запрос — неизменяемое значение версии, Арх. 6.11)."""
    return query.model_copy(update=changes)


__all__ = [
    "DEFAULT_KEY_ORDER",
    "KEY_ORDER_V10",
    "KEY_ORDER_V11",
    "KEY_ORDER_V12",
    "KEY_PARTS",
    "BankRanked",
    "Counterfactual",
    "DiffEntry",
    "DiffInput",
    "RankResult",
    "RankedItem",
    "Scored",
    "SnapshotDiff",
    "band_key",
    "counterfactuals",
    "diff_snapshots",
    "exact_counts",
    "rank_bank",
    "rank_need",
    "replace_query",
    "score_candidate",
    "sort_key",
]
