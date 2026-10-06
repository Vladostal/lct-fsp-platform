"""T6. Синхронизация: идемпотентность, 304, изменившийся ответ, сбои не меняют данные, отзыв разрешения, параллельный
запуск, ограничение частоты; привязка для сида; удаление аккаунта."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import ApiException
from app.fsp_mock import reference as ref
from app.fsp_mock import registry_service
from app.fsp_mock.models import AccessGrant, Athlete
from app.fsp_mock.personas import persona_fsp_id
from app.modules.fsp import linking, service, sync
from app.modules.fsp.gateway import factory
from app.modules.fsp.gateway.base import ExportNotModified, FspUnavailable
from app.modules.fsp.models import (
    ExternalIdentity,
    FspAchievement,
    FspCredential,
    FspSnapshot,
    FspSyncAttempt,
)
from app.modules.identity import service as identity_service
from app.modules.identity.models import AuditEvent
from app.shared.enums import ConsentKind
from tests.fsp import mockdata


@pytest.fixture
def linked(db: Session, make_user: Callable[..., object], athlete: UUID) -> UUID:
    """Кандидат, привязанный к спортсмену с результатом и разрядом (тот же код, что у сида)."""
    mockdata.add_rank(db, athlete, "kms")
    user = make_user("candidate")
    service.seed_link(db, user.id, str(athlete))  # type: ignore[attr-defined]
    db.commit()
    return user.id  # type: ignore[attr-defined]


def failure(mode: str) -> None:
    with registry_service.registry_session() as session:
        registry_service.set_failure_mode(session, mode)


def snapshot_count(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(FspSnapshot)) or 0)


def fact_ids(db: Session) -> set[UUID]:
    return set(db.scalars(select(FspAchievement.id)))


def test_seed_link_creates_link_like_the_flow(db: Session, linked: UUID, athlete: UUID) -> None:
    identity = db.scalars(select(ExternalIdentity)).one()
    assert identity.issuer == "urn:fsp-mock" and identity.subject == str(athlete)
    consent = identity_service.consents(db, linked)[ConsentKind.FSP_DATA]
    assert consent.revoked_at is None
    grant = db.get(AccessGrant, (athlete, ref.CLIENT_ID))
    assert grant is not None and grant.source == "seed"
    assert db.scalar(select(func.count()).select_from(FspAchievement)) == 1
    assert db.scalar(select(func.count()).select_from(FspCredential)) == 1
    attempt = db.scalars(select(FspSyncAttempt)).one()
    assert attempt.trigger == "seed" and attempt.outcome == "ok_changed"
    service.seed_link(db, linked, str(athlete))  # повтор безопасен
    assert db.scalar(select(func.count()).select_from(ExternalIdentity)) == 1
    with pytest.raises(ValueError):
        service.seed_link(db, linked, "00000000-0000-0000-0000-000000000001")


def test_resync_is_idempotent_and_uses_etag(db: Session, linked: UUID, freeze_now: Callable[..., object]) -> None:
    before = fact_ids(db)
    snapshot = db.scalars(select(FspSnapshot)).one()
    checked = snapshot.checked_at
    freeze_now.tick(hours=1)  # type: ignore[attr-defined]
    result = sync.run_sync(db, linked, "manual")
    assert result.outcome == "ok_unchanged"  # 304: ETag совпал
    db.refresh(snapshot)
    assert snapshot.checked_at > checked and snapshot.fetched_at == checked
    assert fact_ids(db) == before and snapshot_count(db) == 1


def test_same_body_without_etag_is_unchanged(db: Session, linked: UUID, freeze_now: Callable[..., object]) -> None:
    """Реестр без ETag отдал то же тело: хэш совпал, факты и их идентификаторы не изменились."""
    before = fact_ids(db)
    snapshot = db.scalars(select(FspSnapshot)).one()
    snapshot.etag = None
    db.commit()
    freeze_now.tick(hours=1)  # type: ignore[attr-defined]
    assert sync.run_sync(db, linked, "stale").outcome == "ok_unchanged"
    assert fact_ids(db) == before and snapshot_count(db) == 1


def test_changed_answer_creates_snapshot_and_keeps_ids(
    db: Session, linked: UUID, athlete: UUID, freeze_now: Callable[..., object]
) -> None:
    old = fact_ids(db)
    mockdata.add_result(db, athlete, title="Кубок", place=2, entries_count=16, days_ago=10)
    db.commit()
    freeze_now.tick(hours=1)  # type: ignore[attr-defined]
    assert sync.run_sync(db, linked, "stale").outcome == "ok_changed"
    new = fact_ids(db)
    assert old < new and len(new) == 2  # прежний факт сохранил идентификатор
    assert snapshot_count(db) == 2
    assert db.scalar(select(func.count()).select_from(FspSnapshot).where(FspSnapshot.is_current.is_(True))) == 1
    # хранятся два последних снимка
    mockdata.add_result(db, athlete, title="Ещё", place=5, days_ago=5)
    db.commit()
    freeze_now.tick(hours=1)  # type: ignore[attr-defined]
    assert sync.run_sync(db, linked, "stale").outcome == "ok_changed"
    assert snapshot_count(db) == 2 and len(fact_ids(db)) == 3


@pytest.mark.parametrize(
    ("mode", "outcome"),
    [("unavailable", "failed_unavailable"), ("malformed", "failed_contract"), ("slow", "failed_unavailable")],
)
def test_failures_do_not_change_data(
    db: Session, linked: UUID, mode: str, outcome: str, freeze_now: Callable[..., object]
) -> None:
    before = fact_ids(db)
    snapshot_before = db.scalars(select(FspSnapshot)).one().checked_at
    failure(mode)
    freeze_now.tick(hours=1)  # type: ignore[attr-defined]
    assert sync.run_sync(db, linked, "stale").outcome == outcome
    assert fact_ids(db) == before
    assert db.scalars(select(FspSnapshot)).one().checked_at == snapshot_before
    last = db.scalars(select(FspSyncAttempt).order_by(FspSyncAttempt.started_at.desc())).first()
    assert last is not None and last.outcome == outcome and last.finished_at is not None and last.error_code
    assert db.scalar(select(func.count()).select_from(ExternalIdentity)) == 1  # привязка сохраняется


def test_revoked_grant_unlinks_with_notice(
    db: Session, client: TestClient, linked: UUID, athlete: UUID, login_as: Callable[..., TestClient]
) -> None:
    with registry_service.registry_session() as session:
        registry_service.revoke_grant(session, athlete, ref.CLIENT_ID, clock.real_now())
    assert sync.run_sync(db, linked, "stale").outcome == "unlinked_revoked"
    for model in (ExternalIdentity, FspAchievement, FspCredential, FspSnapshot):
        assert db.scalar(select(func.count()).select_from(model)) == 0
    notice = db.scalars(select(FspSyncAttempt)).one()
    assert notice.identity_id is None and notice.outcome == "unlinked_revoked"
    assert identity_service.consents(db, linked)[ConsentKind.FSP_DATA].revoked_at is not None
    assert "fsp.unlinked" in set(db.scalars(select(AuditEvent.code)))


def test_notice_is_shown_on_screen_and_removed_on_next_start(
    db: Session,
    client: TestClient,
    make_user: Callable[..., object],
    login_as: Callable[..., TestClient],
    athlete: UUID,
) -> None:
    user = make_user("candidate")
    login_as(user)
    service.seed_link(db, user.id, str(athlete))  # type: ignore[attr-defined]
    with registry_service.registry_session() as session:
        registry_service.revoke_grant(session, athlete, ref.CLIENT_ID, clock.real_now())
    assert client.post("/api/v1/fsp/sync").status_code == 200
    view = client.get("/api/v1/fsp/link").json()
    assert view["status"] == "not_linked" and view["notice"] == "unlinked_revoked"
    assert (
        client.post("/api/v1/fsp/link/start", json={"accept": True, "consent_version": "fsp-data-1"}).status_code == 200
    )
    assert client.get("/api/v1/fsp/link").json()["notice"] is None


def test_minor_in_sync_unlinks_and_hides_profile(
    db: Session, make_user: Callable[..., object], freeze_now: Callable[..., object]
) -> None:
    athlete = mockdata.add_athlete(db)
    mockdata.add_result(db, athlete)
    user = make_user("candidate")
    uid = user.id  # type: ignore[attr-defined]
    text = identity_service.current_consent(ConsentKind.PUBLICATION)
    identity_service.grant_consent(
        db, uid, ConsentKind.PUBLICATION, text.version, text.sha256, "user", clock.real_now()
    )
    service.seed_link(db, uid, str(athlete))  # взрослый на момент привязки
    db.commit()
    registry_athlete = db.get(Athlete, athlete)
    assert registry_athlete is not None
    registry_athlete.birth_date = mockdata.TODAY.replace(year=mockdata.TODAY.year - 16)  # реестр исправил дату
    db.commit()
    freeze_now.tick(hours=1)  # type: ignore[attr-defined]
    assert sync.run_sync(db, uid, "manual").outcome == "unlinked_minor"
    assert db.scalar(select(func.count()).select_from(FspAchievement)) == 0
    assert uid not in identity_service.publication_consent_active(db, [uid])
    assert db.scalars(select(FspSyncAttempt)).one().outcome == "unlinked_minor"


def test_manual_sync_rate_limit(db: Session, linked: UUID, freeze_now: Callable[..., object]) -> None:
    freeze_now.tick(hours=1)  # type: ignore[attr-defined]
    assert sync.run_sync(db, linked, "manual").outcome == "ok_unchanged"
    with pytest.raises(ApiException) as error:
        sync.run_sync(db, linked, "manual")
    assert error.value.status == 429 and error.value.code == "fsp_sync_too_frequent"
    assert 1 <= int(error.value.params["retry_after"]) <= 60  # type: ignore[index]
    freeze_now.tick(seconds=61)  # type: ignore[attr-defined]
    assert sync.run_sync(db, linked, "manual").outcome == "ok_unchanged"


def test_manual_sync_api_rate_limit(
    db: Session,
    client: TestClient,
    make_user: Callable[..., object],
    login_as: Callable[..., TestClient],
    athlete: UUID,
    freeze_now: Callable[..., object],
) -> None:
    user = make_user("candidate")
    login_as(user)
    service.seed_link(db, user.id, str(athlete))  # type: ignore[attr-defined]
    freeze_now.tick(seconds=5)  # type: ignore[attr-defined]
    first = client.post("/api/v1/fsp/sync")
    assert first.status_code == 200 and first.json()["refresh"]["last_outcome"] == "ok_unchanged"
    assert first.json()["refresh"]["can_sync_at"] is not None
    second = client.post("/api/v1/fsp/sync")
    assert second.status_code == 429 and second.json()["code"] == "fsp_sync_too_frequent"
    assert second.json()["params"]["retry_after"] >= 1


def test_parallel_run_is_in_progress(db: Session, linked: UUID) -> None:
    identity = db.scalars(select(ExternalIdentity)).one()
    db.add(FspSyncAttempt(user_id=linked, identity_id=identity.id, trigger="manual", started_at=clock.real_now()))
    db.commit()
    assert sync.run_sync(db, linked, "stale").outcome == "in_progress"


def test_stuck_attempt_is_closed_by_timeout(db: Session, linked: UUID) -> None:
    identity = db.scalars(select(ExternalIdentity)).one()
    stuck = FspSyncAttempt(
        user_id=linked,
        identity_id=identity.id,
        trigger="manual",
        started_at=clock.real_now() - timedelta(seconds=45),
    )
    db.add(stuck)
    db.commit()
    assert sync.run_sync(db, linked, "stale").outcome == "ok_unchanged"
    db.refresh(stuck)
    assert stuck.outcome == "failed_timeout" and stuck.finished_at is not None


def test_not_linked_raises(db: Session, make_user: Callable[..., object]) -> None:
    with pytest.raises(sync.NotLinked):
        sync.run_sync(db, make_user("candidate").id, "stale")  # type: ignore[attr-defined]


def test_only_twenty_attempts_are_kept(db: Session, linked: UUID, freeze_now: Callable[..., object]) -> None:
    for _ in range(25):
        freeze_now.tick(minutes=11)  # type: ignore[attr-defined]
        sync.run_sync(db, linked, "stale")
    assert db.scalar(select(func.count()).select_from(FspSyncAttempt)) == 20


def test_resync_batch(db: Session, linked: UUID, freeze_now: Callable[..., object]) -> None:
    assert service.resync_batch(db, older_than_hours=1, limit=10, pause_s=0) == {}
    freeze_now.tick(hours=170)  # type: ignore[attr-defined]
    outcomes = service.resync_batch(db, older_than_hours=168, limit=10, pause_s=0)
    assert outcomes == {"ok_unchanged": 1}


def test_unlink_reasons(db: Session, linked: UUID, athlete: UUID) -> None:
    service.unlink(db, linked, reason="demo_reset")
    db.commit()
    assert db.scalar(select(func.count()).select_from(ExternalIdentity)) == 0
    assert db.scalar(select(func.count()).select_from(FspSyncAttempt)) == 0  # уведомления только для revoked и minor
    grant = db.get(AccessGrant, (athlete, ref.CLIENT_ID))
    assert grant is not None and grant.revoked_at is not None
    service.unlink(db, linked, reason="user")  # привязки нет: ничего не происходит


def test_account_deletion_with_unavailable_registry(
    db: Session, make_user: Callable[..., object], athlete: UUID
) -> None:
    """Недоступный реестр удаление аккаунта не блокирует; строки модуля уходят в той же транзакции."""
    user = make_user("candidate")
    service.seed_link(db, user.id, str(athlete))  # type: ignore[attr-defined]
    db.commit()
    failure("unavailable")
    assert identity_service.remove_user(db, user.id)  # type: ignore[attr-defined]
    db.commit()
    for model in (ExternalIdentity, FspAchievement, FspSnapshot, FspSyncAttempt):
        assert db.scalar(select(func.count()).select_from(model)) == 0
    grant = db.get(AccessGrant, (athlete, ref.CLIENT_ID))
    assert grant is not None and grant.revoked_at is None  # разрешение «повисло»: реестр недоступен


def test_account_deletion_revokes_grant(db: Session, make_user: Callable[..., object], athlete: UUID) -> None:
    user = make_user("candidate")
    service.seed_link(db, user.id, str(athlete))  # type: ignore[attr-defined]
    db.commit()
    assert identity_service.remove_user(db, user.id)  # type: ignore[attr-defined]
    db.commit()
    grant = db.get(AccessGrant, (athlete, ref.CLIENT_ID))
    assert grant is not None and grant.revoked_at is not None


def test_gateway_etag_not_modified_directly(db: Session, linked: UUID, athlete: UUID) -> None:
    gateway = factory.get_fsp_gateway()
    snapshot = db.scalars(select(FspSnapshot)).one()
    assert isinstance(gateway.fetch_export(str(athlete), etag=snapshot.etag), ExportNotModified)
    failure("unavailable")
    with pytest.raises(FspUnavailable):
        gateway.fetch_export(str(athlete))
    assert gateway.health() is False
    failure("none")
    assert gateway.health() is True


def test_link_module_not_confused_with_helper(db: Session) -> None:
    assert linking.mask_fsp_id("0123456789abcdef") == "…cdef"


def test_demo_pool_for_seed(db: Session, make_user: Callable[..., object]) -> None:
    """Сид не импортирует демо-реестр: пул свободных взрослых и ключи персонажей он берёт из фасада."""
    taken = mockdata.add_athlete(db)
    mockdata.add_result(db, taken, place=1)
    free = mockdata.add_athlete(db)
    mockdata.add_result(db, free, place=2)
    empty = mockdata.add_athlete(db)
    minor = mockdata.add_athlete(db, birth=mockdata.TODAY.replace(year=mockdata.TODAY.year - 16))
    mockdata.add_result(db, minor, place=3)
    service.seed_link(db, make_user("candidate").id, str(taken))  # type: ignore[attr-defined]
    db.commit()
    with_history = {item.fsp_id for item in service.demo_athlete_pool(with_history=True)}
    assert with_history == {str(free)}
    assert str(empty) in {item.fsp_id for item in service.demo_athlete_pool(with_history=False)}
    assert str(minor) not in with_history
    assert service.demo_persona_id("anna") == str(persona_fsp_id("anna"))
