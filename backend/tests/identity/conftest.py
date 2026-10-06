"""Помощники тестов `identity`: регистрация через API, ссылки из писем, выборки из таблиц модуля."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import mail
from app.modules.identity import legal
from app.modules.identity.models import AppUser, AuditEvent, AuthSession, EmailToken, LoginAttempt
from app.shared.enums import ConsentKind

PASSWORD = "Test-pass-2026"  # = tests.conftest.TEST_PASSWORD: пароль, который ставит make_user
_TOKEN_RE = re.compile(r"token=([A-Za-z0-9_-]+)")


def signup_body(email: str, password: str = PASSWORD, role: str = "candidate", **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "email": email,
        "password": password,
        "role": role,
        "consent_processing": True,
        "consent_version": legal.consent_text(ConsentKind.PROCESSING).version,
        "is_adult": True,
    }
    body.update(overrides)
    return body


def link_token(letter: mail.OutgoingMail) -> str:
    """Токен из ссылки письма."""
    found = _TOKEN_RE.search(letter.text)
    assert found, letter.text
    return found.group(1)


def mails_of(mailbox: list[mail.OutgoingMail], template: str, to: str | None = None) -> list[mail.OutgoingMail]:
    return [item for item in mailbox if item.template == template and (to is None or item.to == to)]


@pytest.fixture
def signup(client: TestClient) -> Callable[..., Any]:
    def call(
        email: str, password: str = PASSWORD, role: str = "candidate", *, via: TestClient | None = None, **kw: Any
    ):
        return (via or client).post("/api/v1/auth/signup", json=signup_body(email, password, role, **kw))

    return call


@pytest.fixture
def count(db: Session) -> Callable[[type], int]:
    def counter(model: type) -> int:
        return int(db.scalar(select(func.count()).select_from(model)) or 0)

    return counter


@pytest.fixture
def attempts(db: Session) -> Callable[[str], list[LoginAttempt]]:
    def rows(kind: str) -> list[LoginAttempt]:
        return list(db.scalars(select(LoginAttempt).where(LoginAttempt.kind == kind).order_by(LoginAttempt.id)))

    return rows


def find_user(db: Session, email: str) -> AppUser | None:
    return db.scalar(select(AppUser).where(AppUser.email == email))


def audit_codes(db: Session) -> list[str]:
    return list(db.scalars(select(AuditEvent.code).order_by(AuditEvent.id)))


def session_count(db: Session, user_id: Any) -> int:
    return int(db.scalar(select(func.count()).select_from(AuthSession).where(AuthSession.user_id == user_id)) or 0)


def live_tokens(db: Session, user_id: Any) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(EmailToken)
            .where(EmailToken.user_id == user_id, EmailToken.used_at.is_(None))
        )
        or 0
    )
