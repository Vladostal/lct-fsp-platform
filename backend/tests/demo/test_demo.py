"""Эндпоинты `/demo/*` (Арх. 9.10, 13.5): вход «как…», перезапуск, быстрый демо-тест, часы, сброс."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.core import clock
from app.core import db as core_db
from app.modules.assessment import seeding, sessions
from app.modules.assessment.models import CategoryRow, SessionItemRow, SessionRow, VariantRow
from app.modules.contact.models import Invitation
from app.modules.demo import service as demo
from app.modules.identity import service as identity
from app.modules.identity.models import AppUser, AuthSession
from app.modules.matching.models import ShortlistSnapshot
from app.shared.enums import Role
from tests.seed.support import ADMIN, API, World


def _ids() -> dict[str, str]:
    with core_db.session_scope() as db:
        rows = db.execute(
            select(AppUser.demo_key, AppUser.id).where(
                AppUser.demo_key.in_(["orbita", "anna", "dmitry", "ivan", "gleb", "boris", "olga", "maria", "petr"])
            )
        ).all()
    return {key: str(uid) for key, uid in rows}


def _live_candidate(world: World, email: str) -> tuple[TestClient, str]:
    """Настоящий (не демо) кандидат с подтверждённой почтой и открытой сессией входа."""
    with core_db.session_scope() as db:
        user_id = identity.create_user(
            db, email, "Live-pass-2026", Role.CANDIDATE, verified=True, is_demo=False, demo_key=None
        )
        token = identity.create_session(db, user_id)
    client = world.client()
    client.cookies.set("sid", token)
    return client, str(user_id)


def _answer_rest(client: TestClient, session_id: str) -> dict[str, object]:
    """Ответить верно на всё, что осталось кандидату, и вернуть результат теста."""
    item = client.get(f"{API}/assessment/sessions/{session_id}").json()["item"]
    while item:
        with core_db.session_scope() as db:
            row = db.get(SessionItemRow, item["id"])
            assert row is not None
            variant = db.get(VariantRow, row.variant_id)
            assert variant is not None
            raw = seeding.correct_raw(variant)
        reply = client.post(
            f"{API}/assessment/sessions/{session_id}/answers", json={"item_id": item["id"], "answer": raw}
        )
        assert reply.status_code == 200, reply.text
        item = reply.json().get("next_item")
    result = client.get(f"{API}/assessment/sessions/{session_id}/result")
    assert result.status_code == 200, result.text
    return result.json()


def test_login_as_opens_session_for_named_accounts(seeded: World) -> None:
    anonymous = seeded.client()
    listed = anonymous.get(f"{API}/demo/accounts")
    assert listed.status_code == 200
    assert {"orbita", "anna", "dmitry", "gleb", "petr"} <= {row["key"] for row in listed.json()}
    assert "nina" not in {row["key"] for row in listed.json()}

    candidate = seeded.login("anna")
    me = candidate.get(f"{API}/auth/me").json()
    assert me["role"] == "candidate" and me["is_demo"] is True and me["email"] == "anna@demo.test"
    invitations = candidate.get(f"{API}/candidate/invitations").json()["items"]
    assert [item["status"] for item in invitations] == ["sent"]

    employer = seeded.login("orbita")
    assert employer.get(f"{API}/auth/me").json()["role"] == "employer"
    assert len(employer.get(f"{API}/employer/needs").json()) == 1
    assert seeded.client().post(f"{API}/demo/login", json={"account_key": "nobody"}).status_code == 404
    assert seeded.client().post(f"{API}/demo/login", json={"account_key": "nina"}).status_code == 404


def test_scenario_restart_recreates_named_candidates_and_keeps_orbita(seeded: World, override_settings) -> None:
    url = f"{API}/demo/scenario/restart"
    before = _ids()
    with core_db.session_scope() as db:
        population = db.scalar(select(func.count()).select_from(AppUser).where(AppUser.demo_key.like("cand\\_%")))
        accepted = db.scalar(
            select(func.count())
            .select_from(Invitation)
            .where(Invitation.employer_id == before["orbita"], Invitation.status == "accepted")
        )
        snapshots = db.scalar(
            select(func.count()).select_from(ShortlistSnapshot).where(ShortlistSnapshot.employer_id == before["orbita"])
        )
        live = identity.create_user(
            db,
            "live.candidate@example.com",
            "Live-pass-2026",
            Role.CANDIDATE,
            verified=True,
            is_demo=False,
            demo_key=None,
        )
        live_token = identity.create_session(db, live)

    assert seeded.client().post(url).status_code == 401
    live_client = seeded.client()
    live_client.cookies.set("sid", live_token)
    assert live_client.post(url).status_code == 403

    anna = seeded.login("anna")
    restarted = anna.post(url)
    assert restarted.status_code == 200 and "restarted_at" in restarted.json(), restarted.text
    after = _ids()
    assert after["orbita"] == before["orbita"]
    assert all(after[key] != before[key] for key in before if key != "orbita")
    assert anna.get(f"{API}/auth/me").status_code == 401  # сессия пересозданного аккаунта закрыта
    with core_db.session_scope() as db:
        assert (
            db.scalar(select(func.count()).select_from(AppUser).where(AppUser.demo_key.like("cand\\_%"))) == population
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(Invitation)
                .where(Invitation.employer_id == after["orbita"], Invitation.status == "accepted")
            )
            == accepted
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(ShortlistSnapshot)
                .where(ShortlistSnapshot.employer_id == after["orbita"])
            )
            == snapshots + 1
        )
        fresh = db.scalars(select(Invitation.status).where(Invitation.candidate_id == after["gleb"])).all()
        assert sorted(fresh) == ["expired", "sent"]
        assert db.scalars(select(Invitation.status).where(Invitation.candidate_id == after["dmitry"])).all() == [
            "bounced"
        ]

    # второй вызов посетителя сразу после первого — 429 с retry_after; ведущему лимиты не мешают
    again = seeded.login("orbita").post(url)
    assert again.status_code == 429 and again.json()["params"]["retry_after"] > 0
    assert seeded.client().post(url, headers=ADMIN).status_code == 200

    override_settings(demo_public_restart=False)
    assert seeded.login("orbita").post(url).status_code == 403
    assert seeded.client().post(url, headers=ADMIN).status_code == 200


def test_quick_demo_test_for_live_candidate(seeded: World) -> None:
    quick = f"{API}/demo/assessment/quick-session"
    assert seeded.client().post(quick, json={"grade_code": "middle"}).status_code == 401
    assert seeded.login("orbita").post(quick, json={"grade_code": "middle"}).status_code == 403

    client, user_id = _live_candidate(seeded, "quick.candidate@example.com")
    # без опроса и заявленного грейда быстрый тест не начинается: правила те же, что у обычного
    no_survey = client.post(quick, json={"grade_code": "middle"})
    assert no_survey.status_code == 409 and no_survey.json()["code"] == "survey_required", no_survey.text
    survey = {"direction": "development", "specialization": "backend", "main_language": "python"}
    survey["experience_band"] = "2_4"
    assert client.put(f"{API}/assessment/survey", json={"version": "2026.10", "answers": survey}).status_code == 200
    no_claim = client.post(quick, json={"grade_code": "middle"})
    assert no_claim.status_code == 409 and no_claim.json()["code"] == "claim_required", no_claim.text
    assert client.put(f"{API}/assessment/claim", json={"grade_code": "middle"}).status_code == 200

    started = client.post(quick, json={"grade_code": "middle"})
    assert started.status_code == 200, started.text
    session_id = started.json()["session_id"]
    view = client.get(f"{API}/assessment/sessions/{session_id}").json()
    assert view["status"] == "in_progress" and view["item"] is not None
    with core_db.session_scope() as db:
        row = db.get(SessionRow, session_id)
        assert row is not None and row.flags.get(sessions.FLAG_PREFILLED) is True
        items = sessions.session_items(db, row.id)
        answered = [item for item in items if item.answered_at is not None]
        assert len(answered) == 12 and all(item.score == 1 for item in answered)
        # подставленные ответы «мгновенные», но признаком утечки не считаются
        assert not any(sessions.ITEM_FLAG_FAST in (item.flags or ()) for item in answered)
    again = client.post(quick, json={"grade_code": "middle"})
    assert again.status_code == 409 and again.json()["code"] == "session_active"

    result = _answer_rest(client, session_id)
    assert result["category"] is not None and result["category"]["code"] == "backend:middle", result
    assert any("демо" in note.lower() for note in result["notes"]), result["notes"]
    with core_db.session_scope() as db:
        category = db.get(CategoryRow, user_id)
        assert category is not None and category.is_demo_result is True
        closed = db.get(SessionRow, session_id)
        assert closed is not None and sessions.FLAG_SPEED_SUSPECT not in closed.flags
        assert closed.pooled_items == 14  # демо-результат считается со своими подставленными ответами

    # обычный тест на тот же грейд доступен сразу, и подставленные ответы в его результат не входят
    state = client.get(f"{API}/assessment/state").json()
    assert state["category"]["is_demo_result"] is True  # кандидату видно, что категория демонстрационная
    actions = {row["grade"]["code"]: row for row in state["next_actions"]}
    assert actions["middle"]["available"] is True, actions
    real = client.post(f"{API}/assessment/sessions", json={"grade_code": "middle"})
    assert real.status_code == 201, real.text
    item = real.json()["item"]
    while item:  # на всё отвечаем «не знаю»
        reply = client.post(
            f"{API}/assessment/sessions/{real.json()['id']}/answers", json={"item_id": item["id"], "skipped": True}
        )
        assert reply.status_code == 200, reply.text
        item = reply.json().get("next_item")
    failed = client.get(f"{API}/assessment/sessions/{real.json()['id']}/result").json()
    assert failed["outcome"] == "not_confirmed", failed
    with core_db.session_scope() as db:
        row = db.get(SessionRow, real.json()["id"])
        assert row is not None and row.pooled_items == row.items_answered == 14
        # двенадцать подставленных верных ответов не подняли оценку обычной попытки
        assert row.theta is not None and row.theta < closed.theta
        # неудачная обычная попытка не превращает демо-категорию в настоящую: пометка остаётся
        category = db.get(CategoryRow, user_id)
        assert category is not None and category.grade_code == "middle" and category.is_demo_result is True
    assert client.get(f"{API}/assessment/state").json()["category"]["is_demo_result"] is True


def test_host_clock_and_reset_need_admin_token(seeded: World) -> None:
    state, advance, reset = f"{API}/demo/clock", f"{API}/demo/clock/advance", f"{API}/demo/reset"
    anna = seeded.login("anna")
    assert anna.get(state).status_code == 403
    assert anna.post(advance, json={"hours": 24}).status_code == 403
    assert anna.post(reset).status_code == 403
    assert seeded.client().get(state, headers={"X-Admin-Token": "wrong"}).status_code == 403

    host = seeded.client()
    before = host.get(state, headers=ADMIN)
    assert before.status_code == 200, before.text
    assert host.post(advance, json={"hours": 0}, headers=ADMIN).status_code == 422
    assert host.post(advance, json={"hours": -5}, headers=ADMIN).status_code == 422

    # идущий тест: без подтверждения часы не сдвигаются
    client, _ = _live_candidate(seeded, "clock.candidate@example.com")
    survey = {"direction": "development", "specialization": "backend", "main_language": "python"}
    survey["experience_band"] = "2_4"
    assert client.put(f"{API}/assessment/survey", json={"version": "2026.10", "answers": survey}).status_code == 200
    assert client.put(f"{API}/assessment/claim", json={"grade_code": "junior"}).status_code == 200
    session = client.post(f"{API}/assessment/sessions", json={"grade_code": "junior"})
    assert session.status_code == 201, session.text
    blocked = host.post(advance, json={"hours": 24}, headers=ADMIN)
    assert blocked.status_code == 409 and blocked.json()["code"] == "sessions_in_progress", blocked.text
    assert blocked.json()["params"]["count"] >= 1
    assert host.get(state, headers=ADMIN).json()["offset_seconds"] == before.json()["offset_seconds"]

    moved = host.post(advance, json={"hours": 24 * 8, "force": True}, headers=ADMIN)
    assert moved.status_code == 200, moved.text
    assert moved.json()["offset_seconds"] == before.json()["offset_seconds"] + 8 * 86_400
    # приглашение Анны («ждёт ответа») через 8 дней истекло: срок считается по часам сервиса
    with core_db.session_scope() as db:
        now = clock.now(db)
        anna_id = identity.demo_user_ids(db, ["anna"])[0]
        assert all(
            row.expires_at < now for row in db.scalars(select(Invitation).where(Invitation.candidate_id == anna_id))
        )
    # тест кандидата закрыт по времени при первом обращении
    assert client.get(f"{API}/assessment/sessions/{session.json()['id']}").json()["status"] != "in_progress"

    ids_before = _ids()
    done = host.post(reset, headers=ADMIN)
    assert done.status_code == 200 and "reset_at" in done.json(), done.text
    ids_after = _ids()
    assert set(ids_after) == set(ids_before) and all(ids_after[key] != ids_before[key] for key in ids_before)
    with core_db.session_scope() as db:
        # живой пользователь на месте, сдвиг часов сохранён
        assert (
            db.scalar(select(func.count()).select_from(AppUser).where(AppUser.email == "clock.candidate@example.com"))
            == 1
        )
        assert clock.offset_seconds(db) == moved.json()["offset_seconds"]
    assert host.get(f"{API}/demo/accounts").status_code == 200


def _accept_as_anna(world: World) -> None:
    anna = world.login("anna")
    inbox = anna.get(f"{API}/candidate/invitations").json()["items"]
    assert [row["status"] for row in inbox] == ["sent"], inbox
    accepted = anna.post(f"{API}/candidate/invitations/{inbox[0]['id']}/accept", json={"disclose": ["email"]})
    assert accepted.status_code == 200, accepted.text


def _all_sessions_idle(hours: float) -> None:
    with core_db.session_scope() as db:
        db.execute(update(AuthSession).values(last_seen_at=clock.real_now() - timedelta(hours=hours)))


def _refresh() -> bool:
    with core_db.session_scope() as db:
        return demo.refresh_scenario(db, clock.now(db))


def test_stale_scenario_refreshes_itself_only_when_nobody_uses_it(seeded: World, override_settings) -> None:
    """Стенд без присмотра: устаревший сценарий пересоздаётся сам, но не под руками у посетителя и не по кругу."""
    with core_db.session_scope() as db:
        assert demo.scenario_stale(db) is False
    _all_sessions_idle(hours=5)
    assert _refresh() is False  # свежий сценарий не трогается, даже если им никто не пользуется

    before = _ids()
    _accept_as_anna(seeded)  # на приглашение ответили: «принять с выбором канала» показать больше нечем
    with core_db.session_scope() as db:
        assert demo.scenario_stale(db) is True
    assert _refresh() is False and _ids() == before  # Анна только что была в кабинете

    override_settings(demo_auto_restart=False)
    _all_sessions_idle(hours=3)
    assert _refresh() is False and _ids() == before  # выключено настройкой
    override_settings(demo_auto_restart=True)

    _all_sessions_idle(hours=1.5)
    assert _refresh() is False  # отметка моложе двух часов: возможно, кто-то ещё в кабинете
    _all_sessions_idle(hours=3)
    assert _refresh() is True
    after = _ids()
    assert after["orbita"] == before["orbita"] and all(after[key] != before[key] for key in before if key != "orbita")
    with core_db.session_scope() as db:
        assert demo.scenario_stale(db) is False

    # сценарий снова устарел сразу после автоперезапуска — второй раз за шесть часов он не пересоздаётся
    _accept_as_anna(seeded)
    _all_sessions_idle(hours=3)
    assert _refresh() is False and _ids() == after
