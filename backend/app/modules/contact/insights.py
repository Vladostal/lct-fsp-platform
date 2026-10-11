"""Сводки и предпроверка модуля `contact`: квота, состояние пары, воронки, медиана вилок, показатели.

Всё здесь — чтение без блокировок и без `settle` (Арх. 4.4): статусы считаются через `rules.effective_*`.
Ни одна функция для работодателя не читает минимум кандидата (инвариант I8).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timedelta
from statistics import median
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.assessment import service as assessment_service
from app.modules.catalog import service as catalog_service
from app.modules.contact import checks, projections, rules, texts
from app.modules.contact import constants as c
from app.modules.contact.models import Complaint, EmployerContactState, Invitation, InvitationTerms
from app.modules.contact.schemas import (
    ComplaintAdminView,
    FunnelView,
    InvitationFunnel,
    InvitationPrecheckView,
    InvitationStatsView,
    InvitationSummaryView,
    MissingSkill,
    NeedFunnel,
    NeedInsightsView,
    NotDeliveredItem,
    PairBlockView,
    PairInvitationView,
    PairStateItem,
    PairStatesView,
    PlatformMetricsView,
    PrecheckBlocker,
    PrecheckPair,
    QuotaView,
    ReasonCount,
    SalaryHint,
    StatedFormat,
    StatedSalary,
)
from app.modules.identity import service as identity_service
from app.modules.matching import service as matching_service
from app.modules.profile import service as profile_service
from app.shared.enums import (
    ComplaintReason,
    ComplaintStatus,
    ConditionKind,
    DeclineReason,
    InvitationStatus,
    VisibilityState,
    WorkFormat,
)

# --------------------------------------------------------------------------------------------------------------------
# Квота, предпроверка, состояние пары
# --------------------------------------------------------------------------------------------------------------------


def _quota_from(ctx: checks.SendContext) -> QuotaView:
    return QuotaView(
        daily_used=len(ctx.daily_created),
        daily_limit=ctx.daily_limit,
        frozen=ctx.frozen,
    )


def quota(db: Session, now: datetime, employer_id: UUID) -> QuotaView:
    """Суточный лимит работодателя (Арх. 4.7)."""
    state = checks.employer_state(db, employer_id)
    account = identity_service.users(db, [employer_id]).get(employer_id)
    return QuotaView(
        daily_used=len(checks.daily_created(db, employer_id, now)),
        daily_limit=c.DEMO_DAILY_SEND_LIMIT if account is not None and account.is_demo else c.DAILY_SEND_LIMIT,
        frozen=bool(state and state.sending_frozen_at is not None),
    )


def salary_hint_for(db: Session, now: datetime, category_code: str) -> SalaryHint | None:
    """Медиана вилок принятых приглашений кандидатам категории за `SALARY_HINT_WINDOW_DAYS` (Арх. 4.11).

    Сведения о предложениях работодателей, а не о минимумах кандидатов; правило порогов — `rules.salary_hint`.
    """
    rows = db.execute(
        select(Invitation.employer_id, Invitation.candidate_id, InvitationTerms.salary_from, InvitationTerms.salary_to)
        .join(InvitationTerms, InvitationTerms.invitation_id == Invitation.id)
        .where(
            Invitation.status == InvitationStatus.ACCEPTED.value,
            Invitation.resolved_at > now - timedelta(days=c.SALARY_HINT_WINDOW_DAYS),
        )
    ).all()
    if len(rows) < c.SALARY_HINT_MIN_N:
        return None
    categories = assessment_service.get_categories(db, {row.candidate_id for row in rows})
    offers = [
        (row.employer_id, row.salary_from, row.salary_to)
        for row in rows
        if (category := categories.get(row.candidate_id)) is not None and category.category_code == category_code
    ]
    hint = rules.salary_hint(offers)
    return SalaryHint(from_=hint[0], to=hint[1]) if hint is not None else None


def precheck(
    db: Session, now: datetime, employer_id: UUID, candidate_id: UUID, need_id: UUID | None
) -> InvitationPrecheckView:
    """Несекретная предпроверка отправки (Арх. 4.5): проверки 5.1–5.11, кроме 5.4 и 5.5, без блокировок и записи.

    Вилка и минимум кандидата не участвуют. `candidate_formats` заполняется, только если кандидат доступен для
    приглашения либо пара раскрыта: при блокере `candidate_unavailable` о профиле не сообщается ничего.
    """
    need = matching_service.need_ref(db, employer_id, need_id) if need_id is not None else None  # чужая — 404
    ctx = checks.gather(db, now, employer_id, candidate_id)
    blockers: list[PrecheckBlocker] = []
    seen: set[str] = set()
    for violation in checks.violations(ctx):
        if violation.code in seen:
            continue
        seen.add(violation.code)
        blockers.append(
            PrecheckBlocker(
                code=violation.code,
                message=texts.message(violation.code, violation.params),
                params=violation.params or None,
            )
        )

    revisable: Invitation | None = None
    revised = {inv.revises_id for inv in ctx.pair if inv.revises_id is not None}
    for inv in sorted(ctx.pair, key=lambda item: item.created_at, reverse=True):
        if rules.can_revise(inv, now, has_revision=inv.id in revised):
            revisable = inv
            break
    block = rules.pair_block(ctx.pair, now)
    masked = rules.is_masked_pair(employer_is_demo=ctx.employer_is_demo, candidate_is_demo=ctx.candidate_is_demo)
    condition = projections._condition(revisable) if revisable is not None and not masked else None

    unavailable = "candidate_unavailable" in seen
    formats: list[WorkFormat] = []
    if ctx.candidate_exists and (not unavailable or profile_service.is_disclosed(db, employer_id, candidate_id)):
        formats = list(ctx.candidate_formats)

    category_code: str | None = need.category_code if need is not None else None
    if category_code is None and ctx.candidate_exists and not unavailable:
        category = assessment_service.get_category(db, candidate_id)
        category_code = category.category_code if category is not None else None
    return InvitationPrecheckView(
        can_invite=not blockers,
        blockers=blockers,
        quota=_quota_from(ctx),
        pair=PrecheckPair(
            block_until=block.until if block is not None else None,
            can_revise=revisable is not None,
            revises_id=revisable.id if revisable is not None else None,
            condition=condition,
        ),
        candidate_formats=formats,
        expires_at_preview=now + c.INVITATION_TTL,
        salary_hint=salary_hint_for(db, now, category_code) if category_code else None,
    )


def pair_states(db: Session, now: datetime, employer_id: UUID, candidate_ids: Sequence[UUID]) -> PairStatesView:
    """Состояние пар «я — кандидат» одним запросом по всем идентификаторам (Арх. 9.9; до 100 штук)."""
    by_candidate: dict[UUID, list[Invitation]] = {}
    rows = db.scalars(
        select(Invitation).where(Invitation.employer_id == employer_id, Invitation.candidate_id.in_(set(candidate_ids)))
    )
    for inv in rows:
        by_candidate.setdefault(inv.candidate_id, []).append(inv)
    items: list[PairStateItem] = []
    for candidate_id in dict.fromkeys(candidate_ids):
        pair = by_candidate.get(candidate_id, [])
        last = max(pair, key=lambda item: (item.created_at, item.id), default=None)
        block = rules.pair_block(pair, now)
        items.append(
            PairStateItem(
                candidate_id=candidate_id,
                invitation=(
                    PairInvitationView(id=last.id, status=rules.effective_status(last, now), expires_at=last.expires_at)
                    if last is not None
                    else None
                ),
                pair_block=PairBlockView(code=block.code, until=block.until) if block is not None else None,
            )
        )
    return PairStatesView(items=items)


# --------------------------------------------------------------------------------------------------------------------
# Воронка и сводка причин работодателя (Арх. 4.11; приложение C, §8.1)
# --------------------------------------------------------------------------------------------------------------------


def _funnel(invs: Sequence[Invitation], now: datetime) -> InvitationFunnel:
    funnel = InvitationFunnel()
    for inv in invs:
        status = rules.effective_status(inv, now)
        if status is InvitationStatus.BOUNCED:
            funnel.not_delivered += 1
            continue
        funnel.delivered += 1
        if inv.viewed_at is not None:
            funnel.viewed += 1
        if status is InvitationStatus.ACCEPTED:
            funnel.accepted += 1
        elif status is InvitationStatus.DECLINED:
            funnel.declined += 1
        elif status is InvitationStatus.EXPIRED:
            funnel.expired += 1
        elif status is InvitationStatus.WITHDRAWN:
            funnel.withdrawn += 1
    return funnel


def _reasons(invs: Sequence[Invitation]) -> list[ReasonCount]:
    counts = Counter(inv.decline_reason for inv in invs if inv.status == "declined" and inv.decline_reason)
    return [
        ReasonCount(reason_code=reason, reason_label=texts.DECLINE_REASON_LABELS[reason], count=counts[reason.value])
        for reason in DeclineReason
        if counts[reason.value]
    ]


def _median_response_hours(invs: Sequence[Invitation]) -> float | None:
    """Медиана `resolved_at − created_at` по принятым и отклонённым; при числе ответов меньше порога — `None`."""
    hours = [
        (inv.resolved_at - inv.created_at).total_seconds() / 3600
        for inv in invs
        if inv.status in ("accepted", "declined") and inv.resolved_at is not None
    ]
    return round(median(hours), 1) if len(hours) >= c.MEDIAN_RESPONSE_MIN_N else None


def stats(db: Session, now: datetime, employer_id: UUID) -> InvitationStatsView:
    """Собственная воронка работодателя: итог, разбивка по потребностям, медиана времени до ответа, причины."""
    invs = list(db.scalars(select(Invitation).where(Invitation.employer_id == employer_id)))
    last_foreign = projections.last_foreign_events(db, [inv.id for inv in invs])
    by_need: dict[UUID, list[Invitation]] = {}
    for inv in invs:
        if inv.need_id is not None:
            by_need.setdefault(inv.need_id, []).append(inv)
    return InvitationStatsView(
        total=_funnel(invs, now),
        by_need=[
            NeedFunnel(
                need_id=need_id,
                funnel=_funnel(rows, now),
                awaiting=sum(1 for inv in rows if rules.is_active(rules.effective_status(inv, now).value)),
                updates=sum(
                    1 for inv in rows if rules.is_new_for_employer(inv.employer_seen_at, last_foreign.get(inv.id))
                ),
            )
            for need_id, rows in sorted(by_need.items(), key=lambda item: str(item[0]))
        ],
        median_response_hours=_median_response_hours(invs),
        reasons=_reasons(invs),
    )


def need_insights(db: Session, now: datetime, employer_id: UUID, need_id: UUID) -> NeedInsightsView:
    """Сводка причин по потребности и подсказки к запросу (Арх. 4.11).

    Подсказки по формату и стеку считает подбор по открытым данным; подсказка по зарплате использует только суммы,
    которые кандидаты назвали сами, и медиану вилок категории.
    """
    need = matching_service.need_ref(db, employer_id, need_id)  # чужая — 404
    invs = list(
        db.scalars(select(Invitation).where(Invitation.employer_id == employer_id, Invitation.need_id == need_id))
    )
    accounts = identity_service.users(db, {inv.candidate_id for inv in invs} | {employer_id}) if invs else {}
    employer = accounts.get(employer_id)

    def masked(inv: Invitation) -> bool:
        account = accounts.get(inv.candidate_id)
        return rules.is_masked_pair(
            employer_is_demo=bool(employer and employer.is_demo), candidate_is_demo=bool(account and account.is_demo)
        )

    declined = [inv for inv in invs if inv.status == "declined" and not masked(inv)]
    salaries = Counter(
        inv.decline_condition_salary_from
        for inv in declined
        if inv.decline_condition_kind == ConditionKind.SALARY_FROM.value and inv.decline_condition_salary_from
    )
    formats = Counter(
        inv.decline_condition_work_format
        for inv in declined
        if inv.decline_condition_kind == ConditionKind.WORK_FORMAT.value and inv.decline_condition_work_format
    )
    reasons = _reasons(invs)
    by_reason = {item.reason_code: item.count for item in reasons}

    kinds: set[str] = set()
    if by_reason.get(DeclineReason.FORMAT, 0) >= c.REASON_HINT_MIN:
        kinds.add("add_format")
    if by_reason.get(DeclineReason.STACK, 0) >= c.REASON_HINT_MIN:
        kinds.add("move_must_to_nice")
    hints = matching_service.relaxation_hints(db, employer_id, need_id, kinds, now) if kinds else []

    stated_salary = [StatedSalary(value=int(value), count=count) for value, count in sorted(salaries.items()) if value]
    note: str | None = None
    if by_reason.get(DeclineReason.SALARY, 0) >= c.REASON_HINT_MIN:
        hint = salary_hint_for(db, now, need.category_code)
        note = texts.salary_note(
            [(item.value, item.count) for item in stated_salary], (hint.from_, hint.to) if hint is not None else None
        )
    return NeedInsightsView(
        funnel=_funnel(invs, now),
        reasons=reasons,
        stated_salary=stated_salary,
        stated_formats=[
            StatedFormat(value=WorkFormat(value), count=count) for value, count in sorted(formats.items()) if value
        ],
        hints=hints,
        salary_note=note,
    )


# --------------------------------------------------------------------------------------------------------------------
# Кабинет кандидата: счётчики и воронка спроса (Арх. 4.12)
# --------------------------------------------------------------------------------------------------------------------


def candidate_summary(db: Session, now: datetime, candidate_id: UUID) -> InvitationSummaryView:
    """Счётчики вкладок входящих, счётчик молчания и состояние показа. Ничего не пишет (Арх. 9.9)."""
    invs = list(
        db.scalars(
            select(Invitation).where(
                Invitation.candidate_id == candidate_id, Invitation.status != InvitationStatus.BOUNCED.value
            )
        )
    )
    counts: Counter[str] = Counter()
    prompts = 0
    for inv in invs:
        status = rules.effective_status(inv, now)
        if status in (InvitationStatus.SENT, InvitationStatus.VIEWED):
            counts["awaiting"] += 1
        elif status is InvitationStatus.ACCEPTED:
            counts["accepted"] += 1
            prompts += rules.outcome_prompt(inv.status, inv.resolved_at, inv.candidate_outcome_at is not None, now)
        else:
            counts["archived"] += 1
    return InvitationSummaryView(
        awaiting=counts["awaiting"],
        accepted=counts["accepted"],
        archived=counts["archived"],
        outcome_prompts=prompts,
        strikes=projections.strikes(db, candidate_id),
        visibility=profile_service.visibility(db, candidate_id, now),
    )


def candidate_funnel(db: Session, now: datetime, candidate_id: UUID) -> FunnelView:
    """Воронка спроса кандидата за `FUNNEL_WINDOW_DAYS` (Арх. 4.12).

    Демо-приглашение живому кандидату в `delivered` и `not_delivered` не входит (`rules.counts_for_candidate`,
    поправка R3-mechanics-recheck-4): иначе стадии диагноза живой кандидат не увидел бы никогда.
    """
    since = now - timedelta(days=c.FUNNEL_WINDOW_DAYS)
    rows = db.execute(
        select(Invitation, InvitationTerms)
        .join(InvitationTerms, InvitationTerms.invitation_id == Invitation.id)
        .where(Invitation.candidate_id == candidate_id, Invitation.created_at > since)
        .order_by(Invitation.created_at.desc(), Invitation.id.desc())
    ).all()
    account = identity_service.users(db, [candidate_id]).get(candidate_id)
    candidate_is_demo = bool(account and account.is_demo)
    delivered = 0
    bounced: list[NotDeliveredItem] = []
    for inv, terms in rows:
        if not rules.counts_for_candidate(invitation_is_demo=inv.is_demo, candidate_is_demo=candidate_is_demo):
            continue
        if inv.status == InvitationStatus.BOUNCED.value:
            bounced.append(
                NotDeliveredItem(
                    salary_from=terms.salary_from,
                    salary_to=terms.salary_to,
                    work_format=WorkFormat(terms.work_format),
                    at=inv.created_at,
                )
            )
        else:
            delivered += 1
    exposure = matching_service.exposure_stats(db, candidate_id, since, now)
    visible = profile_service.visibility(db, candidate_id, now).state == VisibilityState.VISIBLE

    missing: MissingSkill | None = None
    if exposure.unconfirmed_must:
        code, needs = Counter(exposure.unconfirmed_must).most_common(1)[0]
        if needs >= c.FUNNEL_SKILL_MIN_NEEDS:
            try:
                missing = MissingSkill(skill=catalog_service.skill_ref(code), needs=needs)
            except KeyError:  # навыка уже нет в справочнике: строка «чего не хватило» не показывается
                missing = None
    return FunnelView(
        window_days=c.FUNNEL_WINDOW_DAYS,
        shown=exposure.needs_shown,
        opened=exposure.employers_opened,
        delivered=delivered,
        not_delivered=len(bounced),
        stage=rules.funnel_stage(
            visible=visible,
            shown=exposure.needs_shown,
            opened=exposure.employers_opened,
            delivered=delivered,
            not_delivered=len(bounced),
        ),
        not_delivered_items=bounced[: c.FUNNEL_NOT_DELIVERED_ITEMS],
        missing_skill=missing,
    )


# --------------------------------------------------------------------------------------------------------------------
# Показатели платформы и жалобы (P1)
# --------------------------------------------------------------------------------------------------------------------


def platform_metrics(db: Session, now: datetime) -> PlatformMetricsView:
    """P1: живые показатели платформы за `METRIC_WINDOW_DAYS` (Арх. 4.12; приложение C, §8.2).

    Не учитываются приглашения кандидатам, чья категория получена быстрым демо-тестом (`is_demo_result`).
    Охват (`coverage_share`) требует списка всех видимых кандидатов, которого у нижних фасадов нет: живой
    эндпоинт отдаёт `null`, число печатает отчёт `eval-contact`.
    """
    since = now - timedelta(days=c.METRIC_WINDOW_DAYS)
    invs = list(db.scalars(select(Invitation).where(Invitation.created_at > since)))
    categories = assessment_service.get_categories(db, {inv.candidate_id for inv in invs}) if invs else {}
    invs = [
        inv
        for inv in invs
        if not ((category := categories.get(inv.candidate_id)) is not None and category.is_demo_result)
    ]
    funnel = _funnel(invs, now)
    answered = funnel.accepted + funnel.declined
    hours = [
        (inv.resolved_at - inv.created_at).total_seconds() / 3600
        for inv in invs
        if inv.status in ("accepted", "declined") and inv.resolved_at is not None
    ]
    confirmed = [
        inv.candidate_contacted for inv in invs if inv.status == "accepted" and inv.candidate_contacted is not None
    ]
    per_candidate = Counter(inv.candidate_id for inv in invs if inv.status != InvitationStatus.BOUNCED.value)
    return PlatformMetricsView(
        window_days=c.METRIC_WINDOW_DAYS,
        invitations=len(invs),
        delivered_share=rules.share(funnel.delivered, len(invs)),
        reply_in_time_share=rules.share(answered, answered + funnel.expired),
        accept_share=rules.share(funnel.accepted, answered + funnel.expired),
        median_response_hours=round(median(hours), 1) if hours else None,
        contact_confirmed_share=rules.share(sum(confirmed), len(confirmed)),
        coverage_share=None,
        concentration_gini=rules.gini(list(per_candidate.values())),
    )


def complaints(db: Session) -> list[ComplaintAdminView]:
    """P1: жалобы для служебного разбора, новые первыми."""
    rows = db.execute(
        select(Complaint, InvitationTerms.company_name)
        .join(InvitationTerms, InvitationTerms.invitation_id == Complaint.invitation_id)
        .order_by(Complaint.created_at.desc(), Complaint.id)
        .limit(500)
    ).all()
    employers = {complaint.employer_id for complaint, _ in rows}
    frozen = (
        set(
            db.scalars(
                select(EmployerContactState.employer_id).where(
                    EmployerContactState.employer_id.in_(employers), EmployerContactState.sending_frozen_at.is_not(None)
                )
            )
        )
        if employers
        else set()
    )
    return [complaint_view(complaint, name, complaint.employer_id in frozen) for complaint, name in rows]


def complaint_view(complaint: Complaint, company_name: str, employer_frozen: bool) -> ComplaintAdminView:
    reason = ComplaintReason(complaint.reason_code)
    return ComplaintAdminView(
        id=complaint.id,
        invitation_id=complaint.invitation_id,
        candidate_id=complaint.candidate_id,
        employer_id=complaint.employer_id,
        company_name=company_name,
        reason_code=reason,
        reason_label=texts.COMPLAINT_REASON_LABELS[reason],
        comment=complaint.comment,
        status=ComplaintStatus(complaint.status),
        created_at=complaint.created_at,
        resolved_at=complaint.resolved_at,
        employer_frozen=employer_frozen,
    )
