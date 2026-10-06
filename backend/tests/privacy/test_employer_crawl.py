"""Приватность на сиде (Арх. 10.4): обход всех `GET` роли `employer` до раскрытия контактов.

Работодатель — настоящий (не демо-аккаунт) без единого раскрытия. В его ответах не должно быть ни имени, ни e-mail,
ни телефона, ни Telegram, ни ссылки, ни текста «О себе» кандидатов сида — в том числе «О себе» с контактами, записанными
словами. Каналы появляются только в `…/contacts` и PDF после согласия кандидата.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from app.core import clock
from app.core import db as core_db
from app.modules.company import service as company
from app.modules.company.dto import CompanyData
from app.modules.identity import service as identity
from app.modules.profile import service as profile
from app.shared.enums import ContactKind, Role
from app.shared.schemas import ContactMethod
from tests.seed.support import API, World


def _secrets() -> list[tuple[str, str]]:
    """Значения, которых не должно быть в ответах: (вид, значение) по всем кандидатам сида."""
    found: list[tuple[str, str]] = []
    with core_db.session_scope() as db:
        users = identity.users(db, identity.demo_user_ids(db))
        for user_id, user in users.items():
            if user.role != Role.CANDIDATE:
                continue
            contacts = profile.own_contacts(db, user_id)
            found.append(("email", user.email))
            found.append(("name", f"{contacts.last_name} {contacts.first_name}"))
            found.append(("name", f"{contacts.first_name} {contacts.last_name}"))
            for kind, value in (("phone", contacts.phone), ("telegram", contacts.telegram), ("link", contacts.link)):
                if value:
                    found.append((kind, value))
            if contacts.phone:
                found.append(("phone", re.sub(r"\D", "", contacts.phone)[-10:]))
            if contacts.about:
                found.append(("about", contacts.about[:40]))
    return found


def _live_employer(world: World) -> Any:
    with core_db.session_scope() as db:
        employer = identity.create_user(
            db, f"live-{uuid4().hex[:6]}@example.com", "Live-pass-2026", Role.EMPLOYER,
            verified=True, is_demo=False, demo_key=None,
        )  # fmt: skip
        company.save_company(
            db,
            employer,
            CompanyData(
                name="Живая компания", sphere="Разработка",
                description="Разрабатываем внутренние сервисы для логистики, команда из двадцати человек.",
                contact_method=ContactMethod(kind=ContactKind.EMAIL, value="hr@example.com"),
            ),
            clock.now(db),
        )  # fmt: skip
        token = identity.create_session(db, employer)
    client = world.client()
    client.cookies.set("sid", token)
    return client


def test_employer_get_endpoints_do_not_leak_undisclosed_candidate_data(seeded: World) -> None:
    secrets = _secrets()
    assert len(secrets) > 600
    client = _live_employer(seeded)
    need = client.post(
        f"{API}/employer/needs",
        json={
            "title": "Backend-разработчик", "team_description": "Команда из шести человек, платёжное ядро.",
            "specialization_code": "backend", "grade_code": "middle", "must_skills": ["python"],
            "nice_skills": ["postgresql"], "work_formats": ["remote"], "salary_from": 200000, "salary_to": 260000,
        },
    )  # fmt: skip
    assert need.status_code == 201, need.text
    need_id = need.json()["id"]
    snapshot = client.post(f"{API}/employer/needs/{need_id}/shortlists").json()
    items = snapshot["items"]
    assert len(items) >= 10
    candidate_ids = [item["candidate_id"] for item in items][:25]
    sent = client.post(
        f"{API}/employer/invitations",
        json={
            "candidate_id": candidate_ids[0], "need_id": need_id, "snapshot_id": snapshot["id"],
            "title": "Backend-разработчик", "description": "Развивать платёжное ядро: Python, PostgreSQL, очереди.",
            "salary_from": 200000, "salary_to": 260000, "work_format": "remote",
            "contact_method": {"kind": "email", "value": "hr@example.com"},
        },
        headers={"Idempotency-Key": str(uuid4())},
    )  # fmt: skip
    assert sent.status_code == 201, sent.text
    values = {
        "need_id": need_id, "snapshot_id": snapshot["id"], "base": snapshot["id"], "invitation_id": sent.json()["id"],
        "candidate_id": candidate_ids[0], "candidate_ids": ",".join(candidate_ids),
    }  # fmt: skip

    visited = 0
    unresolved: list[str] = []
    for path, operations in seeded.app.openapi()["paths"].items():
        get = operations.get("get")
        if get is None or "/employer/" not in path:
            continue
        names = re.findall(r"{(\w+)}", path)
        if any(name not in values for name in names):
            unresolved.append(path)
            continue
        params = {
            p["name"]: values[p["name"]] for p in get.get("parameters", []) if p["in"] == "query" and p.get("required")
        }
        for name in names:
            targets = candidate_ids if name == "candidate_id" else [values[name]]
            for target in targets:
                url = f"{API}{path.removeprefix('/api/v1')}".replace(f"{{{name}}}", target)
                url = re.sub(r"{(\w+)}", lambda m: values[m.group(1)], url)
                reply = client.get(
                    url,
                    params={**params, "candidate_id": target}
                    if name == "candidate_id" and "candidate_id" in params
                    else params,
                )
                visited += 1
                assert reply.status_code < 500, (url, reply.text[:200])
                if url.endswith(("/contacts", "/pdf")):
                    assert reply.status_code in (403, 404), url
                leaked = [kind for kind, value in secrets if value in reply.text]
                assert not leaked, (url, leaked[:3])
        if not names:
            reply = client.get(f"{API}{path.removeprefix('/api/v1')}", params=params)
            visited += 1
            assert reply.status_code < 500, (path, reply.text[:200])
            leaked = [kind for kind, value in secrets if value in reply.text]
            assert not leaked, (path, leaked[:3])
    assert not unresolved, unresolved
    assert visited >= 30
    # Контроль самой проверки: профиль самого кандидата те же значения содержит, и она их находит.
    own = seeded.login_direct("cand_001").get(f"{API}/candidate/profile")
    assert own.status_code == 200 and [kind for kind, value in secrets if value in own.text]
    bank = client.get(f"{API}/employer/candidates", params={"specialization": "backend", "limit": 50})
    assert bank.status_code == 200 and not [k for k, v in secrets if v in bank.text]
