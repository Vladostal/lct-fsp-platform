"""T4. Привязка ФСП ID через API: успех, отмена, чужой и отсутствующий `state`, истёкшая попытка, повтор callback,
конфликты, гонка, несовершеннолетний, нет записи спортсмена, недоступный реестр, лимит попыток, роли."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import clock
from app.fsp_mock import reference as ref
from app.fsp_mock import registry_service
from app.fsp_mock.models import AccessGrant
from app.modules.fsp import linking
from app.modules.fsp.models import (
    ExternalIdentity,
    FspAchievement,
    FspLinkAttempt,
    FspSnapshot,
    FspSyncAttempt,
)
from app.modules.identity import service as identity_service
from app.modules.identity.models import AuditEvent
from app.shared.enums import ConsentKind
from tests.fsp import mockdata
from tests.fsp.conftest import Flow


def result_of(location: str) -> dict[str, str]:
    parts = urlsplit(location)
    assert parts.path == "/candidate/settings/fsp"
    return {key: values[0] for key, values in parse_qs(parts.query).items()}


def audit_codes(db: Session) -> list[str]:
    return list(db.scalars(select(AuditEvent.code).order_by(AuditEvent.id)))


def set_failure_mode(mode: str) -> None:
    with registry_service.registry_session() as session:
        registry_service.set_failure_mode(session, mode)


def test_link_success(flow: Flow, client: TestClient, db: Session, athlete: UUID) -> None:
    location = flow.run(athlete)
    assert result_of(location) == {"result": "linked"}
    view = client.get("/api/v1/fsp/link").json()
    assert view["status"] == "linked" and view["provider_mode"] == "mock"
    assert view["history_status"] == "has_history" and view["no_history_reason"] is None
    assert view["subject_hint"] == "…" + str(athlete)[-4:]
    assert view["consent"]["version"] == "fsp-data-1"
    assert len(view["achievements"]) == 1 and view["achievements"][0]["counted"] is True
    assert view["achievements"][0]["place_label"] == "1 место из 40"
    assert view["signal"]["band"] in {"medium", "high"}
    assert view["refresh"]["last_outcome"] == "ok_changed" and view["refresh"]["source_label"].startswith("Источник")
    assert view["employer_preview"]["level"] in (1, 2, 3)
    identity = db.scalars(select(ExternalIdentity)).one()
    assert identity.issuer == "urn:fsp-mock" and identity.subject == str(athlete) == identity.fsp_id
    assert set(identity.claims) <= {"iss", "sub", "fsp_id"}
    grant = db.get(AccessGrant, (athlete, ref.CLIENT_ID))
    assert grant is not None and grant.source == "oidc" and grant.revoked_at is None
    attempt = db.scalars(select(FspLinkAttempt)).one()
    assert attempt.used_at is not None and attempt.code_verifier == "" and attempt.outcome == "linked"
    assert len(attempt.state_hash) == 64
    codes = audit_codes(db)
    assert "fsp.linked" in codes and "consent_granted" in codes
    consent = identity_service.consents(db, identity.user_id)[ConsentKind.FSP_DATA]
    assert consent.revoked_at is None and consent.version == "fsp-data-1"


def test_callback_headers_and_payload_has_no_region(flow: Flow, db: Session, athlete: UUID) -> None:
    redirect = flow.authorize(flow.start(), athlete)
    response = flow.callback(redirect.headers["location"])
    assert response.status_code == 302
    assert response.headers["Cache-Control"] == "no-store" and response.headers["Referrer-Policy"] == "no-referrer"
    snapshot = db.scalars(select(FspSnapshot)).one()
    assert snapshot.is_current and snapshot.athlete_registered and snapshot.participations_count == 1
    assert "region_code" not in str(snapshot.payload) and "birth" not in str(snapshot.payload)
    assert snapshot.source == "mock" and snapshot.api_version == "1.0.0" and snapshot.etag


def test_cancelled(flow: Flow, db: Session, athlete: UUID) -> None:
    location = flow.run(athlete, decision="deny")
    assert result_of(location) == {"result": "cancelled"}
    assert db.scalar(select(func.count()).select_from(ExternalIdentity)) == 0
    assert db.scalars(select(FspLinkAttempt)).one().outcome == "cancelled"


def test_foreign_state_other_user_in_session(
    flow: Flow,
    make_client: Callable[..., TestClient],
    make_user: Callable[..., object],
    login_as: Callable[..., TestClient],
    db: Session,
    athlete: UUID,
) -> None:
    redirect = flow.authorize(flow.start(), athlete)
    other = login_as(make_user("candidate"), make_client())
    response = Flow(other).callback(redirect.headers["location"])
    assert result_of(response.headers["location"]) == {"result": "error", "reason": "state"}
    assert "fsp.link.user_mismatch" in audit_codes(db)
    assert db.scalar(select(func.count()).select_from(ExternalIdentity)) == 0
    assert db.scalars(select(FspLinkAttempt)).one().used_at is None  # владелец попытки может завершить поток
    owner = flow.callback(redirect.headers["location"])
    assert result_of(owner.headers["location"]) == {"result": "linked"}


@pytest.mark.parametrize("path", ["/api/v1/fsp/link/callback", "/api/v1/fsp/link/callback?state=nope&code=x"])
def test_missing_or_unknown_state(client: TestClient, flow: Flow, path: str) -> None:
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 302
    assert result_of(response.headers["location"]) == {"result": "error", "reason": "state"}


def test_without_session_redirects_to_login_and_keeps_attempt(
    flow: Flow, make_client: Callable[..., TestClient], db: Session, athlete: UUID
) -> None:
    redirect = flow.authorize(flow.start(), athlete)
    anonymous = make_client()
    parts = urlsplit(redirect.headers["location"])
    response = anonymous.get(f"{parts.path}?{parts.query}", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login?next=%2Fcandidate%2Fsettings%2Ffsp"
    assert db.scalars(select(FspLinkAttempt)).one().used_at is None


def test_expired_attempt(flow: Flow, freeze_now: Callable[..., object], athlete: UUID) -> None:
    redirect = flow.authorize(flow.start(), athlete)
    freeze_now.tick(minutes=11)  # type: ignore[attr-defined]
    response = flow.callback(redirect.headers["location"])
    assert result_of(response.headers["location"]) == {"result": "error", "reason": "expired"}


def test_repeated_callback(flow: Flow, db: Session, athlete: UUID) -> None:
    redirect = flow.authorize(flow.start(), athlete)
    first = flow.callback(redirect.headers["location"])
    second = flow.callback(redirect.headers["location"])
    assert result_of(first.headers["location"]) == result_of(second.headers["location"]) == {"result": "linked"}
    assert db.scalar(select(func.count()).select_from(ExternalIdentity)) == 1
    assert db.scalar(select(func.count()).select_from(FspSnapshot)) == 1


def test_repeated_callback_after_cancel_is_expired(flow: Flow, athlete: UUID) -> None:
    redirect = flow.authorize(flow.start(), athlete, decision="deny")
    flow.callback(redirect.headers["location"])
    again = flow.callback(redirect.headers["location"])
    assert result_of(again.headers["location"]) == {"result": "error", "reason": "expired"}


def second_user_flow(
    make_client: Callable[..., TestClient], make_user: Callable[..., object], login_as: Callable[..., TestClient]
) -> Flow:
    return Flow(login_as(make_user("candidate"), make_client()))


def test_conflict_by_subject(
    flow: Flow,
    make_client: Callable[..., TestClient],
    make_user: Callable[..., object],
    login_as: Callable[..., TestClient],
    db: Session,
    athlete: UUID,
) -> None:
    assert result_of(flow.run(athlete)) == {"result": "linked"}
    other = second_user_flow(make_client, make_user, login_as)
    assert result_of(other.run(athlete)) == {"result": "already_linked"}
    assert db.scalar(select(func.count()).select_from(ExternalIdentity)) == 1
    assert "fsp.link.conflict" in audit_codes(db)
    # данные реестра для второго аккаунта не запрашивались и не сохранялись
    assert db.scalar(select(func.count()).select_from(FspAchievement)) == 1
    view = other.client.get("/api/v1/fsp/link").json()
    assert view["status"] == "not_linked" and view["achievements"] == []


def test_conflict_by_fsp_id_with_other_subject(
    flow: Flow,
    make_client: Callable[..., TestClient],
    make_user: Callable[..., object],
    login_as: Callable[..., TestClient],
    db: Session,
    athlete: UUID,
) -> None:
    """Две учётные записи ФСП ID, указывающие на одного спортсмена, — тоже конфликт."""
    owner = make_user("candidate")
    db.add(
        ExternalIdentity(
            user_id=owner.id,  # type: ignore[attr-defined]
            provider="fsp",
            issuer="urn:fsp-mock",
            subject="another-subject",
            fsp_id=str(athlete),
            provider_mode="mock",
            claims={},
            consent_version="fsp-data-1",
            linked_at=clock.real_now(),
        )
    )
    db.commit()
    other = second_user_flow(make_client, make_user, login_as)
    assert result_of(other.run(athlete)) == {"result": "already_linked"}


def test_race_of_two_accounts_ends_in_already_linked(
    flow: Flow,
    make_client: Callable[..., TestClient],
    make_user: Callable[..., object],
    login_as: Callable[..., TestClient],
    db: Session,
    athlete: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Проверка конфликта пропустила второй аккаунт (гонка): уникальность в базе даёт `already_linked`, а не 500."""
    assert result_of(flow.run(athlete)) == {"result": "linked"}
    other = second_user_flow(make_client, make_user, login_as)
    monkeypatch.setattr(linking, "_conflict", lambda *args, **kwargs: False)
    assert result_of(other.run(athlete)) == {"result": "already_linked"}
    assert db.scalar(select(func.count()).select_from(ExternalIdentity)) == 1
    assert db.scalar(select(func.count()).select_from(FspAchievement)) == 1


