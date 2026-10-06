"""Эндпоинты `/demo/*` (Арх. 9.10, 13.5): вход «как…» и перезапуск сценария."""

from __future__ import annotations

from sqlalchemy import func, select

from app.core import db as core_db
from app.modules.contact.models import Invitation
from app.modules.identity import service as identity
from app.modules.identity.models import AppUser
from app.modules.matching.models import ShortlistSnapshot
from app.shared.enums import Role
from tests.seed.support import ADMIN, API, World


def _ids() -> dict[str, str]:
    with core_db.session_scope() as db:
        rows = db.execute(
            select(AppUser.demo_key, AppUser.id).where(
                AppUser.demo_key.in_(["orbita", "anna", "dmitry", "ivan", "gleb", "boris", "olga", "maria", "petr"])
            )
        ).all()
    return {key: str(uid) for key, uid in rows}


def test_login_as_opens_session_for_named_accounts(seeded: World) -> None:
    anonymous = seeded.client()
    listed = anonymous.get(f"{API}/demo/accounts")
    assert listed.status_code == 200
    assert {"orbita", "anna", "dmitry", "gleb", "petr"} <= {row["key"] for row in listed.json()}
    assert "nina" not in {row["key"] for row in listed.json()}

    candidate = seeded.login("anna")
    me = candidate.get(f"{API}/auth/me").json()
    assert me["role"] == "candidate" and me["is_demo"] is True and me["email"] == "anna@demo.test"
    invitations = candidate.get(f"{API}/candidate/invitations").json()["items"]
    assert [item["status"] for item in invitations] == ["sent"]

    employer = seeded.login("orbita")
    assert employer.get(f"{API}/auth/me").json()["role"] == "employer"
    assert len(employer.get(f"{API}/employer/needs").json()) == 1
    assert seeded.client().post(f"{API}/demo/login", json={"account_key": "nobody"}).status_code == 404
    assert seeded.client().post(f"{API}/demo/login", json={"account_key": "nina"}).status_code == 404


def test_scenario_restart_recreates_named_candidates_and_keeps_orbita(seeded: World, override_settings) -> None:
    url = f"{API}/demo/scenario/restart"
    before = _ids()
    with core_db.session_scope() as db:
        population = db.scalar(select(func.count()).select_from(AppUser).where(AppUser.demo_key.like("cand\\_%")))
        accepted = db.scalar(
            select(func.count())
            .select_from(Invitation)
            .where(Invitation.employer_id == before["orbita"], Invitation.status == "accepted")
        )
        snapshots = db.scalar(
            select(func.count()).select_from(ShortlistSnapshot).where(ShortlistSnapshot.employer_id == before["orbita"])
        )
        live = identity.create_user(
            db,
            "live.candidate@example.com",
            "Live-pass-2026",
            Role.CANDIDATE,
            verified=True,
            is_demo=False,
            demo_key=None,
        )
        live_token = identity.create_session(db, live)

    assert seeded.client().post(url).status_code == 401
    live_client = seeded.client()
    live_client.cookies.set("sid", live_token)
    assert live_client.post(url).status_code == 403

    anna = seeded.login("anna")
    restarted = anna.post(url)
    assert restarted.status_code == 200 and "restarted_at" in restarted.json(), restarted.text
    after = _ids()
    assert after["orbita"] == before["orbita"]
    assert all(after[key] != before[key] for key in before if key != "orbita")
    assert anna.get(f"{API}/auth/me").status_code == 401  # сессия пересозданного аккаунта закрыта
    with core_db.session_scope() as db:
        assert (
            db.scalar(select(func.count()).select_from(AppUser).where(AppUser.demo_key.like("cand\\_%"))) == population
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(Invitation)
                .where(Invitation.employer_id == after["orbita"], Invitation.status == "accepted")
            )
            == accepted
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(ShortlistSnapshot)
                .where(ShortlistSnapshot.employer_id == after["orbita"])
            )
            == snapshots + 1
        )
        fresh = db.scalars(select(Invitation.status).where(Invitation.candidate_id == after["gleb"])).all()
        assert sorted(fresh) == ["expired", "sent"]
        assert db.scalars(select(Invitation.status).where(Invitation.candidate_id == after["dmitry"])).all() == [
            "bounced"
        ]

    # второй вызов посетителя сразу после первого — 429 с retry_after; ведущему лимиты не мешают
    again = seeded.login("orbita").post(url)
    assert again.status_code == 429 and again.json()["params"]["retry_after"] > 0
    assert seeded.client().post(url, headers=ADMIN).status_code == 200

    override_settings(demo_public_restart=False)
    assert seeded.login("orbita").post(url).status_code == 403
    assert seeded.client().post(url, headers=ADMIN).status_code == 200
