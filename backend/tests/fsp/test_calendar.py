"""Календарь соревнований (Арх. 7.9): фильтры, порядок, кэш на 6 часов, недоступный реестр, проверка параметров."""

from __future__ import annotations

import importlib
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.fsp_mock import registry_service
from app.modules.fsp.gateway import factory
from app.modules.fsp.models import FspCache
from tests.fsp import mockdata

URL = "/api/v1/fsp/calendar"


def upcoming(db: Session, competition_id: str, days: int, **fields: object) -> None:
    fields.setdefault("status", "registration_open")
    fields.setdefault("protocol_status", "none")
    mockdata.add_competition(db, competition_id, start_in_days=days, entries_count=None, **fields)  # type: ignore[arg-type]


def failure(mode: str) -> None:
    with registry_service.registry_session() as session:
        registry_service.set_failure_mode(session, mode)


@pytest.fixture
def registry(db: Session) -> None:
    upcoming(db, "regional-algo", 30, level="regional", deadline_in_days=20)
    upcoming(db, "national-final", 10, level="national", stage="final", status="scheduled")
    upcoming(db, "qualification", 40, level="national", stage="qualification", discipline="product")
    upcoming(db, "youth", 5, age_group="youth", level="regional")
    upcoming(db, "children", 6, age_group="children", level="regional")
    upcoming(db, "deadline-passed", 15, level="regional", deadline_in_days=-1)
    mockdata.add_competition(db, "finished", days_ago=40)
    mockdata.add_competition(db, "closed", start_in_days=9, status="registration_closed", protocol_status="none")
    db.commit()


def test_calendar_filters_and_order(client: TestClient, candidate: object, registry: None) -> None:
    body = client.get(URL, params={"limit": 10}).json()
    ids = [item["competition_id"] for item in body["items"]]
    # доступные новичку (региональные, отборочные) — первыми; юношеские группы, прошедший срок и завершённые отброшены
    assert ids == ["regional-algo", "qualification", "national-final"]
    first = body["items"][0]
    assert first["level_label"] == "региональный" and first["discipline_label"] == "алгоритмическое программирование"
    assert first["status"] == "registration_open" and first["registration_url"].startswith("https://")
    assert first["age_group_label"] == "мужчины и женщины" and first["format_label"] == "очно"
    assert body["stale"] is False and body["fetched_at"] and body["source_label"] == "Источник: демо-реестр ФСП"
    assert len(client.get(URL).json()["items"]) == 3
    assert len(client.get(URL, params={"limit": 1}).json()["items"]) == 1


def test_calendar_relevance_by_specialization(
    client: TestClient, candidate: object, registry: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    router = importlib.import_module("app.modules.fsp.router")
    monkeypatch.setattr(router, "_specialization", lambda db, user_id: "frontend")
    ids = [item["competition_id"] for item in client.get(URL, params={"limit": 10}).json()["items"]]
    assert ids[:2] == ["qualification", "regional-algo"]  # product ближе к frontend, чем algo


def test_calendar_cache_ttl(
    client: TestClient, candidate: object, registry: None, db: Session, freeze_now: Callable[..., object]
) -> None:
    client.get(URL)
    cache = db.get(FspCache, "calendar")
    assert cache is not None and len(cache.payload) >= 3
    first_fetch = cache.fetched_at
    failure("unavailable")
    fresh = client.get(URL).json()  # кэш свежий: реестр не нужен
    assert fresh["stale"] is False and len(fresh["items"]) == 3
    freeze_now.tick(hours=7)  # type: ignore[attr-defined]
    stale = client.get(URL).json()  # кэш устарел, реестр недоступен: прежний кэш с пометкой
    assert stale["stale"] is True and len(stale["items"]) == 3
    assert db.get(FspCache, "calendar").fetched_at == first_fetch  # type: ignore[union-attr]
    failure("none")
    refreshed = client.get(URL).json()
    assert refreshed["stale"] is False
    assert db.get(FspCache, "calendar").fetched_at > first_fetch  # type: ignore[union-attr]


def test_calendar_unavailable_without_cache_is_empty(
    client: TestClient, candidate: object, registry: None, db: Session
) -> None:
    failure("unavailable")
    body = client.get(URL).json()
    assert body["items"] == [] and body["fetched_at"] is None and body["stale"] is True
    assert db.scalar(select(FspCache.key)) is None


def test_calendar_does_not_require_link_and_validates_limit(
    client: TestClient, candidate: object, registry: None
) -> None:
    assert client.get(URL).status_code == 200
    for bad in ("0", "11", "x"):
        response = client.get(URL, params={"limit": bad})
        assert response.status_code == 422 and response.json()["code"] == "validation_error"


def test_calendar_keycloak_mode_is_unavailable_not_demo(
    client: TestClient, candidate: object, registry: None, override_settings: Callable[..., object]
) -> None:
    override_settings(fsp_mode="keycloak")
    body = client.get(URL).json()
    assert body["items"] == [] and body["stale"] is True
    assert factory is not None
