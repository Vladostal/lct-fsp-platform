"""Вход, выход, лимиты входа, адрес клиента, смена и сброс пароля (Арх. 10.1, 10.2)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.identity import accounts
from app.modules.identity.models import AuthSession
from tests.identity.conftest import PASSWORD, link_token, mails_of, session_count

URL = "/api/v1/auth"


@pytest.fixture(autouse=True)
def _roomy_signup_limit(override_settings):
    override_settings(signup_ip_limit_per_hour=100)


def login(client, email, password=PASSWORD, **kwargs):
    return client.post(f"{URL}/login", json={"email": email, "password": password}, **kwargs)


def test_login_success_and_me(client, make_user, db: Session):
    user = make_user(email="in@example.com", password=PASSWORD)
    response = login(client, "In@Example.com")
    assert response.status_code == 200
    assert response.json()["id"] == str(user.id) and "sid" in response.cookies
    assert client.get(f"{URL}/me").json()["email"] == "in@example.com"
    assert session_count(db, user.id) == 1


def test_wrong_password_is_logged_and_does_not_reveal(client, make_user, attempts):
    make_user(email="known@example.com")
    wrong = login(client, "known@example.com", "Wrong-password-1")
    unknown = login(client, "unknown@example.com", "Wrong-password-1")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() and wrong.json()["code"] == "invalid_credentials"
    # Неудача пережила ответ 401: ошибка зафиксировала запись (`commit=True`).
    assert [row.ok for row in attempts("login")] == [False, False]


def test_password_is_checked_before_verification(make_client, signup, make_user, mailbox):
    """Неподтверждённый адрес: неверный пароль — 401, верный — 403 `email_not_verified` (Арх. 10.1)."""
    browser = make_client()
    signup("pending@example.com", via=browser)
    other = make_client()
    assert login(other, "pending@example.com", "Wrong-password-1").status_code == 401
    forbidden = login(other, "pending@example.com")
    assert forbidden.status_code == 403 and forbidden.json()["code"] == "email_not_verified"


def test_login_lockout_per_address(client, make_user, monkeypatch):
    monkeypatch.setattr(accounts, "LOGIN_MAX_FAILURES_PER_EMAIL", 3)
    make_user(email="lock@example.com")
    for _ in range(3):
        assert login(client, "lock@example.com", "Wrong-password-1").status_code == 401
    blocked = login(client, "lock@example.com", PASSWORD)  # даже верный пароль не принимается
    assert blocked.status_code == 429 and blocked.json()["code"] == "rate_limited"
    assert blocked.json()["params"]["retry_after"] >= 1
    assert login(client, "other@example.com", "x").status_code == 401  # другой адрес не затронут


def test_login_lockout_per_ip_uses_real_ip_header(make_client, make_user, monkeypatch):
    monkeypatch.setattr(accounts, "LOGIN_MAX_FAILURES_PER_IP", 2)
    make_user(email="ipuser@example.com")
    trusted = make_client(client=("172.28.5.2", 40000))
    hit = {"X-Real-IP": "203.0.113.10"}
    for n in range(2):
        assert login(trusted, f"nobody{n}@example.com", "x", headers=hit).status_code == 401
    assert login(trusted, "ipuser@example.com", PASSWORD, headers=hit).status_code == 429
    # Тот же клиент, но другой адрес из заголовка — свой счётчик.
    assert login(trusted, "ipuser@example.com", PASSWORD, headers={"X-Real-IP": "203.0.113.11"}).status_code == 200


def test_client_ip_header_trusted_only_from_proxy_network(make_client, make_user, attempts):
    make_user(email="who@example.com")
    trusted = make_client(client=("172.28.5.2", 40000))
    login(trusted, "who@example.com", "bad", headers={"X-Real-IP": "203.0.113.20"})
    outsider = make_client(client=("198.51.100.4", 40000))
    login(outsider, "who@example.com", "bad", headers={"X-Real-IP": "203.0.113.21"})
    assert [row.ip for row in attempts("login")] == ["203.0.113.20", "198.51.100.4"]


def test_logout_deletes_session(client, make_user, db: Session):
    user = make_user()
    login(client, user.email)
    assert session_count(db, user.id) == 1
    assert client.post(f"{URL}/logout").status_code == 204
    assert session_count(db, user.id) == 0
    assert client.get(f"{URL}/me").status_code == 401


def test_logout_requires_session(client):
    assert client.post(f"{URL}/logout").status_code == 401


def test_change_password(make_client, make_user, db: Session):
    user = make_user(email="chg@example.com")
    here, there = make_client(), make_client()
    login(here, user.email)
    login(there, user.email)
    assert session_count(db, user.id) == 2

    wrong = here.post(
        f"{URL}/password", json={"current_password": "Wrong-password-1", "new_password": "Brand-new-pass-1"}
    )
    assert wrong.status_code == 422 and wrong.json()["code"] == "current_password_invalid"
    assert [item["name"] for item in wrong.json()["fields"]] == ["current_password"]

    short = here.post(f"{URL}/password", json={"current_password": PASSWORD, "new_password": "short"})
    assert short.status_code == 422 and short.json()["fields"][0]["name"] == "new_password"

    ok = here.post(f"{URL}/password", json={"current_password": PASSWORD, "new_password": "Brand-new-pass-1"})
    assert ok.status_code == 204
    assert session_count(db, user.id) == 1  # остальные сессии удалены
    assert here.get(f"{URL}/me").status_code == 200
    assert there.get(f"{URL}/me").status_code == 401
    fresh = make_client()
    assert login(fresh, user.email).status_code == 401
    assert login(fresh, user.email, "Brand-new-pass-1").status_code == 200


def test_demo_account_cannot_change_password(client, make_user, login_as):
    demo = make_user(email="demo-anna@example.com", is_demo=True)
    login_as(demo)
    response = client.post(f"{URL}/password", json={"current_password": PASSWORD, "new_password": "Brand-new-pass-1"})
    assert response.status_code == 403 and response.json()["code"] == "demo_account_readonly"


def test_password_check_failures_are_limited(client, make_user, login_as, monkeypatch):
    monkeypatch.setattr(accounts, "PASSWORD_CHECK_MAX_FAILURES", 2)
    login_as(make_user())
    body = {"current_password": "Wrong-password-1", "new_password": "Brand-new-pass-1"}
    assert [client.post(f"{URL}/password", json=body).status_code for _ in range(2)] == [422, 422]
    assert client.post(f"{URL}/password", json=body).status_code == 429


def test_forgot_and_reset_password(make_client, make_user, mailbox, db: Session, freeze_now):
    user = make_user(email="forgot@example.com")
    signed_in = make_client()
    login(signed_in, user.email)

    anon = make_client()
    for email in ("forgot@example.com", "nobody@example.com"):
        assert anon.post(f"{URL}/password/forgot", json={"email": email}).status_code == 202
    (letter,) = mails_of(mailbox, "password_reset")
    assert letter.to == "forgot@example.com"
    token = link_token(letter)

    reset = anon.post(f"{URL}/password/reset", json={"token": token, "new_password": "Reset-pass-12345"})
    assert reset.status_code == 204
    assert session_count(db, user.id) == 0 and signed_in.get(f"{URL}/me").status_code == 401
    again = anon.post(f"{URL}/password/reset", json={"token": token, "new_password": "Reset-pass-67890"})
    assert again.status_code == 400 and again.json()["code"] == "token_invalid"
    assert login(anon, user.email, PASSWORD).status_code == 401
    assert login(anon, user.email, "Reset-pass-12345").status_code == 200


def test_reset_token_expires(client, make_user, mailbox, freeze_now):
    make_user(email="exp@example.com")
    client.post(f"{URL}/password/forgot", json={"email": "exp@example.com"})
    token = link_token(mailbox[0])
    freeze_now.tick(hours=2)
    response = client.post(f"{URL}/password/reset", json={"token": token, "new_password": "Reset-pass-12345"})
    assert response.status_code == 400 and response.json()["code"] == "token_expired"


def test_forgot_sends_only_to_confirmed_non_demo(client, make_user, mailbox):
    make_user(email="unconfirmed@example.com", verified=False)
    make_user(email="demo-x@example.com", is_demo=True)
    for email in ("unconfirmed@example.com", "demo-x@example.com"):
        assert client.post(f"{URL}/password/forgot", json={"email": email}).status_code == 202
    assert mailbox == []


def test_forgot_three_per_hour(client, make_user, mailbox, freeze_now):
    make_user(email="spam@example.com")
    for _ in range(5):
        assert client.post(f"{URL}/password/forgot", json={"email": "spam@example.com"}).status_code == 202
        freeze_now.tick(seconds=1)
    assert len(mails_of(mailbox, "password_reset")) == 3


def test_reset_for_demo_is_refused(client, make_user, db: Session):
    from app.modules.identity import service

    demo = make_user(email="demo-y@example.com", is_demo=True)
    # Токен демо-аккаунту выдать нельзя через API; проверка на случай ручного токена.
    assert service.demo_user_ids(db) == [demo.id]
    assert db.scalar(select(AuthSession.id)) is None
