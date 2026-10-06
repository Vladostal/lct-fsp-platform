"""Часы сервиса (Арх. 2.4, п. 5; 13.5).

Время сервиса = реальное время UTC + смещение демо-режима из таблицы `service_clock`:

* `now(db)` — время сервиса. Его читают доменные правила: сроки приглашений, паузы теста, свежесть. В запросе оно
  берётся один раз (зависимость `core.deps.Now`) и передаётся в сервисы параметром `now`.
* `real_now()` — реальное время. Только для сессий входа, токенов, лимитов и механики привязки ФСП: демо-сдвиг на
  них не действует.
* `today(db)` — дата «на сегодня» по `APP_TZ` (Europe/Moscow).

SQL-функции времени (`now()`, `CURRENT_TIMESTAMP`) в доменном коде запрещены: все моменты пишет Python.
Время сервиса только растёт: смещение увеличивается и никогда не обнуляется (иначе у живых аккаунтов остались бы
метки «из будущего»).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import BigInteger, CheckConstraint, DateTime, SmallInteger, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.config import get_settings
from app.core.db import Base

_CLOCK_ROW_ID = 1


class ServiceClock(Base):
    """Единственная строка со смещением времени сервиса (Арх. 8.3)."""

    __tablename__ = "service_clock"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    offset_seconds: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _system_now() -> datetime:
    return datetime.now(UTC)


# Источник реального времени. Подменяется только фикстурой тестов `freeze_now`: подмена именно этой переменной,
# а не функции `real_now`, действует и на модули, которые импортировали `real_now` по имени.
_time_source: Callable[[], datetime] = _system_now


def real_now() -> datetime:
    """Реальное время UTC (в тестах — замороженное фикстурой `freeze_now`)."""
    return _time_source()


def offset_seconds(db: Session) -> int:
    """Текущее смещение времени сервиса в секундах; строки нет — смещение 0."""
    value = db.scalar(select(ServiceClock.offset_seconds).where(ServiceClock.id == _CLOCK_ROW_ID))
    return int(value or 0)


def now(db: Session) -> datetime:
    """Время сервиса: `real_now()` плюс смещение демо-часов."""
    return real_now() + timedelta(seconds=offset_seconds(db))


def to_local_date(moment: datetime) -> date:
    """Дата момента в часовом поясе `APP_TZ`."""
    return moment.astimezone(get_settings().tz).date()


def today(db: Session) -> date:
    """Дата «на сегодня» (`as_of`) по времени сервиса и `APP_TZ`."""
    return to_local_date(now(db))


def advance(db: Session, seconds: int) -> int:
    """Сдвинуть время сервиса вперёд на `seconds` и вернуть новое смещение.

    Только вперёд: отрицательный сдвиг отвергается. Вызывает модуль `demo` (`POST /demo/clock/advance`);
    сессии входа и токены сдвиг не затрагивает, потому что считаются по `real_now()`.
    """
    if seconds < 0:
        raise ValueError("время сервиса только растёт: сдвиг не может быть отрицательным")
    stamp = real_now()
    statement = (
        insert(ServiceClock)
        .values(id=_CLOCK_ROW_ID, offset_seconds=seconds, updated_at=stamp)
        .on_conflict_do_update(
            index_elements=[ServiceClock.id],
            set_={"offset_seconds": ServiceClock.offset_seconds + seconds, "updated_at": stamp},
        )
        .returning(ServiceClock.offset_seconds)
    )
    return int(db.execute(statement).scalar_one())