def test_minor_creates_nothing_and_revokes(flow: Flow, client: TestClient, db: Session, candidate: object) -> None:
    minor = mockdata.add_athlete(db, birth=mockdata.TODAY.replace(year=mockdata.TODAY.year - 15))
    mockdata.add_result(db, minor, place=1)
    db.commit()
    user_id = candidate.id  # type: ignore[attr-defined]
    text = identity_service.current_consent(ConsentKind.PUBLICATION)
    identity_service.grant_consent(
        db, user_id, ConsentKind.PUBLICATION, text.version, text.sha256, "user", clock.real_now()
    )
    assert user_id in identity_service.publication_consent_active(db, [user_id])
    assert result_of(flow.run(minor)) == {"result": "minor"}
    assert db.scalar(select(func.count()).select_from(ExternalIdentity)) == 0
    assert db.scalar(select(func.count()).select_from(FspAchievement)) == 0
    assert db.scalar(select(func.count()).select_from(FspSnapshot)) == 0
    grant = db.get(AccessGrant, (minor, ref.CLIENT_ID))
    assert grant is not None and grant.revoked_at is not None  # разрешение в реестре снято
    # поправка R3-data-api-security-3: согласие на публикацию отозвано, событие аудита без персональных данных
    assert user_id not in identity_service.publication_consent_active(db, [user_id])
    event = db.scalars(select(AuditEvent).where(AuditEvent.code == "fsp.minor_detected")).one()
    assert event.params == {} and event.target_user_id == user_id


