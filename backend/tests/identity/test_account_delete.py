"""Удаление аккаунта, карантин адреса, демо-аккаунт (Арх. 10.5)."""

from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import wiring
from app.modules.identity import emails
from app.modules.identity.models import (
    AppUser,
    AuditEvent,
    AuthSession,
    Consent,
    EmailToken,
    LoginAttempt,
)
from tests.identity.conftest import PASSWORD, find_user, link_token, mails_of

URL = "/api/v1/auth"


@pytest.fixture(autouse=True)
def _roomy_signup_limit(override_settings):
    override_settings(signup_ip_limit_per_hour=100)


def register(make_client, signup, mailbox, email, password=PASSWORD):
    browser = make_client()
    signup(email, password, via=browser)
    token = link_token(mails_of(mailbox, "verify_email", email)[-1])
    response = browser.post(f"{URL}/verify-email", json={"token": token})
    assert response.status_code == 200
    return browser, response.json()["id"]


def test_delete_wrong_password(client, make_user, login_as, db: Session):
    user = make_user()
    login_as(user)
    response = client.post(f"{URL}/account/delete", json={"password": "Wrong-password-1"})
    assert response.status_code == 422 and response.json()["code"] == "current_password_invalid"
    assert [item["name"] for item in response.json()["fields"]] == ["password"]
    assert db.get(AppUser, user.id) is not None


def test_delete_runs_handlers_audits_consents_and_removes_rows(make_client, signup, mailbox, db: Session, monkeypatch):
    calls: list[object] = []
    monkeypatch.setattr(wiring, "user_cleanup_handlers", lambda *a, **k: [lambda session, uid: calls.append(uid)])
    browser, user_id = register(make_client, signup, mailbox, "bye@example.com")
    consent = db.scalar(select(Consent).where(Consent.user_id == user_id))
    assert consent is not None
    version, digest = consent.version, consent.text_sha256

    response = browser.post(f"{URL}/account/delete", json={"password": PASSWORD})
    assert response.status_code == 204
    assert [str(item) for item in calls] == [user_id]
    db.expire_all()
    assert find_user(db, "bye@example.com") is None
    for model in (AuthSession, EmailToken, Consent):
        assert db.scalar(select(model.id).where(model.user_id == user_id)) is None
    assert browser.get(f"{URL}/me").status_code == 401

    event = db.scalar(select(AuditEvent).where(AuditEvent.code == "consents_at_deletion"))
    assert event is not None and str(event.target_user_id) == user_id
    (item,) = event.params["consents"]
    assert (item["kind"], item["version"], item["text_sha256"]) == ("processing", version, digest)
    assert item["granted_at"] and item["revoked_at"]
    assert "bye@example.com" not in str(event.params)  # персональных данных в записи нет

    marker = db.scalar(select(LoginAttempt).where(LoginAttempt.kind == "account_deleted"))
    assert marker is not None and marker.ip is None
    assert marker.email_sha256 == emails.email_hash("bye@example.com")
    assert marker.email_sha256 != hashlib.sha256(b"bye@example.com").hexdigest()  # хэш с ключом, не простой SHA-256


def test_failing_cleanup_handler_does_not_block_deletion(make_client, signup, mailbox, db: Session, monkeypatch):
    def broken(session, uid):
        raise RuntimeError("реестр недоступен")

    monkeypatch.setattr(wiring, "user_cleanup_handlers", lambda *a, **k: [broken])
    browser, _ = register(make_client, signup, mailbox, "reg-down@example.com")
    assert browser.post(f"{URL}/account/delete", json={"password": PASSWORD}).status_code == 204
    db.expire_all()
    assert find_user(db, "reg-down@example.com") is None
    event = db.scalar(select(AuditEvent).where(AuditEvent.code == "consents_at_deletion"))
    assert event is not None and event.params["cleanup_failed"]


def test_quarantine_blocks_reregistration_then_expires(make_client, signup, mailbox, db: Session, freeze_now):
    browser, _ = register(make_client, signup, mailbox, "again@example.com")
    assert browser.post(f"{URL}/account/delete", json={"password": PASSWORD}).status_code == 204
    mailbox.clear()

    freeze_now.tick(minutes=5)
    response = signup("again@example.com")
    assert response.status_code == 202
    assert find_user(db, "again@example.com") is None  # аккаунт не создан
    (letter,) = mails_of(mailbox, "reregister_cooldown")
    assert letter.to == "again@example.com" and letter.context["available_at"]
    assert not mails_of(mailbox, "verify_email")

    # Алиас того же ящика карантин не обходит (поправка R3-mechanics-recheck-2).
    signup("again+1@example.com")
    assert find_user(db, "again+1@example.com") is None
    gmail_dotted = make_client()
    signup("a.b.c@gmail.com", via=gmail_dotted)
    assert find_user(db, "a.b.c@gmail.com") is not None  # без удаления карантина нет

    freeze_now.tick(days=31)
    signup("again@example.com")
    assert find_user(db, "again@example.com") is not None
    assert mails_of(mailbox, "verify_email", "again@example.com")


def test_quarantine_uses_configured_cooldown(make_client, signup, mailbox, db: Session, override_settings, freeze_now):
    override_settings(reregister_cooldown_days=0.007)  # около 10 минут, как на стенде
    browser, _ = register(make_client, signup, mailbox, "short@example.com")
    browser.post(f"{URL}/account/delete", json={"password": PASSWORD})
    signup("short@example.com")
    assert find_user(db, "short@example.com") is None
    freeze_now.tick(minutes=11)
    signup("short@example.com")
    assert find_user(db, "short@example.com") is not None


def test_demo_account_readonly(client, make_user, login_as, mailbox, db: Session):
    demo = make_user(email="demo-z@example.com", is_demo=True)
    login_as(demo)
    deleted = client.post(f"{URL}/account/delete", json={"password": PASSWORD})
    assert deleted.status_code == 403 and deleted.json()["code"] == "demo_account_readonly"
    changed = client.post(f"{URL}/password", json={"current_password": PASSWORD, "new_password": "Brand-new-pass-1"})
    assert changed.status_code == 403 and changed.json()["code"] == "demo_account_readonly"
    forgot = client.post(f"{URL}/password/forgot", json={"email": "demo-z@example.com"})
    assert forgot.status_code == 202 and mailbox == []
    assert db.get(AppUser, demo.id) is not None


def test_delete_requires_session(client):
    assert client.post(f"{URL}/account/delete", json={"password": PASSWORD}).status_code == 401


def test_deleting_demo_account_via_facade_leaves_no_quarantine(db: Session):
    from app.modules.identity import service
    from app.shared.enums import Role

    uid = service.create_user(
        db, "demo-k@example.com", PASSWORD, Role.CANDIDATE, verified=True, is_demo=True, demo_key="k"
    )
    service.delete_user(db, uid)
    assert db.get(AppUser, uid) is None
    assert db.scalar(select(LoginAttempt.id).where(LoginAttempt.kind == "account_deleted")) is None
