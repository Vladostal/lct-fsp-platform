"""Профиль компании: `GET`/`PUT /employer/company` и фасад `company.service` (Арх. 9.4, 2.5, 8.3)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiException
from app.modules.company import service
from app.modules.company.dto import CompanyData
from app.modules.company.models import Company
from app.modules.identity import service as identity
from app.shared.enums import ContactKind, Role, TrustLevel
from app.shared.schemas import ContactMethod

URL = "/api/v1/employer/company"
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
DESCRIPTION = (
    "Разрабатываем платформу для спортивных соревнований: сервисы регистрации, расчёта рейтингов и отчётности."
)


def body(**overrides):
    value = {
        "name": "Орбита",
        "sphere": "ИТ-услуги",
        "description": DESCRIPTION,
        "site": "orbita.example.com",
        "city": "Москва",
        "contact_method": {"kind": "email", "value": "HR@Example.com"},
    }
    value.update(overrides)
    return value


def data(**overrides) -> CompanyData:
    values = body(**overrides)
    values["contact_method"] = ContactMethod(**values["contact_method"])
    return CompanyData(**values)


def fields(response) -> set[str]:
    assert response.status_code == 422 and response.json()["code"] == "validation_error"
    return {item["name"] for item in response.json()["fields"]}


@pytest.fixture
def employer(make_user, login_as, client):
    user = make_user(Role.EMPLOYER, email="owner@example.com")
    login_as(user)
    return user


def test_empty_profile_before_first_save(client, employer, db: Session):
    response = client.get(URL)
    assert response.status_code == 200
    view = response.json()
    assert view["is_complete"] is False
    assert all(view[key] is None for key in ("name", "sphere", "description", "site", "city", "contact_method"))
    assert view["trust_level"] == "basic" and view["trust_label"] == "Компания подтвердила только e-mail"
    assert view["on_platform_since"]  # дата регистрации работодателя
    assert service.get_company(db, employer.id) is None and not service.is_complete(db, employer.id)


def test_put_then_get(client, employer, db: Session):
    saved = client.put(URL, json=body())
    assert saved.status_code == 200
    view = saved.json()
    assert view["name"] == "Орбита" and view["is_complete"] is True
    assert view["site"] == "https://orbita.example.com"  # схема добавлена
    assert view["contact_method"] == {"kind": "email", "value": "hr@example.com"}
    assert client.get(URL).json() == view
    assert service.is_complete(db, employer.id)
    assert service.get_company(db, employer.id).trust_level is TrustLevel.BASIC  # type: ignore[union-attr]


def test_put_replaces_profile_and_keeps_created_at(client, employer, db: Session):
    first = client.put(URL, json=body()).json()
    second = client.put(URL, json=body(name="Орбита 2", site=None, city="  ")).json()
    assert second["name"] == "Орбита 2" and second["site"] is None and second["city"] is None
    assert second["on_platform_since"] == first["on_platform_since"]
    assert len(db.scalars(select(Company)).all()) == 1


def test_validation_fields_match_form(client, employer):
    assert fields(client.put(URL, json=body(name="О"))) == {"name"}
    assert fields(client.put(URL, json=body(sphere="x"))) == {"sphere"}
    assert fields(client.put(URL, json=body(description="Коротко"))) == {"description"}
    assert fields(client.put(URL, json=body(description="я" * 2001))) == {"description"}
    assert fields(client.put(URL, json=body(city="г" * 81))) == {"city"}
    assert fields(client.put(URL, json=body(site="not a site"))) == {"site"}
    assert fields(client.put(URL, json=body(site="ftp://example.com"))) == {"site"}
    assert fields(client.put(URL, json=body(contact_method={"kind": "email", "value": "nope"}))) == {
        "contact_method.value"
    }
    assert fields(client.put(URL, json=body(contact_method={"kind": "telegram", "value": "abc"}))) == {
        "contact_method.value"
    }
    assert fields(client.put(URL, json=body(contact_method={"kind": "phone", "value": "12"}))) == {
        "contact_method.value"
    }


def test_contact_values_are_normalized(client, employer):
    phone = client.put(URL, json=body(contact_method={"kind": "phone", "value": "8 (900) 123-45-67"})).json()
    assert phone["contact_method"]["value"] == "+79001234567"
    tg = client.put(URL, json=body(contact_method={"kind": "telegram", "value": "t.me/hr_orbita"})).json()
    assert tg["contact_method"]["value"] == "@hr_orbita"


def test_put_cannot_change_trust_level(client, employer):
    view = client.put(URL, json=body(trust_level="verified")).json()
    assert view["trust_level"] == "basic"


def test_roles_and_session(client, make_user, login_as, make_client):
    assert client.get(URL).status_code == 401
    assert client.put(URL, json=body()).status_code == 401
    login_as(make_user(Role.CANDIDATE))
    assert client.get(URL).status_code == 403
    assert client.put(URL, json=body()).status_code == 403


def test_profiles_are_per_employer(make_client, make_user, login_as):
    one, two = make_client(), make_client()
    login_as(make_user(Role.EMPLOYER), client=one)
    login_as(make_user(Role.EMPLOYER), client=two)
    one.put(URL, json=body(name="Первая"))
    assert two.get(URL).json()["name"] is None
    assert one.get(URL).json()["name"] == "Первая"


def test_facade_save_and_read(db: Session):
    emp = identity.create_user(
        db, "emp@example.com", "pass-12345", Role.EMPLOYER, verified=True, is_demo=False, demo_key=None
    )
    other = identity.create_user(
        db, "emp2@example.com", "pass-12345", Role.EMPLOYER, verified=True, is_demo=False, demo_key=None
    )
    saved = service.save_company(db, emp, data(), NOW)
    assert saved.name == "Орбита" and saved.is_complete and saved.created_at == NOW
    assert saved.contact_method == ContactMethod(kind=ContactKind.EMAIL, value="hr@example.com")

    later = datetime(2026, 10, 7, tzinfo=UTC)
    service.save_company(db, emp, data(name="Орбита+"), later, trust_level=TrustLevel.VERIFIED)
    again = service.get_company(db, emp)
    assert again is not None and again.name == "Орбита+" and again.created_at == NOW
    assert again.trust_level is TrustLevel.VERIFIED

    service.save_company(db, emp, data(name="Орбита++"), later)  # None оставляет уровень как был
    assert service.get_company(db, emp).trust_level is TrustLevel.VERIFIED  # type: ignore[union-attr]

    assert service.companies(db, [emp, other, uuid4()]).keys() == {emp}
    assert service.companies(db, []) == {}
    assert service.get_company(db, other) is None and not service.is_complete(db, other)


def test_facade_validates_for_seed(db: Session):
    emp = identity.create_user(
        db, "emp3@example.com", "pass-12345", Role.EMPLOYER, verified=True, is_demo=False, demo_key=None
    )
    with pytest.raises(ApiException) as caught:
        service.save_company(db, emp, data(description="мало"), NOW)
    assert caught.value.status == 422 and caught.value.fields[0].name == "description"


def test_is_complete_false_for_row_written_around_the_facade(db: Session):
    emp = identity.create_user(
        db, "emp4@example.com", "pass-12345", Role.EMPLOYER, verified=True, is_demo=False, demo_key=None
    )
    db.add(
        Company(
            employer_id=emp,
            name="X",
            sphere="ИТ",
            description="коротко",
            contact_kind="email",
            contact_value="bad",
            trust_level="basic",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    db.flush()
    assert service.is_complete(db, emp) is False


def test_company_is_deleted_with_account(db: Session):
    emp = identity.create_user(
        db, "emp5@example.com", "pass-12345", Role.EMPLOYER, verified=True, is_demo=False, demo_key=None
    )
    service.save_company(db, emp, data(), NOW)
    identity.delete_user(db, emp)
    db.expire_all()
    assert db.scalar(select(Company).where(Company.employer_id == emp)) is None
