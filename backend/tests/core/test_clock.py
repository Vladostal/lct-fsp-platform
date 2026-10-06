"""Часы сервиса (Арх. 2.4, п. 5): сдвиг меняет `clock.now()` и не трогает сессии входа."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import APIRouter
from sqlalchemy import text

from app.core import clock
from app.core.deps import AnyUser


def test_now_equals_real_time_without_offset(db, freeze_now):
    frozen = freeze_now("2026-10-05T09:30:00+00:00")
    assert clock.real_now() == frozen
    assert clock.offset_seconds(db) == 0  # строки service_clock ещё нет — смещение 0
    assert clock.now(db) == frozen


def test_advance_shifts_service_time_only(db, freeze_now):
    frozen = freeze_now("2026-10-05T09:30:00+00:00")
    assert clock.advance(db, 7 * 86400) == 7 * 86400
    assert clock.advance(db, 60) == 7 * 86400 + 60  # сдвиги складываются
    assert clock.now(db) == frozen + timedelta(days=7, seconds=60)
    assert clock.real_now() == frozen, "реальное время от сдвига не зависит"
    row = db.execute(text("SELECT id, offset_seconds FROM service_clock")).all()
    assert [tuple(item) for item in row] == [(1, 7 * 86400 + 60)]


def test_service_time_only_grows(db):
    with pytest.raises(ValueError):
        clock.advance(db, -1)


def test_today_follows_app_timezone(db, freeze_now):
    # 22:30 UTC — в Москве уже следующий день.
    freeze_now(datetime(2026, 10, 5, 22, 30, tzinfo=UTC))
    assert clock.today(db) == date(2026, 10, 6)
    assert clock.to_local_date(datetime(2026, 10, 5, 20, 59, tzinfo=UTC)) == date(2026, 10, 5)


def test_freeze_now_tick_and_naive_input(freeze_now):
    assert freeze_now("2026-10-05T10:00:00") == datetime(2026, 10, 5, 10, tzinfo=UTC)  # без пояса — UTC
    assert freeze_now.tick(30) == datetime(2026, 10, 5, 10, 0, 30, tzinfo=UTC)
    assert freeze_now.tick(days=1) == clock.real_now() == datetime(2026, 10, 6, 10, 0, 30, tzinfo=UTC)


def test_clock_shift_does_not_expire_login_session(probe, tx_router: APIRouter, db, make_user, login_as):
    """Приёмка: сдвиг демо-часов на 30 суток меняет `clock.now()`, но сессия входа (TTL 14 дней) остаётся."""

    @tx_router.get("/me")
    def me(user: AnyUser) -> dict[str, str]:
        return {"id": str(user.id)}

    user = make_user("candidate")
    client = login_as(user, probe(tx_router))
    expires_before = db.execute(
        text("SELECT expires_at FROM auth_session WHERE user_id = :id"), {"id": user.id}
    ).scalar()

    before = clock.now(db)
    clock.advance(db, 30 * 86400)
    assert clock.now(db) - before >= timedelta(days=30)

    assert client.get("/api/v1/me").json() == {"id": str(user.id)}
    expires_after = db.execute(
        text("SELECT expires_at FROM auth_session WHERE user_id = :id"), {"id": user.id}
    ).scalar()
    assert expires_after == expires_before


def test_real_time_does_expire_login_session(probe, tx_router: APIRouter, make_user, login_as, freeze_now):
    @tx_router.get("/me")
    def me(user: AnyUser) -> dict[str, str]:
        return {"id": str(user.id)}

    freeze_now("2026-10-05T10:00:00+00:00")
    client = login_as(make_user("candidate"), probe(tx_router))
    freeze_now.tick(days=14, seconds=1)
    assert client.get("/api/v1/me").status_code == 401


def test_timestamps_come_back_from_database_in_utc(db, freeze_now):
    """Соединение работает в UTC независимо от настроек сервера: моменты времени читаются как записаны."""
    frozen = freeze_now("2026-10-05T21:15:00+00:00")
    clock.advance(db, 1)
    stored = db.execute(text("SELECT updated_at FROM service_clock")).scalar()
    assert stored == frozen and stored.utcoffset() == timedelta(0)
    assert db.execute(text("SHOW timezone")).scalar().upper() == "UTC"
