"""Пароли, токены, сессия входа (Арх. 10.1, 10.6)."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter
from sqlalchemy import text

from app.core import security
from app.core.deps import AnyUser


def _session_row(db, user_id):
    return db.execute(
        text("SELECT expires_at, last_seen_at, token_hash FROM auth_session WHERE user_id = :id"), {"id": user_id}
    ).one()


def test_password_hash_is_argon2id_and_verifies():
    hashed = security.hash_password("Correct-horse-1")
    assert hashed.startswith("$argon2id$")
    assert security.verify_password("Correct-horse-1", hashed)
    assert not security.verify_password("correct-horse-1", hashed)
    assert not security.verify_password("x", None)
    assert not security.verify_password("x", "не хеш")


def test_tokens_are_random_and_only_hash_is_stored(db, make_user, login_as, client):
    assert security.new_token() != security.new_token()
    assert len(security.hash_token("abc")) == 64

    user = make_user()
    login_as(user)
    token = client.cookies.get("sid")
    stored = _session_row(db, user.id).token_hash
    assert stored == security.hash_token(token) and token not in stored


def test_keyed_hash_depends_on_purpose_and_is_not_plain_sha256():
    email = "user@example.com"
    first = security.keyed_hash("email", email)
    assert first == security.keyed_hash("email", email)
    assert first != security.keyed_hash("other", email)
    assert first != security.hash_token(email)


def test_constant_time_equals():
    assert security.constant_time_equals("токен", "токен")
    assert not security.constant_time_equals("токен", "токен2")


def test_fresh_session_is_not_touched_by_requests(probe, tx_router: APIRouter, db, make_user, login_as, freeze_now):
    """Обычный GET со свежей сессией ничего не пишет в базу (закрытый перечень записей при чтении, Арх. 10.1)."""

    @tx_router.get("/me")
    def me(user: AnyUser) -> dict[str, str]:
        return {"id": str(user.id)}

    freeze_now("2026-10-05T10:00:00+00:00")
    user = make_user()
    client = login_as(user, probe(tx_router))
    before = _session_row(db, user.id)

    freeze_now.tick(minutes=59)
    response = client.get("/api/v1/me")
    assert response.status_code == 200
    assert "set-cookie" not in response.headers
    assert _session_row(db, user.id) == before

    freeze_now.tick(minutes=2)  # прошёл час — обновляется только отметка активности
    client.get("/api/v1/me")
    after = _session_row(db, user.id)
    assert after.last_seen_at == before.last_seen_at + timedelta(minutes=61)
    assert after.expires_at == before.expires_at


def test_session_is_renewed_when_less_than_half_ttl_remains(
    probe, tx_router: APIRouter, db, make_user, login_as, freeze_now
):
    @tx_router.get("/me")
    def me(user: AnyUser) -> dict[str, str]:
        return {"id": str(user.id)}

    start = freeze_now("2026-10-05T10:00:00+00:00")
    user = make_user()
    client = login_as(user, probe(tx_router))

    freeze_now.tick(days=6)  # осталось 8 суток из 14 — больше половины, продления нет
    assert "set-cookie" not in client.get("/api/v1/me").headers
    assert _session_row(db, user.id).expires_at == start + timedelta(days=14)

    now = freeze_now.tick(days=2)  # осталось 6 суток — меньше половины
    response = client.get("/api/v1/me")
    assert response.status_code == 200
    assert _session_row(db, user.id).expires_at == now + timedelta(days=14)
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("sid=") and "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    assert "Max-Age=1209600" in cookie and "Secure" not in cookie  # COOKIE_SECURE=false в тестах


def test_cookie_helpers(override_settings):
    from fastapi import Response

    override_settings(cookie_secure=True)
    response = Response()
    security.set_session_cookie(response, "token-value")
    header = response.headers["set-cookie"]
    assert "sid=token-value" in header and "Secure" in header and "HttpOnly" in header

    cleared = Response()
    security.clear_session_cookie(cleared)
    assert 'sid=""' in cleared.headers["set-cookie"] and "Max-Age=0" in cleared.headers["set-cookie"]
