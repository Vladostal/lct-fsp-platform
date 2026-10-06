"""Фикстуры тестов модуля `fsp`: замороженное время, кандидат с сессией, поток привязки через API."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from tests.fsp import mockdata

#: Полдень «сегодня» в тестах: даты реестра считаются от него (`mockdata.TODAY`).
NOW = "2026-10-20T09:00:00+00:00"


@pytest.fixture(autouse=True)
def frozen(freeze_now: Callable[..., object]) -> None:
    freeze_now(NOW)


class Flow:
    """Прохождение потока привязки через HTTP: старт → страница провайдера → решение → callback."""

    def __init__(self, client: TestClient) -> None:
        self.client = client

    def start(self) -> str:
        response = self.client.post("/api/v1/fsp/link/start", json={"accept": True, "consent_version": "fsp-data-1"})
        assert response.status_code == 200, response.text
        return str(response.json()["authorize_url"])

    def authorize(self, url: str, fsp_id: UUID | str | None, *, decision: str = "allow", pick: str | None = None):
        """Нажать кнопку на странице демо-провайдера: вернуть ответ-редирект на callback."""
        parts = urlsplit(url)
        params = {key: values[0] for key, values in parse_qs(parts.query).items()}
        page = self.client.get(f"{parts.path}?{parts.query}")
        assert page.status_code == 200, page.text
        form = dict(params)
        form["decision"] = decision
        if fsp_id is not None:
            form["fsp_id"] = str(fsp_id)
        if pick is not None:
            form["pick"] = pick
        return self.client.post("/api/fsp-mock/oidc/authorize/decision", data=form, follow_redirects=False)

    def callback(self, location: str):
        parts = urlsplit(location)
        return self.client.get(f"{parts.path}?{parts.query}", follow_redirects=False)

    def run(self, fsp_id: UUID | str | None, **kwargs: object) -> str:
        """Весь поток; вернуть `Location` ответа callback (`/candidate/settings/fsp?result=…`)."""
        redirect = self.authorize(self.start(), fsp_id, **kwargs)  # type: ignore[arg-type]
        assert redirect.status_code == 302, redirect.text
        response = self.callback(redirect.headers["location"])
        assert response.status_code == 302
        return response.headers["location"]


@pytest.fixture
def candidate(make_user: Callable[..., object], login_as: Callable[..., TestClient]):  # type: ignore[no-untyped-def]
    user = make_user("candidate")
    login_as(user)
    return user


@pytest.fixture
def flow(client: TestClient, candidate: object) -> Flow:
    return Flow(client)


@pytest.fixture
def athlete(db: Session) -> UUID:
    """Взрослый спортсмен с одним сильным результатом."""
    fsp_id = mockdata.add_athlete(db)
    mockdata.add_result(db, fsp_id, place=1, entries_count=40)
    return fsp_id


@pytest.fixture
def settings_mode() -> str:
    return get_settings().fsp_mode
