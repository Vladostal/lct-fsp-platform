"""Контракт реестра (HTTP): доступ, разрешения, ETag, ошибки, режим отказа, ручки ведущего."""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core import clock
from app.fsp_mock import reference as ref
from app.fsp_mock import registry_service
from app.fsp_mock.models import AccessGrant
from tests.fsp import mockdata

BASE = "/api/fsp-mock/registry/v1"


def grant(db: Session, fsp_id: UUID, *, revoked: bool = False) -> None:
    now = clock.real_now()
    db.add(
        AccessGrant(
            fsp_id=fsp_id,
            client_id=ref.CLIENT_ID,
            scope=ref.SCOPE,
            source="oidc",
            granted_at=now,
            revoked_at=now if revoked else None,
        )
    )
    db.commit()


def test_open_endpoints_without_token(client: TestClient, athlete: UUID) -> None:
    assert client.get(f"{BASE}/health").json()["status"] == "ok"
    response = client.get(f"{BASE}/health")
    assert response.headers["X-Registry-Version"] == ref.REGISTRY_VERSION
    dictionaries = client.get(f"{BASE}/dictionaries").json()
    assert {item["code"] for item in dictionaries["disciplines"]} == set(ref.DISCIPLINES)
    assert dictionaries["ranks"][0]["code"] == "msmk"


def test_export_forbidden_without_admin_token(client: TestClient, athlete: UUID) -> None:
    """R3 и R4 при FSPMOCK_AUTH=none принимают только X-Admin-Token (Арх. 7.11)."""
    for response in (
        client.get(f"{BASE}/athletes/{athlete}/export"),
        client.delete(f"{BASE}/athletes/{athlete}/grant"),
    ):
        assert response.status_code == 403
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["code"] == "insufficient_scope"


def test_admin_router_forbidden_without_token(client: TestClient, athlete: UUID) -> None:
    for method, path, body in (
        ("post", "/api/fsp-mock/admin/control", {"failure_mode": "none"}),
        ("post", f"/api/fsp-mock/admin/athletes/{athlete}/participations", {"competition_id": "x", "place": 1}),
        ("post", f"/api/fsp-mock/admin/athletes/{athlete}/grant/revoke", None),
        ("post", "/api/fsp-mock/admin/reset", None),
    ):
        response = getattr(client, method)(path, json=body) if body else getattr(client, method)(path)
        assert response.status_code == 403, path
        wrong = getattr(client, method)(path, headers={"X-Admin-Token": "wrong"}, **({"json": body} if body else {}))
        assert wrong.status_code == 403, path


def test_export_requires_grant_and_has_no_personal_data(
    client: TestClient, db: Session, admin: dict[str, str], athlete: UUID
) -> None:
    response = client.get(f"{BASE}/athletes/{athlete}/export", headers=admin)
    assert response.status_code == 403 and response.json()["code"] == "grant_required"
    grant(db, athlete)
    response = client.get(f"{BASE}/athletes/{athlete}/export", headers=admin)
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "1.0"
    assert body["athlete"]["is_adult"] is True and body["athlete"]["fsp_id"] == str(athlete)
    assert len(body["participations"]) == 1 and len(body["ranks"]) == 1
    text = response.text
    for forbidden in ("Фамилиев", "Имярек", "Отчествович", "birth", "last_name", "1999", "gender"):
        assert forbidden not in text
    assert body["judge"] is None and body["national_team"] == [] and body["rating"] is None
    assert body["participations"][0]["norm"] is None
    assert response.headers["ETag"].strip('"') == registry_service.etag_of(body)


def test_etag_and_not_modified(client: TestClient, db: Session, admin: dict[str, str], athlete: UUID) -> None:
    grant(db, athlete)
    first = client.get(f"{BASE}/athletes/{athlete}/export", headers=admin)
    etag = first.headers["ETag"]
    again = client.get(f"{BASE}/athletes/{athlete}/export", headers={**admin, "If-None-Match": etag})
    assert again.status_code == 304 and again.content == b""
    mockdata.add_result(db, athlete, title="Другое соревнование", place=2)
    db.commit()
    changed = client.get(f"{BASE}/athletes/{athlete}/export", headers={**admin, "If-None-Match": etag})
    assert changed.status_code == 200


def test_revoked_grant_and_r4_idempotent(client: TestClient, db: Session, admin: dict[str, str], athlete: UUID) -> None:
    grant(db, athlete, revoked=True)
    response = client.get(f"{BASE}/athletes/{athlete}/export", headers=admin)
    assert response.status_code == 403 and response.json()["code"] == "grant_revoked"
    grant_row = db.get(AccessGrant, (athlete, ref.CLIENT_ID))
    assert grant_row is not None
    grant_row.revoked_at = None
    db.commit()
    assert client.delete(f"{BASE}/athletes/{athlete}/grant", headers=admin).status_code == 204
    assert client.delete(f"{BASE}/athletes/{athlete}/grant", headers=admin).status_code == 204
    assert client.get(f"{BASE}/athletes/{athlete}/export", headers=admin).json()["code"] == "grant_revoked"


