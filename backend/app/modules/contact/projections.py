"""Проекции приглашения для двух сторон (Арх. 4.9; приложение C, §5.3).

Одна строка `invitation` — две проекции. Функции этого файла только читают: статус и блокировка пары
показываются через `rules.effective_*`, `settle` не вызывается, блокировки не берутся (Арх. 4.4). Единственная
запись при чтении в модуле — отметка `employer_seen_at` — выполняется роутером, а не здесь.

Скрытый минимум кандидата читается только в проекции кандидата — для метки `below_my_min`.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import and_, func, or_, select, tuple_
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import ApiException
from app.core.pagination import PageParams, make_page
from app.modules.assessment import service as assessment_service
from app.modules.catalog import service as catalog_service
from app.modules.contact import constants as c
from app.modules.contact import rules, texts
from app.modules.contact.dto import DeclineCondition
from app.modules.contact.models import CandidateContactState, Complaint, Invitation, InvitationEvent, InvitationTerms
from app.modules.contact.schemas import (
    CandidateStatus,
    CompanyMetric,
    CompanyMetrics,
    DeclineCandidateView,
    DeclineEmployerView,
    DiscloseOption,
    InvitationCandidateBrief,
    InvitationCandidateRef,
    InvitationCandidateView,
    InvitationCompanyView,
    InvitationEmployerBrief,
    InvitationEmployerView,
    InvitationStrikes,
    NeedBrief,
    OutcomeCandidateView,
    OutcomeEmployerView,
    TimelineEvent,
)
from app.modules.identity import service as identity_service
from app.modules.matching import service as matching_service
from app.modules.matching.dto import InvitationWhy
from app.modules.profile import service as profile_service
from app.shared.enums import (
    CategoryBasis,
    ConditionKind,
    ContactKind,
    DeclineReason,
    DiscloseField,
    EventActor,
    EventCode,
    InvitationStatus,
    TrustLevel,
    WorkFormat,
)
from app.shared.schemas import CategoryRef, ContactMethod, Page, Ref

_ACTIVE = tuple(rules.ACTIVE_STATUSES)
_UNKNOWN_CATEGORY = CategoryRef(
    code="", title="Категория не определена", specialization=Ref(code="", title=""), grade=Ref(code="", title="")
)

EmployerFilter = Literal["all", "awaiting", "accepted", "declined", "expired", "withdrawn", "bounced"]
CandidateFilter = Literal["awaiting", "accepted", "archived"]


# --------------------------------------------------------------------------------------------------------------------
# Общие части
# --------------------------------------------------------------------------------------------------------------------


def effective_filter(status: str, now: datetime) -> ColumnElement[bool]:
    """Условие SQL для фильтра по статусу, как его видит читатель (`rules.effective_status`)."""
    waiting = and_(Invitation.status.in_(_ACTIVE), Invitation.expires_at > now)
    overdue = and_(Invitation.status.in_(_ACTIVE), Invitation.expires_at <= now)
    if status == "awaiting":
        return waiting
    if status == "expired":
        return or_(Invitation.status == InvitationStatus.EXPIRED.value, overdue)
    if status == "archived":
        closed = (InvitationStatus.DECLINED.value, InvitationStatus.EXPIRED.value, InvitationStatus.WITHDRAWN.value)
        return or_(Invitation.status.in_(closed), overdue)
    return Invitation.status == status


def _terms_map(db: Session, ids: Collection[UUID]) -> dict[UUID, InvitationTerms]:
    if not ids:
        return {}
    rows = db.scalars(select(InvitationTerms).where(InvitationTerms.invitation_id.in_(ids)))
    return {row.invitation_id: row for row in rows}


def _condition(inv: Invitation) -> DeclineCondition | None:
    if inv.decline_condition_kind == ConditionKind.SALARY_FROM.value and inv.decline_condition_salary_from is not None:
        return DeclineCondition(kind=ConditionKind.SALARY_FROM, value=inv.decline_condition_salary_from)
    if inv.decline_condition_kind == ConditionKind.WORK_FORMAT.value and inv.decline_condition_work_format:
        return DeclineCondition(kind=ConditionKind.WORK_FORMAT, value=WorkFormat(inv.decline_condition_work_format))
    return None


def _timeline(
    events: Sequence[InvitationEvent], inv: Invitation, now: datetime, *, for_candidate: bool
) -> list[TimelineEvent]:
    """Таймлайн стороны: кандидат не видит `bounced`, жалобу не видит никто, кроме её автора в своём статусе."""
    hidden = {EventCode.COMPLAINT_FILED.value}
    if for_candidate:
        hidden.add(EventCode.BOUNCED.value)
    side = 1 if for_candidate else 0
    items = [
        TimelineEvent(
            code=event.code,
            label=texts.EVENT_LABELS[EventCode(event.code)][side],
            at=event.at,
            actor=EventActor(event.actor),
            note=texts.DEMO_INVITATION_NOTE if for_candidate and event.code == "sent" and inv.is_demo else None,
        )
        for event in events
        if event.code not in hidden
    ]
    if rules.is_active(inv.status) and inv.expires_at <= now:
        # Истечение ещё не материализовано: событие покажет `settle`, а читатель видит его уже сейчас.
        items.append(
            TimelineEvent(
                code=EventCode.EXPIRED.value,
                label=texts.EVENT_LABELS[EventCode.EXPIRED][side],
                at=inv.expires_at,
                actor=EventActor.SYSTEM,
            )
        )
    return items


def _events(db: Session, invitation_id: UUID) -> list[InvitationEvent]:
    return list(
        db.scalars(
            select(InvitationEvent)
            .where(InvitationEvent.invitation_id == invitation_id)
            .order_by(InvitationEvent.at, InvitationEvent.id)
        )
    )


def _page_rows(db: Session, where: Sequence[ColumnElement[bool]], paging: PageParams) -> tuple[list[Invitation], int]:
    """Строки списка по убыванию `(created_at, id)` — на одну больше размера страницы."""
    statement = select(Invitation).where(*where)
    if paging.position is not None:
        try:
            at = datetime.fromisoformat(str(paging.position["at"]))
            last_id = UUID(str(paging.position["id"]))
        except (KeyError, ValueError):
            raise ApiException(422, "cursor_invalid") from None
        statement = statement.where(tuple_(Invitation.created_at, Invitation.id) < (at, last_id))
    rows = db.scalars(statement.order_by(Invitation.created_at.desc(), Invitation.id.desc()).limit(paging.limit + 1))
    return list(rows), paging.limit


def _position(row: Any) -> dict[str, Any]:
    return {"at": row.sent_at.isoformat(), "id": str(row.id)}


# --------------------------------------------------------------------------------------------------------------------
# Проекция работодателя
# --------------------------------------------------------------------------------------------------------------------


@dataclass(slots=True)
class _EmployerLookups:
    """Данные нижних модулей и соседних строк для набора приглашений одного работодателя."""

    terms: dict[UUID, InvitationTerms]
    refs: dict[UUID, InvitationCandidateRef]
    needs: dict[UUID, NeedBrief | None]
    last_foreign: dict[UUID, datetime]
    revisions: dict[UUID, UUID]
    masked: set[UUID] = field(default_factory=set)


def _category_ref(code: str | None, snapshot: dict[str, Any] | None) -> CategoryRef:
    if code:
        try:
            return catalog_service.category_ref(code)
        except KeyError:  # категория вне текущего справочника: подпись берётся из снимка приглашения
            pass
    if snapshot and isinstance(snapshot.get("target"), dict):
        try:
            return CategoryRef.model_validate(snapshot["target"])
        except ValidationError:
            pass
    return _UNKNOWN_CATEGORY


def last_foreign_events(db: Session, ids: Collection[UUID]) -> dict[UUID, datetime]:
    """Момент последнего события, автор которого не работодатель, по каждому приглашению (признак «новое»)."""
    if not ids:
        return {}
    rows = db.execute(
        select(InvitationEvent.invitation_id, func.max(InvitationEvent.at))
        .where(
            InvitationEvent.invitation_id.in_(ids),
            InvitationEvent.actor != EventActor.EMPLOYER.value,
            InvitationEvent.code != EventCode.COMPLAINT_FILED.value,
        )
        .group_by(InvitationEvent.invitation_id)
    ).all()
    return {row[0]: row[1] for row in rows}


def _employer_lookups(db: Session, now: datetime, employer_id: UUID, invs: Sequence[Invitation]) -> _EmployerLookups:
    ids = [inv.id for inv in invs]
    candidate_ids = {inv.candidate_id for inv in invs}
    terms = _terms_map(db, ids)
    profiles = profile_service.pool_view(db, candidate_ids, now) if candidate_ids else {}
    names = profile_service.display_names(db, employer_id, candidate_ids) if candidate_ids else {}
    categories = assessment_service.get_categories(db, candidate_ids) if candidate_ids else {}
    accounts = identity_service.users(db, candidate_ids | {employer_id}) if candidate_ids else {}
    employer = accounts.get(employer_id)

    refs: dict[UUID, InvitationCandidateRef] = {}
    snapshots = {inv.candidate_id: terms[inv.id].match_snapshot for inv in invs if inv.id in terms}
    masked: set[UUID] = set()
    for candidate_id in candidate_ids:
        profile = profiles.get(candidate_id)
        category = categories.get(candidate_id)
        refs[candidate_id] = InvitationCandidateRef(
            candidate_id=candidate_id,
            public_code=profile.public_code if profile is not None else "—",
            display_name=names.get(candidate_id),
            category=_category_ref(category.category_code if category else None, snapshots.get(candidate_id)),
        )
        account = accounts.get(candidate_id)
        if rules.is_masked_pair(
            employer_is_demo=bool(employer and employer.is_demo), candidate_is_demo=bool(account and account.is_demo)
        ):
            masked.add(candidate_id)

    needs: dict[UUID, NeedBrief | None] = {}
    for need_id in {inv.need_id for inv in invs if inv.need_id is not None}:
        try:
            need = matching_service.need_ref(db, employer_id, need_id)
            needs[need_id] = NeedBrief(id=need.need_id, title=need.title)
        except ApiException:  # потребность удалена: приглашение остаётся без ссылки на неё
            needs[need_id] = None

    revisions = (
        {
            row[0]: row[1]
            for row in db.execute(select(Invitation.revises_id, Invitation.id).where(Invitation.revises_id.in_(ids)))
        }
        if ids
        else {}
    )
    return _EmployerLookups(
        terms=terms,
        refs=refs,
        needs=needs,
        last_foreign=last_foreign_events(db, ids),
        revisions=revisions,
        masked=masked,
    )


def _employer_common(inv: Invitation, now: datetime, look: _EmployerLookups) -> dict[str, Any]:
    status = rules.effective_status(inv, now)
    return {
        "id": inv.id,
        "status": status,
        "status_label": texts.STATUS_LABELS_EMPLOYER[status],
        "is_new_for_employer": rules.is_new_for_employer(inv.employer_seen_at, look.last_foreign.get(inv.id)),
        "is_demo": inv.is_demo,
        "candidate": look.refs[inv.candidate_id],
        "need": look.needs.get(inv.need_id) if inv.need_id is not None else None,
        "sent_at": inv.created_at,
        "updated_at": inv.updated_at,
        "expires_at": inv.expires_at,
        "pair_block_until": rules.effective_pair_block_until(inv, now),
        "revises_id": inv.revises_id,
        "can_revise": rules.can_revise(inv, now, has_revision=inv.id in look.revisions),
    }


def _employer_brief(inv: Invitation, now: datetime, look: _EmployerLookups) -> InvitationEmployerBrief:
    terms = look.terms[inv.id]
    return InvitationEmployerBrief(
        **_employer_common(inv, now, look),
        title=terms.title,
        salary_from=terms.salary_from,
        salary_to=terms.salary_to,
        work_format=WorkFormat(terms.work_format),
        city=terms.city,
    )


def employer_view(db: Session, now: datetime, inv: Invitation) -> InvitationEmployerView:
    """Приглашение глазами отправителя. Минимума кандидата, `below_my_min` и жалоб здесь нет (I8)."""
    look = _employer_lookups(db, now, inv.employer_id, [inv])
    terms = look.terms[inv.id]
    common = _employer_common(inv, now, look)
    status: InvitationStatus = common["status"]

    decline: DeclineEmployerView | None = None
    if status is InvitationStatus.DECLINED and inv.decline_reason:
        reason = DeclineReason(inv.decline_reason)
        condition, comment = _condition(inv), inv.decline_comment
        if inv.candidate_id in look.masked:
            # Демо-компания не получает свободный текст и названные условия живого человека (R3-mechanics-recheck-1).
            comment = texts.MASKED_TEXT if (comment or condition) else None
            condition = None
        decline = DeclineEmployerView(
            reason_code=reason, reason_label=texts.DECLINE_REASON_LABELS[reason], condition=condition, comment=comment
        )
    accepted = status is InvitationStatus.ACCEPTED
    return InvitationEmployerView(
        **common,
        title=terms.title,
        description=terms.description,
        salary_from=terms.salary_from,
        salary_to=terms.salary_to,
        work_format=WorkFormat(terms.work_format),
        city=terms.city,
        contact_method=ContactMethod(kind=ContactKind(terms.contact_kind), value=terms.contact_value),
        message=terms.message,
        revision_id=look.revisions.get(inv.id),
        decline=decline,
        contact_sla_until=inv.resolved_at + c.CONTACT_SLA if accepted and inv.resolved_at else None,
        outcome=(
            OutcomeEmployerView(employer_contacted=inv.employer_contacted, candidate_contacted=inv.candidate_contacted)
            if accepted
            else None
        ),
        timeline=_timeline(_events(db, inv.id), inv, now, for_candidate=False),
        can_withdraw=status in (InvitationStatus.SENT, InvitationStatus.VIEWED),
        revise_until=rules.revise_until(inv) if common["can_revise"] else None,
        outcome_prompt=rules.outcome_prompt(inv.status, inv.resolved_at, inv.employer_contacted is not None, now),
    )


def employer_list(
    db: Session, now: datetime, employer_id: UUID, status: str, need_id: UUID | None, paging: PageParams
) -> Page[InvitationEmployerBrief]:
    """Список приглашений работодателя с продолжением; фильтр — по статусу, как его видит читатель."""
    where: list[ColumnElement[bool]] = [Invitation.employer_id == employer_id]
    if status != "all":
        where.append(effective_filter(status, now))
    if need_id is not None:
        where.append(Invitation.need_id == need_id)
    rows, limit = _page_rows(db, where, paging)
    look = _employer_lookups(db, now, employer_id, rows)
    return make_page([_employer_brief(inv, now, look) for inv in rows], limit, _position)


# --------------------------------------------------------------------------------------------------------------------
# Проекция кандидата
# --------------------------------------------------------------------------------------------------------------------


def strikes(db: Session, candidate_id: UUID) -> InvitationStrikes:
    """Счётчик молчания кандидата по записанному значению (чтение его не меняет)."""
    state = db.get(CandidateContactState, candidate_id)
    return InvitationStrikes(count=state.consecutive_expired if state else 0, limit=c.SILENCE_STRIKES)


def company_metrics(db: Session, now: datetime, employer_id: UUID) -> CompanyMetrics:
    """P1: «выходит на связь» и «условия совпадают» по ответам кандидатов за `METRIC_WINDOW_DAYS`.

    Показываются числами «{yes} из {n}» при `n >= METRIC_MIN_N`; на лимиты и ранжирование не влияют (Арх. 4.12).
    """
    from datetime import timedelta

    rows = db.execute(
        select(Invitation.candidate_contacted, Invitation.candidate_terms_matched).where(
            Invitation.employer_id == employer_id,
            Invitation.status == InvitationStatus.ACCEPTED.value,
            Invitation.candidate_outcome_at > now - timedelta(days=c.METRIC_WINDOW_DAYS),
        )
    ).all()
    contacted = [row[0] for row in rows if row[0] is not None]
    matched = [row[1] for row in rows if row[1] is not None]

    def metric(values: list[bool]) -> CompanyMetric | None:
        return CompanyMetric(yes=sum(values), n=len(values)) if len(values) >= c.METRIC_MIN_N else None

    return CompanyMetrics(contact_confirmed=metric(contacted), terms_matched=metric(matched))


def _candidate_status(inv: Invitation, now: datetime) -> CandidateStatus:
    return cast(CandidateStatus, rules.effective_status(inv, now).value)


def _below_my_min(terms: InvitationTerms, min_salary: int | None) -> bool:
    """Метка «ниже вашего минимума» (Арх. 4.6): считается при чтении и отдаётся только кандидату."""
    return not rules.salary_ok(terms.salary_from, min_salary)


def candidate_view(db: Session, now: datetime, inv: Invitation) -> InvitationCandidateView:
    """Приглашение глазами адресата. Позиции, полосы совпадения, вкладов и риска здесь нет (Арх. 4.9)."""
    terms = _terms_map(db, [inv.id])[inv.id]
    status = rules.effective_status(inv, now)
    events = _events(db, inv.id)
    candidate_id = inv.candidate_id

    why: InvitationWhy | None = None
    if terms.match_snapshot:
        try:
            why = InvitationWhy.model_validate(terms.match_snapshot)
        except ValidationError:
            why = None
    if why is None:
        category = assessment_service.get_category(db, candidate_id)
        why = InvitationWhy(
            source="need" if inv.need_id else "bank",
            target=_category_ref(category.category_code if category else None, None),
            # Заявленный грейд: уровня по тесту нет, поэтому «категорию и интервал уровня» работодатель не видел.
            employer_saw=list(
                texts.DECLARED_EMPLOYER_SAW
                if category is not None and category.basis == CategoryBasis.DECLARED
                else texts.DEFAULT_EMPLOYER_SAW
            ),
        )

    options: list[DiscloseOption] = []
    if status in (InvitationStatus.SENT, InvitationStatus.VIEWED):
        filled = profile_service.filled_channels(db, candidate_id)
        privacy = profile_service.privacy(db, candidate_id)
        default = set(
            rules.default_disclose(
                reveal_phone=privacy.reveal_phone,
                reveal_telegram=privacy.reveal_telegram,
                reveal_link=privacy.reveal_link,
                reveal_fsp_details=privacy.reveal_fsp_details,
                filled=filled,
            )
        )
        options = [
            DiscloseOption(
                field=item,
                label=texts.DISCLOSE_LABELS[item],
                available=item is DiscloseField.FSP_DETAILS or item.value in filled,
                default=item in default,
            )
            for item in DiscloseField
        ]

    disclosed: list[DiscloseField] | None = None
    if status is InvitationStatus.ACCEPTED:
        accepted = next((event for event in events if event.code == EventCode.ACCEPTED.value), None)
        raw = (accepted.payload or {}).get("fields", []) if accepted is not None else []
        disclosed = [DiscloseField(item) for item in raw if item in set(DiscloseField)]

    decline: DeclineCandidateView | None = None
    if status is InvitationStatus.DECLINED and inv.decline_reason:
        reason = DeclineReason(inv.decline_reason)
        decline = DeclineCandidateView(
            reason_code=reason, reason_label=texts.DECLINE_REASON_LABELS[reason], condition=_condition(inv)
        )
    accepted_now = status is InvitationStatus.ACCEPTED
    trust = TrustLevel(terms.company_trust_level)
    has_complaint = db.scalar(select(Complaint.id).where(Complaint.invitation_id == inv.id)) is not None
    return InvitationCandidateView(
        id=inv.id,
        status=_candidate_status(inv, now),
        status_label=texts.STATUS_LABELS_CANDIDATE[status],
        is_demo=inv.is_demo,
        sent_at=inv.created_at,
        expires_at=inv.expires_at,
        revision_of=inv.revises_id,
        title=terms.title,
        description=terms.description,
        salary_from=terms.salary_from,
        salary_to=terms.salary_to,
        work_format=WorkFormat(terms.work_format),
        city=terms.city,
        contact_method=ContactMethod(kind=ContactKind(terms.contact_kind), value=terms.contact_value),
        message=terms.message,
        company=InvitationCompanyView(
            name=terms.company_name,
            sphere=terms.company_sphere,
            description=terms.company_description,
            site=terms.company_site,
            on_platform_since=terms.company_since,
            trust_level=trust,
            trust_label=texts.TRUST_LABELS[trust],
            metrics=company_metrics(db, now, inv.employer_id),
        ),
        why=why,
        disclose_options=options,
        disclosed=disclosed,
        decline=decline,
        contact_sla_until=inv.resolved_at + c.CONTACT_SLA if accepted_now and inv.resolved_at else None,
        outcome=(
            OutcomeCandidateView(
                candidate_contacted=inv.candidate_contacted, candidate_terms_matched=inv.candidate_terms_matched
            )
            if accepted_now
            else None
        ),
        strikes=strikes(db, candidate_id) if status is InvitationStatus.EXPIRED else None,
        timeline=_timeline(events, inv, now, for_candidate=True),
        outcome_prompt=rules.outcome_prompt(inv.status, inv.resolved_at, inv.candidate_outcome_at is not None, now),
        can_complain=not has_complaint,
        below_my_min=_below_my_min(terms, profile_service.min_salary(db, candidate_id)),
    )


def candidate_list(
    db: Session, now: datetime, candidate_id: UUID, status: str, paging: PageParams
) -> Page[InvitationCandidateBrief]:
    """Входящие кандидата с продолжением. `bounced` не возвращается никогда (Арх. 9.9)."""
    where = [
        Invitation.candidate_id == candidate_id,
        Invitation.status != InvitationStatus.BOUNCED.value,
        effective_filter(status, now),
    ]
    rows, limit = _page_rows(db, where, paging)
    terms = _terms_map(db, [inv.id for inv in rows])
    min_salary = profile_service.min_salary(db, candidate_id) if rows else None
    own_strikes = strikes(db, candidate_id) if rows else None
    items = []
    for inv in rows:
        snapshot = terms[inv.id]
        status_now = rules.effective_status(inv, now)
        items.append(
            InvitationCandidateBrief(
                id=inv.id,
                status=_candidate_status(inv, now),
                status_label=texts.STATUS_LABELS_CANDIDATE[status_now],
                is_demo=inv.is_demo,
                is_new=status_now is InvitationStatus.SENT,
                company_name=snapshot.company_name,
                title=snapshot.title,
                salary_from=snapshot.salary_from,
                salary_to=snapshot.salary_to,
                work_format=WorkFormat(snapshot.work_format),
                city=snapshot.city,
                sent_at=inv.created_at,
                updated_at=inv.updated_at,
                expires_at=inv.expires_at,
                revision_of=inv.revises_id,
                below_my_min=_below_my_min(snapshot, min_salary),
                strikes=own_strikes if status_now is InvitationStatus.EXPIRED else None,
            )
        )
    return make_page(items, limit, _position)
