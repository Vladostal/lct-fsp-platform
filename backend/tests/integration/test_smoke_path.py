"""Сквозной сценарий на настоящих модулях без подмен (I90): кандидат и работодатель доходят до обмена контактами.

Кандидат: регистрация, подтверждение адреса, профиль и условия, опрос, заявленный грейд, тест до результата с верными
ответами, категория, согласие на публикацию. Работодатель: регистрация, компания, потребность, подборка (в ней этот
кандидат), карточка без контактов, приглашение с вилкой; кандидат принимает с выбором канала, работодатель получает
контакты. Банк заданий — настоящий (31 семейство), письма — настоящие шаблоны из `mailbox`.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.modules.assessment import repo, seeding, sessions
from app.modules.assessment.bank import build_if_empty
from app.modules.assessment.config import get_config
from app.modules.assessment.models import VariantRow
from app.modules.catalog import service as catalog
from app.modules.identity import service as identity_service
from app.shared.enums import ConsentKind

API = "/api/v1"
PASSWORD = "Smoke-pass-2026"
TOKEN = re.compile(r"token=([A-Za-z0-9_-]+)")


@pytest.fixture(autouse=True)
def _real_bank(db: Session, monkeypatch: pytest.MonkeyPatch, override_settings) -> None:
    """Настоящий банк (шаг инициализации стенда) в транзакции теста; доступность пар возвращается после теста."""
    monkeypatch.setattr(catalog, "_available", set(catalog._available))
    override_settings(signup_ip_limit_per_hour=100)
    build_if_empty()
    repo.refresh_availability(db)


def register(client: Any, mailbox: list, email: str, role: str) -> dict[str, Any]:
    body = {
        "email": email,
        "password": PASSWORD,
        "role": role,
        "consent_processing": True,
        "consent_version": identity_service.current_consent(ConsentKind.PROCESSING).version,
        "is_adult": True,
    }
    assert client.post(f"{API}/auth/signup", json=body).status_code == 202
    letter = [m for m in mailbox if m.template == "verify_email" and m.to == email][-1]
    verified = client.post(f"{API}/auth/verify-email", json={"token": TOKEN.search(letter.text).group(1)})
    assert verified.status_code == 200, verified.text
    me = client.get(f"{API}/auth/me").json()
    assert me["role"] == role and me["email"] == email
    return me


def test_candidate_to_employer_contacts(db: Session, make_client, mailbox, freeze_now) -> None:
    freeze_now("2026-10-01T09:00:00+00:00")

    # --- кандидат ----------------------------------------------------------------------------------------------
    cand = make_client()
    me = register(cand, mailbox, "smoke.candidate@example.com", "candidate")
    candidate_id = me["id"]

    profile = cand.put(
        f"{API}/candidate/profile",
        json={
            "last_name": "Смирнова",
            "first_name": "Ольга",
            "phone": "+7 900 111-22-33",
            "city": "Москва",
            "experience_years": 3,
            "roles": [],
            "declared_skills": [{"code": "python"}, {"code": "postgresql"}],
        },
    )
    assert profile.status_code == 200, profile.text
    public_code = profile.json()["public_code"]
    cond = cand.put(
        f"{API}/candidate/conditions",
        json={"min_salary": 200000, "work_formats": ["remote", "hybrid"], "relocation_ready": False},
    )
    assert cond.status_code == 200, cond.text

    version = get_config().survey_version
    survey = {
        "direction": "development",
        "specialization": "backend",
        "main_language": "python",
        "experience_band": "2_4",
        "industry_domains": ["fintech"],
    }
    assert cand.put(f"{API}/assessment/survey", json={"version": version, "answers": survey}).status_code == 200
    claim = cand.put(f"{API}/assessment/claim", json={"grade_code": "middle"})
    assert claim.status_code == 200, claim.text

    started = cand.post(f"{API}/assessment/sessions", json={"grade_code": "middle"})
    assert started.status_code == 201, started.text
    sid, item, answered = started.json()["id"], started.json()["item"], 0
    while item is not None:
        row = db.get(VariantRow, next(i for i in sessions.session_items(db, sid) if str(i.id) == item["id"]).variant_id)
        reply = cand.post(
            f"{API}/assessment/sessions/{sid}/answers",
            json={"item_id": item["id"], "answer": seeding.correct_raw(row), "skipped": False},
            headers={"Idempotency-Key": f"{sid}:{item['id']}"},
        )
        assert reply.status_code == 200, reply.text
        answered += 1
        item = reply.json()["next_item"]
    result = cand.get(f"{API}/assessment/sessions/{sid}/result")
    assert result.status_code == 200 and result.json()["category"]["code"] == "backend:middle", result.text
    assert cand.get(f"{API}/assessment/state").json()["category"]["code"] == "backend:middle"

    pub_version = identity_service.current_consent(ConsentKind.PUBLICATION).version
    granted = cand.post(f"{API}/candidate/consents/publication", json={"action": "grant", "version": pub_version})
    assert granted.status_code == 200 and granted.json()["state"] == "visible", granted.text

    # --- работодатель ------------------------------------------------------------------------------------------
    emp = make_client()
    register(emp, mailbox, "smoke.employer@example.com", "employer")
    company = emp.put(
        f"{API}/employer/company",
        json={
            "name": "Орбита",
            "sphere": "Финтех",
            "description": "Платёжные сервисы для малого бизнеса: эквайринг, выплаты и аналитика.",
            "contact_method": {"kind": "email", "value": "hr@example.com"},
        },
    )
    assert company.status_code == 200, company.text

    need = emp.post(
        f"{API}/employer/needs",
        json={
            "title": "Backend-разработчик в платежи",
            "team_description": "Команда из шести человек, платёжное ядро.",
            "specialization_code": "backend",
            "grade_code": "middle",
            "must_skills": ["python"],
            "nice_skills": ["postgresql"],
            "work_formats": ["remote"],
            "salary_from": 220000,
            "salary_to": 280000,
        },
    )
    assert need.status_code == 201, need.text
    need_id = need.json()["id"]

    shortlist = emp.post(f"{API}/employer/needs/{need_id}/shortlists")
    assert shortlist.status_code in (200, 201), shortlist.text
    snapshot = shortlist.json()
    items = snapshot["items"]
    assert [i for i in items if i["candidate_id"] == candidate_id], snapshot
    snapshot_id = snapshot["id"]
    assert (
        "Смирнова" not in shortlist.text and "+7 900" not in shortlist.text and "smoke.candidate" not in shortlist.text
    )

    card = emp.get(f"{API}/employer/candidates/{candidate_id}", params={"need_id": need_id, "snapshot_id": snapshot_id})
    assert card.status_code == 200, card.text
    assert "Смирнова" not in card.text and "+7 900" not in card.text and "smoke.candidate" not in card.text
    assert public_code in card.text
    assert emp.get(f"{API}/employer/candidates/{candidate_id}/contacts").status_code in (403, 404)

    sent = emp.post(
        f"{API}/employer/invitations",
        json={
            "candidate_id": candidate_id,
            "need_id": need_id,
            "snapshot_id": snapshot_id,
            "title": "Backend-разработчик в платежи",
            "description": "Развивать платёжное ядро: Python, PostgreSQL, очереди. Команда из шести человек.",
            "salary_from": 220000,
            "salary_to": 280000,
            "work_format": "remote",
            "contact_method": {"kind": "email", "value": "hr@example.com"},
            "message": "Будем рады пообщаться",
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert sent.status_code == 201 and sent.json()["status"] == "sent", sent.text
    invitation_id = sent.json()["id"]
    assert sent.json()["candidate"]["display_name"] is None

    # --- кандидат принимает ------------------------------------------------------------------------------------
    listed = cand.get(f"{API}/candidate/invitations").json()["items"]
    assert [i["id"] for i in listed] == [invitation_id]
    view = cand.get(f"{API}/candidate/invitations/{invitation_id}").json()
    assert view["below_my_min"] is False and view["salary_from"] == 220000
    options = {o["field"]: o["available"] for o in view["disclose_options"]}
    assert options["email"] and options["phone"]
    accepted = cand.post(f"{API}/candidate/invitations/{invitation_id}/accept", json={"disclose": ["email", "phone"]})
    assert accepted.status_code == 200 and accepted.json()["disclosed"] == ["email", "phone"], accepted.text

    # --- работодатель получает контакты -------------------------------------------------------------------------
    after = emp.get(f"{API}/employer/invitations/{invitation_id}").json()
    assert after["status"] == "accepted" and after["candidate"]["display_name"] == "Ольга Смирнова"
    contacts = emp.get(f"{API}/employer/candidates/{candidate_id}/contacts")
    assert contacts.status_code == 200, contacts.text
    assert contacts.json()["phone"] and "900" in contacts.text and "smoke.candidate@example.com" in contacts.text

    stray = make_client()
    register(stray, mailbox, "smoke.other@example.com", "employer")
    assert stray.get(f"{API}/employer/candidates/{candidate_id}/contacts").status_code in (403, 404)
