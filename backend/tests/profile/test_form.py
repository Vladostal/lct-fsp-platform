"""Форма профиля: валидация полей, пределы навыков, свои теги, ответ кандидату (Арх. 9.6; приложение B, §1.1)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.profile import service
from app.modules.profile.constants import DECLARED_SKILLS_MAX, PUBLIC_LIMITS
from app.modules.profile.models import CandidateDeclaredSkill
from tests.conftest import TestUser
from tests.profile.conftest import Candidate

BASE = "/api/v1/candidate/profile"


@pytest.fixture
def me(make_user: Callable[..., TestUser], login_as: Callable[..., TestClient]) -> TestUser:
    user = make_user("candidate")
    login_as(user)
    return user


def body(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {"last_name": "Смирнова", "first_name": "Анна"}
    values.update(overrides)
    return values


def test_first_get_creates_profile_with_public_code(client: TestClient, me: TestUser) -> None:
    data = client.get(BASE).json()
    assert data["email"] == me.email
    assert data["public_code"].startswith("К-") and len(data["public_code"]) == 7
    assert data["completeness"]["filled"] == 0 and "last_name" in data["completeness"]["missing"]
    assert client.get(BASE).json()["public_code"] == data["public_code"]  # код стабилен


def test_put_replaces_fields_and_normalizes(client: TestClient, me: TestUser) -> None:
    payload = body(
        middle_name="  Сергеевна ",
        city=" Казань ",
        phone="8 (917) 123-45-67",
        telegram="anna_dev",
        link="github.com/anna-demo",
        experience_years=4,
        roles=["backend_dev", "backend_dev"],
        about="  Люблю тесты.  ",
        declared_skills=[{"code": "python"}, {"code": "python"}, {"custom_label": " Tarantool "}],
    )
    response = client.put(BASE, json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["phone"] == "+79171234567" and data["telegram"] == "@anna_dev"
    assert data["link"] == "https://github.com/anna-demo"
    assert data["city"] == "Казань" and data["about"] == "Люблю тесты."
    assert [r["code"] for r in data["roles"]] == ["backend_dev"]
    assert [(s["code"], s["title"], s["custom"]) for s in data["declared_skills"]] == [
        ("python", "Python", False),
        (None, "Tarantool", True),
    ]
    assert data["completeness"]["missing"] == []


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("last_name", "", "required"),
        ("first_name", "Анна1", "name_invalid"),
        ("first_name", "А" * 61, "name_too_long"),
        ("phone", "12", "phone_invalid"),
        ("telegram", "@ab", "telegram_invalid"),
        ("link", "http://example.com", "link_invalid"),
        ("link", "https://example.com/<script>", "link_invalid"),
        ("experience_years", 41, "experience_out_of_range"),
        ("experience_years", 3.3, "experience_step"),
        ("about", "я" * 1001, "about_too_long"),
        ("city", "г" * 81, "city_too_long"),
    ],
)
def test_field_validation_422(client: TestClient, me: TestUser, field: str, value: Any, code: str) -> None:
    response = client.put(BASE, json=body(**{field: value}))
    assert response.status_code == 422
    assert any(item["name"] == field and item["code"] == code for item in response.json()["fields"]), response.json()


def test_unknown_role_and_skill_codes(client: TestClient, me: TestUser) -> None:
    response = client.put(BASE, json=body(roles=["no_such_role"], declared_skills=[{"code": "no_such_skill"}]))
    assert response.status_code == 422
    codes = {item["code"] for item in response.json()["fields"]}
    assert codes == {"role_unknown", "skill_unknown"}


def test_skill_needs_code_or_label_exactly_one(client: TestClient, me: TestUser) -> None:
    assert client.put(BASE, json=body(declared_skills=[{}])).status_code == 422
    assert client.put(BASE, json=body(declared_skills=[{"code": "python", "custom_label": "x"}])).status_code == 422


def test_declared_skills_limit_counts_custom_tags(client: TestClient, me: TestUser) -> None:
    ok = [{"code": f"tech_{i:02d}"} for i in range(DECLARED_SKILLS_MAX - 5)] + [
        {"custom_label": f"Тег {i}"} for i in range(5)
    ]
    assert client.put(BASE, json=body(declared_skills=ok)).status_code == 200
    too_many = [*ok, {"custom_label": "Лишний"}]
    response = client.put(BASE, json=body(declared_skills=too_many))
    assert response.status_code == 422
    assert response.json()["fields"][0]["code"] == "declared_skills_limit"
    assert PUBLIC_LIMITS["declared_skills_max"] == 30


def test_soft_skills_limit_is_separate(client: TestClient, me: TestUser) -> None:
    soft = [{"code": f"soft_{i:02d}"} for i in range(10)]
    hard = [{"code": f"tech_{i:02d}"} for i in range(30)]
    assert client.put(BASE, json=body(declared_skills=soft + hard)).status_code == 200
    response = client.put(BASE, json=body(declared_skills=[*soft, {"code": "soft_10"}]))
    assert response.status_code == 422
    assert response.json()["fields"][0]["code"] == "soft_skills_limit"


def test_custom_tags_unique_case_insensitively(client: TestClient, me: TestUser, db: Session) -> None:
    response = client.put(
        BASE, json=body(declared_skills=[{"custom_label": "Tarantool"}, {"custom_label": "tarantool"}])
    )
    assert response.status_code == 200
    assert len(response.json()["declared_skills"]) == 1
    assert db.query(CandidateDeclaredSkill).filter_by(user_id=me.id).count() == 1


def test_custom_tag_length(client: TestClient, me: TestUser) -> None:
    assert client.put(BASE, json=body(declared_skills=[{"custom_label": "я" * 41}])).status_code == 422


def test_foreign_resume_upload_is_404(client: TestClient, me: TestUser) -> None:
    from uuid import uuid4

    response = client.put(BASE, json=body(resume_upload_id=str(uuid4())))
    assert response.status_code == 404


def test_candidate_only(client: TestClient, make_user: Callable[..., TestUser], login_as: Callable[..., Any]) -> None:
    assert client.get(BASE).status_code == 401
    login_as(make_user("employer"))
    assert client.get(BASE).status_code == 403


def test_pool_view_hides_what_privacy_hides(db: Session, make_candidate: Callable[..., Candidate], now: Any) -> None:
    from app.modules.profile.dto import PrivacyData

    candidate = make_candidate(published=True)
    full = service.pool_view(db, [candidate.id], now)[candidate.id]
    assert full.visible and full.city == "Казань" and full.declared_skills == ["python", "fastapi"]
    assert full.custom_skills == ["Tarantool"] and full.work_formats == ["remote"]
    service.save_privacy(
        db, candidate.id, PrivacyData(show_city=False, show_experience=False, show_declared_stack=False), now
    )
    hidden = service.pool_view(db, [candidate.id], now)[candidate.id]
    assert hidden.city is None and hidden.experience_years is None and hidden.roles == []
    assert hidden.declared_skills == [] and hidden.custom_skills == []
