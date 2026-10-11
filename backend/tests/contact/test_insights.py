"""Предпроверка, «два мира», состояние пар, медиана вилок, сводки, демо-ответчик, исход и жалоба (P1)."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import event, select

from app.modules.contact import constants as c
from app.modules.contact import service
from app.modules.contact.dto import DeclineCondition
from app.modules.contact.models import EmployerContactState, Invitation, InvitationEvent
from app.modules.matching.dto import ExposureStats
from app.shared.enums import ComplaintReason, ConditionKind, DeclineReason, FitBand, InvitationStatus, VisibilityState
from tests.contact.conftest import offer, send

API = "/api/v1"


def test_two_worlds_differ_only_in_created_status_i8(db, client, login_as, actors, world, now):
    """Ответы работодателю не зависят от `min_salary`, кроме статуса созданного приглашения."""
    pair = actors.pair()
    other = actors.candidate()
    send(db, now, pair.employer.id, other.id)
    login_as(pair.employer)
    urls = [
        f"/employer/invitations/precheck?candidate_id={pair.candidate.id}",
        "/employer/invitations",
        "/employer/invitations/quota",
        "/employer/invitations/stats",
        f"/employer/invitations/pair-states?candidate_ids={pair.candidate.id},{other.id}",
        "/contact/salary-hint?category=backend:middle",
    ]

    def snapshot():
        return [client.get(API + url).json() for url in urls]

    world.candidates[pair.candidate.id].min_salary = None
    low = snapshot()
    calls = len(world.min_salary_calls)
    world.candidates[pair.candidate.id].min_salary = 600_000
    high = snapshot()
    assert low == high
    assert len(world.min_salary_calls) == calls  # предпроверка и списки минимум не читают вовсе

    results = {}
    for name, minimum in (("high", 600_000), ("none", None)):
        nested = db.begin_nested()
        world.candidates[pair.candidate.id].min_salary = minimum
        response = client.post(
            f"{API}/employer/invitations", json=offer(pair.candidate.id), headers={"Idempotency-Key": str(uuid4())}
        )
        body = response.json()
        results[name] = (response.status_code, body.pop("status"), body.pop("status_label"))
        if nested.is_active:
            nested.rollback()
        db.execute(Invitation.__table__.delete().where(Invitation.candidate_id == pair.candidate.id))
        db.commit()
    assert results["high"][:2] == (201, "bounced") and results["none"][:2] == (201, "sent")


def test_precheck_hidden_candidate_and_unknown(db, client, login_as, actors, world, now):
    employer = actors.employer()
    visible = actors.candidate()
    hidden = actors.candidate(state=VisibilityState.UNPUBLISHED)
    login_as(employer)
    ok = client.get(f"{API}/employer/invitations/precheck?candidate_id={visible.id}").json()
    assert ok["can_invite"] is True and ok["blockers"] == [] and ok["candidate_formats"] == ["remote", "hybrid"]
    assert ok["expires_at_preview"].startswith((now + c.INVITATION_TTL).isoformat()[:19])
    assert ok["pair"] == {"block_until": None, "can_revise": False, "revises_id": None, "condition": None}
    responses = [
        client.get(f"{API}/employer/invitations/precheck?candidate_id={candidate_id}").json()
        for candidate_id in (hidden.id, uuid4(), employer.id)
    ]
    for body in responses:
        assert body["can_invite"] is False and body["candidate_formats"] == []
        assert [b["code"] for b in body["blockers"]] == ["candidate_unavailable"]
    assert responses[0] == responses[1] == responses[2]  # скрытый неотличим от несуществующего
    assert (
        client.get(f"{API}/employer/invitations/precheck?candidate_id={visible.id}&need_id={uuid4()}").status_code
        == 404
    )
    assert "min_salary" not in str(ok) and "salary_ok" not in str(ok)


def test_pair_states_for_100_ids_in_one_query(db, client, login_as, actors, world, now, engine):
    employer = actors.employer(trust="verified")
    invited = [actors.candidate() for _ in range(3)]
    sent = [send(db, now, employer.id, candidate.id) for candidate in invited]
    service.decline_invitation(db, now, invited[1].id, sent[1].id, DeclineReason.OTHER)
    bounced = actors.candidate(min_salary=500_000)
    send(db, now, employer.id, bounced.id)
    db.commit()
    ids = [c_.id for c_ in invited] + [bounced.id] + [uuid4() for _ in range(96)]
    login_as(employer)

    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if "FROM invitation" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        response = client.get(f"{API}/employer/invitations/pair-states?candidate_ids={','.join(map(str, ids))}")
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert response.status_code == 200 and len(statements) == 1
    items = response.json()["items"]
    assert [item["candidate_id"] for item in items] == [str(i) for i in ids]
    assert items[0]["invitation"]["status"] == "sent" and items[0]["pair_block"] is None
    assert items[1]["pair_block"]["code"] == "pair_cooldown"
    assert items[3]["invitation"]["status"] == "bounced" and items[3]["pair_block"]["code"] == "conditions_mismatch"
    assert items[4] == {"candidate_id": str(ids[4]), "invitation": None, "pair_block": None, "interest": False}
    too_many = ",".join(str(uuid4()) for _ in range(101))
    assert client.get(f"{API}/employer/invitations/pair-states?candidate_ids={too_many}").status_code == 422
    assert client.get(f"{API}/employer/invitations/pair-states?candidate_ids=abc").status_code == 422


def test_salary_hint_thresholds(db, client, make_client, login_as, actors, world, now):
    """`SALARY_HINT_MIN_N = 10` принятых приглашений категории от `SALARY_HINT_MIN_EMPLOYERS = 3` работодателей."""
    employers = [actors.employer(trust="verified") for _ in range(3)]
    viewer = login_as(employers[0])

    def accept_one(employer, salary_from, category="backend:middle"):
        candidate = actors.candidate(category=category)
        sent = send(db, now, employer.id, candidate.id, salary_from=salary_from, salary_to=salary_from + 40_000)
        service.accept_invitation(db, now, candidate.id, sent.id)
        db.commit()
        return candidate

    for index in range(9):
        last = accept_one(employers[index % 2], 100_000 + index * 10_000)
    url = f"{API}/contact/salary-hint?category=backend:middle"
    assert viewer.get(url).json() is None  # девять приглашений — мало
    accept_one(employers[1], 190_000)
    assert viewer.get(url).json() is None  # десять, но работодателей два
    accept_one(employers[2], 200_000, category="frontend:junior")
    assert viewer.get(url).json() is None  # третий работодатель — в другой категории
    accept_one(employers[2], 200_000)
    assert viewer.get(url).json() == {"from": 150_000, "to": 190_000}
    assert viewer.get(f"{API}/contact/salary-hint?category=frontend:junior").json() is None
    assert viewer.get(f"{API}/contact/salary-hint").status_code == 422
    assert viewer.get(f"{API}/contact/salary-hint?category=bad code").status_code == 422
    assert make_client().get(url).status_code == 401
    # Кандидату категория не нужна: берётся его собственная. Тот же ориентир — в предпроверке.
    assert login_as(last, client=make_client()).get(f"{API}/contact/salary-hint").json() == {
        "from": 150_000,
        "to": 190_000,
    }
    fresh = actors.candidate()
    precheck = viewer.get(f"{API}/employer/invitations/precheck?candidate_id={fresh.id}").json()
    assert precheck["salary_hint"] == {"from": 150_000, "to": 190_000}


def test_stats_and_need_insights(db, client, login_as, actors, world, now, monkeypatch):
    from app.modules.matching import service as matching_service
    from app.modules.matching.dto import RelaxationHint, ShortlistRefinement

    employer = actors.employer(trust="verified")
    need_id = world.add_need(employer.id)
    asked: list[set[str]] = []

    def hints(db_, employer_id, need, kinds, now_):
        asked.append(set(kinds))
        return [
            RelaxationHint(
                code="add_format",
                value="remote",
                text="Добавьте удалённый формат",
                gain=4,
                refinement=ShortlistRefinement(),
            )
        ]

    monkeypatch.setattr(matching_service, "relaxation_hints", hints)
    for index in range(3):
        candidate = actors.candidate()
        sent = send(db, now, employer.id, candidate.id, need_id=str(need_id), work_format="hybrid", city="Москва")
        service.decline_invitation(
            db,
            now + timedelta(hours=index + 1),
            candidate.id,
            sent.id,
            DeclineReason.FORMAT,
            DeclineCondition(kind=ConditionKind.WORK_FORMAT, value="remote"),
        )
    for value in (180_000, 180_000, 200_000):
        candidate = actors.candidate()
        sent = send(db, now, employer.id, candidate.id, need_id=str(need_id))
        service.decline_invitation(
            db,
            now,
            candidate.id,
            sent.id,
            DeclineReason.SALARY,
            DeclineCondition(kind=ConditionKind.SALARY_FROM, value=value),
        )
    send(db, now, employer.id, actors.candidate(min_salary=400_000).id, need_id=str(need_id))
    send(db, now, employer.id, actors.candidate().id)
    db.commit()
    login_as(employer)
    insights = client.get(f"{API}/employer/needs/{need_id}/insights").json()
    assert insights["funnel"] == {
        "delivered": 6, "not_delivered": 1, "viewed": 0, "accepted": 0, "declined": 6, "expired": 0, "withdrawn": 0,
    }  # fmt: skip
    assert {r["reason_code"]: r["count"] for r in insights["reasons"]} == {"salary": 3, "format": 3}
    assert insights["stated_salary"] == [{"value": 180_000, "count": 2}, {"value": 200_000, "count": 1}]
    assert insights["stated_formats"] == [{"value": "remote", "count": 3}]
    assert asked == [{"add_format"}] and insights["hints"][0]["gain"] == 4
    assert "3 кандидата назвали сумму от 180 000" in insights["salary_note"].replace("\xa0", " ")
    assert client.get(f"{API}/employer/needs/{uuid4()}/insights").status_code == 404

    stats = client.get(f"{API}/employer/invitations/stats").json()
    assert stats["total"]["delivered"] == 7 and stats["total"]["not_delivered"] == 1
    assert stats["by_need"] == [{"need_id": str(need_id), "funnel": insights["funnel"], "awaiting": 0, "updates": 6}]
    assert stats["median_response_hours"] is not None


def test_candidate_funnel_stages(db, client, login_as, actors, world, now):
    candidate = actors.candidate()
    login_as(candidate)
    assert client.get(f"{API}/candidate/funnel").json()["stage"] == "not_shown"
    world.exposure = ExposureStats(needs_shown=4, employers_opened=0, unconfirmed_must=["sql", "sql", "sql", "docker"])
    funnel = client.get(f"{API}/candidate/funnel").json()
    assert (funnel["stage"], funnel["shown"]) == ("not_opened", 4)
    assert funnel["missing_skill"] == {"skill": {"code": "sql", "title": "Sql"}, "needs": 3}
    world.exposure = ExposureStats(needs_shown=4, employers_opened=2)
    assert client.get(f"{API}/candidate/funnel").json()["stage"] == "not_invited"
    send(db, now, actors.employer().id, candidate.id)
    assert client.get(f"{API}/candidate/funnel").json()["stage"] == "ok"
    world.candidates[candidate.id].state = VisibilityState.PAUSED
    assert client.get(f"{API}/candidate/funnel").json()["stage"] == "hidden"


# --- демо-ответчик --------------------------------------------------------------------------------------------------


def test_demo_responder_personas(db, actors, world, now, override_settings):
    """Персоны отвечают только в фоновом цикле и по своему расписанию (Арх. 4.14)."""
    employer = actors.employer(is_demo=True)
    personas = {
        name: actors.candidate(is_demo=True, persona=name)
        for name in ("responsive", "selective", "expensive", "silent")
    }
    live = actors.candidate(persona="responsive")  # не демо-аккаунт: ответчик его не трогает
    world.fit_band = FitBand.GOOD
    sent = {name: send(db, now, employer.id, user.id, is_demo=True) for name, user in personas.items()}
    live_sent = send(db, now, actors.employer().id, live.id)

    def statuses():
        db.expire_all()
        return {name: db.get(Invitation, inv.id).status for name, inv in sent.items()}

    service.settle_all(db, now + timedelta(seconds=19))
    assert set(statuses().values()) == {"sent"}
    service.settle_all(db, now + timedelta(seconds=30))
    assert statuses() == {"responsive": "viewed", "selective": "sent", "expensive": "viewed", "silent": "sent"}
    service.settle_all(db, now + timedelta(seconds=60))
    assert statuses() == {"responsive": "accepted", "selective": "viewed", "expensive": "viewed", "silent": "sent"}
    service.settle_all(db, now + timedelta(seconds=90))
    assert statuses() == {"responsive": "accepted", "selective": "declined", "expensive": "declined", "silent": "sent"}
    db.expire_all()
    expensive = db.get(Invitation, sent["expensive"].id)
    assert (expensive.decline_reason, expensive.decline_condition_salary_from) == ("salary", 180_000)
    assert db.get(Invitation, sent["selective"].id).decline_reason == "stack"
    assert db.get(Invitation, live_sent.id).status == "sent"
    events = db.scalars(
        select(InvitationEvent)
        .where(InvitationEvent.invitation_id == sent["responsive"].id)
        .order_by(InvitationEvent.id)
    ).all()
    assert [(e.code, e.payload.get("demo")) for e in events] == [("sent", True), ("viewed", True), ("accepted", True)]
    assert events[2].at == now + timedelta(seconds=60)
    assert [d["candidate_id"] for d in world.disclosures] == [personas["responsive"].id]

    # Пересмотренное приглашение, выполняющее названное условие, персона `expensive` принимает.
    data = offer(personas["expensive"].id, revises_id=str(sent["expensive"].id), salary_from=180_000, salary_to=220_000)
    from app.modules.contact.dto import InvitationData

    revised = service.send_invitation(
        db, now + timedelta(seconds=100), employer.id, InvitationData.model_validate(data), str(uuid4()), is_demo=True
    )
    service.settle_all(db, now + timedelta(seconds=180))
    db.expire_all()
    assert db.get(Invitation, revised.id).status == "accepted"

    # При DEMO_MODE=false ответчик не вызывается, а истечение материализуется как обычно.
    override_settings(demo_mode=False)
    late = actors.candidate(is_demo=True, persona="responsive")
    late_sent = send(db, now + timedelta(days=1), employer.id, late.id, is_demo=True)
    service.settle_all(db, now + timedelta(days=2))
    db.expire_all()
    assert db.get(Invitation, late_sent.id).status == "sent"
    service.settle_all(db, late_sent.expires_at)
    db.expire_all()
    assert db.get(Invitation, late_sent.id).status == "expired"
    assert db.get(Invitation, sent["silent"].id).status == "expired"


def test_responder_runs_only_in_background_cycle(db, client, login_as, actors, world, now, freeze_now):
    employer = actors.employer(is_demo=True)
    candidate = actors.candidate(is_demo=True, persona="responsive")
    sent = send(db, now, employer.id, candidate.id, is_demo=True)
    freeze_now.tick(hours=1)
    login_as(employer)
    for _ in range(2):
        assert client.get(f"{API}/employer/invitations/{sent.id}").json()["status"] == "sent"
    other = actors.candidate(is_demo=True)
    response = client.post(
        f"{API}/employer/invitations", json=offer(other.id), headers={"Idempotency-Key": str(uuid4())}
    )
    assert response.status_code == 201
    db.expire_all()
    assert db.get(Invitation, sent.id).status == "sent"


# --- P1: исход, жалоба, заморозка, показатели -----------------------------------------------------------------------


def test_outcome_complaint_freeze_and_metrics(
    db, client, make_client, login_as, actors, world, now, freeze_now, settings
):
    employer = actors.employer(trust="verified")
    candidates = [actors.candidate() for _ in range(4)]
    sent = [send(db, now, employer.id, candidate.id) for candidate in candidates]
    for candidate, inv in zip(candidates[:3], sent[:3], strict=True):
        service.accept_invitation(db, now, candidate.id, inv.id)
    db.commit()
    employer_client = login_as(employer)
    first = login_as(candidates[0], client=make_client())

    # Исход отмечается только по принятому приглашению.
    pending = login_as(candidates[3], client=make_client())
    refused = pending.post(f"{API}/candidate/invitations/{sent[3].id}/outcome", json={"contacted": True})
    assert (refused.status_code, refused.json()["code"]) == (409, "invitation_not_actionable")
    marked = employer_client.post(f"{API}/employer/invitations/{sent[0].id}/outcome", json={"contacted": True}).json()
    assert marked["outcome"] == {"employer_contacted": True, "candidate_contacted": None}
    assert first.get(f"{API}/candidate/invitations/{sent[0].id}").json()["outcome_prompt"] is False
    freeze_now.tick(hours=80)
    assert first.get(f"{API}/candidate/invitations/{sent[0].id}").json()["outcome_prompt"] is True
    assert first.get(f"{API}/candidate/invitations/summary").json()["outcome_prompts"] == 1
    answered = first.post(
        f"{API}/candidate/invitations/{sent[0].id}/outcome", json={"contacted": True, "terms_matched": False}
    ).json()
    assert answered["outcome"] == {"candidate_contacted": True, "candidate_terms_matched": False}
    assert answered["outcome_prompt"] is False
    assert [e["code"] for e in answered["timeline"]][-2:] == ["contact_marked", "contact_confirmed"]

    # Жалоба — одна на приглашение; работодатель её не видит.
    second = login_as(candidates[1], client=make_client())
    complaint = second.post(
        f"{API}/candidate/invitations/{sent[1].id}/complaint", json={"reason_code": "spam", "comment": "Рассылка"}
    )
    assert complaint.status_code == 200 and complaint.json()["can_complain"] is False
    again = second.post(f"{API}/candidate/invitations/{sent[1].id}/complaint", json={"reason_code": "spam"})
    assert (again.status_code, again.json()["code"]) == (409, "complaint_exists")
    employer_view = employer_client.get(f"{API}/employer/invitations/{sent[1].id}")
    assert "complaint" not in employer_view.text
    assert service.events_since(db, employer.id, 0, 100)[-1].code != "complaint_filed"
    assert employer_client.get(f"{API}/employer/invitations/quota").json()["frozen"] is False

    # Третий сигнал от третьего кандидата (ответ «условия не совпали» считается наравне с жалобой) — заморозка.
    service.file_complaint(db, freeze_now.current, candidates[2].id, sent[2].id, ComplaintReason.RUDE)
    db.commit()
    assert employer_client.get(f"{API}/employer/invitations/quota").json()["frozen"] is True
    blocked = employer_client.post(
        f"{API}/employer/invitations", json=offer(actors.candidate().id), headers={"Idempotency-Key": str(uuid4())}
    )
    assert (blocked.status_code, blocked.json()["code"]) == (403, "sending_frozen")

    # Разбор жалобы: без служебного токена — отказ; `unfreeze` снимает заморозку.
    assert client.get(f"{API}/admin/complaints").status_code in (401, 403)
    admin = make_client()
    headers = {"X-Admin-Token": settings.admin_token}
    listed = admin.get(f"{API}/admin/complaints", headers=headers).json()
    assert len(listed) == 2 and all(item["employer_frozen"] and item["company_name"] == "Орбита" for item in listed)
    resolved = admin.post(
        f"{API}/admin/complaints/{listed[0]['id']}/resolve",
        json={"status": "dismissed", "unfreeze": True},
        headers=headers,
    )
    assert resolved.status_code == 200 and resolved.json()["status"] == "dismissed"
    assert resolved.json()["employer_frozen"] is False
    db.expire_all()
    assert db.get(EmployerContactState, employer.id).sending_frozen_at is None
    assert (
        admin.post(f"{API}/admin/complaints/{uuid4()}/resolve", json={"status": "upheld"}, headers=headers).status_code
        == 404
    )

    metrics = make_client().get(f"{API}/contact/metrics")
    assert metrics.status_code == 200
    body = metrics.json()
    assert (body["invitations"], body["delivered_share"], body["accept_share"]) == (4, 1.0, 1.0)
    assert body["contact_confirmed_share"] == 1.0 and body["concentration_gini"] == 0.0
    assert db.get(Invitation, sent[0].id).status == InvitationStatus.ACCEPTED.value
