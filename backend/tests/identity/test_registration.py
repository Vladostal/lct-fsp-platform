"""Регистрация, подтверждение адреса, заявки, лимиты писем (Арх. 10.1, 10.2; B00b, приёмка)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.identity.models import AppUser, Consent, EmailToken
from tests.identity.conftest import PASSWORD, find_user, link_token, live_tokens, mails_of, signup_body

URL = "/api/v1/auth"


@pytest.fixture(autouse=True)
def _roomy_signup_limit(override_settings):
    override_settings(signup_ip_limit_per_hour=100)


def test_signup_verify_me_logout(client, signup, mailbox, db: Session):
    response = signup("Anna@Example.com", role="candidate")
    assert response.status_code == 202
    assert response.content == b""
    assert "reg" in response.cookies  # браузер регистрации привязан к заявке
    (letter,) = mails_of(mailbox, "verify_email")
    assert letter.to == "anna@example.com"

    user = find_user(db, "anna@example.com")
    assert user is not None and user.email_verified_at is None and user.password_hash is None
    assert db.scalar(select(Consent).where(Consent.user_id == user.id)) is None  # согласия до подтверждения нет

    verified = client.post(f"{URL}/verify-email", json={"token": link_token(letter)})
    assert verified.status_code == 200
    body = verified.json()
    assert body["email"] == "anna@example.com" and body["role"] == "candidate" and body["is_demo"] is False
    assert "sid" in verified.cookies

    me = client.get(f"{URL}/me")
    assert me.status_code == 200 and me.json()["id"] == body["id"]
    db.refresh(user)
    assert user.is_adult_confirmed and user.password_hash
    consent = db.scalar(select(Consent).where(Consent.user_id == user.id))
    assert consent is not None and consent.source == "user" and consent.revoked_at is None

    assert client.post(f"{URL}/logout").status_code == 204
    assert client.get(f"{URL}/me").status_code == 401


def test_token_cannot_be_reused(client, signup, mailbox):
    signup("reuse@example.com")
    token = link_token(mails_of(mailbox, "verify_email")[0])
    assert client.post(f"{URL}/verify-email", json={"token": token}).status_code == 200
    again = client.post(f"{URL}/verify-email", json={"token": token})
    assert again.status_code == 400 and again.json()["code"] == "token_invalid"
    unknown = client.post(f"{URL}/verify-email", json={"token": "nope"})
    assert unknown.status_code == 400 and unknown.json()["code"] == "token_invalid"


def test_expired_token(client, signup, mailbox, freeze_now):
    signup("late@example.com")
    token = link_token(mails_of(mailbox, "verify_email")[0])
    freeze_now.tick(hours=25)
    response = client.post(f"{URL}/verify-email", json={"token": token})
    assert response.status_code == 400 and response.json()["code"] == "token_expired"


def test_taken_address_answers_the_same(client, signup, mailbox, make_user):
    make_user(email="taken@example.com")
    fresh = signup("fresh@example.com")
    taken = signup("taken@example.com")
    assert taken.status_code == fresh.status_code == 202
    assert taken.content == fresh.content
    assert sorted(taken.cookies.keys()) == sorted(fresh.cookies.keys())
    assert [m.template for m in mailbox] == ["verify_email", "already_registered"]
    assert mailbox[1].to == "taken@example.com"


def test_other_browser_needs_password(client, make_client, signup, mailbox, db: Session):
    signup("away@example.com")
    token = link_token(mails_of(mailbox, "verify_email")[0])
    other = make_client()  # ссылку открыли в браузере без cookie регистрации
    needed = other.post(f"{URL}/verify-email", json={"token": token})
    assert needed.status_code == 409 and needed.json()["code"] == "password_required"
    wrong = other.post(f"{URL}/verify-email", json={"token": token, "password": "Wrong-password-1"})
    assert wrong.status_code == 401 and wrong.json()["code"] == "invalid_credentials"
    assert find_user(db, "away@example.com").email_verified_at is None  # type: ignore[union-attr]
    ok = other.post(f"{URL}/verify-email", json={"token": token, "password": PASSWORD})
    assert ok.status_code == 200 and "sid" in ok.cookies


def test_applications_do_not_overwrite_each_other(make_client, signup, mailbox, db: Session, freeze_now):
    """Две заявки на один неподтверждённый адрес: каждая со своим паролем и ролью (Арх. 10.1, поправка 61)."""
    victim, intruder = make_client(), make_client()
    signup("shared@example.com", "Intruder-pass-1", "candidate", via=intruder)
    freeze_now.tick(seconds=61)
    signup("shared@example.com", "Owner-pass-1234", "employer", via=victim)
    first, second = mails_of(mailbox, "verify_email")
    assert live_tokens(db, find_user(db, "shared@example.com").id) == 2  # type: ignore[union-attr]

    # Чужая заявка без cookie регистрации и без своего пароля подтверждение не проходит.
    stranger = make_client()
    assert stranger.post(f"{URL}/verify-email", json={"token": link_token(first)}).status_code == 409
    wrong = stranger.post(f"{URL}/verify-email", json={"token": link_token(first), "password": "Owner-pass-1234"})
    assert wrong.status_code == 401

    # Владелец открывает свою ссылку: аккаунт получает пароль и роль его заявки.
    opened = victim.post(f"{URL}/verify-email", json={"token": link_token(second)})
    assert opened.status_code == 200 and opened.json()["role"] == "employer"
    assert live_tokens(db, opened.json()["id"]) == 0  # остальные токены погашены
    again = intruder.post(f"{URL}/verify-email", json={"token": link_token(first)})
    assert again.status_code == 400 and again.json()["code"] == "token_invalid"

    fresh = make_client()
    assert (
        fresh.post(f"{URL}/login", json={"email": "shared@example.com", "password": "Intruder-pass-1"}).status_code
        == 401
    )
    assert (
        fresh.post(f"{URL}/login", json={"email": "shared@example.com", "password": "Owner-pass-1234"}).status_code
        == 200
    )


def test_consent_comes_from_the_opened_application(make_client, signup, mailbox, db: Session, freeze_now):
    """Согласие и 18+ берутся из заявки, чью ссылку открыли (поправка R3-data-api-security-2)."""
    first_browser, second_browser = make_client(), make_client()
    signup("consent@example.com", "First-pass-1234", via=first_browser)
    freeze_now.tick(seconds=61)
    signup("consent@example.com", "Second-pass-123", via=second_browser)
    second = mails_of(mailbox, "verify_email")[1]
    row = db.scalar(
        select(EmailToken).where(EmailToken.pending_consented_at.is_not(None)).order_by(EmailToken.created_at.desc())
    )
    assert row is not None
    second_browser.post(f"{URL}/verify-email", json={"token": link_token(second)})
    user = find_user(db, "consent@example.com")
    assert user is not None
    granted = db.scalars(select(Consent.granted_at).where(Consent.user_id == user.id)).all()
    assert granted == [row.pending_consented_at]


def test_verification_mail_limits(client, signup, mailbox, freeze_now):
    """Не больше одного письма подтверждения в 60 секунд и трёх в час — регистрация и повтор вместе."""
    signup("limit@example.com")
    resend = client.post(f"{URL}/resend-verification", json={"email": "limit@example.com"})
    assert resend.status_code == 202
    assert len(mails_of(mailbox, "verify_email")) == 1  # слишком рано

    freeze_now.tick(seconds=61)
    assert client.post(f"{URL}/resend-verification", json={"email": "limit@example.com"}).status_code == 202
    freeze_now.tick(seconds=61)
    signup("limit@example.com")
    assert len(mails_of(mailbox, "verify_email")) == 3
    freeze_now.tick(seconds=61)
    assert client.post(f"{URL}/resend-verification", json={"email": "limit@example.com"}).status_code == 202
    assert len(mails_of(mailbox, "verify_email")) == 3  # лимит часа; ответ тот же
    freeze_now.tick(hours=1)
    client.post(f"{URL}/resend-verification", json={"email": "limit@example.com"})
    assert len(mails_of(mailbox, "verify_email")) == 4


def test_resend_keeps_the_application_binding(make_client, signup, mailbox, freeze_now):
    """Повторное письмо несёт ту же заявку: чужой браузер по нему без пароля аккаунт не получит."""
    owner, other = make_client(), make_client()
    signup("resend@example.com", via=owner)
    freeze_now.tick(seconds=61)
    assert other.post(f"{URL}/resend-verification", json={"email": "resend@example.com"}).status_code == 202
    token = link_token(mails_of(mailbox, "verify_email")[-1])
    assert other.post(f"{URL}/verify-email", json={"token": token}).status_code == 409
    assert owner.post(f"{URL}/verify-email", json={"token": token}).status_code == 200


def test_resend_for_unknown_and_verified_is_silent(client, mailbox, make_user):
    make_user(email="done@example.com")
    for email in ("done@example.com", "nobody@example.com"):
        assert client.post(f"{URL}/resend-verification", json={"email": email}).status_code == 202
    assert mailbox == []


def test_already_registered_mail_three_per_hour(client, signup, mailbox, make_user, freeze_now):
    make_user(email="busy@example.com")
    for _ in range(5):
        assert signup("busy@example.com").status_code == 202
        freeze_now.tick(seconds=5)
    assert len(mails_of(mailbox, "already_registered")) == 3


def test_signup_validation(client, signup, mailbox, db: Session):
    def fields(response):
        assert response.status_code == 422 and response.json()["code"] == "validation_error"
        return {item["name"] for item in response.json()["fields"]}

    assert fields(signup("not-an-email")) == {"email"}
    assert fields(signup("x@example.com", password="short")) == {"password"}
    assert fields(signup("x@example.com", consent_processing=False)) == {"consent_processing"}
    assert fields(signup("x@example.com", is_adult=False)) == {"is_adult"}
    assert fields(signup("x@example.com", consent_version="processing-0")) == {"consent_version"}
    bad_role = client.post(f"{URL}/signup", json=signup_body("x@example.com", role="admin"))
    assert bad_role.status_code == 422
    assert mailbox == [] and db.scalar(select(AppUser.id)) is None


def test_signup_ip_limit(make_client, override_settings, mailbox):
    """Лимит регистраций считается по адресу клиента из `X-Real-IP` (доверенная сеть) — тест с двумя адресами."""
    override_settings(signup_ip_limit_per_hour=2)
    proxy = make_client(client=("172.28.5.2", 40000))

    def attempt(n: int, ip: str):
        return proxy.post(f"{URL}/signup", json=signup_body(f"ip{n}@example.com"), headers={"X-Real-IP": ip})

    assert [attempt(n, "203.0.113.5").status_code for n in range(2)] == [202, 202]
    limited = attempt(2, "203.0.113.5")
    assert limited.status_code == 429 and limited.json()["code"] == "rate_limited"
    assert limited.json()["params"]["retry_after"] >= 1
    assert attempt(3, "203.0.113.6").status_code == 202  # другой адрес — свой счётчик


def test_unverified_stub_is_purged_after_ttl(client, signup, mailbox, db: Session, freeze_now):
    signup("stale@example.com")
    assert find_user(db, "stale@example.com") is not None
    freeze_now.tick(days=31)
    signup("other@example.com")  # чистка срабатывает при регистрации
    assert find_user(db, "stale@example.com") is None


# --- слабые пароли --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("password", ["12345678", "0000000000", "aaaaaaaa", "password", "Qwerty123", "ПАРОЛЬ123"])
def test_trivial_password_is_rejected_with_a_field_error(client, signup, mailbox, password: str):
    response = signup("weak@example.com", password)
    assert response.status_code == 422, response.text
    fields = {item["name"]: item for item in response.json()["fields"]}
    assert fields["password"]["code"] == "password_too_simple" and "простой" in fields["password"]["message"]
    assert mailbox == []


@pytest.mark.parametrize("password", ["Demo-2026", "korova 42 plyashet", "12345678a", "длинный пароль фразой"])
def test_ordinary_password_is_accepted(client, signup, password: str):
    assert signup("fine@example.com", password).status_code == 202


def test_trivial_new_password_is_rejected_on_change(client, make_user, login_as):
    user = make_user()
    login_as(user)
    response = client.post(f"{URL}/password", json={"current_password": user.password, "new_password": "11111111"})
    assert response.status_code == 422
    assert response.json()["fields"][0] == {
        "name": "new_password",
        "code": "password_too_simple",
        "message": response.json()["fields"][0]["message"],
    }
