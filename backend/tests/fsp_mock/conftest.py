"""Фикстуры тестов демо-ФСП: замороженное время, небольшой реестр, заголовок администратора."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from tests.fsp import mockdata

NOW = "2026-10-20T09:00:00+00:00"
ADMIN = {"X-Admin-Token": "test-only-admin-token"}


@pytest.fixture(autouse=True)
def frozen(freeze_now: Callable[..., object]) -> None:
    freeze_now(NOW)


@pytest.fixture
def admin() -> dict[str, str]:
    return dict(ADMIN)


@pytest.fixture
def athlete(db: Session) -> UUID:
    fsp_id = mockdata.add_athlete(db)
    mockdata.add_result(db, fsp_id, place=1, entries_count=40)
    mockdata.add_rank(db, fsp_id, "kms")
    db.commit()
    return fsp_id
