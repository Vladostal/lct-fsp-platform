"""Экран кандидата (`GET /fsp/link`): состояния приложения D §7.1, ленивое обновление, уведомления, режим keycloak."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.fsp_mock import generator
from app.fsp_mock.models import Athlete, Entry
from app.modules.fsp import service
from app.modules.fsp.models import ExternalIdentity, FspSnapshot, FspSyncAttempt
from app.scripts import fsp_resync
from tests.fsp import mockdata

LINK = "/api/v1/fsp/link"


@pytest.fixture
def user_client(
    db: Session, make_user: Callable[..., object], login_as: Callable[..., TestClient], client: TestClient
) -> tuple[TestClient, UUID]:
    user = make_user("candidate")
    login_as(user)
    return client, user.id  # type: ignore[attr-defined]


def test_not_linked_view(user_client: tuple[TestClient, UUID]) -> None:
    client, _ = user_client
    view = client.get(LINK).json()
    assert view["status"] == "not_linked" and view["provider_mode"] == "mock"
    assert view["history_status"] is None and view["achievements"] == [] and view["signal"] is None
    assert view["refresh"]["last_outcome"] is None and view["notice"] is None


def test_no_results_and_no_counted_states(db: Session, user_client: tuple[TestClient, UUID]) -> None:
    client, user_id = user_client
    pending = mockdata.add_athlete(db)
    result = mockdata.add_result(db, pending, place=1)
    entry = db.get(Entry, result.entry_id)
    assert entry is not None
    entry.result_status, entry.place = "dsq", None
    db.flush()
    service.seed_link(db, user_id, str(pending))
    view = client.get(LINK).json()
    assert view["history_status"] == "no_history" and view["no_history_reason"] == "no_counted_results"
    assert (
        view["achievements"][0]["counted"] is False and view["achievements"][0]["uncounted_label"] == "дисквалификация"
    )
    assert view["employer_preview"] is None


def test_stale_snapshot_triggers_background_refresh(
    db: Session, user_client: tuple[TestClient, UUID], freeze_now: Callable[..., object]
) -> None:
    client, user_id = user_client
    athlete = mockdata.add_athlete(db)
    mockdata.add_result(db, athlete, place=1)
    service.seed_link(db, user_id, str(athlete))
    db.commit()
    snapshot = db.scalars(select(FspSnapshot)).one()
    first_check = snapshot.checked_at
    client.get(LINK)  # снимок свежий: ничего не запускается
    db.refresh(snapshot)
    assert snapshot.checked_at == first_check
    freeze_now.tick(hours=25)  # type: ignore[attr-defined]
    view = client.get(LINK).json()
    assert view["refresh"]["stale"] is False  # «данные могли устареть» — только после 30 суток
    db.expire_all()
    db.refresh(snapshot)
    assert snapshot.checked_at > first_check  # ответ отдал прежние данные, обновление прошло после ответа
    attempts = db.scalars(select(FspSyncAttempt).order_by(FspSyncAttempt.started_at)).all()
    assert [item.trigger for item in attempts] == ["seed", "stale"]
    freeze_now.tick(minutes=11)  # type: ignore[attr-defined]
    snapshot.checked_at = clock.real_now() - timedelta(
        days=31
    )  # сессия входа столько не живёт: двигаем снимок, не время
    db.commit()
    with registry_down():
        old = client.get(LINK).json()
    assert old["refresh"]["stale"] is True and old["refresh"]["last_outcome"] in {"failed_unavailable", "ok_unchanged"}
    assert len(old["achievements"]) == 1  # сбой обновления данных не меняет


def registry_down():  # type: ignore[no-untyped-def]
    from contextlib import contextmanager

    from app.fsp_mock import registry_service

    @contextmanager
    def cm():  # type: ignore[no-untyped-def]
        with registry_service.registry_session() as session:
            registry_service.set_failure_mode(session, "unavailable")
        try:
            yield
        finally:
            with registry_service.registry_session() as session:
                registry_service.set_failure_mode(session, "none")

    return cm()


def test_recent_failure_blocks_lazy_refresh(
    db: Session, user_client: tuple[TestClient, UUID], freeze_now: Callable[..., object]
) -> None:
    """Автоматические повторы — не чаще раза в 10 минут: сбой только что — ленивого обновления нет."""
    client, user_id = user_client
    athlete = mockdata.add_athlete(db)
    mockdata.add_result(db, athlete, place=1)
    service.seed_link(db, user_id, str(athlete))
    db.commit()
    freeze_now.tick(hours=25)  # type: ignore[attr-defined]
    with registry_down():
        client.get(LINK)  # ленивое обновление не удалось
        attempts = db.scalars(select(FspSyncAttempt)).all()
        assert len(attempts) == 2 and attempts[-1].outcome == "failed_unavailable"
        client.get(LINK)
        assert len(db.scalars(select(FspSyncAttempt)).all()) == 2  # повтора нет
        freeze_now.tick(minutes=11)  # type: ignore[attr-defined]
        client.get(LINK)
        assert len(db.scalars(select(FspSyncAttempt)).all()) == 3


def test_sync_pending_state(
    db: Session, user_client: tuple[TestClient, UUID], freeze_now: Callable[..., object]
) -> None:
    client, user_id = user_client
    athlete = mockdata.add_athlete(db)
    service.seed_link(db, user_id, str(athlete))
    identity = db.scalars(select(ExternalIdentity)).one()
    freeze_now.tick(seconds=10)  # type: ignore[attr-defined]
    db.add(FspSyncAttempt(user_id=user_id, identity_id=identity.id, trigger="manual",
                          started_at=clock.real_now() - timedelta(seconds=5)))  # fmt: skip
    db.commit()
    assert client.get(LINK).json()["history_status"] == "sync_pending"


def test_minor_notice_is_one_shot(
    db: Session, user_client: tuple[TestClient, UUID], freeze_now: Callable[..., object]
) -> None:
    client, user_id = user_client
    athlete = mockdata.add_athlete(db)
    service.seed_link(db, user_id, str(athlete))
    db.commit()
    registry_athlete = db.get(Athlete, athlete)
    assert registry_athlete is not None
    registry_athlete.birth_date = mockdata.TODAY.replace(year=mockdata.TODAY.year - 15)
    db.commit()
    freeze_now.tick(hours=1)  # type: ignore[attr-defined]
    view = client.post(LINK.replace("link", "sync")).json()
    assert view["status"] == "not_linked" and view["notice"] == "unlinked_minor"


def test_keycloak_mode_start_is_503(
    user_client: tuple[TestClient, UUID], override_settings: Callable[..., object]
) -> None:
    override_settings(fsp_mode="keycloak")
    client, _ = user_client
    response = client.post(f"{LINK}/start", json={"accept": True, "consent_version": "fsp-data-1"})
    assert response.status_code == 503 and response.json()["code"] == "fsp_unavailable"


def test_resync_script_runs(
    db: Session, make_user: Callable[..., object], freeze_now: Callable[..., object], capsys: pytest.CaptureFixture[str]
) -> None:
    athlete = mockdata.add_athlete(db)
    service.seed_link(db, make_user("candidate").id, str(athlete))  # type: ignore[attr-defined]
    db.commit()
    freeze_now.tick(hours=200)  # type: ignore[attr-defined]
    assert fsp_resync.main(["--older-than-hours", "168", "--limit", "10", "--pause", "0"]) == 0
    assert "ok_unchanged: 1" in capsys.readouterr().out


def test_init_step_seeds_once(db: Session) -> None:
    generator.seed_if_empty()
    first = db.scalar(select(Athlete.fsp_id).where(Athlete.persona_key == "anna"))
    assert first is not None
    generator.seed_if_empty()  # повтор ничего не меняет
    assert db.scalar(select(Athlete.fsp_id).where(Athlete.persona_key == "anna")) == first
