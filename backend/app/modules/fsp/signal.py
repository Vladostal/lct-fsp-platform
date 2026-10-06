"""Чистое ядро модуля `fsp`: нормализация участий, вес результата, сигнал, лидерство, обобщённая строка.

Арх. 7.6–7.8; приложение D, §5.1–5.9, §6.1–6.4. Версия правил — `constants.FSP_SIGNAL_VERSION`.

Ядро не знает о базе, HTTP и настройках приватности: на вход приходят простые структуры (`Participation`, `Fact`,
`Rank`), дата `as_of` и специализация. Тот же код вызывают рабочий сервис, валидация подбора и тесты, поэтому
файл не импортирует SQLAlchemy (Арх. 2.4, п. 6). Судейство, сборные и нормативы ЕВСК не моделируются
(Арх. 15.1, № 47): нижнюю границу сигнала дают только действующие разряды и звания.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Literal
from uuid import UUID

from app.modules.fsp import constants as c

Band = Literal["none", "low", "medium", "high"]
LeadershipLevel = Literal["none", "basic", "strong"]
DisplayMode = Literal["none", "summary", "detailed"]

ROLE_ATHLETE = "athlete"
ROLE_COACH = "coach"
TEAM = "team"

_KNOWN_TIER: dict[str, str] = {
    "international": "national",
    "national": "national",
    "interregional": "interregional",
    "regional": "regional",
    "municipal": "regional",
}
#: Уровни, на которых роль тренера считается сильным опытом лидерства.
_COACH_STRONG_LEVELS = frozenset({"international", "national", "interregional"})
#: Уровни, на которых роль тренера подтверждает навык наставничества (не ниже регионального).
_COACH_MENTORING_LEVELS = frozenset({"international", "national", "interregional", "regional"})
_LEADERSHIP_TIERS = frozenset({"national", "interregional"})
_PUBLIC_SPEAKING_STAGES = frozenset({"final", "single"})


# ---------------------------------------------------------------------------------------------------------------------
# Входные и выходные структуры
# ---------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Participation:
    """Одна запись `participations[]` выгрузки реестра — вход нормализации (приложение D, §2.3)."""

    entry_id: str
    member_role: str
    is_captain: bool
    participation: str | None
    team_size: int | None
    discipline_code: str
    level: str
    kind: str
    stage: str
    series_code: str | None
    competition_status: str
    protocol_status: str
    date_start: date | None
    date_end: date | None
    entries_count: int | None
    result_status: str
    place: int | None
    place_to: int | None


@dataclass(frozen=True, slots=True)
class NormalizedFact:
    """Расчётные поля факта `fsp_achievement`, выведенные из участия (приложение D, §5.1)."""

    entry_id: str
    member_role: str
    series_code: str | None
    event_date: date | None
    field_size: int | None
    tier: str | None
    place_eff: float | None
    result_bucket: str | None
    verified: bool
    counted: bool
    uncounted_reason: str | None
    base_points: float


@dataclass(frozen=True, slots=True)
class Fact:
    """Сохранённый факт участия в объёме, нужном расчёту сигнала, лидерства и обобщённой строки."""

    id: UUID
    entry_id: str
    discipline_code: str
    level: str
    stage: str
    tier: str | None
    participation: str | None
    member_role: str
    is_captain: bool
    result_bucket: str | None
    event_date: date | None
    verified: bool
    counted: bool
    base_points: float
    anon_period: str | None = None
    anon_k_a: int | None = None
    anon_k_b: int | None = None


@dataclass(frozen=True, slots=True)
class Rank:
    """Разряд или звание из реестра (`fsp_credential` вида `rank`)."""

    id: UUID
    code: str
    discipline_code: str | None
    assigned_on: date | None
    valid_until: date | None
    revoked_on: date | None


@dataclass(frozen=True, slots=True)
class ContributionItem:
    """Вклад одного зачтённого факта в сумму `S` — для объяснения выдачи."""

    fact_id: UUID
    p: float
    base_points: float
    decay: float
    relevance: float
    order_weight: float


@dataclass(frozen=True, slots=True)
class SignalResult:
    """Результат расчёта `fsp_signal` для одного кандидата."""

    value: float
    results_value: float
    floor_value: float
    floor_source: Literal["rank"] | None
    counted: int
    contributions: tuple[ContributionItem, ...]
    band: Band


@dataclass(frozen=True, slots=True)
class SkillEvidence:
    """Навык, подтверждённый фактом ФСП: родной навык дисциплины либо софт-навык роли."""

    skill_code: str
    source: Literal["discipline", "role"]
    fact_id: UUID
    confirmed_at: date


@dataclass(frozen=True, slots=True)
class PublicSummary:
    """Обобщённая строка достижений, видимая работодателю до раскрытия (приложение D, §6.2)."""

    level: Literal[1, 2, 3]
    headline: str
    short: str
    more: bool
    shortened: bool


# ---------------------------------------------------------------------------------------------------------------------
# Нормализация участия в факт (приложение D, §5.1)
# ---------------------------------------------------------------------------------------------------------------------


def tier_of(level: str) -> str | None:
    """Огрублённый уровень соревнования (Арх. 7.6).

    `international | national → national`; `interregional → interregional`; `regional | municipal → regional`;
    неизвестный уровень — `None`. Международный слит со всероссийским, муниципальный — с региональным: отдельные
    корзины были бы слишком малы для порога анонимности.
    """
    return _KNOWN_TIER.get(level)


def effective_place(place: int | None, place_to: int | None) -> float | None:
    """`place_eff = (place + place_to) / 2`; при `place_to = None` — `place`; без места — `None` (Арх. 7.6)."""
    if place is None:
        return None
    return (place + (place_to if place_to is not None else place)) / 2


def result_bucket(place_eff: float | None, field_size: int | None) -> str:
    """Корзина результата для обобщённой строки (приложение D, §5.1).

    `medal` — `ceil(place_eff) ≤ 3` и место в верхней половине поля (либо размер поля неизвестен);
    `top_half` — поле известно и `place_eff ≤ N / 2`; иначе `participant`, в том числе при участии без места.
    """
    if place_eff is None:
        return "participant"
    in_top_half = field_size is not None and place_eff <= field_size / 2
    if math.ceil(place_eff) <= 3 and (field_size is None or in_top_half):
        return "medal"
    return "top_half" if in_top_half else "participant"


def w_place(place_eff: float | None, field_size: int | None) -> float:
    """Множитель места `W_PLACE` (Арх. 7.6).

    Без места — 0.25. Иначе `linear = 0.25 + 0.35 · clip((N − place_eff) / (N − 1), 0, 1)` (при неизвестном `N`
    или `N ≤ 1` доля равна 0); призёр (`ceil(place_eff) ≤ 3` в верхней половине поля либо при неизвестном поле)
    получает `max(linear, {1: 1.00, 2: 0.85, 3: 0.75}[rank])`. Призовой коэффициент не применяется, если место
    в нижней половине поля: «третий из четырёх» — не призёр.
    """
    if place_eff is None:
        return c.PLACE_FLOOR
    share = 0.0
    if field_size is not None and field_size > 1:
        share = min(1.0, max(0.0, (field_size - place_eff) / (field_size - 1)))
    linear = c.PLACE_FLOOR + c.PLACE_SPAN * share
    rank = math.ceil(place_eff)
    if rank <= 3 and (field_size is None or place_eff <= field_size / 2):
        return max(linear, c.MEDAL.get(rank, linear))
    return linear


def w_field(field_size: int | None) -> float:
    """Поправка на размер поля `W_FIELD`: 0.5 при неизвестном `N`, иначе `clip(N / 8, 0.5, 1.0)` (Арх. 7.6)."""
    if field_size is None:
        return c.FIELD_UNKNOWN
    return min(1.0, max(c.FIELD_MIN, field_size / c.FIELD_REF))


def w_team(participation: str | None, team_size: int | None) -> float:
    """Размывание командного результата `W_TEAM` (Арх. 7.6).

    1.0 для личного; `1 / (1 + 0.1 · (team_size − 1))` для командного; 0.7, если размер команды неизвестен.
    Вклад одного участника в командный результат неизвестен, поэтому чем больше команда, тем меньше вес.
    """
    if participation != TEAM:
        return 1.0
    if team_size is None or team_size < 1:
        return c.TEAM_UNKNOWN
    return 1.0 / (1.0 + c.TEAM_DILUTION * (team_size - 1))


def base_points(
    *,
    level: str,
    kind: str,
    stage: str,
    place_eff: float | None,
    field_size: int | None,
    participation: str | None,
    team_size: int | None,
) -> float:
    """Вес одного результата, не зависящий от времени и специализации (Арх. 7.6).

    `base_points = W_LEVEL[level] · W_KIND[kind] · W_STAGE[stage] · W_PLACE(place_eff, N) · W_FIELD(N) · W_TEAM`.
    Неизвестный вид соревнования считается как `other`, неизвестный этап — как `qualification` (самый осторожный
    вес); неизвестный уровень даёт 0 — такой факт не зачитывается.
    """
    level_weight = c.W_LEVEL.get(level)
    if level_weight is None:
        return 0.0
    kind_weight = c.W_KIND.get(kind, c.W_KIND[c.KIND_FALLBACK])
    stage_weight = c.W_STAGE.get(stage, c.W_STAGE[c.STAGE_FALLBACK])
    value = level_weight * kind_weight * stage_weight
    value *= w_place(place_eff, field_size) * w_field(field_size) * w_team(participation, team_size)
    return round(value, 4)


def normalize_participation(item: Participation, today: date) -> NormalizedFact:
    """Превратить участие в факт: правила 1–7 зачёта (приложение D, §5.1). Правило серии — `resolve_series`.

    Факт не зачитывается (первое сработавшее): 1 — роль не `athlete`; 2 — протокол или результат аннулирован;
    3 — соревнование не завершено, протокол не официальный либо результата ещё нет; 4 — `dsq`; 5 — `dns`;
    6 — неизвестный уровень; 7 — нет даты либо она в будущем. `verified` — не сработало ни одно из правил 2–7
    (роль значения не имеет). `base_points` считается для подтверждённых фактов роли `athlete`, для остальных 0.
    """
    event_date = item.date_end or item.date_start
    place_eff = effective_place(item.place, item.place_to)
    field_size = item.entries_count
    tier = tier_of(item.level)

    reason: str | None = None
    if item.protocol_status == "annulled" or item.result_status == "annulled":
        reason = "annulled"
    elif item.competition_status != "finished" or item.protocol_status != "official" or item.result_status == "pending":
        reason = "not_finished"
    elif item.result_status == "dsq":
        reason = "dsq"
    elif item.result_status == "dns":
        reason = "dns"
    elif tier is None:
        reason = "unknown_level"
    elif event_date is None or event_date > today:
        reason = "no_date"
    verified = reason is None

    is_athlete = item.member_role == ROLE_ATHLETE
    if not is_athlete:
        reason = "role_not_athlete"  # правило 1 стоит первым: тренеру причина всегда одна
    points = 0.0
    if verified and is_athlete:
        points = base_points(
            level=item.level,
            kind=item.kind,
            stage=item.stage,
            place_eff=place_eff,
            field_size=field_size,
            participation=item.participation,
            team_size=item.team_size,
        )
    return NormalizedFact(
        entry_id=item.entry_id,
        member_role=item.member_role,
        series_code=item.series_code,
        event_date=event_date,
        field_size=field_size,
        tier=tier,
        place_eff=place_eff,
        result_bucket=result_bucket(place_eff, field_size) if item.place is not None or verified else None,
        verified=verified,
        counted=verified and is_athlete,
        uncounted_reason=reason,
        base_points=points,
    )


def resolve_series(facts: Sequence[NormalizedFact]) -> list[NormalizedFact]:
    """Правило 8: в одной серии зачитывается один факт — с наибольшим `base_points` (приложение D, §5.1).

    Этапы и финал одного сезона не складываются: остальные факты серии получают причину
    `superseded_in_series`. При равенстве `base_points` остаётся факт с более поздней датой, затем — с большим
    `entry_id` (чтобы результат не зависел от порядка записей в выгрузке).
    """
    best: dict[str, NormalizedFact] = {}
    for fact in facts:
        if not fact.counted or fact.series_code is None:
            continue
        current = best.get(fact.series_code)
        if current is None or _series_key(fact) > _series_key(current):
            best[fact.series_code] = fact
    resolved: list[NormalizedFact] = []
    for fact in facts:
        if fact.counted and fact.series_code is not None and best[fact.series_code] is not fact:
            fact = replace(fact, counted=False, uncounted_reason="superseded_in_series")
        resolved.append(fact)
    return resolved


def _series_key(fact: NormalizedFact) -> tuple[float, date, str]:
    return (fact.base_points, fact.event_date or date.min, fact.entry_id)


def normalize_all(items: Iterable[Participation], today: date) -> list[NormalizedFact]:
    """Нормализовать выгрузку целиком: дубликаты `(entry_id, member_role)` — берётся последний, затем правила 1–8."""
    unique: dict[tuple[str, str], Participation] = {}
    for item in items:
        unique[(item.entry_id, item.member_role)] = item
    return resolve_series([normalize_participation(item, today) for item in unique.values()])


# ---------------------------------------------------------------------------------------------------------------------
# Сигнал (приложение D, §5.3, §5.5, §5.6)
# ---------------------------------------------------------------------------------------------------------------------


def age_years(event_date: date, as_of: date) -> float:
    """Давность события в годах: `max(0, (as_of − event_date).days / 365.25)`."""
    return max(0.0, (as_of - event_date).days / 365.25)


def decay(event_date: date, as_of: date) -> float:
    """Затухание результата: `0.5 ** (age_years / 2.0)` — период полураспада 2 года (Арх. 7.6).

    Через год остаётся 0.71, через два — 0.50, через три — 0.35, через четыре — 0.25.
    """
    return float(0.5 ** (age_years(event_date, as_of) / c.HALF_LIFE_YEARS))


def relevance(discipline_code: str, specialization: str | None) -> float:
    """Перенос «дисциплина → специализация» по матрице `R` (Арх. 7.6).

    Для дисциплины или специализации вне таблицы (в том числе когда у кандидата ещё нет категории) —
    `R_DEFAULT = 0.5`.
    """
    row = c.RELEVANCE.get(discipline_code)
    if row is None or specialization is None:
        return c.R_DEFAULT
    return row.get(specialization, c.R_DEFAULT)


def rank_is_active(rank: Rank, as_of: date) -> bool:
    """Действует ли разряд на дату `as_of` (приложение D, §5.5).

    Не отозван и (`valid_until ≥ as_of`, если срок задан; иначе — звание: граница действует
    `TITLE_FLOOR_YEARS = 6` лет от присвоения). Разряд, присвоенный позже `as_of`, ещё не действует.
    """
    if rank.revoked_on is not None:
        return False
    if rank.assigned_on is not None and rank.assigned_on > as_of:
        return False
    if rank.valid_until is not None:
        return rank.valid_until >= as_of
    if rank.assigned_on is None:
        return False
    return (as_of - rank.assigned_on).days <= c.TITLE_FLOOR_YEARS * 365.25


def rank_floor(ranks: Iterable[Rank], specialization: str | None, as_of: date) -> float:
    """Нижняя граница сигнала по действующим разрядам: `max(RANK_FLOOR[c] · Rr(c))`; 0, если их нет (Арх. 7.6).

    `Rr(c) = R[дисциплина разряда][специализация]`, а если реестр не назвал дисциплину — `R_RANK_UNKNOWN = 0.7`.
    Разряд выводится из тех же результатов, поэтому он не слагаемое, а граница снизу: реестр может знать разряд,
    но не иметь оцифрованного протокола.
    """
    best = 0.0
    for rank in ranks:
        weight = c.RANK_FLOOR.get(rank.code)
        if weight is None or not rank_is_active(rank, as_of):
            continue
        transfer = c.R_RANK_UNKNOWN if rank.discipline_code is None else relevance(rank.discipline_code, specialization)
        best = max(best, weight * transfer)
    return best


def signal_band(value: float) -> Band:
    """Полоса сигнала: `none` при 0; `low` < 0.3; `medium` < 0.6; `high` ≥ 0.6 (Арх. 7.6)."""
    if value <= 0:
        return "none"
    if value < c.SIGNAL_BAND_MEDIUM:
        return "low"
    if value < c.SIGNAL_BAND_HIGH:
        return "medium"
    return "high"


def ordered_contributions(facts: Iterable[Fact], specialization: str | None, as_of: date) -> list[ContributionItem]:
    """Вклады зачтённых фактов по убыванию `p_k = base_points_k · R · decay_k` (приложение D, §5.3).

    При равенстве `p` раньше идёт факт с более поздней датой, затем с меньшим `entry_id`: порядок записей
    в выгрузке на результат не влияет. `order_weight = 0.6 ** (i − 1)` — убывающая отдача по числу результатов.
    """
    scored: list[tuple[float, date, str, Fact, float, float]] = []
    for fact in facts:
        if not fact.counted or fact.event_date is None:
            continue
        fade = decay(fact.event_date, as_of)
        transfer = relevance(fact.discipline_code, specialization)
        scored.append((fact.base_points * transfer * fade, fact.event_date, fact.entry_id, fact, fade, transfer))
    scored.sort(key=lambda row: (-row[0], -row[1].toordinal(), row[2]))
    return [
        ContributionItem(
            fact_id=fact.id,
            p=p,
            base_points=fact.base_points,
            decay=fade,
            relevance=transfer,
            order_weight=c.GAMMA**index,
        )
        for index, (p, _, _, fact, fade, transfer) in enumerate(scored)
    ]


def compute_signal(
    facts: Sequence[Fact], ranks: Sequence[Rank], specialization: str | None, as_of: date
) -> SignalResult:
    """Сигнал достижений ФСП одного кандидата на дату `as_of` (Арх. 7.6).

    ```
    p_k       = base_points_k · R[discipline_k][specialization] · 0.5 ** (age_years_k / 2)     # только зачтённые
    S         = Σ_i 0.6 ** (i − 1) · p_(i)                    # по убыванию p: убывающая отдача
    F_results = 1 − exp(−S / 0.4)                             # насыщение
    F_floor   = max(RANK_FLOOR[c] · R по действующим разрядам)    # 0, если разрядов нет
    fsp_signal = round(max(F_results, F_floor), 4)
    ```

    Свойства (тесты): `0 ≤ fsp_signal < 1`; без зачтённых фактов и действующих разрядов — ровно 0; добавление
    зачтённого факта и улучшение места значение не уменьшают; со временем без новых стартов значение не растёт;
    количество не заменяет уровень. Роли (капитан, тренер) в сигнал не входят.
    """
    contributions = ordered_contributions(facts, specialization, as_of)
    total = sum(item.order_weight * item.p for item in contributions)
    results_value = 1.0 - math.exp(-total / c.TAU) if total > 0 else 0.0
    floor_value = rank_floor(ranks, specialization, as_of)
    value = round(max(results_value, floor_value), 4)
    return SignalResult(
        value=value,
        results_value=round(results_value, 4),
        floor_value=round(floor_value, 4),
        floor_source="rank" if floor_value > 0 and floor_value >= results_value else None,
        counted=len(contributions),
        contributions=tuple(contributions[: c.CONTRIBUTIONS_LIMIT]),
        band=signal_band(value),
    )


# ---------------------------------------------------------------------------------------------------------------------
# Лидерство и подтверждение навыков (приложение D, §5.7, §5.8)
# ---------------------------------------------------------------------------------------------------------------------


def _in_window(fact: Fact, as_of: date) -> bool:
    return fact.event_date is not None and age_years(fact.event_date, as_of) <= c.LEADERSHIP_WINDOW_YEARS


def captain_facts(facts: Iterable[Fact], as_of: date) -> list[Fact]:
    """Факты капитана в окне 4 лет: подтверждённый, роль `athlete`, `is_captain`, командное участие."""
    return [
        fact
        for fact in facts
        if fact.verified
        and fact.member_role == ROLE_ATHLETE
        and fact.is_captain
        and fact.participation == TEAM
        and _in_window(fact, as_of)
    ]


def coach_facts(facts: Iterable[Fact], as_of: date) -> list[Fact]:
    """Факты тренера в окне 4 лет: подтверждённый факт с ролью `coach`."""
    return [fact for fact in facts if fact.verified and fact.member_role == ROLE_COACH and _in_window(fact, as_of)]


def leadership_level(facts: Sequence[Fact], as_of: date) -> LeadershipLevel:
    """Уровень лидерства по ролям за последние 4 года (приложение D, §5.8; судейство не моделируется).

    `strong` — тренер команды на соревновании уровня `international | national | interregional`, либо капитан
    команды с призовым местом при `tier = national`, либо капитан в трёх и более соревнованиях; `basic` — есть
    хотя бы один факт капитана или тренера; иначе `none`. В `fsp_signal` роли не входят: сила навыка и опыт
    ведения людей — разные вещи.
    """
    captain = captain_facts(facts, as_of)
    coach = coach_facts(facts, as_of)
    if any(fact.level in _COACH_STRONG_LEVELS for fact in coach):
        return "strong"
    if any(fact.tier == "national" and fact.result_bucket == "medal" for fact in captain):
        return "strong"
    if len(captain) >= c.CAPTAIN_STRONG_COUNT:
        return "strong"
    return "basic" if captain or coach else "none"


def skill_evidence(
    facts: Sequence[Fact], as_of: date, is_known_skill: Callable[[str], bool] | None = None
) -> list[SkillEvidence]:
    """Навыки, подтверждённые фактами ФСП (Арх. 7.6; приложение D, §5.7–5.8).

    Дисциплина подтверждает только родные навыки и никогда — язык или фреймворк: `algo` → `algorithms`,
    `data_structures`; `product` → `teamwork`, `mvp_delivery` (и `public_speaking` для финала или соревнования
    без этапов уровня `national | interregional`); `infosec` → `infosec`, `vulnerability_analysis`;
    `uav` → `uav_programming`; `robotics` → `robotics`, `embedded`; любая командная → `teamwork`.
    Условие: зачтённый факт с `base_points · decay ≥ EVIDENCE_MIN_POINTS = 0.10` (без матрицы `R`: навык родной
    для дисциплины). Роли (окно 4 года): `leadership` — капитан при `tier ∈ {national, interregional}` либо
    в трёх и более соревнованиях; `mentoring` — тренер на соревновании уровня не ниже регионального.
    По каждому навыку остаётся одно подтверждение — с наибольшим `base_points · decay`, затем более позднее.
    Коды, которых нет в справочнике (`is_known_skill`), пропускаются. Сила подтверждения — константа подбора.
    """
    best: dict[str, tuple[float, date, SkillEvidence]] = {}

    def offer(code: str, source: Literal["discipline", "role"], fact: Fact, weight: float) -> None:
        if fact.event_date is None or (is_known_skill is not None and not is_known_skill(code)):
            return
        current = best.get(code)
        if current is None or (weight, fact.event_date) > (current[0], current[1]):
            best[code] = (weight, fact.event_date, SkillEvidence(code, source, fact.id, fact.event_date))

    for fact in facts:
        if not fact.counted or fact.event_date is None:
            continue
        weight = fact.base_points * decay(fact.event_date, as_of)
        if weight < c.EVIDENCE_MIN_POINTS:
            continue
        for code in c.DISCIPLINE_SKILLS.get(fact.discipline_code, ()):
            offer(code, "discipline", fact, weight)
        if fact.participation == TEAM:
            offer(c.SKILL_TEAMWORK, "discipline", fact, weight)
        speaks = fact.stage in _PUBLIC_SPEAKING_STAGES and fact.tier in _LEADERSHIP_TIERS
        if fact.discipline_code == "product" and speaks:
            offer(c.SKILL_PUBLIC_SPEAKING, "discipline", fact, weight)

    captain = captain_facts(facts, as_of)
    many = len(captain) >= c.CAPTAIN_STRONG_COUNT
    for fact in captain:
        if many or fact.tier in _LEADERSHIP_TIERS:
            offer(c.SKILL_LEADERSHIP, "role", fact, 0.0)
    for fact in coach_facts(facts, as_of):
        if fact.level in _COACH_MENTORING_LEVELS:
            offer(c.SKILL_MENTORING, "role", fact, 0.0)
    return [item for _, _, item in sorted(best.values(), key=lambda row: row[2].skill_code)]


# ---------------------------------------------------------------------------------------------------------------------
# Показ работодателю (приложение D, §6.1, §6.2, §6.4)
# ---------------------------------------------------------------------------------------------------------------------


def has_verified_facts(facts: Iterable[Fact], ranks: Iterable[Rank]) -> bool:
    """Есть ли подтверждённые сведения ФСП (Арх. 7.7).

    Подтверждённый результат в любой роли (в том числе тренера) либо разряд без отзыва — действующий или
    истёкший. Один предикат используется в трёх местах: `history_status = has_history`, режим показа,
    фильтр работодателя.
    """
    return any(fact.verified for fact in facts) or any(rank.revoked_on is None for rank in ranks)


def is_visible(*, linked: bool, show_summary: bool) -> bool:
    """`visible = linked and show_summary`: участие в ранжировании, фильтре, подтверждениях и доводах (Арх. 7.7).

    Скрыто — значит не учитывается: иначе место в выдаче и фильтр выдавали бы то, что кандидат скрыл.
    """
    return linked and show_summary


def display_mode(
    *, linked: bool, has_verified: bool, show_summary: bool, reveal_details: bool, disclosed: bool
) -> DisplayMode:
    """Режим блока ФСП для работодателя (Арх. 7.7).

    ```
    'none'      если not linked или нет подтверждённых фактов
    'detailed'  если disclosed and reveal_details
    'summary'   если show_summary
    'none'      иначе
    ```
    """
    if not linked or not has_verified:
        return "none"
    if disclosed and reveal_details:
        return "detailed"
    return "summary" if show_summary else "none"


def period_of(event_date: date, as_of: date) -> str:
    """Корзина давности: `recent` ≤ 730 дней, `mid` ≤ 1461 день, иначе `old` (Арх. 7.7)."""
    days = (as_of - event_date).days
    if days <= c.PERIOD_RECENT_DAYS:
        return "recent"
    return "mid" if days <= c.PERIOD_MID_DAYS else "old"


def public_summary(
    facts: Sequence[Fact], ranks: Sequence[Rank], specialization: str | None, as_of: date, k_anon: int
) -> PublicSummary | None:
    """Обобщённая строка достижений до раскрытия (Арх. 7.7; приложение D, §6.2).

    Строится по ведущему зачтённому факту (наибольший `p`, тот же порядок, что в сигнале) из четырёх огрублённых
    признаков: дисциплина, `tier`, период, корзина результата. Уровень обобщения зависит от счётчиков реестра
    при пороге `K = k_anon`: `k_a ≥ K` — все четыре признака (уровень 3); иначе `k_b ≥ K` — дисциплина и уровень
    (уровень 2); иначе «Есть подтверждённые достижения ФСП» (уровень 1). `k_a` считается неизвестным, если
    корзина давности сменилась после снимка (`anon_period != period`). Зачтённых фактов нет (только разряд или
    роли) — уровень 1. Нет подтверждённых сведений — `None`. `more` — зачтённых фактов два и больше; число
    и состав остальных не раскрываются. До раскрытия не показываются год, название, точное место, команда,
    роль и разряд.
    """
    if not has_verified_facts(facts, ranks):
        return None
    by_id = {fact.id: fact for fact in facts}
    contributions = ordered_contributions(facts, specialization, as_of)
    generic = PublicSummary(
        level=1,
        headline=c.SUMMARY_GENERIC_HEADLINE,
        short=c.SUMMARY_GENERIC_SHORT,
        more=len(contributions) >= 2,
        shortened=bool(contributions),
    )
    if not contributions:
        return generic
    lead = by_id[contributions[0].fact_id]
    if lead.event_date is None or lead.tier is None:
        return generic
    period = period_of(lead.event_date, as_of)
    bucket = lead.result_bucket or "participant"
    discipline = lead.discipline_code if lead.discipline_code in c.DISCIPLINE_LABEL else c.DISCIPLINE_OTHER
    discipline_label = c.DISCIPLINE_LABEL[discipline]
    discipline_title = discipline_label[:1].upper() + discipline_label[1:]
    k_a = lead.anon_k_a if lead.anon_period == period else None
    more = len(contributions) >= 2
    if k_a is not None and k_a >= k_anon:
        headline = " · ".join(
            (discipline_title, c.TIER_LABEL[lead.tier], c.PERIOD_LABEL[period], c.BUCKET_LABEL[bucket])
        )
        short = f"{c.TIER_SHORT[lead.tier]} · {c.BUCKET_SHORT[bucket]}"
        return PublicSummary(level=3, headline=headline, short=short, more=more, shortened=False)
    if lead.anon_k_b is not None and lead.anon_k_b >= k_anon:
        return PublicSummary(
            level=2,
            headline=f"{discipline_title} · {c.TIER_LABEL[lead.tier]}",
            short=c.TIER_SHORT[lead.tier],
            more=more,
            shortened=True,
        )
    return generic
