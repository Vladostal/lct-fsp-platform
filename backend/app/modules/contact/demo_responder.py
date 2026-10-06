"""Демо-ответчик (Арх. 4.14): синтетические кандидаты отвечают на приглашения по своей персоне.

Работает только в фоновом цикле (`service.settle_all`) и только при `DEMO_MODE`. Использует те же функции
переходов, что и живые пользователи (`service.do_view`, `do_accept`, `do_decline`); события помечены
`payload.demo = true`. Время отсчитывается от `created_at` приглашения по часам сервиса, поэтому ответ приходит
с точностью до периода цикла (30 секунд).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiException
from app.modules.contact import rules
from app.modules.contact.dto import DeclineCondition
from app.modules.contact.models import CandidateContactState, Invitation, InvitationTerms
from app.modules.identity import service as identity_service
from app.modules.profile import service as profile_service
from app.shared.enums import ConditionKind, DeclineReason, InvitationStatus

log = logging.getLogger("app.contact.demo")


@dataclass(frozen=True, slots=True)
class DueAction:
    """Назревшее действие персоны по одному приглашению."""

    invitation_id: UUID
    candidate_id: UUID
    persona: str
    answer: bool


@dataclass(slots=True)
class Plan:
    """Что ответчик должен сделать в этом проходе цикла; `candidate_ids` блокируются вместе с истёкшими."""

    actions: list[DueAction] = field(default_factory=list)

    @property
    def candidate_ids(self) -> set[UUID]:
        return {action.candidate_id for action in self.actions}


def plan(db: Session, now: datetime) -> Plan:
    """Найти без блокировок приглашения демо-кандидатов, по которым пора просмотреть или ответить."""
    rows = db.execute(
        select(Invitation.id, Invitation.candidate_id, Invitation.status, Invitation.created_at).where(
            Invitation.status.in_(rules.ACTIVE_STATUSES), Invitation.expires_at > now
        )
    ).all()
    if not rows:
        return Plan()
    accounts = identity_service.users(db, {row.candidate_id for row in rows})
    personas: dict[UUID, str | None] = {}
    result = Plan()
    for row in sorted(rows, key=lambda item: (item.created_at, item.id)):
        account = accounts.get(row.candidate_id)
        if account is None or not account.is_demo:
            continue
        if row.candidate_id not in personas:
            personas[row.candidate_id] = profile_service.demo_persona(db, row.candidate_id)
        persona = personas[row.candidate_id]
        timing = rules.demo_timing(persona)
        if timing is None or persona is None:
            continue
        view_after, answer_after = timing
        answer_due = now >= row.created_at + answer_after
        view_due = row.status == InvitationStatus.SENT.value and now >= row.created_at + view_after
        if answer_due or view_due:
            result.actions.append(DueAction(row.id, row.candidate_id, persona, answer_due))
    return result


def _revision_meets_condition(db: Session, inv: Invitation, terms: InvitationTerms) -> bool:
    """Выполняет ли пересмотренное приглашение сумму, названную персоной `expensive` при отказе."""
    if inv.revises_id is None:
        return False
    original = db.get(Invitation, inv.revises_id)
    return (
        original is not None
        and original.decline_condition_kind == ConditionKind.SALARY_FROM.value
        and original.decline_condition_salary_from is not None
        and terms.salary_from >= original.decline_condition_salary_from
    )


def run(db: Session, now: datetime, plan_: Plan, states: dict[UUID, CandidateContactState]) -> int:
    """Выполнить назревшие действия; вызывается из `settle` после блокировки строк кандидатов. Возвращает число
    выполненных ответов и просмотров. Сбой одного действия откатывается точкой сохранения и цикл не срывает.
    """
    from app.modules.contact import service

    done = 0
    for action in plan_.actions:
        state = states.get(action.candidate_id)
        if state is None:
            continue
        try:
            with db.begin_nested():
                inv = db.scalar(
                    select(Invitation)
                    .where(Invitation.id == action.invitation_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if inv is None or not rules.is_active(inv.status) or now >= inv.expires_at:
                    continue
                service.do_view(db, now, inv, demo=True)
                if action.answer:
                    terms = db.get(InvitationTerms, inv.id)
                    if terms is None:
                        continue
                    decision = rules.demo_decision(
                        action.persona,
                        salary_from=terms.salary_from,
                        fit_band=inv.fit_band_at_send,
                        revision_meets_condition=_revision_meets_condition(db, inv, terms),
                    )
                    if decision is None:
                        continue
                    if decision.action == "accept":
                        service.do_accept(db, now, inv, state, None, demo=True)
                    else:
                        condition = None
                        if decision.condition_salary_from is not None:
                            condition = DeclineCondition(
                                kind=ConditionKind.SALARY_FROM, value=decision.condition_salary_from
                            )
                        service.do_decline(
                            db, now, inv, state, decision.reason or DeclineReason.OTHER, condition, None, demo=True
                        )
                db.flush()
                done += 1
        except ApiException as exc:
            log.warning("демо-ответчик: приглашение %s пропущено (%s)", action.invitation_id, exc.code)
    return done
