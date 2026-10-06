"""Сквозной сценарий на настоящих фасадах `identity`, `company` и `profile` (Арх. 2.5).

Подменяются только `assessment` (категория кандидата) и `matching.explain_for_invitation`: эти модули пишутся
параллельно. Тест ловит расхождения сигнатур и договорённостей с соседями, которых не видно на подменах.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import text

from app.modules.assessment import service as assessment_service
from app.modules.catalog import service as catalog_service
from app.modules.company import service as company_service
from app.modules.company.dto import CompanyData
from app.modules.identity import service as identity_service
from app.modules.matching import service as matching_service
from app.modules.matching.dto import InvitationExplain, InvitationWhy
from app.modules.profile import service as profile_service
from app.modules.profile.dto import ConditionsData, ProfileData
from app.shared.enums import ConsentKind, ContactKind, WorkFormat
from app.shared.schemas import ContactMethod
from tests.contact.conftest import World, category_ref, offer

API = "/api/v1"


def test_bounce_send_accept_on_real_lower_modules(
    db, client, make_client, login_as, make_user, monkeypatch, freeze_now
):
    now = freeze_now("2026-10-01T09:00:00+00:00")
    fake = World()
    monkeypatch.setattr(assessment_service, "get_category", lambda db_, cid: fake._category(cid))
    monkeypatch.setattr(
        assessment_service,
        "get_categories",
        lambda db_, cids: {cid: cat for cid in cids if (cat := fake._category(cid)) is not None},
    )
    monkeypatch.setattr(catalog_service, "category_ref", category_ref)
    monkeypatch.setattr(
        matching_service,
        "explain_for_invitation",
        lambda db_, eid, cid, need_id, snapshot_id, now_: InvitationExplain(
            why=InvitationWhy(source="bank", target=category_ref("backend:middle")), scorer_version="test"
        ),
    )

    candidate = make_user("candidate")
    fake.add_candidate(candidate.id)
    profile_service.save_profile(
        db, candidate.id, ProfileData(last_name="Петрова", first_name="Анна", phone="+7 900 000-00-00"), now
    )
    profile_service.save_conditions(
        db, candidate.id, ConditionsData(min_salary=200_000, work_formats=[WorkFormat.REMOTE]), now
    )
    version = identity_service.current_consent(ConsentKind.PUBLICATION).version
    assert profile_service.set_publication(db, candidate.id, granted=True, version=version, now=now).state == "visible"

    employers = [make_user("employer"), make_user("employer")]
    for employer in employers:
        company_service.save_company(
            db,
            employer.id,
            CompanyData(
                name="Орбита",
                sphere="Финтех",
                description="Платёжные сервисы для малого бизнеса: эквайринг, выплаты и аналитика.",
                contact_method=ContactMethod(kind=ContactKind.EMAIL, value="hr@example.com"),
            ),
            now,
        )
    db.commit()

    low = login_as(employers[0])
    bounced = low.post(
        f"{API}/employer/invitations", json=offer(candidate.id), headers={"Idempotency-Key": str(uuid4())}
    )
    assert bounced.status_code == 201 and bounced.json()["status"] == "bounced", bounced.text
    high = login_as(employers[1], client=make_client())
    sent = high.post(
        f"{API}/employer/invitations",
        json=offer(candidate.id, salary_from=200_000, salary_to=260_000),
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert sent.status_code == 201 and sent.json()["status"] == "sent", sent.text
    assert sent.json()["candidate"]["display_name"] is None
    assert "Петрова" not in sent.text and "+7 900" not in sent.text

    inbox = login_as(candidate, client=make_client())
    listed = inbox.get(f"{API}/candidate/invitations").json()["items"]
    assert [item["id"] for item in listed] == [sent.json()["id"]]
    view = inbox.get(f"{API}/candidate/invitations/{listed[0]['id']}").json()
    assert view["below_my_min"] is False
    options = {o["field"]: (o["available"], o["default"]) for o in view["disclose_options"]}
    assert options["email"] == (True, True) and options["phone"] == (True, False) and options["telegram"][0] is False
    accepted = inbox.post(
        f"{API}/candidate/invitations/{listed[0]['id']}/accept", json={"disclose": ["email", "phone"]}
    )
    assert accepted.status_code == 200 and accepted.json()["disclosed"] == ["email", "phone"], accepted.text

    after = high.get(f"{API}/employer/invitations/{listed[0]['id']}").json()
    assert after["status"] == "accepted" and after["candidate"]["display_name"] == "Анна Петрова"
    contacts = profile_service.contacts_for_pair(db, employers[1].id, candidate.id)
    assert contacts is not None and contacts.phone and contacts.email == candidate.email
    assert profile_service.contacts_for_pair(db, employers[0].id, candidate.id) is None
    logged = (
        db.execute(text("SELECT kind FROM access_log WHERE candidate_id = :c"), {"c": candidate.id}).scalars().all()
    )
    assert logged == ["contacts_disclosed"]  # одна запись: её пишет profile.disclose
