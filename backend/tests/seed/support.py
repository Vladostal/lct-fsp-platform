"""Общая подготовка для тестов `seed`, `demo`, `privacy`: настоящий банк, настоящий сид, настоящая фиксация.

Сид занимает десятки секунд, поэтому он выполняется один раз на модуль тестов и по-настоящему фиксируется
в базе запуска; после модуля все таблицы очищаются, как после `db_factory`. Тесты работают с приложением через
обычные `TestClient` (без подмены `get_db`): каждый запрос — своя транзакция. Письма в `mailbox` не попадают:
демо-аккаунтам письма не уходят (Арх. 4.14).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app import wiring
from app.core import db as core_db
from app.modules.catalog import service as catalog

API = "/api/v1"
ADMIN = {"X-Admin-Token": "test-only-admin-token"}


@dataclass
class World:
    """Что вернул первый прогон сида и как войти в аккаунты."""

    first_run: dict[str, Any]
    app: FastAPI
    clients: list[TestClient] = field(default_factory=list)

    def client(self) -> TestClient:
        client = TestClient(self.app)
        self.clients.append(client)
        return client

    def login(self, key: str, client: TestClient | None = None) -> TestClient:
        """Вход «как…» через `POST /demo/login`; именованный аккаунт сценария."""
        client = client or self.client()
        reply = client.post(f"{API}/demo/login", json={"account_key": key})
        assert reply.status_code == 200, reply.text
        return client

    def login_direct(self, demo_key: str) -> TestClient:
        """Сессия любого демо-аккаунта (компании `company_N`, кандидаты `cand_NNN`) напрямую через `identity`."""
        from app.modules.identity import service as identity

        client = self.client()
        with core_db.session_scope() as db:
            user_id = identity.demo_user_ids(db, [demo_key])[0]
            token = identity.create_session(db, user_id)
        client.cookies.set("sid", token)
        return client


def _truncate_all(engine: Engine) -> None:
    tables = [
        f'"{table.schema}"."{table.name}"' if table.schema else f'"{table.name}"'
        for table in core_db.Base.metadata.sorted_tables
    ]
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE"))


def seeded_world(engine: Engine, app: FastAPI) -> Iterator[World]:
    """Тело модульной фикстуры `seeded`: банк, демо-реестр ФСП, сид; после модуля — очистка."""
    saved = set(catalog._available)
    try:
        wiring.load("app.modules.assessment.bank:build_if_empty")()
        wiring.load("app.fsp_mock.generator:seed_if_empty")()
        from app.seed import demo

        first = demo.run_all()
        world = World(first_run=first, app=app)
        yield world
        for client in world.clients:
            client.close()
    finally:
        catalog._available.clear()
        catalog._available.update(saved)
        _truncate_all(engine)


def db_session() -> Session:
    return core_db.new_session()


def make_world_fixture() -> Any:
    @pytest.fixture(scope="module")
    def seeded(engine: Engine, app: FastAPI) -> Iterator[World]:
        yield from seeded_world(engine, app)

    return seeded


UUIDLike = UUID
