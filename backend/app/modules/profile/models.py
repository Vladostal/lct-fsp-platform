"""Таблицы модуля `profile` (Арх. 8.4).

Все моменты времени пишет Python (Арх. 2.4, п. 5). Внешние ключи — только на `app_user(id)`, с каскадным удалением:
удаление аккаунта уносит профиль, условия, настройки, загрузки резюме и раскрытия. Исключение — `access_log.employer_id`
без внешнего ключа: запись журнала переживает удаление работодателя, кандидат по-прежнему видит, кто получал его
данные (название компании хранится копией).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_check
from app.shared.enums import AccessKind, DemoPersona, DisclosureSource, WorkFormat

_USER_FK = "app_user.id"


def _all_formats() -> list[str]:
    return [item.value for item in WorkFormat]


class CandidateProfile(Base):
    """Профиль кандидата: одна строка на пользователя, создаётся лениво при первом обращении кандидата."""

    __tablename__ = "candidate_profile"
    __table_args__ = (
        CheckConstraint(
            "demo_persona IS NULL OR demo_persona IN (" + ", ".join(f"'{item.value}'" for item in DemoPersona) + ")",
            name="demo_persona",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey(_USER_FK, ondelete="CASCADE"), primary_key=True)
    #: «К-» и 5 цифр; случайный, из `user_id` не выводится.
    public_code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    last_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    middle_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram: Mapped[str | None] = mapped_column(Text, nullable=True)
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    experience_years: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)
    roles: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    about: Mapped[str | None] = mapped_column(Text, nullable=True)
    grade_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    specialization_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Ручная пауза показа.
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Автопауза за молчание: ставит и снимает модуль `contact`; по сроку перестаёт действовать без записи.
    auto_paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    auto_paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    demo_persona: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CandidateDeclaredSkill(Base):
    """Заявленный навык: код справочника либо свой тег (ровно одно из двух)."""

    __tablename__ = "candidate_declared_skill"
    __table_args__ = (
        CheckConstraint("(skill_code IS NULL) <> (custom_label IS NULL)", name="one_of_code_or_label"),
        CheckConstraint("source IN ('manual', 'resume')", name="source"),
        Index("uq_candidate_declared_skill_user_id_skill_code", "user_id", "skill_code", unique=True),
        Index("ix_candidate_declared_skill_user_id", "user_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey(_USER_FK, ondelete="CASCADE"), nullable=False)
    skill_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)


# Свои теги уникальны без учёта регистра: индекс по выражению объявляется после класса, когда колонки уже существуют.
Index(
    "uq_candidate_declared_skill_user_id_custom_label",
    CandidateDeclaredSkill.user_id,
    func.lower(CandidateDeclaredSkill.custom_label),
    unique=True,
)


class ResumeUpload(Base):
    """Загрузка резюме. Байты файла не хранятся; `result` только предзаполняет форму и обнуляется (Арх. 6.14)."""

    __tablename__ = "resume_upload"
    __table_args__ = (
        CheckConstraint("status IN ('parsed', 'failed')", name="status"),
        Index("ix_resume_upload_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey(_USER_FK, ondelete="CASCADE"), nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    pages: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    engine: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    accepted_fields: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    parser_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PrivacySettings(Base):
    """Настройки приватности. Строки нет — действуют значения по умолчанию (`PrivacySettingsDTO`).

    `reveal_*` по умолчанию выключены (поправка рецензии R3-data-api-security-6): каналы, кроме e-mail,
    кандидат раскрывает только явным выбором.
    """

    __tablename__ = "privacy_settings"

    user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey(_USER_FK, ondelete="CASCADE"), primary_key=True)
    show_city: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_experience: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_declared_stack: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_about: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_fsp_summary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reveal_phone: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reveal_telegram: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reveal_link: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reveal_fsp_details: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hidden_domains: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CandidateConditions(Base):
    """Условия кандидата. `min_salary` — скрытый минимум: читает его только `service.min_salary` (Арх. 4.6)."""

    __tablename__ = "candidate_conditions"
    __table_args__ = (CheckConstraint("cardinality(work_formats) > 0", name="work_formats_not_empty"),)

    candidate_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey(_USER_FK, ondelete="CASCADE"), primary_key=True)
    min_salary: Mapped[int | None] = mapped_column(Integer, nullable=True)
    work_formats: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=_all_formats)
    relocation_ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ContactDisclosure(Base):
    """Раскрытие контактов пары «работодатель — кандидат». Строки не обновляются и не удаляются (кроме каскада)."""

    __tablename__ = "contact_disclosure"
    __table_args__ = (
        enum_check("source", DisclosureSource),
        CheckConstraint("(invitation_id IS NULL) <> (application_id IS NULL)", name="one_of_refs"),
        Index(
            "uq_contact_disclosure_invitation_id",
            "invitation_id",
            unique=True,
            postgresql_where=text("invitation_id IS NOT NULL"),
        ),
        Index(
            "uq_contact_disclosure_application_id",
            "application_id",
            unique=True,
            postgresql_where=text("application_id IS NOT NULL"),
        ),
        Index("ix_contact_disclosure_employer_id_candidate_id", "employer_id", "candidate_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    employer_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey(_USER_FK, ondelete="CASCADE"), nullable=False)
    candidate_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey(_USER_FK, ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    #: Идентификаторы сущностей модулей `contact` и `vacancies` — без внешнего ключа (Арх. 2.4, п. 3).
    invitation_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    application_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    fields: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    disclosed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AccessLog(Base):
    """Журнал доступа: что работодатели делали с данными кандидата (Арх. 10.8)."""

    __tablename__ = "access_log"
    __table_args__ = (
        enum_check("kind", AccessKind),
        Index("ix_access_log_candidate_id_at", "candidate_id", "at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    candidate_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey(_USER_FK, ondelete="CASCADE"), nullable=False)
    #: Без внешнего ключа: запись переживает удаление аккаунта работодателя.
    employer_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    #: Копия названия компании на момент события.
    company_name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    ref_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
