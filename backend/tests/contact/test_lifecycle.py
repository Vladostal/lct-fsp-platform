"""Жизненный цикл приглашения: ответы кандидата, истечение и `settle`, автопауза, отзыв, чтение без записи."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.errors import ApiException
from app.modules.contact import constants as c
from app.modules.contact import service, settle
from app.modules.contact.dto import DeclineCondition
from app.modules.contact.models import CandidateContactState, EmployerContactState, Invitation, InvitationEvent
from app.shared.enums import ConditionKind, DeclineReason, DiscloseField, InvitationStatus, WorkFormat
from tests.contact.conftest import send

API = "/api/v1"


def _strikes(db, candidate_id):
    db.expire_all()
    state = db.get(CandidateContactState, candidate_id)
    return state.consecutive_expired if state else 0


def _events(db, invitation_id):
    return db.scalars(
        select(InvitationEvent.code).where(InvitationEvent.invitation_id == invitation_id).order_by(InvitationEvent.id)
    ).all()


def _dump(db):
    """Снимок строк состояния модуля — чтобы показать, что чтение ничего не меняет."""
    db.expire_all()
    invitations = [
        (i.id, i.status, i.resolved_at, i.slot_release_at, i.pair_block_until, i.viewed_at, i.updated_at)
        for i in db.scalars(select(Invitation).order_by(Invitation.id))
    ]
    candidates = [(s.candidate_id, s.consecutive_expired) for s in db.scalars(select(CandidateContactState))]
    employers = [
        (s.employer_id, s.slot_limit_override, s.sending_frozen_at) for s in db.scalars(select(EmployerContactState))
    ]
    return (
        invitations,
        sorted(candidates),
        sorted(employers),
        db.scalar(select(func.count()).select_from(InvitationEvent)),
    )


# --- ответы кандидата -----------------------------------------------------------------------------------------------


def test_view_accept_discloses_and_frees_slot(
    db, client, make_client, login_as, actors, world, now, freeze_now, mailbox
):
    pair = actors.pair()
    sent = send(db, now, pair.employer.id, pair.candidate.id)
    login_as(pair.candidate)
    viewed = client.post(f"{API}/candidate/invitations/{sent.id}/view").json()
    assert viewed["status"] == "viewed" and viewed["status_label"] == "Ждёт ответа"
    assert {o["field"]: (o["available"], o["default"]) for o in viewed["disclose_options"]} == {
        "email": (True, True),
        "phone": (True, False),
        "telegram": (False, False),
        "link": (False, False),
        "fsp_details": (True, False),
    }
    bad = client.post(f"{API}/candidate/invitations/{sent.id}/accept", json={"disclose": ["telegram"]})
    assert (bad.status_code, bad.json()["code"]) == (422, "disclose_invalid")
    only_fsp = client.post(f"{API}/candidate/invitations/{sent.id}/accept", json={"disclose": ["fsp_details"]})
    assert only_fsp.status_code == 422

    freeze_now.tick(hours=2)
    accepted = client.post(f"{API}/candidate/invitations/{sent.id}/accept", json={"disclose": ["email", "phone"]})
    body = accepted.json()
    assert accepted.status_code == 200 and body["status"] == "accepted"
    assert body["disclosed"] == ["email", "phone"] and body["disclose_options"] == []
    assert body["contact_sla_until"].startswith((now + timedelta(hours=2 + 72)).isoformat()[:19])
    assert world.disclosures[0]["fields"] == [DiscloseField.EMAIL, DiscloseField.PHONE]
    assert world.disclosures[0]["ref_id"] == sent.id
    assert world.access_log == []  # журнал доступа пишет сам profile.disclose, второй записи нет
    assert [m.to for m in mailbox if m.template == "invitation_answered"] == [pair.employer.email]
    assert _events(db, sent.id) == ["sent", "viewed", "accepted"]

    # Повтор совпадающего действия — 200; другое действие по терминальному статусу — 409 со статусом.
    assert client.post(f"{API}/candidate/invitations/{sent.id}/accept").status_code == 200
    declined = client.post(f"{API}/candidate/invitations/{sent.id}/decline", json={"reason_code": "other"})
    assert (declined.status_code, declined.json()["code"]) == (409, "invitation_not_actionable")
    assert declined.json()["params"] == {"status": "accepted"}
    assert len(world.disclosures) == 1 and _events(db, sent.id) == ["sent", "viewed", "accepted"]

    employer = login_as(pair.employer, client=make_client())
    quota = employer.get(f"{API}/employer/invitations/quota").json()
    assert quota["used"] == 0  # согласие освобождает слот сразу
    view = employer.get(f"{API}/employer/invitations/{sent.id}").json()
    assert view["status"] == "accepted" and view["is_new_for_employer"] is True and view["slot"]["occupied"] is False
    assert employer.get(f"{API}/employer/invitations/{sent.id}").json()["is_new_for_employer"] is False
    assert view["pair_block_until"].startswith((now + timedelta(hours=2, days=30)).isoformat()[:19])


def test_accept_default_disclose_uses_privacy(db, actors, world, now):
    pair = actors.pair()
    world.candidates[pair.candidate.id].privacy.reveal_phone = True
    sent = send(db, now, pair.employer.id, pair.candidate.id)
    service.accept_invitation(db, now, pair.candidate.id, sent.id)
    assert world.disclosures[0]["fields"] == [DiscloseField.EMAIL, DiscloseField.PHONE]


def test_decline_conditions(db, client, make_client, login_as, actors, world, now):
    pair = actors.pair()
    sent = send(db, now, pair.employer.id, pair.candidate.id)
    login_as(pair.candidate)
    url = f"{API}/candidate/invitations/{sent.id}/decline"
    invalid = [
        {"reason_code": "salary", "condition": {"kind": "salary_from", "value": 150_000}},  # не больше «от»
        {"reason_code": "salary", "condition": {"kind": "salary_from", "value": 162_000}},  # не кратно 5 000
        {"reason_code": "stack", "condition": {"kind": "salary_from", "value": 180_000}},  # причина не та
        {"reason_code": "format", "condition": {"kind": "work_format", "value": "remote"}},  # равен предложенному
        {"reason_code": "format", "condition": {"kind": "work_format", "value": "office"}},  # не из форматов
    ]
    for body in invalid:
        response = client.post(url, json=body)
        assert (response.status_code, response.json()["code"]) == (422, "condition_invalid"), body
    assert client.post(url, json={"reason_code": "other", "comment": "x" * 301}).status_code == 422
    ok = client.post(
        url,
        json={"reason_code": "salary", "condition": {"kind": "salary_from", "value": 180_000}, "comment": "Мало"},
    )
    assert ok.status_code == 200 and ok.json()["status"] == "declined"
    assert ok.json()["decline"] == {
        "reason_code": "salary",
        "reason_label": "Зарплата",
        "condition": {"kind": "salary_from", "value": 180_000},
    }
    employer_view = login_as(pair.employer, client=make_client()).get(f"{API}/employer/invitations/{sent.id}").json()
    assert employer_view["decline"]["comment"] == "Мало" and employer_view["can_revise"] is True
    assert employer_view["revise_until"] and employer_view["slot"]["occupied"] is False


def test_masked_pair_hides_decline_details_and_access_log(db, client, login_as, actors, world, now):
    """Демо-компания не получает условие и комментарий живого кандидата."""
    demo = actors.employer(is_demo=True)
    live, second = actors.candidate(), actors.candidate()
    declined = send(db, now, demo.id, live.id, is_demo=True)
    service.decline_invitation(
        db,
        now,
        live.id,
        declined.id,
        DeclineReason.SALARY,
        DeclineCondition(kind=ConditionKind.SALARY_FROM, value=300_000),
        "мой телефон +7 900 000-00-00",
    )
    accepted = send(db, now, demo.id, second.id, is_demo=True)
    service.accept_invitation(db, now, second.id, accepted.id)
    db.commit()
    login_as(demo)
    response = client.get(f"{API}/employer/invitations/{declined.id}")
    assert response.json()["decline"] == {
        "reason_code": "salary",
        "reason_label": "Зарплата",
        "condition": None,
        "comment": "Скрыто в демо-режиме",
    }
    assert "300000" not in response.text and "+7 900" not in response.text
    precheck = client.get(f"{API}/employer/invitations/precheck?candidate_id={live.id}").json()
    assert precheck["pair"]["condition"] is None
    assert len(world.disclosures) == 1 and world.access_log == []


# --- срок и settle --------------------------------------------------------------------------------------------------


def test_accept_one_second_before_deadline_and_at_deadline(db, client, make_client, login_as, actors, now, freeze_now):
    employer = actors.employer()
    early, late = actors.candidate(), actors.candidate()
    first = send(db, now, employer.id, early.id)
    second = send(db, now, employer.id, late.id)
    freeze_now(first.expires_at - timedelta(seconds=1))
    ok = login_as(early).post(f"{API}/candidate/invitations/{first.id}/accept")
    assert ok.status_code == 200 and ok.json()["status"] == "accepted"
    freeze_now(second.expires_at)
    late_client = login_as(late, client=make_client())
    refused = late_client.post(f"{API}/candidate/invitations/{second.id}/accept")
    assert (refused.status_code, refused.json()["code"]) == (409, "invitation_not_actionable")
    assert refused.json()["params"] == {"status": "expired"}
    db.expire_all()
    row = db.get(Invitation, second.id)
    # Истечение материализовано, хотя запрос завершился ошибкой.
    assert (row.status, row.resolved_at, row.slot_release_at) == ("expired", second.expires_at, second.expires_at)
    assert row.pair_block_until == second.expires_at + timedelta(days=30)
    assert _events(db, second.id) == ["sent", "expired"]
    view = late_client.get(f"{API}/candidate/invitations/{second.id}").json()
    assert view["status"] == "expired" and view["strikes"] == {"count": 1, "limit": 2}


def test_double_settle_creates_one_event_i5(db, actors, now):
    pair = actors.pair()
    sent = send(db, now, pair.employer.id, pair.candidate.id)
    later = sent.expires_at + timedelta(hours=1)
    assert settle.settle(db, later, everything=True) == 1
    assert settle.settle(db, later, everything=True) == 0
    service.settle_all(db, later + timedelta(minutes=1))
    assert settle.settle(db, later, candidate_id=pair.candidate.id) == 0
    assert _events(db, sent.id) == ["sent", "expired"]
    event = db.scalars(select(InvitationEvent).where(InvitationEvent.code == "expired")).one()
    assert (event.at, event.actor) == (sent.expires_at, "system")
    assert _strikes(db, pair.candidate.id) == 1
    with pytest.raises(ValueError):
        settle.settle(db, later)


def test_reads_do_not_settle_or_write(db, client, make_client, login_as, actors, world, now, freeze_now, monkeypatch):
    """Читающие эндпоинты не вызывают `settle` и не меняют статусы, слоты и счётчики (Арх. 4.4, 10.1)."""
    pair = actors.pair()
    need_id = world.add_need(pair.employer.id)
    sent = send(db, now, pair.employer.id, pair.candidate.id, need_id=str(need_id))
    other = send(db, now, pair.employer.id, actors.candidate().id)
    freeze_now(sent.expires_at + timedelta(minutes=5))
    before = _dump(db)

    def forbidden(*args, **kwargs):
        raise AssertionError("чтение вызвало запись или блокировку")

    for name in ("settle", "lock_candidates", "lock_employer"):
        monkeypatch.setattr(settle, name, forbidden)

    employer = login_as(pair.employer)
    candidate = login_as(pair.candidate, client=make_client())
    employer_urls = [
        "/employer/invitations",
        "/employer/invitations?status=expired",
        "/employer/invitations/quota",
        "/employer/invitations/stats",
        f"/employer/invitations/pair-states?candidate_ids={pair.candidate.id}",
        f"/employer/invitations/precheck?candidate_id={pair.candidate.id}",
        f"/employer/needs/{need_id}/insights",
        "/contact/salary-hint?category=backend:middle",
        "/contact/metrics",
    ]
    candidate_urls = [
        "/candidate/invitations?status=archived",
        "/candidate/invitations/summary",
        f"/candidate/invitations/{sent.id}",
        "/candidate/funnel",
        "/contact/salary-hint",
    ]
    for url in employer_urls:
        assert employer.get(API + url).status_code == 200, url
    for url in candidate_urls:
        assert candidate.get(API + url).status_code == 200, url
    assert _dump(db) == before
    assert db.scalar(select(func.count()).where(Invitation.employer_seen_at.is_not(None))) == 0

    # Истёкшее, но не материализованное: отдаётся как expired и слот не занимает.
    assert db.get(Invitation, sent.id).status == "sent"
    assert employer.get(f"{API}/employer/invitations/quota").json()["used"] == 0
    listed = employer.get(f"{API}/employer/invitations?status=expired").json()["items"]
    assert {item["id"] for item in listed} == {str(sent.id), str(other.id)}
    assert all(item["status"] == "expired" and item["slot"]["occupied"] is False for item in listed)
    assert employer.get(f"{API}/employer/invitations?status=awaiting").json()["items"] == []
    summary = candidate.get(f"{API}/candidate/invitations/summary").json()
    assert (summary["awaiting"], summary["archived"]) == (0, 1)
    assert candidate.get(f"{API}/candidate/invitations?status=awaiting").json()["items"] == []
    pair_state = employer.get(f"{API}/employer/invitations/pair-states?candidate_ids={pair.candidate.id}").json()
    assert pair_state["items"][0]["invitation"]["status"] == "expired"
    assert pair_state["items"][0]["pair_block"]["code"] == "pair_cooldown"

    # Единственная запись при чтении — отметка просмотра работодателем.
    detail = employer.get(f"{API}/employer/invitations/{sent.id}").json()
    assert detail["status"] == "expired" and detail["timeline"][-1]["code"] == "expired"
    after = _dump(db)
    assert after == before
    assert db.scalar(select(func.count()).where(Invitation.employer_seen_at.is_not(None))) == 1


def test_withdraw_holds_slot_until_original_deadline(db, client, make_client, login_as, actors, now, freeze_now):
    pair = actors.pair()
    sent = send(db, now, pair.employer.id, pair.candidate.id)
    employer = login_as(pair.employer)
    freeze_now.tick(days=1)
    withdrawn = employer.post(f"{API}/employer/invitations/{sent.id}/withdraw")
    body = withdrawn.json()
    assert withdrawn.status_code == 200 and body["status"] == "withdrawn" and body["can_withdraw"] is False
    assert body["slot"] == {"occupied": True, "release_at": sent.expires_at.isoformat().replace("+00:00", "Z")}
    assert employer.post(f"{API}/employer/invitations/{sent.id}/withdraw").status_code == 200
    assert employer.get(f"{API}/employer/invitations/quota").json()["used"] == 1
    candidate = login_as(pair.candidate, client=make_client())
    refused = candidate.post(f"{API}/candidate/invitations/{sent.id}/accept")
    assert (refused.status_code, refused.json()["params"]) == (409, {"status": "withdrawn"})
    assert candidate.get(f"{API}/candidate/invitations/{sent.id}").json()["status_label"] == "Отозвано работодателем"
    assert _strikes(db, pair.candidate.id) == 0
    freeze_now(sent.expires_at)
    assert employer.get(f"{API}/employer/invitations/quota").json()["used"] == 0
    stranger = login_as(actors.employer(), client=make_client())
    assert stranger.post(f"{API}/employer/invitations/{sent.id}/withdraw").status_code == 404
    assert stranger.get(f"{API}/employer/invitations/{sent.id}").status_code == 404
    assert (
        login_as(actors.candidate(), client=make_client()).get(f"{API}/candidate/invitations/{sent.id}").status_code
        == 404
    )


def test_withdraw_after_deadline_materializes_expired(db, client, login_as, actors, now, freeze_now):
    pair = actors.pair()
    sent = send(db, now, pair.employer.id, pair.candidate.id)
    freeze_now(sent.expires_at + timedelta(seconds=1))
    refused = login_as(pair.employer).post(f"{API}/employer/invitations/{sent.id}/withdraw")
    assert (refused.status_code, refused.json()["params"]) == (409, {"status": "expired"})
    db.expire_all()
    assert db.get(Invitation, sent.id).status == "expired"


# --- автопауза ------------------------------------------------------------------------------------------------------


def test_auto_pause_cycle(db, client, login_as, actors, world, now, freeze_now):
    """Два истечения подряд — автопауза; ответ между ними обнуляет счёт; автоснятие — счётчик 1; «Я на связи» — 0."""
    candidate = actors.candidate()
    fake = world.candidates[candidate.id]
    t = now
    # Истечение, затем ответ, затем истечение: паузы нет.
    first = send(db, t, actors.employer().id, candidate.id)
    t = first.expires_at
    service.settle_all(db, t)
    assert _strikes(db, candidate.id) == 1 and fake.auto_paused_until is None
    answered = send(db, t, actors.employer().id, candidate.id)
    service.decline_invitation(db, t + timedelta(hours=1), candidate.id, answered.id, DeclineReason.OTHER)
    assert _strikes(db, candidate.id) == 0
    third = send(db, t, actors.employer().id, candidate.id)
    fourth = send(db, t + timedelta(hours=1), actors.employer().id, candidate.id)
    service.settle_all(db, third.expires_at)
    assert _strikes(db, candidate.id) == 1 and fake.auto_paused_until is None
    # Второе истечение подряд ставит автопаузу на 14 дней от срока приглашения.
    service.settle_all(db, fourth.expires_at + timedelta(minutes=3))
    assert _strikes(db, candidate.id) == 2
    assert fake.auto_paused_until == fourth.expires_at + timedelta(days=c.AUTO_PAUSE_MAX_DAYS)

    # Пока пауза действует, отправка даёт candidate_unavailable.
    employer = actors.employer()
    during = fourth.expires_at + timedelta(days=1)
    with pytest.raises(ApiException) as error:
        send(db, during, employer.id, candidate.id)
    assert error.value.code == "candidate_unavailable"
    db.rollback()

    # Через 14 дней пауза снимается при первой же операции со строкой кандидата; счётчик равен 1.
    after = fake.auto_paused_until + timedelta(seconds=1)
    fifth = send(db, after, employer.id, candidate.id)
    assert fifth.status == InvitationStatus.SENT and fake.auto_paused_until is None
    assert _strikes(db, candidate.id) == 1
    # Одно истечение после автоснятия снова ставит паузу; «Я на связи» снимает её и обнуляет счётчик.
    freeze_now(fifth.expires_at)
    service.settle_all(db, fifth.expires_at)
    assert _strikes(db, candidate.id) == 2 and fake.auto_paused_until is not None
    login_as(candidate)
    summary = client.get(f"{API}/candidate/invitations/summary").json()
    assert summary["strikes"] == {"count": 2, "limit": 2}
    assert summary["visibility"]["state"] == "paused" and summary["visibility"]["pause_reason"] == "auto_silence"
    resumed = client.post(f"{API}/candidate/invitations/resume")
    assert resumed.status_code == 200 and resumed.json()["state"] == "visible"
    assert _strikes(db, candidate.id) == 0 and fake.auto_paused_until is None


def test_demo_invitation_gives_no_strike_and_is_not_counted_in_funnel(
    db, client, login_as, actors, world, now, freeze_now
):
    """Поправки R3-mechanics-recheck-4 и R3-data-api-security-11."""
    demo = actors.employer(is_demo=True)
    live = actors.candidate()
    sent = send(db, now, demo.id, live.id, is_demo=True)
    login_as(live)
    funnel = client.get(f"{API}/candidate/funnel").json()
    assert (funnel["delivered"], funnel["stage"]) == (0, "not_shown")
    assert client.get(f"{API}/candidate/invitations").json()["items"][0]["is_demo"] is True
    service.settle_all(db, sent.expires_at)
    db.commit()
    assert db.get(Invitation, sent.id).status == "expired" and _strikes(db, live.id) == 0
    # У демо-аккаунтов сценария учитывается всё.
    synthetic = actors.candidate(is_demo=True)
    second = send(db, now, demo.id, synthetic.id, is_demo=True)
    service.settle_all(db, second.expires_at)
    assert _strikes(db, synthetic.id) == 1


def test_pair_blocked_30_days_after_each_terminal_status(db, actors, world, now):
    employer = actors.employer(trust="verified")
    cases = {}
    for name in ("accepted", "declined", "withdrawn", "expired"):
        candidate = actors.candidate()
        sent = send(db, now, employer.id, candidate.id)
        cases[name] = (candidate, sent)
    service.accept_invitation(db, now, cases["accepted"][0].id, cases["accepted"][1].id)
    service.decline_invitation(db, now, cases["declined"][0].id, cases["declined"][1].id, DeclineReason.OTHER)
    service.withdraw_invitation(db, now, employer.id, cases["withdrawn"][1].id)
    db.commit()
    resolved = {"accepted": now, "declined": now, "withdrawn": now, "expired": now + c.INVITATION_TTL}
    for name, (candidate, _) in cases.items():
        just_before = resolved[name] + timedelta(days=30) - timedelta(seconds=1)
        with pytest.raises(ApiException) as error:
            send(db, max(just_before, now + c.INVITATION_TTL), employer.id, candidate.id)
        assert error.value.code == "pair_cooldown", name
        assert error.value.params == {"until": (resolved[name] + timedelta(days=30)).isoformat()}
        db.rollback()
        assert send(db, resolved[name] + timedelta(days=30), employer.id, candidate.id).status == InvitationStatus.SENT


def test_candidate_view_has_no_ranking_keys(db, client, login_as, actors, world, now):
    pair = actors.pair()
    need_id = world.add_need(pair.employer.id)
    sent = send(db, now, pair.employer.id, pair.candidate.id, need_id=str(need_id))
    login_as(pair.candidate)
    payloads = [
        client.get(f"{API}/candidate/invitations/{sent.id}").json(),
        client.get(f"{API}/candidate/invitations").json(),
        client.get(f"{API}/candidate/invitations/summary").json(),
        client.get(f"{API}/candidate/funnel").json(),
    ]

    def keys(value):
        if isinstance(value, dict):
            for key, inner in value.items():
                yield key
                yield from keys(inner)
        elif isinstance(value, list):
            for inner in value:
                yield from keys(inner)

    found = {key for payload in payloads for key in keys(payload)}
    assert not found & {"position", "fit_band", "fit_band_at_send", "contributions", "risk", "slot", "min_salary"}
    assert payloads[0]["why"]["target"]["code"] == "backend:middle" and payloads[0]["company"]["name"] == "Орбита"
    assert WorkFormat(payloads[0]["work_format"]) is WorkFormat.REMOTE


def test_pagination_and_bad_cursor(db, client, login_as, actors, now, freeze_now):
    employer = actors.employer()
    for _ in range(5):
        send(db, freeze_now.tick(60), employer.id, actors.candidate().id)
    login_as(employer)
    first = client.get(f"{API}/employer/invitations?limit=2").json()
    second = client.get(f"{API}/employer/invitations?limit=2&cursor={first['next_cursor']}").json()
    third = client.get(f"{API}/employer/invitations?limit=2&cursor={second['next_cursor']}").json()
    ids = [item["id"] for page in (first, second, third) for item in page["items"]]
    assert len(ids) == len(set(ids)) == 5 and third["next_cursor"] is None
    assert client.get(f"{API}/employer/invitations?cursor=e30").status_code == 422
    assert client.get(f"{API}/employer/invitations?status=nope").status_code == 422
    assert client.get(f"{API}/employer/invitations/{uuid4()}").status_code == 404
