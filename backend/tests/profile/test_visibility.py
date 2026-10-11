"""Состояние показа (четыре состояния, автопауза по сроку), публикация и ручная пауза (Арх. 6.1, 9.6, 10.5)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.profile import service
from app.modules.profile.models import CandidateProfile
from app.shared.enums import PauseReason, VisibilityState
from tests.profile.conftest import Candidate, publication_version

CONSENT = "/api/v1/candidate/consents"
PUBLICATION = "/api/v1/candidate/consents/publication"
VISIBILITY = "/api/v1/candidate/visibility"


def test_four_states(db: Session, make_candidate: Callable[..., Candidate], now: datetime) -> None:
    not_ready = make_candidate(category=False)
    unpublished = make_candidate()
    visible = make_candidate(published=True)
    paused = make_candidate(published=True)
    row = db.get(CandidateProfile, paused.id)
    assert row is not None
    row.paused_at = now
    db.flush()
    states = {
        name: service.visibility(db, c.id, now)
        for name, c in (("nr", not_ready), ("un", unpublished), ("vi", visible), ("pa", paused))
    }
    assert states["nr"].state == VisibilityState.NOT_READY
    assert states["un"].state == VisibilityState.UNPUBLISHED
    assert states["vi"].state == VisibilityState.VISIBLE and states["vi"].pause_reason is None
    assert states["pa"].state == VisibilityState.PAUSED and states["pa"].pause_reason == PauseReason.MANUAL


def test_not_ready_wins_over_consent(
    db: Session, make_candidate: Callable[..., Candidate], now: datetime, world: Any
) -> None:
    candidate = make_candidate(published=True)
    world.categories.discard(candidate.id)  # категорию отняли (например, сброс результатов)
    assert service.visibility(db, candidate.id, now).state == VisibilityState.NOT_READY


def test_auto_pause_expires_without_a_write(
    db: Session, make_candidate: Callable[..., Candidate], now: datetime
) -> None:
    candidate = make_candidate(published=True)
    until = now + timedelta(days=1)
    service.set_auto_pause(db, candidate.id, now, until)
    during = service.visibility(db, candidate.id, now + timedelta(hours=1))
    assert during.state == VisibilityState.PAUSED
    assert during.pause_reason == PauseReason.AUTO_SILENCE and during.auto_paused_until == until
    row = db.get(CandidateProfile, candidate.id)
    assert row is not None
    snapshot = (row.auto_paused_at, row.auto_paused_until, row.updated_at)
    after = service.visibility(db, candidate.id, until + timedelta(seconds=1))
    assert after.state == VisibilityState.VISIBLE and after.auto_paused_until is None
    db.refresh(row)
    assert (row.auto_paused_at, row.auto_paused_until, row.updated_at) == snapshot  # срок снят чтением, без записи
    assert service.auto_pause_until(db, candidate.id) == until


def test_manual_and_auto_pause_report_auto(
    db: Session, make_candidate: Callable[..., Candidate], now: datetime
) -> None:
    candidate = make_candidate(published=True)
    row = db.get(CandidateProfile, candidate.id)
    assert row is not None
    row.paused_at = now
    service.set_auto_pause(db, candidate.id, now, now + timedelta(days=2))
    state = service.visibility(db, candidate.id, now + timedelta(hours=1))
    assert state.pause_reason == PauseReason.AUTO_SILENCE
    service.clear_auto_pause(db, candidate.id)
    assert service.visibility(db, candidate.id, now).pause_reason == PauseReason.MANUAL
    assert service.auto_pause_until(db, candidate.id) is None


def test_publication_conflicts(
    client: TestClient, login_as: Callable[..., Any], db: Session, make_candidate: Callable[..., Candidate]
) -> None:
    no_category = make_candidate(category=False)
    login_as(no_category)
    response = client.post(PUBLICATION, json={"action": "grant", "version": publication_version()})
    assert (response.status_code, response.json()["code"]) == (409, "no_category")

    empty = make_candidate(filled=False)
    login_as(empty)
    response = client.post(PUBLICATION, json={"action": "grant", "version": publication_version()})
    assert (response.status_code, response.json()["code"]) == (409, "profile_incomplete")

    ready = make_candidate()
    login_as(ready)
    response = client.post(PUBLICATION, json={"action": "grant", "version": "устаревшая"})
    assert (response.status_code, response.json()["code"]) == (409, "consent_version_outdated")


def test_grant_and_revoke_publication(
    client: TestClient, login_as: Callable[..., Any], make_candidate: Callable[..., Candidate]
) -> None:
    candidate = make_candidate()
    login_as(candidate)
    granted = client.post(PUBLICATION, json={"action": "grant", "version": publication_version()})
    assert granted.status_code == 200 and granted.json()["state"] == "visible"
    view = client.get(CONSENT).json()
    assert view["publication"]["granted"] is True and view["publication"]["version"] == publication_version()
    assert view["publication"]["current_version"] == publication_version()
    assert view["visibility"]["state"] == "visible" and view["fsp_data"] is None
    revoked = client.post(PUBLICATION, json={"action": "revoke", "version": publication_version()})
    assert revoked.json()["state"] == "unpublished"
    assert client.get(CONSENT).json()["publication"]["granted"] is False


def test_declared_category_allows_publication(
    client: TestClient, login_as: Callable[..., Any], make_candidate: Callable[..., Candidate], world: Any
) -> None:
    """Заявленный грейд (тест по специализации готовится) — тоже категория: профиль можно опубликовать."""
    candidate = make_candidate(category=False)
    world.declared.add(candidate.id)
    login_as(candidate)
    granted = client.post(PUBLICATION, json={"action": "grant", "version": publication_version()})
    assert granted.status_code == 200 and granted.json()["state"] == "visible"


def test_manual_pause_roundtrip(
    client: TestClient, login_as: Callable[..., Any], make_candidate: Callable[..., Candidate]
) -> None:
    candidate = make_candidate(published=True)
    login_as(candidate)
    paused = client.post(VISIBILITY, json={"state": "paused"}).json()
    assert paused == {"state": "paused", "pause_reason": "manual", "auto_paused_until": None}
    assert client.post(VISIBILITY, json={"state": "visible"}).json()["state"] == "visible"


def test_pause_requires_publication_consent(
    client: TestClient, login_as: Callable[..., Any], make_candidate: Callable[..., Candidate]
) -> None:
    candidate = make_candidate()
    login_as(candidate)
    response = client.post(VISIBILITY, json={"state": "paused"})
    assert (response.status_code, response.json()["code"]) == (409, "publication_consent_required")
