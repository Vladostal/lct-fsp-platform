"""Таблица `company` (Арх. 8.3): профиль компании, одна строка на работодателя.

Строки нет, пока работодатель не сохранил профиль; внешний ключ на `app_user` каскадный, поэтому удаление
аккаунта удаляет и профиль. Моменты времени пишет Python (Арх. 8.1).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_check
from app.shared.enums import ContactKind, TrustLevel


class Company(Base):
    """Профиль компании работодателя; `employer_id` равен `app_user.id`."""

    __tablename__ = "company"
    __table_args__ = (enum_check("contact_kind", ContactKind), enum_check("trust_level", TrustLevel))

    employer_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    sphere: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    site: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_kind: Mapped[str] = mapped_column(Text, nullable=False)
    contact_value: Mapped[str] = mapped_column(Text, nullable=False)
    trust_level: Mapped[str] = mapped_column(Text, nullable=False, default=TrustLevel.BASIC.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
