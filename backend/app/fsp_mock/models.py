"""Таблицы демо-реестра ФСП — схема `fspmock` (Арх. 8.12). Платформа их не читает.

Модель повторяет итоговый протокол: соревнование → строка протокола (команда или личный участник) → состав →
результат. ФИО, дата рождения и пол спортсмена существуют только здесь и в API реестра не отдаются.
Судейство и сборные не моделируются (Арх. 15.1, № 47).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, Numeric, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import FSPMOCK_SCHEMA, Base

_SCHEMA = {"schema": FSPMOCK_SCHEMA}


class Athlete(Base):
    """Спортсмен. `fsp_id` совпадает с `sub` демо-провайдера ФСП ID."""

    __tablename__ = "athlete"
    __table_args__ = _SCHEMA

    fsp_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    last_name: Mapped[str] = mapped_column(Text, nullable=False)
    first_name: Mapped[str] = mapped_column(Text, nullable=False)
    middle_name: Mapped[str] = mapped_column(Text, nullable=False)
    birth_date: Mapped[date] = mapped_column(Date, nullable=False)
    gender: Mapped[str] = mapped_column(Text, nullable=False)
    region_code: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    #: Ключ типового персонажа (только мок).
    persona_key: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    #: Латентная соревновательная сила для генератора (только мок, наружу не отдаётся).
    latent_skill: Mapped[float] = mapped_column(Float, nullable=False)


class Competition(Base):
    """Спортивное соревнование: одна запись на соревнование ЕКП; этап и финал — разные записи с общей серией."""

    __tablename__ = "competition"
    __table_args__ = (Index("ix_competition_status_date_start", "status", "date_start"), _SCHEMA)

    competition_id: Mapped[str] = mapped_column(Text, primary_key=True)
    ekp_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    discipline_code: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    series_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    age_group: Mapped[str] = mapped_column(Text, nullable=False)
    participation: Mapped[str] = mapped_column(Text, nullable=False)
    team_size_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    team_size_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    format: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    protocol_status: Mapped[str] = mapped_column(Text, nullable=False)
    date_start: Mapped[date] = mapped_column(Date, nullable=False)
    date_end: Mapped[date] = mapped_column(Date, nullable=False)
    registration_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    city: Mapped[str | None] = mapped_column(Text, nullable=True)
    region_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    organizer: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Размер поля — атрибут соревнования, а не число строк таблицы: у международных здесь только российские участники.
    entries_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    athletes_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    regions_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    registration_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    protocol_url: Mapped[str | None] = mapped_column(Text, nullable=True)


class Entry(Base):
    """Строка итогового протокола: команда или личный участник вместе с результатом."""

    __tablename__ = "entry"
    __table_args__ = (Index("ix_entry_competition_id", "competition_id"), _SCHEMA)

    entry_id: Mapped[str] = mapped_column(Text, primary_key=True)
    competition_id: Mapped[str] = mapped_column(
        Text, ForeignKey(f"{FSPMOCK_SCHEMA}.competition.competition_id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    team_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    region_code: Mapped[str] = mapped_column(Text, nullable=False)
    result_status: Mapped[str] = mapped_column(Text, nullable=False)
    place: Mapped[int | None] = mapped_column(Integer, nullable=True)
    place_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    score_max: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    solved: Mapped[int | None] = mapped_column(Integer, nullable=True)
    problems_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    penalty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    criteria: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)


class EntryMember(Base):
    """Состав строки протокола: спортсмены, тренер, представитель. `fsp_id` — не внешний ключ."""

    __tablename__ = "entry_member"
    __table_args__ = (Index("ix_entry_member_fsp_id", "fsp_id"), _SCHEMA)

    entry_id: Mapped[str] = mapped_column(
        Text, ForeignKey(f"{FSPMOCK_SCHEMA}.entry.entry_id", ondelete="CASCADE"), primary_key=True
    )
    fsp_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    role: Mapped[str] = mapped_column(Text, primary_key=True)
    is_captain: Mapped[bool] = mapped_column(Boolean, nullable=False)


class RankAssignment(Base):
    """Присвоение разряда или звания."""

    __tablename__ = "rank_assignment"
    __table_args__ = (Index("ix_rank_assignment_fsp_id", "fsp_id"), _SCHEMA)

    rank_id: Mapped[str] = mapped_column(Text, primary_key=True)
    fsp_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    rank_code: Mapped[str] = mapped_column(Text, nullable=False)
    assigned_on: Mapped[date] = mapped_column(Date, nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    order_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    discipline_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    basis_entry_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    revoked_on: Mapped[date | None] = mapped_column(Date, nullable=True)


class AccessGrant(Base):
    """Разрешение «спортсмен → клиент»: регистрируется первой выгрузкой с пользовательским токеном."""

    __tablename__ = "access_grant"
    __table_args__ = _SCHEMA

    fsp_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    client_id: Mapped[str] = mapped_column(Text, primary_key=True)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    #: `oidc` — выдано в потоке входа; `seed` — создано сидом демо-данных.
    source: Mapped[str] = mapped_column(Text, nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuthCode(Base):
    """Код авторизации демо-провайдера: в базе только SHA-256, срок 60 секунд, одноразовый."""

    __tablename__ = "auth_code"
    __table_args__ = _SCHEMA

    code_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    #: Не внешний ключ: «новый ФСП ID без записи спортсмена» получает код для `sub`, которого нет в реестре.
    fsp_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    client_id: Mapped[str] = mapped_column(Text, nullable=False)
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    nonce: Mapped[str] = mapped_column(Text, nullable=False)
    code_challenge: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Control(Base):
    """Служебные значения мока: режим отказа, версия данных, параметры сида."""

    __tablename__ = "control"
    __table_args__ = _SCHEMA

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
