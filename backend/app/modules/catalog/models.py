"""Таблица модуля `catalog` (Арх. 8.3): очередь на пополнение словаря навыков.

Строка не привязана к пользователю и не содержит ничего, кроме термина, источника и счётчика: что именно можно
записывать, решает `service.log_miss` (поправка R3-data-api-security-5; 152-ФЗ). Срок хранения —
`service.MISS_LOG_RETENTION_DAYS`.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class SkillMissLog(Base):
    """Нераспознанный термин: сколько раз встретился и когда в последний раз."""

    __tablename__ = "skill_miss_log"
    __table_args__ = (
        CheckConstraint("source IN ('resume', 'need')", name="source"),
        CheckConstraint("cnt >= 1", name="cnt_positive"),
    )

    term: Mapped[str] = mapped_column(Text, primary_key=True)
    source: Mapped[str] = mapped_column(Text, primary_key=True)
    cnt: Mapped[int] = mapped_column(Integer, default=1)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
