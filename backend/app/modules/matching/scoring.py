"""Чистое ядро подбора: покрытие требований, сила профиля, фильтры-условия, ключ порядка (Арх. 6.3–6.8).

Файл не импортирует SQLAlchemy и не обращается к фасадам: валидация (`app.eval.matching`) вызывает тот же код,
что и рабочий сервис (Арх. 2.4, п. 6). Покрытие и сила не складываются в один балл: порядок — лексикографический
(Арх. 6.7). Все округления целочисленные или «половина вверх», чтобы один вход всегда давал один результат.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal
from uuid import UUID

from app.modules.matching import constants as C
from app.modules.matching.dto import ShortlistQuery
from app.modules.matching.features import CONFIRMED_KINDS, CandidateFeatures, SkillEvidence, evidence_preference
from app.shared.enums import EvidenceKind, FitBand, Relation, TestOutcome

#: `implies_closure(skill) -> frozenset[str]`: навыки, которые следуют из данного (каталог, Арх. 6.2).
Closure = Callable[[str], frozenset[str]]

StrengthLabel = Literal["high", "medium", "base"]

SECTION_ORDER: dict[Relation, int] = {Relation.EXACT: 0, Relation.LOWER_WITH_MARGIN: 1, Relation.HIGHER: 2}

#: Коды причин фильтров-условий в фиксированном порядке (Арх. 6.4).
REASON_UNAVAILABLE = "unavailable"
REASON_CATEGORY = "category_excluded"
REASON_MARGIN = "margin_required"
REASON_FORMAT = "format"
REASON_FSP = "require_fsp"
REASON_LIMIT = "below_limit"


@dataclass(frozen=True, slots=True)
class ScoringParams:
    """Константы формул (Арх. 6.15). Рабочий код использует `DEFAULT_PARAMS`; иные значения — только абляции
    и чувствительность в `make eval-matching` (Арх. 12.3).
    """

    e_test: float = C.E_TEST
    e_test_single: float = C.E_TEST_SINGLE
    e_pulse: float = C.E_PULSE
    e_fsp: float = C.E_FSP
    e_declared: float = C.E_DECLARED
    w_must: int = C.W_MUST
    w_nice: int = C.W_NICE
    gap_cap_band: int = C.GAP_CAP_BAND
    fit_strong_min: int = C.FIT_STRONG_MIN
    fit_good_min: int = C.FIT_GOOD_MIN
    w_test: float = C.W_TEST
    w_fsp: float = C.W_FSP
    z_lower: float = C.Z_LOWER
    under: float = C.UNDER
    strength_high_min: int = C.STRENGTH_HIGH_MIN
    strength_medium_min: int = C.STRENGTH_MEDIUM_MIN
    #: Абляция «без роста неопределённости»: нижняя граница считается по `se`, а не по `se_eff`.
    use_se_eff: bool = True


DEFAULT_PARAMS = ScoringParams()


@dataclass(frozen=True, slots=True)
class RequirementEvidence:
    """Доказательство по одному требованию запроса (Арх. 6.2, «Доказательство по требованию»)."""

    skill_code: str
    priority: Literal["must", "nice"]
    kind: EvidenceKind
    weight: float
    #: Частный навык, который закрыл требование по `implies`; `None`, если сработал сам навык.
    via_skill_code: str | None
    evidence: SkillEvidence | None


@dataclass(frozen=True, slots=True)
class Coverage:
    """Покрытие требований (Арх. 6.5). `pct = None` — в запросе нет навыков; полосы в ключе тогда равны 0."""

    pct: int | None
    band: int
    confirmed_pct: int | None
    confirmed_band: int
    must_total: int
    must_covered: int
    must_confirmed: int
    nice_total: int
    nice_covered: int
    must_gap: bool
    capped: bool
    requirements: tuple[RequirementEvidence, ...]

    @property
    def has_requirements(self) -> bool:
        """Есть ли в запросе хотя бы один навык."""
        return self.pct is not None


@dataclass(frozen=True, slots=True)
class Strength:
    """Сила подтверждённого профиля (Арх. 6.6): `value` 0.0..100.0, полосы по 10 баллов."""

    t: float
    t_fresh: float
    x10: int
    band: int
    label: StrengthLabel

    @property
    def value(self) -> float:
        """Сила в баллах с одним знаком после запятой: `strength_x10 / 10`."""
        return self.x10 / 10


def round_half_up(value: float) -> int:
    """Округление до целого, половина вверх (Арх. 6.6): `floor(value + 0.5)`.

    Встроенный `round` округляет половину к чётному и дал бы разные полосы на границе.
    """
    return math.floor(value + 0.5)


def round1(value: float) -> float:
    """Округление до одного знака, половина вверх: вклады в объяснении (Арх. 6.10)."""
    result = round_half_up(value * 10) / 10
    return 0.0 if result == 0 else result


def evidence_weight(kind: EvidenceKind, full: bool, params: ScoringParams = DEFAULT_PARAMS) -> float:
    """Вес доказательства `e` по виду (Арх. 6.2).

    `test` — 1.0, если группа подтверждена целиком (`full`), иначе 0.7 (решено одно задание с тегом навыка);
    `pulse` — 0.7; `fsp` — 0.7; `declared` — 0.3; `none` — 0.
    """
    if kind == EvidenceKind.TEST:
        return params.e_test if full else params.e_test_single
    if kind == EvidenceKind.PULSE:
        return params.e_pulse
    if kind == EvidenceKind.FSP:
        return params.e_fsp
    if kind == EvidenceKind.DECLARED:
        return params.e_declared
    return 0.0


def resolve_requirement(
    evidence: Mapping[str, SkillEvidence],
    skill_code: str,
    priority: Literal["must", "nice"],
    closure: Closure,
    params: ScoringParams = DEFAULT_PARAMS,
) -> RequirementEvidence:
    """Лучшее доказательство по требованию (Арх. 6.2).

    `S(skill) = {skill} ∪ {s : skill ∈ implies_closure[s]}` — сам навык и все частные, из которых он следует.
    Среди доказательств кандидата по навыкам из `S` берётся запись с наибольшим весом, при равенстве — с более
    поздней датой, затем по порядку вида `test, pulse, fsp, declared`. Перенос только вверх по `implies`:
    подтверждённый `postgresql` закрывает требование `sql`, обратного переноса нет. Доказательств с нулевым
    весом не бывает: такое требование остаётся `none`.
    """
    best: SkillEvidence | None = None
    best_key: tuple[float, float, int, int] | None = None
    for code, item in evidence.items():
        if code != skill_code and skill_code not in closure(code):
            continue
        weight = evidence_weight(item.kind, item.full, params)
        if weight <= 0:
            continue
        # Последний элемент ключа: при полном равенстве сам навык предпочтительнее частного (стабильный `via`).
        key = (*evidence_preference(item, weight), 1 if code == skill_code else 0)
        if best_key is None or key > best_key or (key == best_key and best is not None and code < best.skill_code):
            best, best_key = item, key
    if best is None or best_key is None:
        return RequirementEvidence(skill_code, priority, EvidenceKind.NONE, 0.0, None, None)
    via = best.skill_code if best.skill_code != skill_code else None
    return RequirementEvidence(skill_code, priority, best.kind, best_key[0], via, best)


def coverage(
    evidence: Mapping[str, SkillEvidence],
    must_skills: Sequence[str],
    nice_skills: Sequence[str],
    closure: Closure,
    params: ScoringParams = DEFAULT_PARAMS,
) -> Coverage:
    """Покрытие требований потребности доказательствами кандидата (Арх. 6.5).

    ```
    R = [(skill, W_MUST) для must_skills] + [(skill, W_NICE) для nice_skills];  e10 = round(10 · e) ∈ {10, 7, 3, 0}
    num           = Σ w_r · e10_r;   den = 10 · Σ w_r
    coverage_pct  = (200 · num + den) // (2 · den)            # округление 100·num/den, половина вверх
    num_conf      = Σ w_r · e10_r только по требованиям с kind ∈ {test, pulse, fsp}
    confirmed_pct = (200 · num_conf + den) // (2 · den)
    must_covered  = число обязательных с e > 0;   must_gap = must_total > 0 и must_covered < must_total
    confirmed_band = (confirmed_pct + 5) // 10                # 0..10 — второй ключ порядка (после силы, 6.7)
    coverage_band  = (coverage_pct + 5) // 10                 # 0..10 — третий ключ и основа подписи совпадения
    если must_gap: coverage_band = min(coverage_band, GAP_CAP_BAND)
    ```

    Заявленное не входит в `confirmed_band`, поэтому перечисление в профиле всех навыков потребности не поднимает
    кандидата выше того, у кого больше сила либо при равной силе больше подтверждено. Пустой список требований:
    `pct = None`, обе полосы равны 0 — пустое поле никогда не считается «покрыто на 100 %».
    """
    requirements = tuple(
        [resolve_requirement(evidence, skill, "must", closure, params) for skill in must_skills]
        + [resolve_requirement(evidence, skill, "nice", closure, params) for skill in nice_skills]
    )
    must = [item for item in requirements if item.priority == "must"]
    nice = [item for item in requirements if item.priority == "nice"]
    must_covered = sum(1 for item in must if item.weight > 0)
    must_confirmed = sum(1 for item in must if item.kind in CONFIRMED_KINDS)
    nice_covered = sum(1 for item in nice if item.weight > 0)
    must_gap = bool(must) and must_covered < len(must)
    if not requirements:
        return Coverage(None, 0, None, 0, 0, 0, 0, 0, 0, False, False, ())

    num = num_conf = weight_sum = 0
    for item in requirements:
        w = params.w_must if item.priority == "must" else params.w_nice
        e10 = round_half_up(item.weight * 10)
        weight_sum += w
        num += w * e10
        if item.kind in CONFIRMED_KINDS:
            num_conf += w * e10
    den = 10 * weight_sum
    pct = (200 * num + den) // (2 * den)
    confirmed_pct = (200 * num_conf + den) // (2 * den)
    band = (pct + 5) // 10
    capped = must_gap and band > params.gap_cap_band
    if must_gap:
        band = min(band, params.gap_cap_band)
    return Coverage(
        pct=pct,
        band=band,
        confirmed_pct=confirmed_pct,
        confirmed_band=(confirmed_pct + 5) // 10,
        must_total=len(must),
        must_covered=must_covered,
        must_confirmed=must_confirmed,
        nice_total=len(nice),
        nice_covered=nice_covered,
        must_gap=must_gap,
        capped=capped,
        requirements=requirements,
    )


def _clip01(value: float) -> float:
    return 0.0 if value < 0 else 1.0 if value > 1 else value


def strength(features: CandidateFeatures, params: ScoringParams = DEFAULT_PARAMS) -> Strength:
    """Сила подтверждённого профиля относительно порога своей категории (Арх. 6.6).

    ```
    LB       = theta − Z_LOWER · se_eff                        # нижняя граница уровня, а не точка
    T        = clip( (LB − cut + UNDER · width) / ((1 + UNDER) · width), 0, 1 )
    T_fresh  = то же при se вместо se_eff
    F        = fsp_signal
    strength_x10  = round_half_up( 1000 · (W_TEST · T + W_FSP · F) )
    strength_band = min(9, strength_x10 // 100)                # полосы по 10 баллов
    strength_label = high при strength ≥ 55; medium при ≥ 30; иначе base
    ```

    `T = 1/3` при `LB = cut`, `T = 1` при `LB = cut + width`, `T = 0` при `LB ≤ cut − width/2`. От потребности
    сила не зависит. ФСП — добавка с насыщением: без истории `F = 0`, вычитания нет; наибольший вклад — 30 баллов.
    Свежесть — не прибавка к баллу, а рост `se_eff` (его считает только `assessment`, Арх. 5.6). Заявленные
    данные в силу не входят.
    """
    width = features.width if features.width > 0 else 1.0
    scale = (1 + params.under) * width
    se_used = features.se_eff if params.use_se_eff else features.se
    t = _clip01((features.theta - params.z_lower * se_used - features.cut + params.under * width) / scale)
    t_fresh = _clip01((features.theta - params.z_lower * features.se - features.cut + params.under * width) / scale)
    signal = _clip01(features.fsp_signal)
    x10 = max(0, min(1000, round_half_up(1000 * (params.w_test * t + params.w_fsp * signal))))
    value = x10 / 10
    label: StrengthLabel
    if value >= params.strength_high_min:
        label = "high"
    elif value >= params.strength_medium_min:
        label = "medium"
    else:
        label = "base"
    return Strength(t=t, t_fresh=t_fresh, x10=x10, band=min(9, x10 // 100), label=label)


def fit_band(cov: Coverage, params: ScoringParams = DEFAULT_PARAMS) -> FitBand | None:
    """Подпись совпадения для работодателя — не ключ порядка; зависит только от покрытия (Арх. 6.7).

    `strong` — `coverage_pct ≥ 70` и нет `must_gap`; `good` — `≥ 40`; `partial` — иначе; `None` — в запросе нет
    навыков. При весе заявленного 0.3 одними заявлениями не получить даже `good`.
    """
    if cov.pct is None:
        return None
    if cov.pct >= params.fit_strong_min and not cov.must_gap:
        return FitBand.STRONG
    if cov.pct >= params.fit_good_min:
        return FitBand.GOOD
    return FitBand.PARTIAL


def sections_for(query: ShortlistQuery, grades: Sequence[str]) -> dict[str, Relation]:
    """Рекомендованные категории запроса: грейд → раздел (Арх. 6.3).

    `grades` — коды грейдов каталога от младшего к старшему, `i` — индекс целевого. `exact` — `grades[i]`;
    `lower_with_margin` — `grades[i−1]` (только кандидаты с текущим вердиктом «с запасом», это проверяет
    `first_failed_filter`); `higher` — `grades[i+1]`. Порядок разделов фиксирован, разделы не смешиваются.
    `grade_codes` из уточнения только сужает набор. Смежные специализации не рекомендуются.
    """
    sections: dict[str, Relation] = {query.grade_code: Relation.EXACT}
    if query.grade_code in grades:
        index = list(grades).index(query.grade_code)
        if index > 0:
            sections[grades[index - 1]] = Relation.LOWER_WITH_MARGIN
        if index + 1 < len(grades):
            sections[grades[index + 1]] = Relation.HIGHER
    if query.grade_codes is not None:
        allowed = set(query.grade_codes)
        sections = {grade: relation for grade, relation in sections.items() if grade in allowed}
    return dict(sorted(sections.items(), key=lambda pair: SECTION_ORDER[pair[1]]))


def first_failed_filter(
    features: CandidateFeatures | None, query: ShortlistQuery, sections: Mapping[str, Relation]
) -> str | None:
    """Первая невыполненная проверка фильтров-условий либо `None` (Арх. 6.4); порядок фиксирован.

    1. состояние показа `visible` (в пул входят только видимые: `features = None` означает «кандидата в пуле
       нет») — `unavailable`;
    2. категория входит в разделы запроса — `category_excluded`;
    3. для раздела `lower_with_margin` текущий вердикт `confirmed_with_margin` — `margin_required`;
    4. `query.work_formats ∩ features.work_formats ≠ ∅` — `format`;
    5. `require_fsp = false` либо `fsp_verified` — `require_fsp`.

    Шестую проверку — место в разделе не дальше `SECTION_LIMITS[relation]` (`below_limit`) — выполняет
    `ranking.rank_need` после упорядочивания. Покрытие обязательных навыков, вилка, город и состояние пары
    фильтрами не являются: изменение вилки запроса не меняет ни состав, ни порядок.
    """
    if features is None:
        return REASON_UNAVAILABLE
    relation = sections.get(features.grade_code)
    if features.specialization_code != query.specialization_code or relation is None:
        return REASON_CATEGORY
    if relation == Relation.LOWER_WITH_MARGIN and features.verdict != TestOutcome.CONFIRMED_WITH_MARGIN:
        return REASON_MARGIN
    if not features.work_formats.intersection(str(item) for item in query.work_formats):
        return REASON_FORMAT
    if query.require_fsp and not features.fsp_verified:
        return REASON_FSP
    return None


def exposure_bucket(exposure_7d: int) -> int:
    """Корзина показов `floor(log2(1 + exposure_7d))` (Арх. 6.7): реже показанные идут раньше среди равных."""
    return (max(0, exposure_7d) + 1).bit_length() - 1


def tie_hash(seed: str, candidate_id: UUID) -> str:
    """Детерминированный жребий `sha256(f"{seed}:{candidate_id}")` — последний ключ порядка (Арх. 6.7)."""
    return hashlib.sha256(f"{seed}:{candidate_id}".encode()).hexdigest()


def shortlist_seed(employer_id: UUID, need_id: UUID) -> str:
    """Сид подборки `sha256(f"{employer_id}:{need_id}")` (Арх. 6.7): у разных работодателей порядок равных
    разный, у одной потребности он стабилен между версиями.
    """
    return hashlib.sha256(f"{employer_id}:{need_id}".encode()).hexdigest()


def bank_seed(employer_id: UUID, day: date) -> str:
    """Сид банка `sha256(f"{employer_id}:{день по Москве}")` (Арх. 6.9): порядок равных стабилен в течение дня."""
    return hashlib.sha256(f"{employer_id}:{day.isoformat()}".encode()).hexdigest()
