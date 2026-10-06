"""Таблицы модуля `contact` (Арх. 8.9).

Соглашения Арх. 8.1: первичные ключи — `uuid4` из Python, у журнала событий — `bigserial`; моменты времени пишет
Python; внешние ключи на `app_user` и внутри модуля — `ON DELETE CASCADE` (удаление аккаунта и сброс демо — один
`DELETE FROM app_user`); ссылки на сущности чужих модулей (`need_id`, `snapshot_id`) — без внешнего ключа.

Строки `candidate_contact_state` и `employer_contact_state` служат блокировками операций (порядок блокировок —
Арх. 4.4, реализация — `settle.py`). Строка `invitation_terms` неизменяема: триггер `BEFORE UPDATE` поднимает
исключение (инвариант I3). DDL триггера создаётся событием `after_create`, то есть и `core.db.create_schema`,
и тестами; в начальную миграцию его переносит сборочный пакет из констант `TERMS_IMMUTABLE_*` этого файла.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    DDL,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    Uuid,
    event,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_check
from app.shared.enums import (
    ComplaintReason,
    ComplaintStatus,
    ConditionKind,
    ContactKind,
    DeclineReason,
    EventActor,
    EventCode,
    FitBand,
    InvitationStatus,
    TrustLevel,
    WorkFormat,
)

_ACTIVE_SQL = "status IN ('sent', 'viewed')"


class CandidateContactState(Base):
    """Счётчик молчания кандидата; строка — блокировка операций с его входящими."""

    __tablename__ = "candidate_contact_state"
    __table_args__ = (CheckConstraint("consecutive_expired >= 0", name="consecutive_expired_non_negative"),)

    candidate_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True)
    #: Истёкших приглашений подряд без единого ответа между ними (Арх. 4.10).
    consecutive_expired: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EmployerContactState(Base):
    """Состояние отправок работодателя; строка — блокировка его отправок."""

    __tablename__ = "employer_contact_state"

    employer_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True)
    #: Заменяет `SLOT_LIMIT[trust_level]`; нужен демо-компаниям (Арх. 4.14).
    slot_limit_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sending_frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sending_frozen_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Invitation(Base):
    """Приглашение: жизненный цикл пары «работодатель — кандидат» (Арх. 4.2)."""

    __tablename__ = "invitation"
    __table_args__ = (
        enum_check("status", InvitationStatus),
        enum_check("fit_band_at_send", FitBand),
        enum_check("decline_reason", DeclineReason),
        enum_check("decline_condition_kind", ConditionKind),
        enum_check("decline_condition_work_format", WorkFormat),
        # I6: момент закрытия заполнен тогда и только тогда, когда статус терминальный.
        CheckConstraint(f"(resolved_at IS NULL) = ({_ACTIVE_SQL})", name="resolved_iff_terminal"),
        # I1: у пары не больше одного приглашения в sent или viewed.
        Index(
            "uq_invitation_active_pair", "employer_id", "candidate_id", unique=True, postgresql_where=text(_ACTIVE_SQL)
        ),
        # I7: у приглашения не больше одного пересмотренного.
        Index("uq_invitation_revises_id", "revises_id", unique=True, postgresql_where=text("revises_id IS NOT NULL")),
        Index("uq_invitation_employer_idempotency", "employer_id", "idempotency_key", unique=True),
        Index("ix_invitation_employer_status", "employer_id", "status"),
        Index("ix_invitation_candidate_status", "candidate_id", "status"),
        Index("ix_invitation_need_id", "need_id", postgresql_where=text("need_id IS NOT NULL")),
        Index("ix_invitation_due", "expires_at", postgresql_where=text(_ACTIVE_SQL)),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    employer_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    candidate_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    #: Потребность и версия подборки, из которой отправлено; `None` — приглашение из банка кандидатов.
    need_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    snapshot_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    #: Исходное приглашение, если это пересмотренное (Арх. 4.8).
    revises_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("invitation.id", ondelete="CASCADE"), nullable=True
    )
    idempotency_key: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    #: Отправлено демо-компанией либо помечено сидом; чип «демо» в интерфейсе (Арх. 4.14).
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Полоса совпадения на момент отправки — для демо-ответчика и отчётов; в схемы кандидата не входит (Арх. 4.9).
    fit_band_at_send: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: С этого момента запись не занимает слот; `None`, пока статус `sent` или `viewed`.
    slot_release_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: До этого момента новое приглашение паре запрещено.
    pair_block_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decline_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decline_condition_kind: Mapped[str | None] = mapped_column(Text, nullable=True)
    decline_condition_salary_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decline_condition_work_format: Mapped[str | None] = mapped_column(Text, nullable=True)
    decline_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    employer_contacted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    employer_outcome_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    candidate_contacted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    candidate_terms_matched: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    candidate_outcome_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Последнее открытие работодателем — для признака «новое». Единственная запись при чтении (Арх. 4.4, 10.1).
    employer_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InvitationTerms(Base):
    """Неизменяемый снимок условий и компании на момент отправки (строка 1:1 с приглашением, только вставка)."""

    __tablename__ = "invitation_terms"
    __table_args__ = (
        enum_check("company_trust_level", TrustLevel),
        enum_check("work_format", WorkFormat),
        enum_check("contact_kind", ContactKind),
    )

    invitation_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("invitation.id", ondelete="CASCADE"), primary_key=True)
    company_name: Mapped[str] = mapped_column(Text, nullable=False)
    company_sphere: Mapped[str] = mapped_column(Text, nullable=False)
    company_description: Mapped[str] = mapped_column(Text, nullable=False)
    company_site: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_since: Mapped[date] = mapped_column(Date, nullable=False)
    company_trust_level: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    salary_from: Mapped[int] = mapped_column(Integer, nullable=False)
    salary_to: Mapped[int] = mapped_column(Integer, nullable=False)
    work_format: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_kind: Mapped[str] = mapped_column(Text, nullable=False)
    contact_value: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: «Почему вас пригласили» — готовая проекция кандидата из `matching.explain_for_invitation` (Арх. 4.9).
    match_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    scorer_version: Mapped[str | None] = mapped_column(Text, nullable=True)


class InvitationEvent(Base):
    """Журнал событий приглашения: одно событие на каждый переход и каждую отметку; только вставка."""

    __tablename__ = "invitation_event"
    __table_args__ = (
        enum_check("code", EventCode),
        enum_check("actor", EventActor),
        Index("ix_invitation_event_invitation_id", "invitation_id"),
        Index("ix_invitation_event_employer_id_id", "employer_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    invitation_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("invitation.id", ondelete="CASCADE"), nullable=False)
    #: Копия владельца приглашения: по ней события читает модуль интеграций (`events_since`).
    employer_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    #: Для `expired` — `expires_at`, а не момент обнаружения.
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Complaint(Base):
    """Жалоба кандидата на доставленное приглашение (P1, Арх. 4.13): одна на приглашение."""

    __tablename__ = "complaint"
    __table_args__ = (
        enum_check("reason_code", ComplaintReason),
        enum_check("status", ComplaintStatus),
        Index("ix_complaint_employer_id_created_at", "employer_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    invitation_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("invitation.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    candidate_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    employer_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    reason_code: Mapped[str] = mapped_column(Text, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default=ComplaintStatus.OPEN.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# --------------------------------------------------------------------------------------------------------------------
# Неизменяемость снимка условий (I3)
# --------------------------------------------------------------------------------------------------------------------

#: Функция триггера: любое обновление строки снимка — ошибка. Удаление не запрещено: оно нужно каскаду при
#: удалении аккаунта и сбросу демо-данных.
TERMS_IMMUTABLE_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION invitation_terms_immutable() RETURNS trigger AS $body$
BEGIN
    RAISE EXCEPTION 'invitation_terms: строка неизменяема после вставки'
        USING ERRCODE = 'restrict_violation';
END;
$body$ LANGUAGE plpgsql
"""

TERMS_IMMUTABLE_TRIGGER_SQL = """
CREATE TRIGGER trg_invitation_terms_immutable
    BEFORE UPDATE ON invitation_terms
    FOR EACH ROW EXECUTE FUNCTION invitation_terms_immutable()
"""

event.listen(InvitationTerms.__table__, "after_create", DDL(TERMS_IMMUTABLE_FUNCTION_SQL))
event.listen(InvitationTerms.__table__, "after_create", DDL(TERMS_IMMUTABLE_TRIGGER_SQL))
