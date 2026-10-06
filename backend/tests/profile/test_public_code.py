"""Код кандидата «К-» и пять цифр; повтор генерации при коллизии (Арх. 8.4, 15.1 № 65)."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from datetime import datetime

import pytest
from sqlalchemy.orm import Session

from app.modules.profile import profiles
from app.modules.profile.constants import PUBLIC_CODE_ATTEMPTS
from app.modules.profile.models import CandidateProfile
from tests.conftest import TestUser

CODE_RE = re.compile(r"^К-\d{5}$")  # «К» — кириллическая


def test_generated_format() -> None:
    codes = {profiles.generate_public_code() for _ in range(200)}
    assert all(CODE_RE.fullmatch(code) for code in codes) and len(codes) > 150


def test_collision_is_retried(
    db: Session, make_user: Callable[..., TestUser], now: datetime, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = profiles.ensure_profile(db, make_user("candidate").id, now)
    answers: Iterator[str] = iter([first.public_code, first.public_code, "К-00007"])
    monkeypatch.setattr(profiles, "generate_public_code", lambda: next(answers))
    second = profiles.ensure_profile(db, make_user("candidate").id, now)
    assert second.public_code == "К-00007" and second.public_code != first.public_code
    assert db.query(CandidateProfile).count() == 2  # неудачные попытки откатились точкой сохранения


def test_gives_up_after_ten_attempts(
    db: Session, make_user: Callable[..., TestUser], now: datetime, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = profiles.ensure_profile(db, make_user("candidate").id, now)
    calls: list[int] = []

    def always_taken() -> str:
        calls.append(1)
        return first.public_code

    monkeypatch.setattr(profiles, "generate_public_code", always_taken)
    with pytest.raises(RuntimeError):
        profiles.ensure_profile(db, make_user("candidate").id, now)
    assert len(calls) == PUBLIC_CODE_ATTEMPTS


def test_code_is_stable_per_user(db: Session, make_user: Callable[..., TestUser], now: datetime) -> None:
    user = make_user("candidate")
    row = profiles.ensure_profile(db, user.id, now)
    assert CODE_RE.fullmatch(row.public_code)
    assert profiles.ensure_profile(db, user.id, now).public_code == row.public_code