def test_no_athlete_record_links_without_history(flow: Flow, client: TestClient, db: Session) -> None:
    location = flow.run(None, pick="new_account")
    assert result_of(location) == {"result": "linked"}
    view = client.get("/api/v1/fsp/link").json()
    assert view["status"] == "linked" and view["history_status"] == "no_history"
    assert view["no_history_reason"] == "athlete_not_found" and view["achievements"] == []
    assert view["signal"]["band"] == "none" and view["employer_preview"] is None
    snapshot = db.scalars(select(FspSnapshot)).one()
    assert snapshot.athlete_registered is False and snapshot.payload == {}


def test_registry_unavailable_at_link(
    flow: Flow, client: TestClient, db: Session, athlete: UUID, freeze_now: Callable[..., object]
) -> None:
    set_failure_mode("unavailable")
    assert result_of(flow.run(athlete)) == {"result": "linked"}
    view = client.get("/api/v1/fsp/link").json()
    assert view["status"] == "linked" and view["history_status"] == "sync_failed"
    assert view["refresh"]["last_outcome"] == "failed_unavailable" and view["achievements"] == []
    assert db.scalar(select(func.count()).select_from(FspSnapshot)) == 0
    # разрешение выдано в потоке входа: «Повторить» не отвязывает кандидата
    set_failure_mode("none")
    freeze_now.tick(seconds=5)  # type: ignore[attr-defined]
    retry = client.post("/api/v1/fsp/sync")
    assert retry.status_code == 200
    assert retry.json()["history_status"] == "has_history" and retry.json()["refresh"]["last_outcome"] == "ok_changed"


def test_contract_error_at_link(flow: Flow, client: TestClient, athlete: UUID) -> None:
    set_failure_mode("malformed")
    assert result_of(flow.run(athlete)) == {"result": "linked"}
    view = client.get("/api/v1/fsp/link").json()
    assert view["history_status"] == "sync_failed" and view["refresh"]["last_outcome"] == "failed_contract"


def test_attempt_limit(flow: Flow, client: TestClient, freeze_now: Callable[..., object]) -> None:
    for _ in range(5):
        flow.start()
    sixth = client.post("/api/v1/fsp/link/start", json={"accept": True, "consent_version": "fsp-data-1"})
    assert sixth.status_code == 429 and sixth.json()["code"] == "fsp_too_many_attempts"
    assert sixth.json()["params"]["retry_after"] >= 1
    freeze_now.tick(minutes=11)  # type: ignore[attr-defined]
    assert (
        client.post("/api/v1/fsp/link/start", json={"accept": True, "consent_version": "fsp-data-1"}).status_code == 200
    )


