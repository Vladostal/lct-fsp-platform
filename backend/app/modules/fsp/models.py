"""Таблицы модуля `fsp` (Арх. 8.7): привязка ФСП ID, попытки привязки и синхронизации, снимки, факты, кэш календаря.

Соглашения Арх. 8.1: первичные ключи — `uuid4` из Python (у фактов — `uuid5`, чтобы повторная синхронизация не
меняла идентификаторы), моменты времени пишет Python, внешние ключи на `app_user` — `ON DELETE CASCADE`.
Значения, пришедшие из реестра (`fsp_achievement`, `fsp_credential`), хранятся без `CHECK`: неизвестное
значение должно сохраниться, а не уронить синхронизацию.

В модели нет: токенов ФСП ID; ФИО, даты рождения и региона спортсмена; хранимого значения сигнала.
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
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _user_fk() -> ForeignKey:
    """Внешний ключ на `app_user` с каскадом; объект принадлежит одной колонке, поэтому каждый раз новый."""
    return ForeignKey("app_user.id", ondelete="CASCADE")


class ExternalIdentity(Base):
    """Привязка аккаунта к ФСП ID: один ФСП ID — один аккаунт, один аккаунт — один ФСП ID."""

    __tablename__ = "external_identity"
    __table_args__ = (
        UniqueConstraint("provider", "issuer", "subject", name="uq_external_identity_provider_issuer_subject"),
        UniqueConstraint("provider", "issuer", "fsp_id", name="uq_external_identity_provider_issuer_fsp_id"),
        UniqueConstraint("user_id", "provider", name="uq_external_identity_user_id_provider"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid, _user_fk(), nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    issuer: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    fsp_id: Mapped[str] = mapped_column(Text, nullable=False)
    provider_mode: Mapped[str] = mapped_column(Text, nullable=False)
    #: Белый список утверждений ID-токена (`constants.CLAIMS_WHITELIST`).
    claims: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    consent_version: Mapped[str] = mapped_column(Text, nullable=False)
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FspLinkAttempt(Base):
    """Попытка привязки: состояние потока OIDC живёт 10 минут; `state` хранится только хэшем."""

    __tablename__ = "fsp_link_attempt"
    __table_args__ = (Index("ix_fsp_link_attempt_user_id_created_at", "user_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid, _user_fk(), nullable=False)
    state_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    nonce: Mapped[str] = mapped_column(Text, nullable=False)
    #: После callback затирается пустой строкой.
    code_verifier: Mapped[str] = mapped_column(Text, nullable=False)
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    provider_mode: Mapped[str] = mapped_column(Text, nullable=False)
    consent_version: Mapped[str] = mapped_column(Text, nullable=False)
    consent_text_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)


class FspSnapshot(Base):
    """Снимок выгрузки реестра. Хранятся два последних; текущий — `is_current`."""

    __tablename__ = "fsp_snapshot"
    __table_args__ = (
        Index(
            "uq_fsp_snapshot_identity_id_current",
            "identity_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        Index("ix_fsp_snapshot_user_id", "user_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    identity_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("external_identity.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(Uuid, _user_fk(), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    registry_url: Mapped[str] = mapped_column(Text, nullable=False)
    api_version: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    etag: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Выгрузка без региона спортсмена и участий (поправка R3-data-api-security-12); `{}` — записи спортсмена нет.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    athlete_registered: Mapped[bool] = mapped_column(Boolean, nullable=False)
    participations_count: Mapped[int] = mapped_column(Integer, nullable=False)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FspSyncAttempt(Base):
    """Попытка синхронизации; по строке `unlinked_*` с `identity_id IS NULL` кандидат видит уведомление об отвязке."""

    __tablename__ = "fsp_sync_attempt"
    __table_args__ = (
        Index(
            "uq_fsp_sync_attempt_identity_id_running",
            "identity_id",
            unique=True,
            postgresql_where=text("finished_at IS NULL"),
        ),
        Index("ix_fsp_sync_attempt_user_id_started_at", "user_id", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid, _user_fk(), nullable=False)
    identity_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("external_identity.id", ondelete="CASCADE"), nullable=True
    )
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class FspAchievement(Base):
    """Факт участия: нормализованная строка протокола самого кандидата (Арх. 8.7).

    `id = uuid5(NAMESPACE_FSP, "{user_id}:{entry_id}:{member_role}")`: повторная синхронизация идентификаторов
    не меняет, поэтому ссылки подбора на факт-доказательство не ломаются.
    """

    __tablename__ = "fsp_achievement"
    __table_args__ = (
        UniqueConstraint("user_id", "entry_id", "member_role", name="uq_fsp_achievement_user_id_entry_id_member_role"),
        Index("ix_fsp_achievement_user_id_counted", "user_id", "counted"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(Uuid, _user_fk(), nullable=False)
    snapshot_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("fsp_snapshot.id", ondelete="CASCADE"), nullable=False)
    entry_id: Mapped[str] = mapped_column(Text, nullable=False)
    competition_id: Mapped[str] = mapped_column(Text, nullable=False)
    competition_title: Mapped[str] = mapped_column(Text, nullable=False)
    ekp_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    discipline_code: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    series_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    tier: Mapped[str | None] = mapped_column(Text, nullable=True)
    age_group: Mapped[str] = mapped_column(Text, nullable=False)
    participation: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[str | None] = mapped_column(Text, nullable=True)
    date_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    protocol_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    field_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    regions_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    member_role: Mapped[str] = mapped_column(Text, nullable=False)
    is_captain: Mapped[bool] = mapped_column(Boolean, nullable=False)
    team_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    team_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_status: Mapped[str] = mapped_column(Text, nullable=False)
    place: Mapped[int | None] = mapped_column(Integer, nullable=True)
    place_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    place_eff: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    score: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    score_max: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    solved: Mapped[int | None] = mapped_column(Integer, nullable=True)
    problems_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    penalty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_bucket: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    counted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    uncounted_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_points: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    anon_period: Mapped[str | None] = mapped_column(Text, nullable=True)
    anon_k_a: Mapped[int | None] = mapped_column(Integer, nullable=True)
    anon_k_b: Mapped[int | None] = mapped_column(Integer, nullable=True)


class FspCredential(Base):
    """Разряд или звание из реестра. Другие виды (сборная, судейство) в MVP не моделируются (Арх. 15.1, № 47)."""

    __tablename__ = "fsp_credential"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", "source_key", name="uq_fsp_credential_user_id_kind_source_key"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(Uuid, _user_fk(), nullable=False)
    snapshot_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("fsp_snapshot.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    source_key: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    discipline_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    level: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    revoked_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    season: Mapped[int | None] = mapped_column(Integer, nullable=True)
    order_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_by: Mapped[str | None] = mapped_column(Text, nullable=True)


class FspCache(Base):
    """Кэш общих ответов реестра (календарь на 6 часов)."""

    __tablename__ = "fsp_cache"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    payload: Mapped[Any] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
