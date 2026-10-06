"""Фоновый цикл (Арх. 2.6): отдельная сессия, фиксация, письма после неё, устойчивость к ошибкам задач."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from app import wiring
from app.core import background, clock, mail
from app.core.background import Job, run_job

LETTER = {"link": "http://localhost:8080/x", "expires_hours": 24}


def job(fn, name: str = "test.job", **kwargs) -> Job:
    return Job(name=f"{name}.{uuid4().hex[:6]}", seconds=60, loader=lambda: fn, **kwargs)


def test_job_gets_session_and_service_time_and_is_committed(db, freeze_now, mailbox):
    frozen = freeze_now("2026-10-05T12:00:00+00:00")
    clock.advance(db, 3600)
    db.commit()
    seen = {}

    def task(session, now) -> None:
        seen["now"] = now
        clock.advance(session, 60)
        mail.enqueue(session, "verify_email", "bg@example.com", LETTER)
        assert mailbox == []  # до фиксации письмо не уходит

    assert run_job(job(task)) is True
    assert seen["now"] == frozen + timedelta(hours=1), "задаче передаётся время сервиса, а не реальное"
    assert clock.offset_seconds(db) == 3660
    assert [item.to for item in mailbox] == ["bg@example.com"]


def test_failed_job_rolls_back_drops_mail_and_does_not_stop_the_loop(db, mailbox, caplog):
    def task(session, now) -> None:
        clock.advance(session, 60)
        mail.enqueue(session, "verify_email", "bg@example.com", LETTER)
        raise RuntimeError("задача упала")

    failing = job(task)
    with caplog.at_level(logging.ERROR, logger="app.background"):
        background._run_guarded(failing)  # исключение не выходит наружу
    assert "завершилась ошибкой" in caplog.text
    assert clock.offset_seconds(db) == 0 and mailbox == []
    assert failing.disabled is False  # следующая попытка — по расписанию


def test_stub_facade_disables_job_until_restart(db, caplog):
    def not_ready(session, now) -> None:
        raise NotImplementedError("заглушка фасада")

    stub = job(not_ready)
    with caplog.at_level(logging.WARNING, logger="app.background"):
        background._run_guarded(stub)
    assert stub.disabled is True and "ещё не реализована" in caplog.text


def test_missing_function_is_skipped(db):
    assert run_job(Job(name="test.absent", seconds=60, loader=lambda: None)) is False


def test_job_is_skipped_while_another_process_holds_its_lock(engine, db):
    calls: list[int] = []
    guarded = job(lambda session, now: calls.append(1))
    with engine.connect() as other:
        other.execute(text("SELECT pg_advisory_lock(:key)"), {"key": background.lock_key(guarded.name)})
        assert run_job(guarded) is False and calls == []
        other.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": background.lock_key(guarded.name)})
    assert run_job(guarded) is True and calls == [1]
    assert run_job(guarded) is True, "блокировка должна освобождаться после каждого запуска"


def test_real_time_job_ignores_demo_shift(db, freeze_now):
    frozen = freeze_now("2026-10-05T12:00:00+00:00")
    clock.advance(db, 86400)
    db.commit()
    seen = {}
    assert run_job(job(lambda session, now: seen.update(now=now), real_time=True))
    assert seen["now"] == frozen


def test_purge_removes_only_sessions_expired_more_than_30_days_ago(db, make_user, freeze_now):
    now = freeze_now("2026-10-05T12:00:00+00:00")
    user = make_user()
    rows = {"old": now - timedelta(days=31), "recent": now - timedelta(days=5), "active": now + timedelta(days=3)}
    for label, expires_at in rows.items():
        db.execute(
            text(
                "INSERT INTO auth_session (id, user_id, token_hash, created_at, expires_at, last_seen_at) "
                "VALUES (:id, :user_id, :hash, :created, :expires, :created)"
            ),
            {
                "id": uuid4(),
                "user_id": user.id,
                "hash": label,
                "created": now - timedelta(days=60),
                "expires": expires_at,
            },
        )
    assert background.purge_technical_logs(db, now) >= 1
    left = db.execute(text("SELECT token_hash FROM auth_session WHERE user_id = :id ORDER BY 1"), {"id": user.id})
    assert [row.token_hash for row in left] == ["active", "recent"]
    assert background.purge_job().real_time is True and background.purge_job().seconds == 86400


def test_loop_runs_due_jobs_and_stops_on_signal(db, monkeypatch):
    monkeypatch.setattr(background, "FIRST_RUN_DELAY_SECONDS", 0)
    monkeypatch.setattr(background, "TICK_SECONDS", 0.01)
    calls: list[str] = []
    fast = job(lambda session, now: calls.append("fast"))
    fast.seconds = 0.02
    broken = job(lambda session, now: 1 / 0)

    async def scenario() -> None:
        stop = asyncio.Event()
        loop = asyncio.create_task(background.run_loop([broken, fast], stop))
        for _ in range(200):
            if len(calls) >= 2:
                break
            await asyncio.sleep(0.01)
        stop.set()
        await asyncio.wait_for(loop, timeout=5)

    asyncio.run(scenario())
    assert len(calls) >= 2, "задача должна выполняться повторно, а упавшая соседняя — не останавливать цикл"


def test_lock_key_is_stable_and_fits_int4():
    key = background.lock_key("contact.service:settle_all")
    assert key == background.lock_key("contact.service:settle_all") != background.lock_key("other")
    assert 0 <= key <= 0x7FFFFFFF


@pytest.mark.parametrize("enabled", [True, False])
def test_lifespan_starts_loop_only_when_enabled(enabled, engine, override_settings, monkeypatch):
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.main import create_app

    started: list[int] = []

    async def fake_loop(jobs, stop) -> None:
        started.append(len(jobs))
        await stop.wait()

    monkeypatch.setattr(background, "run_loop", fake_loop)
    override_settings(background_enabled=enabled, wiring_strict=False)
    with TestClient(create_app(get_settings())) as client:
        assert client.get("/api/v1/health").status_code == 200
    # 1 задача чистки журналов + фоновые задачи модулей при текущих флагах.
    assert started == ([1 + len(wiring.periodic_tasks())] if enabled else [])
