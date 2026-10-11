"""Отправка приглашения: шаги и проверки Арх. 4.5, сверка вилки 4.6, пересмотр 4.8, поправки рецензии."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.core.errors import ApiException
from app.modules.contact import constants as c
from app.modules.contact import service
from app.modules.contact.dto import DeclineCondition, InvitationData
from app.modules.contact.models import CandidateContactState, Invitation, InvitationEvent, InvitationTerms
from app.shared.enums import ConditionKind, DeclineReason, InvitationStatus, VisibilityState
from tests.contact.conftest import offer, send


def _post(client, employer, candidate_id, key=None, **overrides):
    return client.post(
        "/api/v1/employer/invitations",
        json=offer(candidate_id, **overrides),
        headers={"Idempotency-Key": str(key or uuid4())},
    )


def test_send_creates_sent_with_snapshot_event_and_mail(db, client, login_as, actors, world, now, mailbox):
    pair = actors.pair()
    need_id = world.add_need(pair.employer.id)
    login_as(pair.employer)
    response = _post(client, pair.employer, pair.candidate.id, need_id=str(need_id))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "sent"
    assert body["expires_at"].startswith((now + c.INVITATION_TTL).isoformat()[:19])
    assert body["need"] == {"id": str(need_id), "title": "Backend-разработчик"}
    assert "below_my_min" not in response.text and "fit_band" not in response.text
    inv = db.get(Invitation, body["id"])
    assert inv.fit_band_at_send == "strong" and inv.snapshot_id == world.needs[need_id].snapshot_id
    events = db.scalars(select(InvitationEvent.code).where(InvitationEvent.invitation_id == inv.id)).all()
    assert events == ["sent"]
    assert [m.to for m in mailbox] == [pair.candidate.email]


def test_idempotency_key_returns_same_invitation_with_200(db, client, login_as, actors, now):
    pair = actors.pair()
    login_as(pair.employer)
    key = uuid4()
    first = _post(client, pair.employer, pair.candidate.id, key)
    second = _post(client, pair.employer, pair.candidate.id, key)
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"]
    assert db.scalar(select(func.count()).select_from(Invitation)) == 1
    assert client.post("/api/v1/employer/invitations", json=offer(pair.candidate.id)).status_code == 422


def test_field_validation(client, login_as, actors, now):
    pair = actors.pair()
    login_as(pair.employer)
    wide = _post(client, pair.employer, pair.candidate.id, salary_from=100_000, salary_to=200_000)
    assert wide.status_code == 422 and wide.json()["code"] == "salary_range_too_wide"
    assert wide.json()["params"] == {"max_to": 150_000}
    no_city = _post(client, pair.employer, pair.candidate.id, work_format="hybrid")
    assert no_city.status_code == 422 and no_city.json()["fields"][0]["name"] == "city"
    office = _post(client, pair.employer, pair.candidate.id, work_format="office", city="Москва")
    assert office.status_code == 422 and office.json()["code"] == "format_not_accepted"
    foreign_need = _post(client, pair.employer, pair.candidate.id, need_id=str(uuid4()))
    assert foreign_need.status_code == 404


def test_unknown_or_non_candidate_addressee_is_unavailable_without_state_rows(db, client, login_as, actors, now):
    """Поправка R3-data-api-security-8: случайный UUID и UUID работодателя — тот же `candidate_unavailable`."""
    employer, other = actors.employer(), actors.employer()
    login_as(employer)
    for candidate_id in (uuid4(), other.id):
        response = _post(client, employer, candidate_id)
        assert (response.status_code, response.json()["code"]) == (409, "candidate_unavailable")
    assert db.scalar(select(func.count()).select_from(CandidateContactState)) == 0


def test_checks_in_table_order(db, client, login_as, actors, world, now):
    pair = actors.pair()
    login_as(pair.employer)
    world.companies[pair.employer.id].is_complete = False
    world.candidates[pair.candidate.id].state = VisibilityState.PAUSED
    assert _post(client, pair.employer, pair.candidate.id).json()["code"] == "company_profile_incomplete"
    world.companies[pair.employer.id].is_complete = True
    assert _post(client, pair.employer, pair.candidate.id).json()["code"] == "candidate_unavailable"
    world.candidates[pair.candidate.id].state = VisibilityState.VISIBLE
    assert _post(client, pair.employer, pair.candidate.id).status_code == 201
    again = _post(client, pair.employer, pair.candidate.id)
    assert (again.status_code, again.json()["code"]) == (409, "active_invitation_exists")
    assert again.json()["params"]["invitation_id"]


def test_inbox_full_and_pause_give_same_code(db, client, login_as, actors, world, now):
    """Заполненные входящие и пауза дают один код; кода `candidate_inbox_full` нет."""
    candidate = actors.candidate()
    for _ in range(c.CANDIDATE_INBOX_CAPACITY):
        send(db, now, actors.employer().id, candidate.id)
    employer = actors.employer()
    login_as(employer)
    full = _post(client, employer, candidate.id)
    precheck_full = client.get(f"/api/v1/employer/invitations/precheck?candidate_id={candidate.id}").json()
    paused = actors.candidate(state=VisibilityState.PAUSED)
    hidden = _post(client, employer, paused.id)
    assert full.status_code == hidden.status_code == 409
    assert full.json() == hidden.json()
    assert full.json()["code"] == "candidate_unavailable"
    assert [b["code"] for b in precheck_full["blockers"]] == ["candidate_unavailable"]
    assert precheck_full["candidate_formats"] == []
    assert "candidate_inbox_full" not in full.text + str(precheck_full)


def test_daily_limit_and_demo_account_exemption(db, client, login_as, make_client, actors, world, now, monkeypatch):
    monkeypatch.setattr(c, "DAILY_SEND_LIMIT", 3)
    employer = actors.employer(trust="verified")
    for _ in range(3):
        send(db, now, employer.id, actors.candidate().id)
    login_as(employer)
    response = _post(client, employer, actors.candidate().id)
    assert (response.status_code, response.json()["code"]) == (429, "daily_limit_exceeded")
    assert response.json()["params"]["retry_after"] > 0

    # Демо-аккаунт: суточный лимит не применяется (Арх. 4.14); 25 отправок за сутки проходят.
    demo = actors.employer(is_demo=True)
    for _ in range(25):
        assert send(db, now, demo.id, actors.candidate(is_demo=True).id).status == InvitationStatus.SENT
    quota = login_as(demo, client=make_client()).get("/api/v1/employer/invitations/quota").json()
    assert quota["daily_used"] == 25 and quota["daily_limit"] == c.DEMO_DAILY_SEND_LIMIT


# --- сверка вилки ---------------------------------------------------------------------------------------------------


def test_bounced_hidden_from_candidate_and_shown_in_funnel(
    db, client, make_client, login_as, actors, world, now, freeze_now, mailbox
):
    pair = actors.pair(min_salary=220_000)
    login_as(pair.employer)
    response = _post(client, pair.employer, pair.candidate.id)
    body = response.json()
    assert response.status_code == 201 and body["status"] == "bounced"
    assert body["status_label"] == "Не доставлено" and body["can_revise"] is True
    assert "220000" not in response.text.replace(" ", "")  # минимум в ответ не попадает
    assert mailbox == []

    candidate_client = login_as(pair.candidate, client=make_client())
    for status in ("awaiting", "accepted", "archived"):
        assert candidate_client.get(f"/api/v1/candidate/invitations?status={status}").json()["items"] == []
    assert candidate_client.get(f"/api/v1/candidate/invitations/{body['id']}").status_code == 404
    assert candidate_client.post(f"/api/v1/candidate/invitations/{body['id']}/accept").status_code == 404
    funnel = candidate_client.get("/api/v1/candidate/funnel").json()
    assert (funnel["delivered"], funnel["not_delivered"], funnel["stage"]) == (0, 1, "blocked_by_min")
    assert funnel["not_delivered_items"][0]["salary_from"] == 150_000
    assert "company" not in str(funnel) and "Орбита" not in str(funnel)

    again = _post(client, pair.employer, pair.candidate.id, salary_from=400_000, salary_to=500_000)
    assert (again.status_code, again.json()["code"]) == (409, "conditions_mismatch")
    assert again.json()["params"]["until"] == (now + timedelta(days=30)).isoformat()
    precheck = client.get(f"/api/v1/employer/invitations/precheck?candidate_id={pair.candidate.id}").json()
    assert precheck["blockers"][0]["code"] == "conditions_mismatch" and precheck["pair"]["can_revise"] is True


def test_check_always_applies_five_employers_all_bounced(db, client, make_client, login_as, actors, world, now):
    """Сверка действует всегда (бюджета нет): пять вилок ниже минимума — пять `bounced`, кандидату — ничего."""
    candidate = actors.candidate(min_salary=300_000)
    statuses = [send(db, now, actors.employer().id, candidate.id).status for _ in range(5)]
    assert statuses == [InvitationStatus.BOUNCED] * 5
    summary = login_as(candidate, client=make_client()).get("/api/v1/candidate/invitations/summary").json()
    assert (summary["awaiting"], summary["accepted"], summary["archived"]) == (0, 0, 0)


def test_revision_after_bounced_and_i9_two_checks_per_pair(db, client, login_as, actors, world, now, freeze_now):
    pair = actors.pair(min_salary=200_000)
    login_as(pair.employer)
    first = _post(client, pair.employer, pair.candidate.id).json()
    assert first["status"] == "bounced" and world.min_salary_calls == [pair.candidate.id]

    for salary_from in (150_000, 140_000):  # та же или меньшая нижняя граница — 422
        same = _post(client, pair.employer, pair.candidate.id, revises_id=first["id"], salary_from=salary_from)
        assert (same.status_code, same.json()["code"]) == (422, "revision_below_condition")
    assert len(world.min_salary_calls) == 1

    revised = _post(
        client, pair.employer, pair.candidate.id, revises_id=first["id"], salary_from=160_000, salary_to=200_000
    )
    assert revised.status_code == 201 and revised.json()["status"] == "bounced"  # сверка пройдена заново
    assert revised.json()["revises_id"] == first["id"] and revised.json()["can_revise"] is False
    assert len(world.min_salary_calls) == 2

    # Третья попытка отклоняется до сверки: и пересмотр исходного, и пересмотр пересмотренного, и новая отправка.
    third = _post(
        client, pair.employer, pair.candidate.id, revises_id=first["id"], salary_from=250_000, salary_to=300_000
    )
    fourth = _post(
        client,
        pair.employer,
        pair.candidate.id,
        revises_id=revised.json()["id"],
        salary_from=250_000,
        salary_to=300_000,
    )
    plain = _post(client, pair.employer, pair.candidate.id, salary_from=250_000, salary_to=300_000)
    assert [(r.status_code, r.json()["code"]) for r in (third, fourth, plain)] == [
        (409, "revision_not_allowed"),
        (409, "revision_not_allowed"),
        (409, "conditions_mismatch"),
    ]
    assert len(world.min_salary_calls) == 2  # I9: за 30 дней — две сверки
    detail = client.get(f"/api/v1/employer/invitations/{first['id']}").json()
    assert detail["revision_id"] == revised.json()["id"]
    assert [e["code"] for e in detail["timeline"]] == ["bounced", "revised"]


def test_revision_after_bounced_can_deliver_and_window_closes(db, client, login_as, actors, world, now, freeze_now):
    pair = actors.pair(min_salary=200_000)
    late = actors.candidate(min_salary=200_000)
    login_as(pair.employer)
    first = _post(client, pair.employer, pair.candidate.id).json()
    other = _post(client, pair.employer, late.id).json()
    ok = _post(client, pair.employer, pair.candidate.id, revises_id=first["id"], salary_from=200_000, salary_to=250_000)
    assert ok.status_code == 201 and ok.json()["status"] == "sent"
    freeze_now.tick(days=c.REVISION_WINDOW_DAYS)
    expired_window = _post(
        client, pair.employer, late.id, revises_id=other["id"], salary_from=200_000, salary_to=250_000
    )
    assert (expired_window.status_code, expired_window.json()["code"]) == (409, "revision_not_allowed")


def test_revision_pass_cannot_be_used_for_other_candidate_or_employer(
    db, client, make_client, login_as, actors, world, now
):
    """Поправка R3-data-api-security-1: исходное приглашение — того же работодателя и того же кандидата."""
    pair = actors.pair(min_salary=200_000)
    blocked = actors.candidate(min_salary=200_000)
    login_as(pair.employer)
    source = _post(client, pair.employer, pair.candidate.id).json()
    assert _post(client, pair.employer, blocked.id).json()["status"] == "bounced"
    calls = len(world.min_salary_calls)

    # «Пропуск» от одного кандидата к другому, заблокированному, не работает.
    cross = _post(client, pair.employer, blocked.id, revises_id=source["id"], salary_from=300_000, salary_to=400_000)
    assert (cross.status_code, cross.json()["code"]) == (409, "revision_not_allowed")
    # Чужой работодатель не может сослаться на чужое приглашение и ничего о нём не узнаёт.
    stranger = actors.employer()
    foreign = _post(
        login_as(stranger, client=make_client()),
        stranger,
        pair.candidate.id,
        revises_id=source["id"],
        salary_from=160_000,
    )
    missing = _post(login_as(stranger, client=make_client()), stranger, pair.candidate.id, revises_id=str(uuid4()))
    assert foreign.status_code == missing.status_code == 409
    assert foreign.json() == missing.json()
    assert len(world.min_salary_calls) == calls
    assert db.scalar(select(func.count()).select_from(Invitation)) == 2


def test_revision_after_decline_with_condition(db, client, login_as, actors, world, now):
    pair = actors.pair()
    sent = send(db, now, pair.employer.id, pair.candidate.id)
    service.decline_invitation(
        db,
        now,
        pair.candidate.id,
        sent.id,
        DeclineReason.SALARY,
        DeclineCondition(kind=ConditionKind.SALARY_FROM, value=180_000),
    )
    db.commit()
    login_as(pair.employer)
    plain = _post(client, pair.employer, pair.candidate.id)
    assert (plain.status_code, plain.json()["code"]) == (409, "pair_cooldown")
    below = _post(
        client, pair.employer, pair.candidate.id, revises_id=str(sent.id), salary_from=170_000, salary_to=220_000
    )
    assert (below.status_code, below.json()["code"]) == (422, "revision_below_condition")
    good = _post(
        client, pair.employer, pair.candidate.id, revises_id=str(sent.id), salary_from=180_000, salary_to=220_000
    )
    assert good.status_code == 201 and good.json()["status"] == "sent"
    second = _post(
        client, pair.employer, pair.candidate.id, revises_id=str(sent.id), salary_from=190_000, salary_to=220_000
    )
    assert (second.status_code, second.json()["code"]) == (409, "revision_not_allowed")  # I7
    precheck = client.get(f"/api/v1/employer/invitations/precheck?candidate_id={pair.candidate.id}").json()
    assert precheck["pair"]["can_revise"] is False


def test_decline_without_condition_cannot_be_revised(db, client, login_as, actors, now):
    pair = actors.pair()
    sent = send(db, now, pair.employer.id, pair.candidate.id)
    service.decline_invitation(db, now, pair.candidate.id, sent.id, DeclineReason.COMPANY)
    db.commit()
    login_as(pair.employer)
    response = _post(
        client, pair.employer, pair.candidate.id, revises_id=str(sent.id), salary_from=250_000, salary_to=300_000
    )
    assert (response.status_code, response.json()["code"]) == (409, "revision_not_allowed")


# --- неизменяемость снимка ------------------------------------------------------------------------------------------


def test_terms_update_fails_i3(db, actors, now):
    pair = actors.pair()
    sent = send(db, now, pair.employer.id, pair.candidate.id)
    with pytest.raises(DBAPIError), db.begin_nested():
        db.execute(text("UPDATE invitation_terms SET salary_from = 1 WHERE invitation_id = :id"), {"id": sent.id})
    assert db.get(InvitationTerms, sent.id).salary_from == 150_000


def test_company_snapshot_survives_company_edit(db, client, login_as, actors, world, now):
    pair = actors.pair()
    sent = send(db, now, pair.employer.id, pair.candidate.id)
    world.add_company(pair.employer.id, name="Новое имя")
    login_as(pair.candidate)
    view = client.get(f"/api/v1/candidate/invitations/{sent.id}").json()
    assert view["company"]["name"] == "Орбита" and view["company"]["trust_label"]


# --- демо-компания --------------------------------------------------------------------------------------------------


def test_demo_sender_restricted_and_demo_invitation_skips_check(db, client, make_client, login_as, actors, world, now):
    """Проверка 5.11 и демо-приглашение (Арх. 4.14): вручную нельзя, `is_demo=True` проходит без сверки."""
    demo = actors.employer(is_demo=True)
    live = actors.candidate(min_salary=400_000)
    login_as(demo)
    manual = _post(client, demo, live.id)
    assert (manual.status_code, manual.json()["code"]) == (409, "demo_sender_restricted")
    assert client.get(f"/api/v1/employer/invitations/precheck?candidate_id={live.id}").json()["blockers"][0][
        "code"
    ] == ("demo_sender_restricted")

    calls = len(world.min_salary_calls)
    sent = send(db, now, demo.id, live.id, is_demo=True)
    assert sent.status == InvitationStatus.SENT and sent.is_demo and len(world.min_salary_calls) == calls

    candidate_client = login_as(live, client=make_client())
    view = candidate_client.get(f"/api/v1/candidate/invitations/{sent.id}").json()
    brief = candidate_client.get("/api/v1/candidate/invitations").json()["items"][0]
    assert view["below_my_min"] is True and brief["below_my_min"] is True and view["is_demo"] is True
    employer_view = client.get(f"/api/v1/employer/invitations/{sent.id}")
    employer_list = client.get("/api/v1/employer/invitations")
    assert "below_my_min" not in employer_view.text + employer_list.text

    # Приглашения сида между демо-аккаунтами сверку проходят.
    dmitry = actors.candidate(is_demo=True, min_salary=400_000)
    assert send(db, now, demo.id, dmitry.id, is_demo=True).status == InvitationStatus.BOUNCED


def test_below_my_min_after_raising_minimum(db, client, login_as, actors, world, now):
    pair = actors.pair(min_salary=100_000)
    sent = send(db, now, pair.employer.id, pair.candidate.id)
    login_as(pair.candidate)
    assert client.get(f"/api/v1/candidate/invitations/{sent.id}").json()["below_my_min"] is False
    world.candidates[pair.candidate.id].min_salary = 200_000
    assert client.get(f"/api/v1/candidate/invitations/{sent.id}").json()["below_my_min"] is True


def test_facade_rejects_bad_key_and_reports_status(db, actors, now):
    pair = actors.pair()
    with pytest.raises(ApiException) as error:
        service.send_invitation(db, now, pair.employer.id, InvitationData.model_validate(offer(pair.candidate.id)), "x")
    assert error.value.status == 422
    assert service.has_active_invitation(db, pair.employer.id, pair.candidate.id) is False
    sent = send(db, now, pair.employer.id, pair.candidate.id)
    assert service.has_active_invitation(db, pair.employer.id, pair.candidate.id) is True
    export = service.invitation_for_export(db, pair.employer.id, sent.id)
    assert export.salary_from == 150_000 and export.status == InvitationStatus.SENT
    events = service.events_since(db, pair.employer.id, 0, 10)
    assert [e.code for e in events] == ["sent"] and events[0].payload == {}
