"""Условия кандидата и настройки приватности (Арх. 4.6, 8.4, 9.6)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.profile import service
from app.modules.profile.constants import PUBLIC_LIMITS
from app.shared.salary import min_salary_ladder
from tests.conftest import TestUser

MIN_SALARY_LADDER = min_salary_ladder()
CONDITIONS = "/api/v1/candidate/conditions"
PRIVACY = "/api/v1/candidate/settings/privacy"


@pytest.fixture
def me(make_user: Callable[..., TestUser], login_as: Callable[..., TestClient]) -> TestUser:
    user = make_user("candidate")
    login_as(user)
    return user


def test_defaults_without_row(client: TestClient, me: TestUser) -> None:
    assert client.get(CONDITIONS).json() == {
        "min_salary": None,
        "work_formats": ["office", "hybrid", "remote"],
        "relocation_ready": False,
    }


def test_save_and_read_back(client: TestClient, me: TestUser, db: Session) -> None:
    step = MIN_SALARY_LADDER[3]
    response = client.put(
        CONDITIONS, json={"min_salary": step, "work_formats": ["remote", "hybrid"], "relocation_ready": True}
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"min_salary": step, "work_formats": ["hybrid", "remote"], "relocation_ready": True}
    assert service.min_salary(db, me.id) == step


def test_value_outside_ladder_is_422(client: TestClient, me: TestUser) -> None:
    off = MIN_SALARY_LADDER[3] + 1
    response = client.put(CONDITIONS, json={"min_salary": off, "work_formats": ["remote"]})
    assert response.status_code == 422
    assert response.json()["code"] == "min_salary_not_on_ladder"
    assert response.json()["fields"][0]["name"] == "min_salary"


def test_not_set_clears_minimum(client: TestClient, me: TestUser, db: Session) -> None:
    client.put(CONDITIONS, json={"min_salary": MIN_SALARY_LADDER[2], "work_formats": ["remote"]})
    client.put(CONDITIONS, json={"min_salary": None, "work_formats": ["remote"]})
    assert service.min_salary(db, me.id) is None


def test_formats_must_not_be_empty(client: TestClient, me: TestUser) -> None:
    assert client.put(CONDITIONS, json={"min_salary": None, "work_formats": []}).status_code == 422
    assert client.put(CONDITIONS, json={"min_salary": None, "work_formats": ["moon"]}).status_code == 422


def test_public_limits_names() -> None:
    assert {
        "min_salary_low",
        "min_salary_high",
        "min_salary_step",
        "salary_min",
        "salary_max",
        "salary_max_ratio",
        "declared_skills_max",
    } <= set(PUBLIC_LIMITS)


def test_privacy_defaults_keep_channels_closed(client: TestClient, me: TestUser) -> None:
    data = client.get(PRIVACY).json()
    assert data["show_city"] and data["show_experience"] and data["show_about"] and data["show_fsp_summary"]
    # Поправка R3-data-api-security-6: каналы, кроме e-mail, по умолчанию не раскрываются.
    assert not any(data[name] for name in ("reveal_phone", "reveal_telegram", "reveal_link", "reveal_fsp_details"))


def test_privacy_put_and_hidden_domains_preserved(client: TestClient, me: TestUser) -> None:
    payload: dict[str, Any] = {"show_city": False, "reveal_phone": True, "hidden_domains": ["Example.com"]}
    data = client.put(PRIVACY, json=payload).json()
    assert data["show_city"] is False and data["reveal_phone"] is True and data["hidden_domains"] == ["example.com"]
    # Экран P0 про домены не знает: тело без поля список не стирает.
    again = client.put(PRIVACY, json={"show_city": True}).json()
    assert again["show_city"] is True and again["reveal_phone"] is False and again["hidden_domains"] == ["example.com"]
    assert client.put(PRIVACY, json={"hidden_domains": ["not a domain"]}).status_code == 422
    assert client.put(PRIVACY, json={"hidden_domains": [f"d{i}.example.com" for i in range(6)]}).status_code == 422