def test_new_start_supersedes_previous_attempt(flow: Flow, db: Session, athlete: UUID) -> None:
    first = flow.start()
    flow.start()
    attempts = db.scalars(select(FspLinkAttempt).order_by(FspLinkAttempt.created_at)).all()
    assert [item.outcome for item in attempts] == ["superseded", None]
    redirect = flow.authorize(first, athlete)
    response = flow.callback(redirect.headers["location"])
    assert result_of(response.headers["location"]) == {"result": "error", "reason": "expired"}


def test_start_validation_and_exists(flow: Flow, client: TestClient, athlete: UUID) -> None:
    refused = client.post("/api/v1/fsp/link/start", json={"accept": False, "consent_version": "fsp-data-1"})
    assert refused.status_code == 422 and refused.json()["code"] == "fsp_consent_required"
    outdated = client.post("/api/v1/fsp/link/start", json={"accept": True, "consent_version": "fsp-data-0"})
    assert outdated.status_code == 409 and outdated.json()["code"] == "fsp_consent_outdated"
    assert outdated.json()["params"]["version"] == "fsp-data-1"
    assert client.post("/api/v1/fsp/link/start", json={}).status_code == 422
    flow.run(athlete)
    exists = client.post("/api/v1/fsp/link/start", json={"accept": True, "consent_version": "fsp-data-1"})
    assert exists.status_code == 409 and exists.json()["code"] == "fsp_link_exists"


def test_authorize_url_uses_settings_redirect_and_pkce(flow: Flow) -> None:
    query = parse_qs(urlsplit(flow.start()).query)
    assert query["redirect_uri"] == ["http://localhost:8080/api/v1/fsp/link/callback"]
    assert query["code_challenge_method"] == ["S256"] and len(query["state"][0]) >= 43
    assert query["scope"] == ["openid fsp.achievements.read"] and query["client_id"] == [ref.CLIENT_ID]


def test_consent_endpoint(client: TestClient, candidate: object) -> None:
    body = client.get("/api/v1/fsp/consent").json()
    assert body["version"] == "fsp-data-1" and len(body["text_sha256"]) == 64
    assert "судейск" not in body["text"] and "сборн" not in body["text"]
    assert set(body["data_items"]) == {"competition", "result", "team", "team_role", "rank"}


def test_unlink_removes_everything_and_is_idempotent(
    flow: Flow, client: TestClient, db: Session, athlete: UUID
) -> None:
    flow.run(athlete)
    user_id = db.scalars(select(ExternalIdentity.user_id)).one()
    assert client.delete("/api/v1/fsp/link").status_code == 204
    for model in (ExternalIdentity, FspAchievement, FspSnapshot, FspSyncAttempt, FspLinkAttempt):
        assert db.scalar(select(func.count()).select_from(model)) == 0, model
    consent = identity_service.consents(db, user_id)[ConsentKind.FSP_DATA]
    assert consent.revoked_at is not None  # запись остаётся как доказательство
    grant = db.get(AccessGrant, (athlete, ref.CLIENT_ID))
    assert grant is not None and grant.revoked_at is not None
    assert client.delete("/api/v1/fsp/link").status_code == 204
    view = client.get("/api/v1/fsp/link").json()
    assert view["status"] == "not_linked" and view["notice"] is None
    assert result_of(flow.run(athlete)) == {"result": "linked"}  # ФСП ID свободен сразу


def test_roles_and_authentication(
    client: TestClient,
    make_client: Callable[..., TestClient],
    make_user: Callable[..., object],
    login_as: Callable[..., TestClient],
) -> None:
    employer = login_as(make_user("employer"), make_client())
    calls = [
        ("get", "/api/v1/fsp/consent"),
        ("get", "/api/v1/fsp/link"),
        ("post", "/api/v1/fsp/link/start"),
        ("post", "/api/v1/fsp/sync"),
        ("delete", "/api/v1/fsp/link"),
        ("get", "/api/v1/fsp/calendar"),
    ]
    anonymous = make_client()
    for method, path in calls:
        kwargs = (
            {"json": {"accept": True, "consent_version": "fsp-data-1"}} if method == "post" and "start" in path else {}
        )
        assert getattr(employer, method)(path, **kwargs).status_code == 403, path
        assert getattr(anonymous, method)(path, **kwargs).status_code == 401, path
    response = employer.get("/api/v1/fsp/link/callback?state=x", follow_redirects=False)
    assert response.status_code == 302 and "reason=state" in response.headers["location"]


def test_sync_when_not_linked_is_404(client: TestClient, candidate: object) -> None:
    response = client.post("/api/v1/fsp/sync")
    assert response.status_code == 404 and response.json()["code"] == "fsp_not_linked"