def test_unknown_athlete_and_validation(client: TestClient, db: Session, admin: dict[str, str]) -> None:
    ghost = uuid4()
    grant(db, ghost)
    response = client.get(f"{BASE}/athletes/{ghost}/export", headers=admin)
    assert response.status_code == 404 and response.json()["code"] == "athlete_not_found"
    bad = client.get(f"{BASE}/athletes/not-a-uuid/export", headers=admin)
    assert bad.status_code == 422 and bad.json()["code"] == "validation_error"
    assert bad.headers["content-type"].startswith("application/problem+json")
    assert client.get(f"{BASE}/competitions/nope").json()["code"] == "competition_not_found"
    assert client.get(f"{BASE}/competitions?limit=0").status_code == 422


def test_minor_flag_without_birth_date(client: TestClient, db: Session, admin: dict[str, str]) -> None:
    minor = mockdata.add_athlete(db, birth=mockdata.TODAY.replace(year=mockdata.TODAY.year - 16))
    grant(db, minor)
    body = client.get(f"{BASE}/athletes/{minor}/export", headers=admin).json()
    assert body["athlete"]["is_adult"] is False


def test_competitions_filters_and_cursor(client: TestClient, db: Session) -> None:
    ids = [
        mockdata.add_competition(
            db, f"UP-{i}", status="registration_open", start_in_days=10 + i, protocol_status="none"
        )
        for i in range(3)
    ]
    mockdata.add_competition(db, "OLD", days_ago=100)
    db.commit()
    page = client.get(f"{BASE}/competitions?status=registration_open&limit=2").json()
    assert [item["competition_id"] for item in page["items"]] == ids[:2] and page["next_cursor"]
    rest = client.get(f"{BASE}/competitions?status=registration_open&limit=2&cursor={page['next_cursor']}").json()
    assert [item["competition_id"] for item in rest["items"]] == ids[2:] and rest["next_cursor"] is None
    assert client.get(f"{BASE}/competitions/OLD").json()["status"] == "finished"
    assert client.get(f"{BASE}/competitions?discipline=robotics").json()["items"] == []


def test_failure_modes(client: TestClient, db: Session, admin: dict[str, str], athlete: UUID) -> None:
    grant(db, athlete)
    response = client.post("/api/fsp-mock/admin/control", json={"failure_mode": "unavailable"}, headers=admin)
    assert response.json() == {"failure_mode": "unavailable"}
    down = client.get(f"{BASE}/athletes/{athlete}/export", headers=admin)
    assert down.status_code == 503 and down.json()["code"] == "registry_unavailable" and "Retry-After" in down.headers
    assert client.get(f"{BASE}/health").status_code == 503
    client.post("/api/fsp-mock/admin/control", json={"failure_mode": "malformed"}, headers=admin)
    malformed = client.get(f"{BASE}/athletes/{athlete}/export", headers=admin)
    assert malformed.status_code == 200 and malformed.headers["content-type"].startswith("text/html")
    assert client.post("/api/fsp-mock/admin/control", json={"failure_mode": "bogus"}, headers=admin).status_code == 422
    client.post("/api/fsp-mock/admin/control", json={"failure_mode": "none"}, headers=admin)
    assert client.get(f"{BASE}/athletes/{athlete}/export", headers=admin).status_code == 200


def test_admin_add_participation_and_revoke(
    client: TestClient, db: Session, admin: dict[str, str], athlete: UUID
) -> None:
    grant(db, athlete)
    competition = mockdata.add_competition(db, title="Новое соревнование", entries_count=20)
    db.commit()
    before = len(client.get(f"{BASE}/athletes/{athlete}/export", headers=admin).json()["participations"])
    added = client.post(
        f"/api/fsp-mock/admin/athletes/{athlete}/participations",
        json={"competition_id": competition, "place": 3},
        headers=admin,
    )
    assert added.status_code == 201 and added.json()["place"] == 3
    after = client.get(f"{BASE}/athletes/{athlete}/export", headers=admin).json()["participations"]
    assert len(after) == before + 1
    missing = client.post(
        f"/api/fsp-mock/admin/athletes/{uuid4()}/participations",
        json={"competition_id": competition, "place": 3},
        headers=admin,
    )
    assert missing.status_code == 404
    revoke = client.post(f"/api/fsp-mock/admin/athletes/{athlete}/grant/revoke", headers=admin)
    assert revoke.status_code == 204
    assert client.get(f"{BASE}/athletes/{athlete}/export", headers=admin).json()["code"] == "grant_revoked"


def test_anonymity_counters(client: TestClient, db: Session, admin: dict[str, str], athlete: UUID) -> None:
    """Счётчики анонимности считает реестр: k_b — те же (дисциплина, tier), k_a — ещё и период, корзина."""
    for place in (2, 3, 25):
        mockdata.add_result(db, mockdata.add_athlete(db), place=place, entries_count=40, title=f"Соревнование {place}")
    db.commit()
    grant(db, athlete)
    body = client.get(f"{BASE}/athletes/{athlete}/export", headers=admin).json()
    anonymity = body["participations"][0]["anonymity"]
    assert anonymity["period"] == "recent"
    assert anonymity["k_b"] == 4 and anonymity["k_a"] == 3  # три призёра: 1, 2, 3 места; 25-е — «верхняя половина» нет
