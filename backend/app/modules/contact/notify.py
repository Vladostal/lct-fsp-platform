"""Письма модуля `contact` (Арх. 4.2, T1, T4, T5; 15.1, № 34).

Письмо кандидату о новом приглашении — P0: без него срок в 7 дней теряет смысл для пассивного кандидата. Письмо
работодателю об ответе — P1. Письма ставятся в очередь транзакции (`core.mail.enqueue`) и уходят только после её
фиксации; при откате и повторе `run_in_tx` очередь сбрасывается.

Демо-аккаунтам письма не отправляются: у синтетических кандидатов и демо-компаний нет настоящего ящика, а сид
создаёт историю из сотен приглашений. В письмах нет персональных данных второй стороны: кандидат назван кодом.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.core import mail
from app.modules.contact import constants as c
from app.modules.contact import rules, texts
from app.modules.contact.models import Invitation, InvitationTerms
from app.modules.identity import service as identity_service
from app.modules.identity.dto import UserDTO
from app.modules.profile import service as profile_service
from app.shared.enums import DeclineReason, InvitationStatus, WorkFormat
from app.shared.text import fmt_date, fmt_salary_range

log = logging.getLogger("app.contact.notify")


def invitation_sent(db: Session, inv: Invitation, terms: InvitationTerms, candidate: UserDTO) -> None:
    """Письмо кандидату о доставленном приглашении (только при `sent`; о `bounced` кандидат не узнаёт)."""
    if candidate.is_demo or inv.status != InvitationStatus.SENT.value:
        return
    mail.enqueue(
        db,
        "invitation_new",
        to=candidate.email,
        context={
            "invitation_id": str(inv.id),
            "company_name": terms.company_name,
            "title": terms.title,
            "salary": fmt_salary_range(terms.salary_from, terms.salary_to),
            "work_format": texts.WORK_FORMAT_LABELS[WorkFormat(terms.work_format)],
            "city": terms.city,
            "expires_on": fmt_date(inv.expires_at),
            "is_demo": inv.is_demo,
        },
    )


def invitation_answered(db: Session, inv: Invitation, terms: InvitationTerms, now: datetime) -> None:
    """P1: письмо работодателю о согласии или отказе кандидата. Сбой нижних фасадов ответ кандидата не срывает."""
    try:
        employer = identity_service.users(db, [inv.employer_id]).get(inv.employer_id)
        if employer is None or employer.is_demo:
            return
        profile = profile_service.pool_view(db, [inv.candidate_id], now).get(inv.candidate_id)
    except NotImplementedError:  # фасад нижнего модуля не реализован: письмо P1 пропускается
        return
    accepted = inv.status == InvitationStatus.ACCEPTED.value
    reason = DeclineReason(inv.decline_reason) if inv.decline_reason else None
    public_code = profile.public_code if profile is not None else "кандидат"
    mail.enqueue(
        db,
        "invitation_answered",
        to=employer.email,
        context={
            "invitation_id": str(inv.id),
            "title": terms.title,
            "public_code": public_code,
            "accepted": accepted,
            "subject_line": "Кандидат принял приглашение" if accepted else "Кандидат отклонил приглашение",
            "headline": (
                f"Кандидат {public_code} принял ваше приглашение."
                if accepted
                else f"Кандидат {public_code} отклонил ваше приглашение."
            ),
            "contact_until": fmt_date((inv.resolved_at or now) + c.CONTACT_SLA),
            "reason_label": texts.DECLINE_REASON_LABELS[reason] if reason else "",
            "can_revise": (not accepted) and rules.can_revise(inv, now, has_revision=False),
        },
    )
