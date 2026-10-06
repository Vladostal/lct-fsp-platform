"""Фасад `identity.service` (Арх. 2.5): пользователи, согласия, аудит, сессии, лимиты, тексты."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import security
from app.core.errors import ApiException
from app.modules.identity import emails, service
from app.modules.identity.models import AuditEvent, Consent, LoginAttempt
from app.shared.enums import ConsentKind, Role

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def test_create_user_and_read(db: Session):
    uid = service.create_user(
        db, "Seed@Example.com", "Test-pass-2026", Role.EMPLOYER, verified=True, is_demo=False, demo_key=None
    )
    user = service.get_user(db, uid)
    assert user.email == "seed@example.com" and user.role is Role.EMPLOYER
    assert user.email_verified_at is not None and not user.is_demo
    assert service.users(db, [uid, uuid4()]).keys() == {uid}
    assert service.users(db, []) == {}
    consent = service.consents(db, uid)[ConsentKind.PROCESSING]
    assert consent.revoked_at is None
    row = db.scalar(select(Consent).where(Consent.user_id == uid))
    assert row is not None and row.source == "seed"
    with pytest.raises(ValueError):
        service.create_user(db, "seed@example.com", "x", Role.CANDIDATE, verified=True, is_demo=False, demo_key=None)


def test_get_user_missing_is_404(db: Session):
    with pytest.raises(ApiException) as caught:
        service.get_user(db, uuid4())
    assert caught.value.status == 404 and caught.value.code == "not_found"


def test_demo_users_and_keys(db: Session):
    a = service.create_user(
        db, "demo-a@example.com", "pass-12345", Role.CANDIDATE, verified=True, is_demo=True, demo_key="anna"
    )
    b = service.create_user(
        db, "demo-b@example.com", "pass-12345", Role.EMPLOYER, verified=True, is_demo=True, demo_key="orbita"
    )
    service.create_user(
        db, "real@example.com", "pass-12345", Role.CANDIDATE, verified=True, is_demo=False, demo_key=None
    )
    assert set(service.demo_user_ids(db)) == {a, b}
    assert service.demo_user_ids(db, ["orbita"]) == [b]
    assert service.demo_user_ids(db, []) == []
    with pytest.raises(ValueError):
        service.create_user(
            db, "demo-c@example.com", "pass-12345", Role.CANDIDATE, verified=True, is_demo=True, demo_key="anna"
        )


def test_consent_grant_revoke_and_publication(db: Session):
    uid = service.create_user(
        db, "c@example.com", "pass-12345", Role.CANDIDATE, verified=True, is_demo=False, demo_key=None
    )
    text = service.current_consent(ConsentKind.PUBLICATION)
    assert service.publication_consent_active(db, [uid]) == set()
    service.grant_consent(db, uid, ConsentKind.PUBLICATION, text.version, text.sha256, "user", NOW)
    assert service.publication_consent_active(db, [uid, uuid4()]) == {uid}
    service.grant_consent(
        db, uid, ConsentKind.PUBLICATION, text.version, text.sha256, "user", NOW
    )  # повтор — без новой строки
    assert len(db.scalars(select(Consent).where(Consent.kind == "publication")).all()) == 1

    service.revoke_consent(db, uid, ConsentKind.PUBLICATION, NOW)
    assert service.publication_consent_active(db, [uid]) == set()
    consent = service.consents(db, uid)[ConsentKind.PUBLICATION]
    assert consent.revoked_at == NOW

    service.grant_consent(
        db, uid, ConsentKind.PUBLICATION, text.version, text.sha256, "user", NOW
    )  # согласие можно дать снова
    assert service.publication_consent_active(db, [uid]) == {uid}
    assert service.consents(db, uid)[ConsentKind.PUBLICATION].revoked_at is None
    service.revoke_consent(db, uid, ConsentKind.FSP_DATA, NOW)  # нечего отзывать — не ошибка


def test_new_version_replaces_active_consent(db: Session):
    uid = service.create_user(
        db, "v@example.com", "pass-12345", Role.CANDIDATE, verified=True, is_demo=False, demo_key=None
    )
    service.grant_consent(db, uid, ConsentKind.PUBLICATION, "v1", "a" * 64, "user", NOW)
    service.grant_consent(db, uid, ConsentKind.PUBLICATION, "v2", "b" * 64, "user", NOW)
    rows = db.scalars(select(Consent).where(Consent.kind == "publication").order_by(Consent.version)).all()
    assert [(row.version, row.revoked_at is None) for row in rows] == [("v1", False), ("v2", True)]
    assert service.consents(db, uid)[ConsentKind.PUBLICATION].version == "v2"


def test_consent_source_is_validated(db: Session):
    uid = service.create_user(
        db, "s@example.com", "pass-12345", Role.CANDIDATE, verified=True, is_demo=False, demo_key=None
    )
    with pytest.raises(ValueError):
        service.grant_consent(db, uid, ConsentKind.PUBLICATION, "v1", "a" * 64, "robot", NOW)


def test_current_consent_texts():
    for kind in (ConsentKind.PROCESSING, ConsentKind.PUBLICATION):
        text = service.current_consent(kind)
        assert text.version and text.title and text.text
        assert text.sha256 == hashlib.sha256(text.text.encode()).hexdigest()
    with pytest.raises(LookupError):
        service.current_consent(ConsentKind.FSP_DATA)  # текст принадлежит модулю fsp


def test_audit_keeps_only_given_params(db: Session):
    uid = uuid4()
    service.audit(db, "something", actor_user_id=uid, params={"when": NOW, "id": uid, "items": {1, 2}})
    row = db.scalar(select(AuditEvent).where(AuditEvent.code == "something"))
    assert row is not None and row.actor_user_id == uid
    assert row.params["when"] == NOW.isoformat() and row.params["id"] == str(uid)


def test_create_session_opens_working_cookie(client, db: Session):
    uid = service.create_user(
        db, "sess@example.com", "pass-12345", Role.CANDIDATE, verified=True, is_demo=True, demo_key="s"
    )
    token = service.create_session(db, uid)
    db.commit()
    client.cookies.set(security.SESSION_COOKIE, token)
    assert client.get("/api/v1/auth/me").json()["id"] == str(uid)


def test_canonical_email_and_hash():
    assert emails.canonical_email("Name+tag@Example.com") == "name@example.com"
    assert emails.canonical_email("n.a.m.e+x@gmail.com") == "name@gmail.com"
    assert emails.canonical_email("n.a.m.e@googlemail.com") == "name@gmail.com"
    assert emails.canonical_email("a.b@example.com") == "a.b@example.com"  # точки значимы не везде
    assert emails.email_hash("a+1@example.com") == emails.email_hash("a@example.com")
    assert emails.email_hash("a@example.com") != hashlib.sha256(b"a@example.com").hexdigest()
    assert emails.normalize_email("  Bob@Example.COM ") == "bob@example.com"
    assert emails.normalize_email("nope") is None


# --- общий счётчик лимитов ------------------------------------------------------------------------------------------


def _call(db: Session, n: int, **kw):
    for _ in range(n):
        service.throttle(db, "bank_page", limit=3, window_s=60, **kw)
        db.commit()


def test_throttle_by_ip(db: Session, freeze_now):
    _call(db, 3, ip="1.1.1.1")
    with pytest.raises(ApiException) as caught:
        _call(db, 1, ip="1.1.1.1")
    assert caught.value.status == 429 and caught.value.code == "rate_limited"
    assert 1 <= caught.value.params["retry_after"] <= 60
    _call(db, 3, ip="2.2.2.2")  # другой адрес — свой счётчик
    freeze_now.tick(seconds=61)
    _call(db, 1, ip="1.1.1.1")  # окно прошло


def test_throttle_by_user_and_global(db: Session):
    first = service.create_user(
        db, "t1@example.com", "pass-12345", Role.EMPLOYER, verified=True, is_demo=False, demo_key=None
    )
    second = service.create_user(
        db, "t2@example.com", "pass-12345", Role.EMPLOYER, verified=True, is_demo=False, demo_key=None
    )
    _call(db, 3, user_id=first)
    with pytest.raises(ApiException):
        _call(db, 1, user_id=first)
    _call(db, 3, user_id=second)
    # Общий счётчик без ключей считает все строки вида: 6 уже записано.
    with pytest.raises(ApiException):
        _call(db, 1)
    rows = db.scalars(select(LoginAttempt).where(LoginAttempt.kind == "bank_page")).all()
    assert len(rows) == 6  # отклонённые попытки не записываются
    assert all(row.email_sha256 and "@" not in row.email_sha256 for row in rows)


def test_throttle_counts_one_event_once_per_transaction(db: Session):
    """Две границы одного действия (по IP и общая) — одно событие, а не два."""
    service.throttle(db, "demo_restart", ip="3.3.3.3", limit=1, window_s=60)
    service.throttle(db, "demo_restart", limit=1, window_s=60)
    db.commit()
    assert len(db.scalars(select(LoginAttempt).where(LoginAttempt.kind == "demo_restart")).all()) == 1
    with pytest.raises(ApiException):
        service.throttle(db, "demo_restart", ip="3.3.3.3", limit=1, window_s=60)


def test_throttle_rejects_bad_kind(db: Session):
    with pytest.raises(ValueError):
        service.throttle(db, "Bad Kind!", limit=1, window_s=60)
