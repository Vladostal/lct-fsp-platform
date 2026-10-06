"""Таблицы модуля `assessment` (Арх. 8.5).

Поля `assessment_variant.answer`, `misconception_answers` и `assessment_session_item.score`, `error_tag` не входят
ни в одну схему ответа ролей `candidate` и `employer`.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_check
from app.shared.enums import (
    ClaimSource,
    EvidenceSource,
    FamilyStatus,
    GradeChangeKind,
    ItemStatus,
    SessionKind,
    SessionStatus,
    SkillVerdict,
    SlotRole,
    TestOutcome,
    VariantStatus,
)

_TS = DateTime(timezone=True)


def _user_fk(*, primary_key: bool = False) -> Mapped[UUID]:
    return mapped_column(Uuid, ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=primary_key, nullable=False)


class SurveyResponse(Base):
    """Ответы на опрос; история не перезаписывается."""

    __tablename__ = "assessment_survey_response"
    __table_args__ = (Index(None, "candidate_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = _user_fk()
    survey_version: Mapped[str] = mapped_column(Text, nullable=False)
    answers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    specialization_code: Mapped[str] = mapped_column(Text, nullable=False)
    lang_module: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False)


class AssessmentProfile(Base):
    """Текущее состояние кандидата в тестировании: специализация опроса и заявленный грейд."""

    __tablename__ = "assessment_profile"

    candidate_id: Mapped[UUID] = _user_fk(primary_key=True)
    survey_response_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    specialization_code: Mapped[str] = mapped_column(Text, nullable=False)
    lang_module: Mapped[str | None] = mapped_column(Text, nullable=True)
    claimed_grade: Mapped[str | None] = mapped_column(Text, nullable=True)
    claim_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    specialization_changed_at: Mapped[datetime | None] = mapped_column(_TS, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False)


class GradeClaim(Base):
    """Заявления грейда."""

    __tablename__ = "assessment_grade_claim"
    __table_args__ = (
        Index(None, "candidate_id", "created_at"),
        enum_check("source", ClaimSource),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = _user_fk()
    specialization_code: Mapped[str] = mapped_column(Text, nullable=False)
    grade_code: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False)


class FamilyRow(Base):
    """Семейство заданий в банке."""

    __tablename__ = "assessment_family"
    __table_args__ = (
        Index(None, "group_code", "status"),
        enum_check("status", FamilyStatus),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    group_code: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    specializations: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    skill_tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    priority: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_changed_at: Mapped[datetime] = mapped_column(_TS, nullable=False)


class FamilyLevelRow(Base):
    """Уровень семейства: сложность и расчётное время."""

    __tablename__ = "assessment_family_level"

    family_id: Mapped[str] = mapped_column(
        Text, ForeignKey("assessment_family.id", ondelete="CASCADE"), primary_key=True
    )
    level: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    b: Mapped[Decimal] = mapped_column(Numeric(3, 1), nullable=False)
    time_budget_s: Mapped[int] = mapped_column(Integer, nullable=False)


class VariantRow(Base):
    """Заранее созданный вариант задания. `payload` видит кандидат; `answer` не отдаётся никому."""

    __tablename__ = "assessment_variant"
    __table_args__ = (
        UniqueConstraint("family_id", "family_version", "level", "seed"),
        Index(None,
            "family_id",
            "level",
            "status",
            "served_count",
        ),
        Index(None, "content_hash"),
        enum_check("status", VariantStatus),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    family_id: Mapped[str] = mapped_column(Text, ForeignKey("assessment_family.id", ondelete="CASCADE"), nullable=False)
    family_version: Mapped[int] = mapped_column(Integer, nullable=False)
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # Seed — первые 8 байт HMAC, целое без знака до 2^64 − 1 (приложение A, §2.7): в BIGINT со знаком не помещается.
    seed: Mapped[Decimal] = mapped_column(Numeric(20, 0), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    answer: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    misconception_answers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    features: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    guess: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    served_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))


class SessionRow(Base):
    """Сессия теста. Одна активная на кандидата — частичный уникальный индекс."""

    __tablename__ = "assessment_session"
    __table_args__ = (
        Index(
            "uq_assessment_session_candidate_id_active",
            "candidate_id",
            unique=True,
            postgresql_where=text("status = 'in_progress'"),
        ),
        Index(None,
            "candidate_id",
            "specialization_code",
            "finished_at",
        ),
        enum_check("status", SessionStatus),
        enum_check("kind", SessionKind),
        enum_check("outcome", TestOutcome),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = _user_fk()
    specialization_code: Mapped[str] = mapped_column(Text, nullable=False)
    target_grade: Mapped[str] = mapped_column(Text, nullable=False)
    lang_module: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    seed: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(_TS, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(_TS, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(_TS, nullable=True)
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    theta: Mapped[float | None] = mapped_column(Float, nullable=True)
    se: Mapped[float | None] = mapped_column(Float, nullable=True)
    p_pass: Mapped[float | None] = mapped_column(Float, nullable=True)
    p_margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    items_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_answered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pooled_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blueprint: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    flags: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    bank_version: Mapped[str] = mapped_column(Text, nullable=False)
    engine_version: Mapped[str] = mapped_column(Text, nullable=False)


class SessionItemRow(Base):
    """Задание сессии и ответ на него. `a_used`, `b_used`, `c_used` записываются в момент выдачи."""

    __tablename__ = "assessment_session_item"
    __table_args__ = (
        UniqueConstraint("session_id", "position"),
        UniqueConstraint("session_id", "family_id"),
        Index(None, "variant_id"),
        enum_check("status", ItemStatus),
        enum_check("slot_role", SlotRole),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("assessment_session.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    stage: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    slot_role: Mapped[str] = mapped_column(Text, nullable=False)
    slot_group: Mapped[str | None] = mapped_column(Text, nullable=True)
    family_id: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    variant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("assessment_variant.id"), nullable=False)
    a_used: Mapped[float] = mapped_column(Float, nullable=False)
    b_used: Mapped[float] = mapped_column(Float, nullable=False)
    c_used: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    shown_at: Mapped[datetime | None] = mapped_column(_TS, nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(_TS, nullable=True)
    answer: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    parse_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    error_tag: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    time_spent_ms_server: Mapped[int | None] = mapped_column(Integer, nullable=True)
    client: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    flags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list, server_default=text("'{}'"))


class CategoryRow(Base):
    """Действующая категория кандидата: не больше одной."""

    __tablename__ = "assessment_category"
    __table_args__ = (
        Index(None, "specialization_code", "grade_code"),
        enum_check("verdict", TestOutcome),
    )

    candidate_id: Mapped[UUID] = _user_fk(primary_key=True)
    specialization_code: Mapped[str] = mapped_column(Text, nullable=False)
    grade_code: Mapped[str] = mapped_column(Text, nullable=False)
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    theta: Mapped[float] = mapped_column(Float, nullable=False)
    se: Mapped[float] = mapped_column(Float, nullable=False)
    items_count: Mapped[int] = mapped_column(Integer, nullable=False)
    level_session_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(_TS, nullable=False)
    level_updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False)
    last_grade_change_at: Mapped[datetime | None] = mapped_column(_TS, nullable=True)
    change_available_at: Mapped[datetime] = mapped_column(_TS, nullable=False)
    last_evidence_at: Mapped[datetime] = mapped_column(_TS, nullable=False)
    #: Категория получена быстрым демо-тестом (Арх. 13.5): в отчётах платформы не учитывается.
    is_demo_result: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))


class GradeChange(Base):
    """История присвоений и смен грейда."""

    __tablename__ = "assessment_grade_change"
    __table_args__ = (
        Index(None, "candidate_id", "created_at"),
        enum_check("kind", GradeChangeKind),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = _user_fk()
    specialization_code: Mapped[str] = mapped_column(Text, nullable=False)
    from_grade: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_grade: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    session_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False)


class SkillEvidenceRow(Base):
    """Вердикт по группе и теги верно решённых семейств (Арх. 5.6); `source` — тест или короткое задание."""

    __tablename__ = "assessment_skill_evidence"
    __table_args__ = (enum_check("source", EvidenceSource), enum_check("verdict", SkillVerdict))

    candidate_id: Mapped[UUID] = _user_fk(primary_key=True)
    specialization_code: Mapped[str] = mapped_column(Text, primary_key=True)
    group_code: Mapped[str] = mapped_column(Text, primary_key=True)
    source: Mapped[str] = mapped_column(Text, primary_key=True)
    items: Mapped[int] = mapped_column(Integer, nullable=False)
    correct: Mapped[int] = mapped_column(Integer, nullable=False)
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    level_grade: Mapped[str] = mapped_column(Text, nullable=False)
    tags_correct: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    ref_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    last_at: Mapped[datetime] = mapped_column(_TS, nullable=False)


class ExposureRow(Base):
    """Счётчик экспозиции: в скольких сессиях пары (специализация, грейд) встретилось семейство."""

    __tablename__ = "assessment_exposure"

    specialization_code: Mapped[str] = mapped_column(Text, primary_key=True)
    grade_code: Mapped[str] = mapped_column(Text, primary_key=True)
    family_id: Mapped[str] = mapped_column(Text, primary_key=True)
    served_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class BlueprintCounter(Base):
    """Число начатых сессий пары (специализация, грейд) — знаменатель экспозиции."""

    __tablename__ = "assessment_blueprint_counter"

    specialization_code: Mapped[str] = mapped_column(Text, primary_key=True)
    grade_code: Mapped[str] = mapped_column(Text, primary_key=True)
    sessions_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


__all__ = [
    "AssessmentProfile",
    "BlueprintCounter",
    "CategoryRow",
    "ExposureRow",
    "FamilyLevelRow",
    "FamilyRow",
    "GradeChange",
    "GradeClaim",
    "SessionItemRow",
    "SessionRow",
    "SkillEvidenceRow",
    "SurveyResponse",
    "VariantRow",
]
