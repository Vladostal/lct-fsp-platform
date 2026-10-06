"""Проверки 5.1–5.11 отправки приглашения (Арх. 4.5) — общие для отправки и предпроверки.

`gather` только читает: под блокировками его вызывает отправка (после `settle`), без блокировок — предпроверка.
Ни одна проверка не зависит от минимума кандидата (инвариант I8): `profile.min_salary` здесь не вызывается.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.errors import ApiException, ParamValue, field_error
from app.modules.company import service as company_service
from app.modules.company.dto import CompanyDTO
from app.modules.contact import constants as c
from app.modules.contact import rules, texts
from app.modules.contact.models import EmployerContactState, Invitation
from app.modules.identity import service as identity_service
from app.modules.profile import service as profile_service
from app.shared.enums import Role, VisibilityState, WorkFormat


@dataclass(frozen=True, slots=True)
class Violation:
    """Невыполненная проверка: номер строки таблицы 4.5, HTTP-статус, код и параметры ошибки."""

    number: str
    status: int
    code: str
    params: dict[str, ParamValue] = field(default_factory=dict)

    def to_exception(self) -> ApiException:
        fields = None
        if self.code == "format_not_accepted":
            fields = [field_error("work_format", self.code, texts.message(self.code))]
        return ApiException(
            self.status, self.code, texts.message(self.code, self.params), params=self.params or None, fields=fields
        )


@dataclass(slots=True)
class SendContext:
    """Всё, что нужно проверкам: состояние работодателя, кандидата и пары на момент `now`."""

    now: datetime
    employer_id: UUID
    candidate_id: UUID
    employer_is_demo: bool
    #: Адресат существует и имеет роль кандидата (поправка R3-data-api-security-8).
    candidate_exists: bool
    candidate_is_demo: bool
    company: CompanyDTO | None
    frozen: bool
    slot_override: int | None
    candidate_visible: bool
    candidate_formats: list[WorkFormat]
    pair: list[Invitation]
    slot_rows: list[Invitation]
    daily_created: list[datetime]
    inbox_count: int

    @property
    def slot_limit(self) -> int:
        return rules.slot_limit(self.slot_override, self.company.trust_level if self.company else None)

    @property
    def slots(self) -> tuple[int, datetime | None]:
        return rules.slots_used(self.slot_rows, self.now)

    @property
    def daily_limit(self) -> int:
        # Суточный лимит к демо-аккаунтам не применяется (Арх. 4.14): ими пользуются несколько посетителей.
        return c.DEMO_DAILY_SEND_LIMIT if self.employer_is_demo else c.DAILY_SEND_LIMIT

    @property
    def active_of_pair(self) -> Invitation | None:
        for inv in self.pair:
            if rules.is_active(inv.status) and inv.expires_at > self.now:
                return inv
        return None


def employer_state(db: Session, employer_id: UUID) -> EmployerContactState | None:
    return db.get(EmployerContactState, employer_id)


def slot_rows(db: Session, employer_id: UUID, now: datetime) -> list[Invitation]:
    """Приглашения работодателя, которые могут занимать слот: ждущие ответа и с `slot_release_at > now`."""
    return list(
        db.scalars(
            select(Invitation).where(
                Invitation.employer_id == employer_id,
                or_(Invitation.status.in_(rules.ACTIVE_STATUSES), Invitation.slot_release_at > now),
            )
        )
    )


def daily_created(db: Session, employer_id: UUID, now: datetime) -> list[datetime]:
    """Моменты попыток отправки за скользящие 24 часа, включая `bounced` (Арх. 4.7)."""
    return list(
        db.scalars(
            select(Invitation.created_at).where(
                Invitation.employer_id == employer_id, Invitation.created_at > now - c.DAILY_WINDOW
            )
        )
    )


def gather(db: Session, now: datetime, employer_id: UUID, candidate_id: UUID) -> SendContext:
    """Прочитать состояние для проверок 5.1–5.11. Ничего не пишет и не блокирует."""
    accounts = identity_service.users(db, [employer_id, candidate_id])
    employer = accounts.get(employer_id)
    candidate = accounts.get(candidate_id)
    candidate_exists = candidate is not None and candidate.role == Role.CANDIDATE

    state = employer_state(db, employer_id)
    visible = False
    formats: list[WorkFormat] = []
    inbox = 0
    pair: list[Invitation] = []
    if candidate_exists:
        visible = profile_service.visibility(db, candidate_id, now).state == VisibilityState.VISIBLE
        if visible and candidate_id in profile_service.hidden_from_employer(db, employer_id, [candidate_id]):
            visible = False  # P1: компания в списке «не показывать» кандидата — тот же ответ, что и пауза
        profile = profile_service.pool_view(db, [candidate_id], now).get(candidate_id)
        formats = list(profile.work_formats) if profile is not None else []
        pair = list(
            db.scalars(
                select(Invitation).where(Invitation.employer_id == employer_id, Invitation.candidate_id == candidate_id)
            )
        )
        inbox = len(
            db.scalars(
                select(Invitation.id).where(
                    Invitation.candidate_id == candidate_id,
                    Invitation.status.in_(rules.ACTIVE_STATUSES),
                    Invitation.expires_at > now,
                )
            ).all()
        )
    return SendContext(
        now=now,
        employer_id=employer_id,
        candidate_id=candidate_id,
        employer_is_demo=bool(employer and employer.is_demo),
        candidate_exists=candidate_exists,
        candidate_is_demo=bool(candidate and candidate.is_demo),
        company=company_service.get_company(db, employer_id),
        frozen=bool(state and state.sending_frozen_at is not None),
        slot_override=state.slot_limit_override if state else None,
        candidate_visible=visible,
        candidate_formats=formats,
        pair=pair,
        slot_rows=slot_rows(db, employer_id, now),
        daily_created=daily_created(db, employer_id, now),
        inbox_count=inbox,
    )


def violations(
    ctx: SendContext,
    *,
    work_format: WorkFormat | None = None,
    revision: Violation | None = None,
    is_revision: bool = False,
    demo_call: bool = False,
) -> list[Violation]:
    """Невыполненные проверки в порядке таблицы 4.5; отправка берёт первую, предпроверка — все.

    `work_format = None` пропускает проверку 5.4 (предпроверка формата не знает); `revision` — уже вычисленный
    результат проверки 5.5; при `is_revision` пропускается блокировка пары 5.7 (Арх. 4.8).
    """
    now = ctx.now
    found: list[Violation] = []
    if ctx.company is None or not ctx.company.is_complete:
        found.append(Violation("5.1", 409, "company_profile_incomplete"))
    if ctx.frozen:
        found.append(Violation("5.2", 403, "sending_frozen"))
    if not ctx.candidate_exists or not ctx.candidate_visible:
        found.append(Violation("5.3", 409, "candidate_unavailable"))
    if work_format is not None and work_format not in ctx.candidate_formats:
        found.append(Violation("5.4", 422, "format_not_accepted"))
    if revision is not None:
        found.append(revision)
    active = ctx.active_of_pair
    if active is not None:
        found.append(Violation("5.6", 409, "active_invitation_exists", {"invitation_id": str(active.id)}))
    if not is_revision:
        block = rules.pair_block(ctx.pair, now)
        if block is not None:
            found.append(Violation("5.7", 409, block.code, {"until": block.until.isoformat()}))
    if not ctx.employer_is_demo:
        retry_after = rules.daily_retry_after(ctx.daily_created, now)
        if retry_after is not None:
            found.append(Violation("5.8", 429, "daily_limit_exceeded", {"retry_after": retry_after}))
    used, next_release = ctx.slots
    if used >= ctx.slot_limit:
        params: dict[str, ParamValue] = {"used": used, "limit": ctx.slot_limit}
        if next_release is not None:
            params["next_release_at"] = next_release.isoformat()
        found.append(Violation("5.9", 409, "quota_exceeded", params))
    if ctx.inbox_count >= c.CANDIDATE_INBOX_CAPACITY:
        # Тот же код и текст, что в 5.3: счёт и срок освобождения входящих работодателю не сообщаются.
        found.append(Violation("5.10", 409, "candidate_unavailable"))
    if rules.demo_sender_restricted(
        demo_call=demo_call, employer_is_demo=ctx.employer_is_demo, candidate_is_demo=ctx.candidate_is_demo
    ):
        found.append(Violation("5.11", 409, "demo_sender_restricted"))
    return found
