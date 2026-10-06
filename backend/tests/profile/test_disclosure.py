"""Раскрытие контактов, `contacts_for_pair`, маскируемая пара, журнал доступа (Арх. 4.14, 10.4, 10.8)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.modules.profile import service
from app.modules.profile.constants import MASKED_VALUE
from app.modules.profile.dto import PdfContacts, PrivacyData
from app.modules.profile.models import AccessLog, ContactDisclosure
from app.shared.enums import AccessKind, DiscloseField, DisclosureSource
from tests.conftest import TestUser
from tests.profile.conftest import Candidate, World


def invite(db: Session, employer: TestUser, candidate: Candidate, now: datetime, *fields: DiscloseField) -> Any:
    ref = uuid4()
    service.disclose(
        db, employer.id, candidate.id, source=DisclosureSource.INVITATION, ref_id=ref, fields=fields, now=now
    )
    return ref


def test_nothing_before_disclosure(
    db: Session, make_candidate: Callable[..., Candidate], make_employer: Callable[..., TestUser]
) -> None:
    candidate, employer = make_candidate(published=True), make_employer()
    assert service.contacts_for_pair(db, employer.id, candidate.id) is None
    assert not service.is_disclosed(db, employer.id, candidate.id)
    assert service.disclosed_map(db, employer.id, [candidate.id]) == {}
    assert service.display_names(db, employer.id, [candidate.id]) == {}


def test_disclose_is_idempotent_by_ref(
    db: Session, make_candidate: Callable[..., Candidate], make_employer: Callable[..., TestUser], now: datetime
) -> None:
    candidate, employer = make_candidate(published=True), make_employer()
    ref = invite(db, employer, candidate, now, DiscloseField.PHONE)
    service.disclose(
        db,
        employer.id,
        candidate.id,
        source=DisclosureSource.INVITATION,
        ref_id=ref,
        fields=[DiscloseField.TELEGRAM, DiscloseField.LINK],
        now=now + timedelta(hours=1),
    )
    rows = db.scalars(select(ContactDisclosure)).all()
    assert len(rows) == 1 and set(rows[0].fields) == {"email", "phone"}  # набор не меняется; e-mail — всегда
    assert db.scalars(select(AccessLog).where(AccessLog.kind == "contacts_disclosed")).all().__len__() == 1
    assert service.is_disclosed(db, employer.id, candidate.id)


def test_fields_are_united_across_disclosures(
    db: Session, make_candidate: Callable[..., Candidate], make_employer: Callable[..., TestUser], now: datetime
) -> None:
    candidate, employer = make_candidate(published=True), make_employer()
    invite(db, employer, candidate, now, DiscloseField.PHONE)
    service.disclose(
        db,
        employer.id,
        candidate.id,
        source=DisclosureSource.APPLICATION,
        ref_id=uuid4(),
        fields=[DiscloseField.LINK],
        now=now,
    )
    assert service.disclosed_map(db, employer.id, [candidate.id]) == {candidate.id: {"email", "phone", "link"}}
    other = make_employer()
    assert service.disclosed_map(db, other.id, [candidate.id]) == {}  # раскрытие — свойство пары


def test_only_chosen_channels_are_returned(
    db: Session, make_candidate: Callable[..., Candidate], make_employer: Callable[..., TestUser], now: datetime
) -> None:
    candidate, employer = make_candidate(published=True), make_employer()
    invite(db, employer, candidate, now, DiscloseField.TELEGRAM)
    contacts = service.contacts_for_pair(db, employer.id, candidate.id)
    assert contacts is not None and not contacts.masked
    assert (contacts.first_name, contacts.last_name, contacts.middle_name) == ("Анна", "Смирнова", "Сергеевна")
    assert contacts.email == candidate.email and contacts.telegram == "@anna_dev"
    assert contacts.phone is None and contacts.link is None
    assert contacts.custom_skills == ["Tarantool"]
    assert contacts.disclosed_fields == [DiscloseField.EMAIL, DiscloseField.TELEGRAM]
    # Те же данные идут в PDF: невыбранных каналов нет и там.
    assert PdfContacts.from_contacts(contacts).model_dump() == {
        "email": candidate.email,
        "phone": None,
        "telegram": "@anna_dev",
        "link": None,
    }
    assert service.display_names(db, employer.id, [candidate.id]) == {candidate.id: "Анна Смирнова"}


def test_about_is_never_given_before_disclosure(
    db: Session, make_candidate: Callable[..., Candidate], make_employer: Callable[..., TestUser], now: datetime
) -> None:
    candidate, employer = make_candidate(published=True), make_employer()
    pool = service.pool_view(db, [candidate.id], now)[candidate.id].model_dump_json()
    assert "Пишу серверный код" not in pool and "anna@example.com" not in pool and "Смирнова" not in pool
    invite(db, employer, candidate, now)
    contacts = service.contacts_for_pair(db, employer.id, candidate.id)
    assert contacts is not None and contacts.about is not None and "Пишу серверный код" in contacts.about
    service.save_privacy(db, candidate.id, PrivacyData(show_about=False), now)
    again = service.contacts_for_pair(db, employer.id, candidate.id)
    assert again is not None and again.about is None  # настройка скрывает «О себе» и от раскрытой пары


def test_filled_channels(db: Session, make_candidate: Callable[..., Candidate]) -> None:
    full = make_candidate()
    assert service.filled_channels(db, full.id) == {"email", "phone", "telegram", "link", "fsp_details"}
    bare = make_candidate(phone=None, telegram=None, link=None)
    assert service.filled_channels(db, bare.id) == {"email", "fsp_details"}


def test_own_contacts_need_complete_profile(
    db: Session, make_candidate: Callable[..., Candidate], now: datetime
) -> None:
    candidate = make_candidate()
    own = service.own_contacts(db, candidate.id)
    assert own.phone == "+79171234567" and own.email == candidate.email and own.disclosed_at is None
    empty = make_candidate(filled=False)
    import pytest

    from app.core.errors import ApiException

    with pytest.raises(ApiException) as error:
        service.own_contacts(db, empty.id)
    assert error.value.code == "profile_incomplete"


# --- GET /employer/candidates/{id}/contacts ------------------------------------------------------------------


def url(candidate: Candidate) -> str:
    return f"/api/v1/employer/candidates/{candidate.id}/contacts"


def test_endpoint_403_before_and_only_chosen_after(
    db: Session,
    client: TestClient,
    login_as: Callable[..., Any],
    make_candidate: Callable[..., Candidate],
    make_employer: Callable[..., TestUser],
    now: datetime,
) -> None:
    candidate, employer = make_candidate(published=True), make_employer()
    login_as(employer)
    response = client.get(url(candidate))
    assert (response.status_code, response.json()["code"]) == (403, "not_disclosed")
    assert client.get(f"/api/v1/employer/candidates/{uuid4()}/contacts").status_code == 404
    invite(db, employer, candidate, now, DiscloseField.PHONE)
    data = client.get(url(candidate)).json()
    assert data["phone"] == "+79171234567" and data["telegram"] is None and data["link"] is None
    assert data["email"] == candidate.email and data["masked"] is False
    assert data["disclosed_fields"] == ["email", "phone"] and "min_salary" not in data and "about" not in data


def test_contacts_viewed_logged_once_a_day(
    db: Session,
    client: TestClient,
    login_as: Callable[..., Any],
    make_candidate: Callable[..., Candidate],
    make_employer: Callable[..., TestUser],
    now: datetime,
    freeze_now: Any,
) -> None:
    candidate, employer = make_candidate(published=True), make_employer()
    invite(db, employer, candidate, now)
    login_as(employer)

    def viewed() -> int:
        return len(db.scalars(select(AccessLog).where(AccessLog.kind == AccessKind.CONTACTS_VIEWED.value)).all())

    client.get(url(candidate))
    client.get(url(candidate))
    assert viewed() == 1
    freeze_now.tick(hours=23)
    client.get(url(candidate))
    assert viewed() == 1
    freeze_now.tick(hours=2)
    client.get(url(candidate))
    assert viewed() == 2


def test_access_log_keeps_company_name_after_employer_deleted(
    db: Session,
    client: TestClient,
    login_as: Callable[..., Any],
    make_candidate: Callable[..., Candidate],
    make_employer: Callable[..., TestUser],
    now: datetime,
) -> None:
    candidate = make_candidate(published=True)
    employer = make_employer(name="ООО «Исчезающая»")
    ref = invite(db, employer, candidate, now)
    service.log_access(db, candidate.id, employer.id, AccessKind.PDF_DOWNLOADED, ref, now + timedelta(minutes=5))
    db.commit()
    db.execute(text("DELETE FROM app_user WHERE id = :id"), {"id": employer.id})  # каскад уносит раскрытие
    login_as(candidate)
    items = client.get("/api/v1/candidate/access-log").json()["items"]
    assert [(i["kind"], i["company_name"]) for i in items] == [
        ("pdf_downloaded", "ООО «Исчезающая»"),
        ("contacts_disclosed", "ООО «Исчезающая»"),
    ]
    assert items[0]["kind_label"] and db.scalars(select(ContactDisclosure)).all() == []


def test_access_log_is_paged_and_resolves_ref_type(
    db: Session,
    client: TestClient,
    login_as: Callable[..., Any],
    make_candidate: Callable[..., Candidate],
    make_employer: Callable[..., TestUser],
    now: datetime,
) -> None:
    candidate, employer = make_candidate(published=True), make_employer()
    ref = invite(db, employer, candidate, now)
    for minute in (1, 2):
        service.log_access(
            db, candidate.id, employer.id, AccessKind.PDF_DOWNLOADED, ref, now + timedelta(minutes=minute)
        )
    login_as(candidate)
    first = client.get("/api/v1/candidate/access-log", params={"limit": 2}).json()
    assert len(first["items"]) == 2 and first["next_cursor"]
    assert first["items"][0]["ref"] == {"type": "invitation", "id": str(ref)}
    second = client.get("/api/v1/candidate/access-log", params={"limit": 2, "cursor": first["next_cursor"]}).json()
    assert [i["kind"] for i in second["items"]] == ["contacts_disclosed"] and second["next_cursor"] is None
    assert client.get("/api/v1/candidate/access-log", params={"cursor": "мусор"}).status_code == 422


def test_other_candidates_log_is_not_visible(
    db: Session,
    client: TestClient,
    login_as: Callable[..., Any],
    make_candidate: Callable[..., Candidate],
    make_employer: Callable[..., TestUser],
    now: datetime,
) -> None:
    mine, other, employer = make_candidate(), make_candidate(published=True), make_employer()
    invite(db, employer, other, now)
    login_as(mine)
    assert client.get("/api/v1/candidate/access-log").json()["items"] == []


# --- маскируемая пара (Арх. 4.14) ----------------------------------------------------------------------------


def test_masked_pair_demo_employer_live_candidate(
    db: Session,
    client: TestClient,
    login_as: Callable[..., Any],
    make_candidate: Callable[..., Candidate],
    make_employer: Callable[..., TestUser],
    now: datetime,
    world: World,
) -> None:
    # Кандидат получил категорию быстрым демо-тестом (чип «демо»), но аккаунт у него живой.
    candidate = make_candidate(published=True)
    world.demo_results.add(candidate.id)
    employer = make_employer(is_demo=True)
    assert service.pool_view(db, [candidate.id], now)[candidate.id].is_demo is True  # чип не влияет на решение
    invite(db, employer, candidate, now, DiscloseField.PHONE, DiscloseField.TELEGRAM, DiscloseField.LINK)

    assert db.scalars(select(ContactDisclosure)).all().__len__() == 1  # раскрытие записано
    assert db.scalars(select(AccessLog).where(AccessLog.kind == "contacts_disclosed")).all().__len__() == 1
    # Снаружи пара выглядит как до раскрытия.
    assert service.is_disclosed(db, employer.id, candidate.id) is False
    assert service.disclosed_map(db, employer.id, [candidate.id]) == {}
    assert service.display_names(db, employer.id, [candidate.id]) == {}

    contacts = service.contacts_for_pair(db, employer.id, candidate.id)
    assert contacts is not None and contacts.masked is True
    for name in ("first_name", "last_name", "middle_name", "about", "email", "phone", "telegram", "link"):
        assert getattr(contacts, name) == MASKED_VALUE
    assert contacts.custom_skills == [] and contacts.disclosed_fields == []

    login_as(employer)
    response = client.get(url(candidate))
    assert response.status_code == 200 and response.json()["masked"] is True
    for secret in ("Анна", "Смирнова", "+7917", "anna_dev", "github.com", candidate.email, "Tarantool"):
        assert secret not in response.text
    assert db.scalars(select(AccessLog).where(AccessLog.kind == "contacts_viewed")).all() == []


def test_masking_depends_on_account_flags_only(
    db: Session, make_candidate: Callable[..., Candidate], make_employer: Callable[..., TestUser], now: datetime
) -> None:
    demo_candidate = make_candidate(published=True, is_demo=True)
    live_employer, demo_employer = make_employer(), make_employer(is_demo=True)
    for employer in (live_employer, demo_employer):
        invite(db, employer, demo_candidate, now)
        contacts = service.contacts_for_pair(db, employer.id, demo_candidate.id)
        assert contacts is not None and contacts.masked is False and contacts.last_name == "Смирнова"
        assert service.is_disclosed(db, employer.id, demo_candidate.id)
    live_candidate = make_candidate(published=True)
    invite(db, live_employer, live_candidate, now)
    contacts = service.contacts_for_pair(db, live_employer.id, live_candidate.id)
    assert contacts is not None and contacts.masked is False


# --- «не показывать компаниям» (P1) --------------------------------------------------------------------------


def test_hidden_domains(
    db: Session,
    client: TestClient,
    login_as: Callable[..., Any],
    make_candidate: Callable[..., Candidate],
    make_user: Callable[..., TestUser],
    world: World,
    now: datetime,
) -> None:
    candidate = make_candidate(published=True)
    employer = make_user("employer", email="hr@current-employer.example.com")
    other = make_user("employer", email="hr@elsewhere.example.com")
    service.save_privacy(
        db, candidate.id, PrivacyData.model_validate({"hidden_domains": ["Current-Employer.example.com"]}), now
    )
    assert service.hidden_from_employer(db, employer.id, [candidate.id]) == {candidate.id}
    assert service.hidden_from_employer(db, other.id, [candidate.id]) == set()
    login_as(employer)
    assert client.get(url(candidate)).status_code == 404
