"""Таблицы модуля `matching` (Арх. 8.8).

Соглашения Арх. 8.1: ключи — `uuid` из Python; моменты времени пишет Python (значений по умолчанию `now()` в DDL
нет); перечисления — `text` с `CHECK`; внешние ключи — `ON DELETE CASCADE`, поэтому удаление аккаунта и сброс
демо-данных проходят одним `DELETE FROM app_user`. Ссылки на сущности чужих модулей — без внешнего ключа, кроме
`app_user(id)`.

Строки `shortlist_snapshot` и `shortlist_item` после вставки не обновляются; единственное исключение — каскад
при удалении аккаунта кандидата.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_check
from app.shared.enums import DiffMark, ExposureSource, FitBand, NeedStatus, Relation


class Need(Base):
    """Потребность работодателя: кого он ищет (Арх. 6.14)."""

    __tablename__ = "need"
    __table_args__ = (
        enum_check("status", NeedStatus),
        Index("ix_need_employer_id_status_created_at", "employer_id", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    employer_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    team_description: Mapped[str] = mapped_column(Text, nullable=False)
    specialization_code: Mapped[str] = mapped_column(Text, nullable=False)
    grade_code: Mapped[str] = mapped_column(Text, nullable=False)
    must_skills: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    nice_skills: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    work_formats: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    city: Mapped[str | None] = mapped_column(Text, nullable=True)
    salary_from: Mapped[int] = mapped_column(Integer, nullable=False)
    salary_to: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    parse_meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: Без внешнего ключа: версия ссылается на потребность, а не наоборот.
    latest_snapshot_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ShortlistSnapshot(Base):
    """Версия подборки — неизменяемый снимок одного запуска ранжирования (Арх. 6.11)."""

    __tablename__ = "shortlist_snapshot"
    __table_args__ = (
        UniqueConstraint("need_id", "version_no"),
        Index("ix_shortlist_snapshot_employer_id_created_at", "employer_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    need_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("need.id", ondelete="CASCADE"), nullable=False)
    employer_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("shortlist_snapshot.id", ondelete="CASCADE"), nullable=True
    )
    #: `ShortlistQuery` в каноническом виде.
    query: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    query_hash: Mapped[str] = mapped_column(Text, nullable=False)
    query_changes: Mapped[str | None] = mapped_column(Text, nullable=True)
    scorer_version: Mapped[str] = mapped_column(Text, nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    seed: Mapped[str] = mapped_column(Text, nullable=False)
    #: `[{category_code, relation, count}]`.
    categories: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    #: `{category_total, available, format_ok, must_ok, shown}`.
    funnel: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    #: `{added, dropped, moved_up, moved_down}` к родителю.
    diff: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: `[{candidate_id, category_code, reason_code, reason_text}]`; код кандидата подставляется при чтении.
    dropped: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    #: `RelaxationHint[]`.
    hints: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ShortlistItem(Base):
    """Строка версии подборки: позиция, полосы и объяснение на момент создания."""

    __tablename__ = "shortlist_item"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "position"),
        enum_check("relation", Relation),
        enum_check("diff_mark", DiffMark),
        # fit_band допускает NULL: в запросе нет навыков.
        enum_check("fit_band", FitBand),
        Index("ix_shortlist_item_candidate_id", "candidate_id"),
    )

    snapshot_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("shortlist_snapshot.id", ondelete="CASCADE"), primary_key=True
    )
    candidate_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    relation: Mapped[str] = mapped_column(Text, nullable=False)
    coverage_pct: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    coverage_band: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    confirmed_band: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    strength: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False)
    strength_band: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    fit_band: Mapped[str | None] = mapped_column(Text, nullable=True)
    diff_mark: Mapped[str] = mapped_column(Text, nullable=False)
    diff_delta: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: `MatchExplanation`; подробного текста ФСП в нём нет (Арх. 6.10).
    explanation: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class NeedPin(Base):
    """Закрепление кандидата: принадлежит потребности, а не версии, и переживает уточнения."""

    __tablename__ = "need_pin"

    need_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("need.id", ondelete="CASCADE"), primary_key=True)
    candidate_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True)
    #: Версия, в которой закрепили (справочно, без внешнего ключа).
    snapshot_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    pinned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExposureEvent(Base):
    """Показ кандидата работодателю: не больше одной строки в день на пару (Арх. 6.13)."""

    __tablename__ = "exposure_event"
    __table_args__ = (
        enum_check("source", ExposureSource),
        Index("ix_exposure_event_candidate_id_day", "candidate_id", "day"),
    )

    employer_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True)
    candidate_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    opened: Mapped[bool] = mapped_column(Boolean, nullable=False)
