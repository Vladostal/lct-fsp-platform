"""Симуляция механики контакта (Арх. 12.4; приложение C, §8.3).

Модель:

* популяция кандидатов по Арх. 12.1: персона (`responsive` 55 %, `selective` 20 %, `expensive` 15 %, `silent` 10 %),
  минимум (у 30 % не задан, у остальных — ступень лестницы, ближайшая к медиане × exp(N(0, 0.2))), сила профиля;
* 30 работодателей с одной потребностью: подборка — 40 кандидатов по убыванию «сила + шум работодателя»; раз в сутки
  работодатель приглашает следующих по подборке, пока не набрано три согласия и не исчерпан суточный лимит;
  вилка равна вилке потребности;
* внимание кандидата: вероятность ответить в срок `p = base[persona] / (1 + ALPHA * max(0, pending - 1))` —
  допущение о перегрузе; что ответить, решает боевая `rules.demo_decision`;
* режимы: A — без лимитов; B — суточный лимит отправки, ёмкость входящих и автопауза.

Сверка вилки, право и условия пересмотра считаются боевыми
функциями `app.modules.contact.rules` с боевыми константами.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from statistics import median
from uuid import UUID

from app.modules.contact import constants as c
from app.modules.contact import rules
from app.shared.enums import DemoPersona, FitBand, InvitationStatus
from app.shared.salary import MIN_SALARY_HIGH, MIN_SALARY_LOW, MIN_SALARY_STEP, SALARY_MAX_RATIO, min_salary_ladder

EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
HORIZON_DAYS = 28
EMPLOYERS = 30
SHORTLIST = 40
TARGET_ACCEPTS = 3
CATEGORY_MEDIAN = 160_000
#: Вероятность ответить в срок без перегруза — допущение модели.
BASE_REPLY = {
    DemoPersona.RESPONSIVE: 0.9,
    DemoPersona.SELECTIVE: 0.8,
    DemoPersona.EXPENSIVE: 0.8,
    DemoPersona.SILENT: 0.0,
}
PERSONA_SHARE = (
    (DemoPersona.RESPONSIVE, 0.55),
    (DemoPersona.SELECTIVE, 0.20),
    (DemoPersona.EXPENSIVE, 0.15),
    (DemoPersona.SILENT, 0.10),
)
MODES = ("A", "B")
MODE_LABELS = {
    "A": "A — без лимитов",
    "B": "B — суточный лимит, ёмкость входящих, автопауза",
}


def at(hours: float) -> datetime:
    """Момент симуляции: часы от начала горизонта."""
    return EPOCH + timedelta(hours=hours)


@dataclass(slots=True)
class Candidate:
    """Синтетический кандидат (Арх. 12.1)."""

    index: int
    persona: DemoPersona
    min_salary: int | None
    strength: float
    pending: int = 0
    strikes: int = 0
    paused_until: datetime | None = None
    delivered: int = 0


@dataclass(slots=True)
class Inv:
    """Приглашение симуляции: те же поля, что читают боевые правила (`rules.InvitationFacts`)."""

    employer: int
    candidate: int
    salary_from: int
    status: str
    created_at: datetime
    expires_at: datetime
    resolved_at: datetime | None = None
    pair_block_until: datetime | None = None
    # Поля пересмотра (`rules.RevisableFacts`).
    employer_id: UUID = field(default_factory=lambda: UUID(int=0))
    candidate_id: UUID = field(default_factory=lambda: UUID(int=0))
    revises_id: UUID | None = None
    decline_condition_kind: str | None = None
    decline_condition_salary_from: int | None = None
    decline_condition_work_format: str | None = None
    reply_at: datetime | None = None
    fit: FitBand = FitBand.GOOD
    is_revision: bool = False
    revised: bool = False


@dataclass(slots=True)
class Employer:
    """Работодатель с одной потребностью и её подборкой."""

    index: int
    salary_from: int
    shortlist: list[int]
    cursor: int = 0
    accepts: int = 0
    first_accept_day: float | None = None
    invitations: list[Inv] = field(default_factory=list)
    revise_queue: list[Inv] = field(default_factory=list)


@dataclass(slots=True)
class RunResult:
    """Счётчики одного прогона."""

    sent: int = 0
    bounced: int = 0
    accepted: int = 0
    declined: int = 0
    expired: int = 0
    response_hours: list[float] = field(default_factory=list)
    needs_filled: int = 0
    first_accept_days: list[float] = field(default_factory=list)
    coverage: float = 0.0
    gini: float | None = None
    revisions_after_bounce: int = 0
    revisions_after_bounce_delivered: int = 0
    attempts_by_quartile: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
    bounced_by_quartile: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
    feasible_at_10: float = 0.0
    feasible_at_10_median: float = 0.0
    auto_pauses: int = 0


def snap_to_ladder(value: float) -> int:
    """Ступень лестницы минимума, ближайшая к значению."""
    step = round((value - MIN_SALARY_LOW) / MIN_SALARY_STEP)
    return int(min(MIN_SALARY_HIGH, max(MIN_SALARY_LOW, MIN_SALARY_LOW + step * MIN_SALARY_STEP)))


def make_population(rng: random.Random, n: int, silent_share: float) -> list[Candidate]:
    """Популяция по Арх. 12.1; доля молчащих меняется в анализе чувствительности за счёт остальных персон."""
    rest = 1.0 - silent_share
    base_rest = 1.0 - 0.10
    weights: list[tuple[DemoPersona, float]] = [
        (persona, share / base_rest * rest) for persona, share in PERSONA_SHARE if persona != DemoPersona.SILENT
    ]
    weights.append((DemoPersona.SILENT, silent_share))
    personas = [persona for persona, _ in weights]
    shares = [share for _, share in weights]
    result = []
    for index in range(n):
        minimum = None if rng.random() < 0.30 else snap_to_ladder(CATEGORY_MEDIAN * math.exp(rng.gauss(0, 0.2)))
        result.append(Candidate(index, rng.choices(personas, shares)[0], minimum, rng.gauss(0, 1)))
    return result


def make_employers(rng: random.Random, population: list[Candidate]) -> list[Employer]:
    """30 работодателей: вилка потребности около медианы категории, подборка — по силе профиля с шумом."""
    employers = []
    for index in range(EMPLOYERS):
        salary_from = int(round(CATEGORY_MEDIAN * math.exp(rng.gauss(0.05, 0.12)) / 10_000) * 10_000)
        ranked = sorted(population, key=lambda cand: cand.strength + rng.gauss(0, 0.7), reverse=True)
        employers.append(Employer(index, salary_from, [cand.index for cand in ranked[:SHORTLIST]]))
    return employers


def _fit(position: int) -> FitBand:
    return FitBand.STRONG if position < SHORTLIST // 3 else FitBand.GOOD


def run_once(seed: int, mode: str, alpha: float, silent_share: float, n: int) -> RunResult:
    """Один прогон на 28 суток. Популяция и подборки зависят только от `seed` — режимы сравниваются на одних данных."""
    world_rng = random.Random(seed)
    population = make_population(world_rng, n, silent_share)
    employers = make_employers(world_rng, population)
    rng = random.Random(seed * 7919 + ord(mode))
    result = RunResult()
    limits_on = mode == "B"
    order = sorted(range(n), key=lambda i: population[i].strength)
    quartile = {index: min(3, rank * 4 // n) for rank, index in enumerate(order)}
    active: list[Inv] = []

    def resolve(now: datetime) -> None:
        """Ответы и истечения, назревшие к `now` (переходы T4–T6)."""
        nonlocal active
        still: list[Inv] = []
        for inv in sorted(active, key=lambda item: item.reply_at or item.expires_at):
            cand = population[inv.candidate]
            employer = employers[inv.employer]
            if inv.reply_at is not None and inv.reply_at <= now:
                meets = (
                    inv.is_revision
                    and inv.decline_condition_salary_from is not None
                    and inv.salary_from >= inv.decline_condition_salary_from
                )
                decision = rules.demo_decision(
                    cand.persona, salary_from=inv.salary_from, fit_band=inv.fit, revision_meets_condition=meets
                )
                assert decision is not None
                inv.resolved_at = inv.reply_at
                cand.pending -= 1
                cand.strikes = 0
                result.response_hours.append((inv.reply_at - inv.created_at).total_seconds() / 3600)
                if decision.action == "accept":
                    inv.status = InvitationStatus.ACCEPTED.value
                    result.accepted += 1
                    employer.accepts += 1
                    if employer.first_accept_day is None:
                        employer.first_accept_day = (inv.reply_at - EPOCH).total_seconds() / 86400
                else:
                    inv.status = InvitationStatus.DECLINED.value
                    result.declined += 1
                    if decision.condition_salary_from is not None and not inv.is_revision:
                        inv.decline_condition_kind = "salary_from"
                        inv.decline_condition_salary_from = decision.condition_salary_from
                        employer.revise_queue.append(inv)
            elif inv.expires_at <= now:
                inv.status = InvitationStatus.EXPIRED.value
                inv.resolved_at = inv.expires_at
                cand.pending -= 1
                result.expired += 1
                cand.strikes += 1
                if limits_on and rules.strike_triggers_pause(cand.strikes) and cand.paused_until is None:
                    cand.paused_until = inv.expires_at + c.AUTO_PAUSE_MAX
                    result.auto_pauses += 1
            else:
                still.append(inv)
        active = still
        for cand in population:
            if cand.paused_until is not None and cand.paused_until <= now:
                cand.paused_until = None
                cand.strikes = rules.strikes_after_auto_resume()

    def attempt(employer: Employer, cand: Candidate, salary_from: int, now: datetime, original: Inv | None) -> Inv:
        """Отправка: боевая сверка вилки; `sent` либо `bounced`."""
        delivered = rules.salary_ok(salary_from, cand.min_salary)
        inv = Inv(
            employer=employer.index,
            candidate=cand.index,
            salary_from=salary_from,
            status=(InvitationStatus.SENT if delivered else InvitationStatus.BOUNCED).value,
            created_at=now,
            expires_at=now + c.INVITATION_TTL,
            fit=_fit(employer.shortlist.index(cand.index)),
            is_revision=original is not None,
        )
        result.attempts_by_quartile[quartile[cand.index]] += 1
        employer.invitations.append(inv)
        if original is not None:
            original.revised = True
            inv.decline_condition_salary_from = original.decline_condition_salary_from
            if original.status == InvitationStatus.BOUNCED.value:
                result.revisions_after_bounce += 1
                result.revisions_after_bounce_delivered += delivered
        if not delivered:
            inv.resolved_at = now
            result.bounced += 1
            result.bounced_by_quartile[quartile[cand.index]] += 1
            if original is None:
                employer.revise_queue.append(inv)
            return inv
        result.sent += 1
        cand.pending += 1
        cand.delivered += 1
        base = BASE_REPLY[cand.persona]
        probability = base / (1 + alpha * max(0, cand.pending - 1))
        if rng.random() < probability:
            inv.reply_at = now + timedelta(hours=rng.uniform(2, c.INVITATION_TTL_DAYS * 24 - 1))
        active.append(inv)
        return inv

    def available(cand: Candidate, now: datetime) -> bool:
        if not limits_on:
            return True
        if cand.paused_until is not None and cand.paused_until > now:
            return False
        return cand.pending < c.CANDIDATE_INBOX_CAPACITY

    def can_send(employer: Employer, now: datetime) -> bool:
        """Боевой суточный лимит: попытки за скользящие 24 часа, включая недоставленные."""
        if not limits_on:
            return True
        return rules.daily_retry_after([inv.created_at for inv in employer.invitations], now) is None

    for day in range(HORIZON_DAYS):
        now = at(day * 24)
        resolve(now)
        for employer in rng.sample(employers, len(employers)):
            if employer.accepts >= TARGET_ACCEPTS:
                continue
            # Пересмотры: после bounced — «от» на шаг выше; после отказа с суммой — названная сумма, если в бюджете.
            queue, employer.revise_queue = employer.revise_queue, []
            for original in queue:
                if not can_send(employer, now) or not rules.can_revise(original, now, has_revision=original.revised):
                    continue
                cand = population[original.candidate]
                if original.status == InvitationStatus.BOUNCED.value:
                    proposal = original.salary_from + MIN_SALARY_STEP
                else:
                    proposal = original.decline_condition_salary_from or original.salary_from
                budget = int(employer.salary_from * 1.25)
                if proposal > budget or not available(cand, now):
                    continue
                if not rules.revision_terms_ok(
                    original, original.salary_from, salary_from=proposal, work_format="remote"
                ):
                    continue
                attempt(employer, cand, proposal, now, original)
            while employer.cursor < len(employer.shortlist) and can_send(employer, now):
                cand = population[employer.shortlist[employer.cursor]]
                employer.cursor += 1
                if available(cand, now):
                    attempt(employer, cand, employer.salary_from, now, None)
    end = at(HORIZON_DAYS * 24)
    resolve(end)

    result.needs_filled = sum(1 for employer in employers if employer.accepts >= TARGET_ACCEPTS)
    result.first_accept_days = [e.first_accept_day for e in employers if e.first_accept_day is not None]
    result.coverage = sum(1 for cand in population if cand.delivered > 0) / n
    result.gini = rules.gini([cand.delivered for cand in population])
    top = [(employer, index) for employer in employers for index in employer.shortlist[:10]]
    result.feasible_at_10 = sum(rules.salary_ok(e.salary_from, population[i].min_salary) for e, i in top) / len(top)
    result.feasible_at_10_median = sum(
        rules.salary_ok(CATEGORY_MEDIAN, population[i].min_salary) for _, i in top
    ) / len(top)
    return result


@dataclass(slots=True)
class Aggregate:
    """Средние по прогонам одного режима."""

    mode: str
    runs: int
    invitations: float
    delivered_share: float | None
    reply_in_time_share: float | None
    accept_share: float | None
    median_response_hours: float | None
    coverage: float
    gini: float | None
    needs_filled_share: float
    median_days_to_first_accept: float | None
    bounced_share_by_quartile: list[float | None]
    revision_success_share: float | None
    feasible_at_10: float
    feasible_at_10_median: float
    auto_pauses: float


def aggregate(mode: str, results: list[RunResult]) -> Aggregate:
    """Свести прогоны: показатели платформы (Арх. 4.12) считаются по суммам счётчиков, остальное — средним."""
    runs = len(results)
    sent = sum(r.sent for r in results)
    bounced = sum(r.bounced for r in results)
    accepted = sum(r.accepted for r in results)
    declined = sum(r.declined for r in results)
    expired = sum(r.expired for r in results)
    hours = [h for r in results for h in r.response_hours]
    first = [d for r in results for d in r.first_accept_days]
    ginis = [r.gini for r in results if r.gini is not None]
    attempts = [sum(r.attempts_by_quartile[q] for r in results) for q in range(4)]
    bounces = [sum(r.bounced_by_quartile[q] for r in results) for q in range(4)]
    revisions = sum(r.revisions_after_bounce for r in results)
    return Aggregate(
        mode=mode,
        runs=runs,
        invitations=(sent + bounced) / runs,
        delivered_share=rules.share(sent, sent + bounced),
        reply_in_time_share=rules.share(accepted + declined, accepted + declined + expired),
        accept_share=rules.share(accepted, accepted + declined + expired),
        median_response_hours=round(median(hours), 1) if hours else None,
        coverage=round(sum(r.coverage for r in results) / runs, 4),
        gini=round(sum(ginis) / len(ginis), 4) if ginis else None,
        needs_filled_share=round(sum(r.needs_filled for r in results) / (runs * EMPLOYERS), 4),
        median_days_to_first_accept=round(median(first), 1) if first else None,
        bounced_share_by_quartile=[rules.share(bounces[q], attempts[q]) for q in range(4)],
        revision_success_share=rules.share(sum(r.revisions_after_bounce_delivered for r in results), revisions),
        feasible_at_10=round(sum(r.feasible_at_10 for r in results) / runs, 4),
        feasible_at_10_median=round(sum(r.feasible_at_10_median for r in results) / runs, 4),
        auto_pauses=round(sum(r.auto_pauses for r in results) / runs, 2),
    )


def compare(seed: int, runs: int, alpha: float, silent_share: float, n: int) -> dict[str, Aggregate]:
    """Оба режима на одних и тех же популяциях (одни зёрна прогонов)."""
    return {
        mode: aggregate(mode, [run_once(seed + index, mode, alpha, silent_share, n) for index in range(runs)])
        for mode in MODES
    }


# --------------------------------------------------------------------------------------------------------------------
# Адаптивный перебор минимума (Арх. 4.6, 12.4)
# --------------------------------------------------------------------------------------------------------------------


@dataclass(slots=True)
class AttackCost:
    """Стоимость точного восстановления минимума одного кандидата при `accounts` аккаунтах."""

    accounts: int
    mean_probes: float
    max_probes: int
    mean_accounts_used: float
    mean_days: float
    max_days: int
    same_day_share: float


def _attack_one(target: int | None, accounts: int) -> tuple[int, int, int]:
    """Двоичный поиск минимума одного кандидата с боевыми правилами. Возвращает (проб, аккаунтов, суток).

    Гипотезы: «не задан» и 29 ступеней лестницы. Проба с нижней границей `v` сообщает один бит: `sent` — минимум
    не выше `v`, `bounced` — выше. Ограничения на аккаунт те же, что в бою: у пары две сверки за `PAIR_RETRY_DAYS` —
    исходная отправка и, только после `bounced` и только с большей нижней границей, один пересмотр
    (`rules.can_revise`, `rules.revision_terms_ok`); после `sent` аккаунт для этого кандидата закрыт на 30 дней.
    Суточный лимит одной цели не мешает: двадцать попыток в сутки больше двух проб.
    """
    ladder = min_salary_ladder()
    # Пороги проб: значение ниже лестницы отличает «не задан» от первой ступени.
    thresholds = [MIN_SALARY_LOW - MIN_SALARY_STEP, *ladder]
    hypotheses: list[int | None] = [None, *ladder]  # hypotheses[i] «проходит» при пробе thresholds[j], если i <= j
    truth = hypotheses.index(target)
    low, high = 0, len(hypotheses) - 1
    probes = day = 0
    used: set[int] = set()
    while low < high:
        for account in range(accounts):
            if low >= high:
                break
            used.add(account)
            now = at(day * 24)
            middle = (low + high) // 2
            first = _probe(thresholds[middle], target, now, None)
            probes += 1
            if first.status == InvitationStatus.SENT.value:
                assert truth <= middle
                high = middle
                continue  # аккаунт для этой цели исчерпан: приглашение доставлено, пара занята
            low = middle + 1
            if low >= high:
                break
            middle = (low + high) // 2
            # Пересмотр после bounced: нижняя граница обязана быть строго больше — двоичный поиск идёт вверх.
            assert rules.can_revise(first, now, has_revision=False)
            assert rules.revision_terms_ok(
                first, first.salary_from, salary_from=thresholds[middle], work_format="remote"
            )
            second = _probe(thresholds[middle], target, now, first)
            probes += 1
            assert not rules.can_revise(second, now, has_revision=False)  # пересмотренное пересмотреть нельзя
            if second.status == InvitationStatus.SENT.value:
                high = middle
            else:
                low = middle + 1
        if low < high:
            day += c.PAIR_RETRY_DAYS  # все аккаунты исчерпаны: ждать снятия блокировки пары
    assert low == truth
    return probes, len(used), day


def _probe(salary_from: int, target: int | None, now: datetime, original: Inv | None) -> Inv:
    delivered = rules.salary_ok(salary_from, target)
    inv = Inv(
        employer=0,
        candidate=0,
        salary_from=salary_from,
        status=(InvitationStatus.SENT if delivered else InvitationStatus.BOUNCED).value,
        created_at=now,
        expires_at=now + c.INVITATION_TTL,
        revises_id=UUID(int=1) if original is not None else None,
    )
    if not delivered:
        inv.resolved_at = now
        inv.pair_block_until = now + c.PAIR_RETRY
    return inv


def attack_costs() -> list[AttackCost]:
    """Перебор по всем 30 гипотезам о минимуме при 1, 3 и 5 аккаунтах: среднее и худший случай."""
    targets: list[int | None] = [None, *min_salary_ladder()]
    costs = []
    for accounts in (1, 3, 5):
        outcomes = [_attack_one(target, accounts) for target in targets]
        costs.append(
            AttackCost(
                accounts=accounts,
                mean_probes=round(sum(o[0] for o in outcomes) / len(outcomes), 2),
                max_probes=max(o[0] for o in outcomes),
                mean_accounts_used=round(sum(o[1] for o in outcomes) / len(outcomes), 2),
                mean_days=round(sum(o[2] for o in outcomes) / len(outcomes), 1),
                max_days=max(o[2] for o in outcomes),
                same_day_share=round(sum(1 for o in outcomes if o[2] == 0) / len(outcomes), 4),
            )
        )
    return costs


def revision_pass_blocked() -> bool:
    """Сценарий поправки R3-data-api-security-1: «пропуск» от приглашения одному кандидату к другому.

    Боевая `rules.same_pair` отклоняет пересмотр, если исходное приглашение принадлежит другому работодателю
    или адресовано другому кандидату; иначе один аккаунт вёл бы двоичный поиск без ограничения I9.
    """
    employer, first, second = UUID(int=10), UUID(int=20), UUID(int=30)
    original = _probe(100_000, 200_000, at(0), None)
    original.employer_id, original.candidate_id = employer, first
    return (
        rules.same_pair(original, employer, first)
        and not rules.same_pair(original, employer, second)
        and not rules.same_pair(original, UUID(int=11), first)
    )


#: Верх вилки при данном «от» — для подписи в отчёте.
RATIO = SALARY_MAX_RATIO
