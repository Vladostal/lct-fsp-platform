"""Эндпоинты `/assessment/*` и `/admin/assessment/*` (Арх. 9.5): контракт, ошибки, скрытые поля."""

# ruff: noqa: E501 — подписи отчёта и длинные проверки читаются лучше в одну строку

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.assessment import candidate, preview, repo, seeding, service, sessions
from app.modules.assessment.config import get_config
from app.modules.assessment.models import FamilyRow, GradeClaim, VariantRow
from app.modules.catalog import service as catalog
from tests.assessment.conftest import T0

pytestmark = pytest.mark.usefixtures("bank")

API = "/api/v1/assessment"
HIDDEN = {"answer", "score", "error_tag", "misconception_answers", "explanation", "features", "theta", "se", "b_used"}
ADMIN = {"X-Admin-Token": "test-only-admin-token"}

SURVEY = {
    "direction": "development",
    "specialization": "backend",
    "main_language": "python",
    "experience_band": "2_4",
    "industry_domains": ["fintech", "telecom"],
}


def keys(data: Any) -> set[str]:
    if isinstance(data, dict):
        return set(data) | {k for value in data.values() for k in keys(value)}
    if isinstance(data, list):
        return {k for value in data for k in keys(value)}
    return set()


def test_full_path_over_http(db: Session, make_user, login_as, freeze_now) -> None:
    freeze_now(T0)
    user = make_user("candidate")
    client = login_as(user)
    version = get_config().survey_version

    schema = client.get(f"{API}/survey").json()
    assert schema["version"] == version and schema["answers"] is None
    assert [q["id"] for q in schema["questions"]] == ["direction", "specialization", "main_language", "experience_band", "industry_domains"]
    specs = {o["code"]: o for o in schema["questions"][1]["options"]}
    assert specs["backend"]["available"] and specs["backend"]["parent"] == "development" and not specs["mobile"]["available"]
    assert client.get(f"{API}/state").json()["survey_completed"] is False
    assert client.get(f"{API}/blueprints").json()["code"] == "survey_required"
    assert client.post(f"{API}/sessions", json={"grade_code": "middle"}).json()["code"] == "survey_required"

    assert client.put(f"{API}/survey", json={"version": "old", "answers": SURVEY}).json()["code"] == "survey_version_mismatch"
    bad = client.put(f"{API}/survey", json={"version": version, "answers": {**SURVEY, "main_language": "javascript"}})
    assert bad.status_code == 422 and bad.json()["fields"][0]["name"] == "answers.main_language"
    many = client.put(f"{API}/survey", json={"version": version, "answers": {**SURVEY, "industry_domains": ["fintech", "gov", "media", "other"]}})
    assert many.status_code == 422
    # Специализация без теста опросом принимается (категория в ней будет заявленной); затем кандидат выбирает backend.
    no_test = client.put(f"{API}/survey", json={"version": version, "answers": {**SURVEY, "direction": "quality_infra", "specialization": "qa", "main_language": "other"}})
    assert no_test.status_code == 200 and no_test.json()["answers"]["specialization"] == "qa"
    saved = client.put(f"{API}/survey", json={"version": version, "answers": SURVEY})
    assert saved.status_code == 200 and saved.json()["answers"] == SURVEY

    assert client.post(f"{API}/sessions", json={"grade_code": "middle"}).json()["code"] == "claim_required"
    assert client.put(f"{API}/claim", json={"grade_code": "principal"}).json()["code"] == "grade_unavailable"
    state = client.put(f"{API}/claim", json={"grade_code": "middle"}).json()
    assert state["claimed_grade"] == {"code": "middle", "title": "Middle"} and state["claim_locked"] is False
    assert state["direction"]["code"] == "development" and state["main_language"] == {"code": "python", "title": "Python"}
    assert [(a["kind"], a["available"], a["recommended"]) for a in state["next_actions"]] == [("take_claimed", True, True)]

    plans = client.get(f"{API}/blueprints").json()
    assert [p["grade"]["code"] for p in plans] == ["junior", "middle", "senior"] and all(p["available"] for p in plans)
    middle = plans[1]
    assert (middle["items_min"], middle["items_max"], middle["time_limit_min"], middle["time_limit_max_min"]) == (14, 26, 40, 70)
    assert sum(s["slots"] for s in middle["skills"]) == 14 and {"py", "sql", "any"} <= {s["group_code"] for s in middle["skills"]}

    assert client.post(f"{API}/sessions", json={"grade_code": "senior"}).json()["code"] == "grade_not_allowed"
    started = client.post(f"{API}/sessions", json={"grade_code": "middle"})
    assert started.status_code == 201
    view = started.json()
    sid = view["id"]
    assert view["status"] == "in_progress" and view["target"]["code"] == "backend:middle" and view["item"]["skill_label"]
    again = client.post(f"{API}/sessions", json={"grade_code": "middle"})
    assert (again.status_code, again.json()["code"], again.json()["params"]) == (409, "session_active", {"session_id": sid})
    assert client.put(f"{API}/survey", json={"version": version, "answers": SURVEY}).json()["code"] == "session_active"
    assert client.put(f"{API}/claim", json={"grade_code": "junior"}).json()["code"] == "claim_locked"
    assert client.get(f"{API}/sessions/{sid}/result").status_code == 202
    assert client.get(f"{API}/sessions/{sid}/result").json() == {"status": "in_progress"}
    assert client.get(f"{API}/state").json()["active_session"]["id"] == sid

    seen = [view]
    item = view["item"]
    answered = 0
    while item is not None:
        row = db.get(VariantRow, next(i for i in sessions.session_items(db, sid) if str(i.id) == item["id"]).variant_id)
        body = {"item_id": item["id"], "answer": seeding.correct_raw(row), "skipped": False, "client": {"time_spent_ms": 900, "junk": 1}}
        headers = {"Idempotency-Key": f"{sid}:{item['id']}"}
        reply = client.post(f"{API}/sessions/{sid}/answers", json=body, headers=headers)
        assert reply.status_code == 200, reply.text
        if answered == 0:
            repeat = client.post(f"{API}/sessions/{sid}/answers", json=body, headers=headers)
            assert repeat.status_code == 200 and repeat.json()["next_item"] == reply.json()["next_item"]
            other = client.post(f"{API}/sessions/{sid}/answers", json=body, headers={"Idempotency-Key": "x"})
            assert (other.status_code, other.json()["code"]) == (409, "item_already_answered")
        answered += 1
        data = reply.json()
        seen.append(data)
        assert data["progress"]["answered"] == answered
        item = data["next_item"]
    assert data["finished"] is True and answered == 14

    result = client.get(f"{API}/sessions/{sid}/result")
    assert result.status_code == 200
    body = result.json()
    assert body["outcome"] == "confirmed_with_margin" and body["category"]["code"] == "backend:middle"
    assert body["items_answered"] == 14 and body["level"]["thresholds"][1] == {"grade": {"code": "middle", "title": "Middle"}, "pos": 50.0}
    history = client.get(f"{API}/history").json()
    # Опросов в истории два: сначала принятый qa (специализация без теста), затем backend.
    assert [h["kind"] for h in history] == ["test", "survey", "survey"] and history[0]["title"] == "Тест на Middle"
    state = client.get(f"{API}/state").json()
    assert state["category"]["code"] == "backend:middle" and state["claim_locked"] is True
    assert state["category"]["basis"] == "test" and state["category"]["level_session_id"] == sid and state["level"] is not None
    assert body["category"]["basis"] == "test" and service.get_category(db, user.id).basis == "test"
    assert [(lv.basis, lv.theta is not None, lv.age_days) for lv in service.get_levels(db, candidate_ids=[user.id], now=T0)] == [("test", True, 0)]
    session_view = client.get(f"{API}/sessions/{sid}").json()
    assert session_view["status"] == "finished" and session_view["item"] is None

    # В ответах кандидату нет ключа варианта, балла, тега ошибки и единиц θ.
    leaked = keys([seen, body, history, state, session_view, plans]) & HIDDEN
    assert not leaked, leaked

    # Чужая сессия — 404; работодателю раздел кандидата закрыт.
    stranger = login_as(make_user("candidate"))
    for path in (f"{API}/sessions/{sid}", f"{API}/sessions/{sid}/result"):
        assert stranger.get(path).status_code == 404
    assert stranger.post(f"{API}/sessions/{sid}/answers", json={"item_id": "x", "skipped": True}).status_code == 404
    assert stranger.get(f"{API}/sessions/not-a-uuid").status_code == 404
    employer = login_as(make_user("employer"))
    assert employer.get(f"{API}/state").status_code == 403


QA_SURVEY = {"direction": "quality_infra", "specialization": "qa", "main_language": "other", "experience_band": "2_4"}


def test_declared_category_over_http(db: Session, make_user, login_as, freeze_now) -> None:
    """Специализация без теста: опрос и заявление грейда дают категорию `basis = declared` без уровня и без теста."""
    freeze_now(T0)
    user = make_user("candidate")
    client = login_as(user)
    version = get_config().survey_version
    assert not catalog.is_available("qa")

    assert client.put(f"{API}/survey", json={"version": version, "answers": QA_SURVEY}).status_code == 200
    state = client.get(f"{API}/state").json()
    assert state["specialization"]["code"] == "qa" and state["category"] is None and state["next_actions"] == []
    assert client.get(f"{API}/blueprints").json() == []
    assert client.put(f"{API}/claim", json={"grade_code": "principal"}).json()["code"] == "grade_unavailable"

    claimed = client.put(f"{API}/claim", json={"grade_code": "middle"})
    assert claimed.status_code == 200
    state = claimed.json()
    assert state["category"]["code"] == "qa:middle" and state["category"]["basis"] == "declared"
    assert state["category"]["level_session_id"] is None and state["level"] is None and state["next_actions"] == []
    assert state["claimed_grade"]["code"] == "middle" and state["claim_locked"] is False
    assert state["category"]["assigned_at"] == state["category"]["change_available_at"]  # первая смена доступна сразу
    assert client.put(f"{API}/claim", json={"grade_code": "middle"}).status_code == 200  # повтор ничего не меняет
    started = client.post(f"{API}/sessions", json={"grade_code": "middle"})
    assert (started.status_code, started.json()["code"]) == (422, "grade_unavailable")

    dto = service.get_category(db, user.id)
    assert dto is not None and (dto.basis, dto.category_code, dto.verdict, dto.level_session_id) == ("declared", "qa:middle", None, None)
    (level,) = service.get_levels(db, specialization_code="qa", now=T0)
    assert (level.basis, level.verdict, level.theta, level.se, level.se_eff, level.tested_at, level.last_evidence_at) == ("declared", None, None, None, None, None, None)
    assert level.age_days is None and level.stale is False
    cfg = get_config()
    assert (level.cut, level.cut_next, level.width) == (cfg.theta_cut["middle"], cfg.theta_cut["middle"] + cfg.grade_width, cfg.grade_width)
    assert service.level_views(db, [user.id], T0) == {} and service.skill_evidence(db, [user.id]) == {user.id: []}
    assert sessions.category_state(repo.category(db, user.id), "qa") is None  # правила заявленную категорию не видят
    assert not keys(state) & HIDDEN

    # Первая смена заявленного грейда свободна (ошибочный клик), вторая — не раньше чем через 90 дней.
    freeze_now(T0 + timedelta(days=1))
    fixed = client.put(f"{API}/claim", json={"grade_code": "senior"}).json()
    assert fixed["category"]["code"] == "qa:senior" and fixed["claimed_grade"]["code"] == "senior"
    freeze_now(T0 + timedelta(days=30))
    client = login_as(user)  # сессия входа живёт 14 дней: после сдвига часов входим заново
    early = client.put(f"{API}/claim", json={"grade_code": "junior"})
    assert (early.status_code, early.json()["code"]) == (409, "cooldown_active")
    assert early.json()["params"] == {"reason": "grade_change", "available_at": (T0 + timedelta(days=91)).isoformat()}
    assert client.get(f"{API}/state").json()["category"]["code"] == "qa:senior"
    freeze_now(T0 + timedelta(days=91, minutes=1))
    client = login_as(user)  # сессия входа живёт 14 дней: после сдвига часов входим заново
    late = client.put(f"{API}/claim", json={"grade_code": "junior"})
    assert late.status_code == 200 and late.json()["category"]["code"] == "qa:junior"
    assert [h["kind"] for h in client.get(f"{API}/history").json()] == ["survey"]
    claims = db.scalars(select(GradeClaim).where(GradeClaim.candidate_id == user.id).order_by(GradeClaim.created_at)).all()
    assert [c.grade_code for c in claims] == ["middle", "senior", "junior"]


def test_unavailable_test_never_gives_declared_category(db: Session, candidate_ready: Callable[..., Any], make_user, login_as) -> None:
    """Тест написан, но недоступен (банк не собран, специализация выключена): заявленной категории не бывает."""
    ready = candidate_ready(None)  # опрос backend пройден, пока тест был доступен
    confirmed = candidate_ready("junior")
    done = sessions.start_session(db, confirmed.id, "junior", T0)
    while done.status == "in_progress":
        item = next(i for i in sessions.session_items(db, done.id) if i.status == "shown")
        raw = seeding.correct_raw(db.get(VariantRow, item.variant_id))
        sessions.submit_answer(db, confirmed.id, str(done.id), str(item.id), raw, False, None, None, T0 + timedelta(minutes=1))
    before = service.get_category(db, confirmed.id)
    assert before is not None and before.basis == "test"

    catalog.publish_availability(set())
    fresh = login_as(make_user("candidate"))
    reply = fresh.put(f"{API}/survey", json={"version": get_config().survey_version, "answers": SURVEY})
    assert (reply.status_code, reply.json()["code"]) == (422, "specialization_unavailable")
    client = login_as(ready)
    for grade in ("junior", "senior"):
        reply = client.put(f"{API}/claim", json={"grade_code": grade})
        assert (reply.status_code, reply.json()["code"]) == (422, "grade_unavailable")
    state = client.get(f"{API}/state").json()
    assert state["category"] is None and state["claimed_grade"] is None
    assert len(client.get(f"{API}/blueprints").json()) == 3  # планы показываются, но недоступны
    reply = login_as(confirmed).put(f"{API}/claim", json={"grade_code": "senior"})
    assert (reply.status_code, reply.json()["code"]) == (422, "grade_unavailable")
    with pytest.raises(ValueError):
        service.seed_declared(db, candidate_id=ready.id, specialization_code="backend", grade_code="middle", now=T0)
    # Даже в обход проверки заявление не заменяет подтверждённую тестом категорию той же специализации.
    with pytest.raises(Exception) as error:
        sessions.declare_category(db, confirmed.id, "backend", "senior", T0)
    assert error.value.code == "claim_locked"
    after = service.get_category(db, confirmed.id)
    assert after is not None and (after.basis, after.category_code, after.verdict, after.level_session_id) == ("test", before.category_code, before.verdict, before.level_session_id)


def test_seed_declared(db: Session, make_user) -> None:
    user = make_user("candidate")
    with pytest.raises(ValueError):
        service.seed_declared(db, candidate_id=user.id, specialization_code="backend", grade_code="middle", now=T0)
    with pytest.raises(ValueError):
        service.seed_declared(db, candidate_id=user.id, specialization_code="qa", grade_code="principal", now=T0)
    for _ in range(2):  # идемпотентна
        service.seed_declared(db, candidate_id=user.id, specialization_code="qa", grade_code="senior", now=T0, experience_band="4_plus")
    dto = service.get_category(db, user.id)
    assert dto is not None and (dto.category_code, dto.basis, dto.assigned_at) == ("qa:senior", "declared", T0)
    declared = service.survey_declared(db, [user.id])[user.id]
    assert (declared.direction, declared.experience_band) == ("quality_infra", "4_plus")
    state = candidate.state_view(db, user.id, T0)
    assert state.claimed_grade.code == "senior" and state.category.basis == "declared" and state.level is None
    assert db.scalar(select(func.count()).select_from(GradeClaim).where(GradeClaim.candidate_id == user.id)) == 1


def test_specialization_change(db: Session, candidate_ready: Callable[..., Any]) -> None:
    user = candidate_ready("junior")
    version = get_config().survey_version
    done = sessions.start_session(db, user.id, "junior", T0)
    sessions.finalize(db, done, T0 + timedelta(minutes=1), by_time=False)
    front = {"direction": "development", "specialization": "frontend", "main_language": "typescript", "experience_band": "lt1"}
    later = T0 + timedelta(days=1)
    with pytest.raises(Exception) as error:
        candidate.put_survey(db, user.id, version, front, False, later)
    assert error.value.code == "specialization_change_requires_confirm"
    candidate.put_survey(db, user.id, version, front, True, later)
    state = candidate.state_view(db, user.id, later)
    assert state.specialization.code == "frontend" and state.claimed_grade is None and state.claim_locked is False
    candidate.put_claim(db, user.id, "junior", later)
    switched = sessions.start_session(db, user.id, "junior", later)
    assert switched.specialization_code == "frontend" and switched.lang_module == "js" and switched.kind == "initial"
    sessions.finalize(db, switched, later + timedelta(minutes=1), by_time=False)
    back = {**front, "specialization": "backend", "main_language": "go"}
    with pytest.raises(Exception) as error:
        candidate.put_survey(db, user.id, version, back, True, later + timedelta(days=5))
    assert error.value.code == "cooldown_active" and error.value.params["reason"] == "specialization_change"


def test_no_lang_module_goes_to_code(db: Session, candidate_ready: Callable[..., Any]) -> None:
    user = candidate_ready("junior", language="java")
    session = sessions.start_session(db, user.id, "junior", T0)
    items = sessions.session_items(db, session.id)
    assert session.lang_module is None and sum(1 for i in items if i.slot_group == "code") == 4
    assert not any(i.family_id.startswith(("py.", "js.")) for i in items)
    sessions.finalize(db, session, T0 + timedelta(minutes=2), by_time=False)
    result = candidate.result_view(db, user.id, str(session.id), T0 + timedelta(minutes=3))
    assert "Языковой модуль не проверялся: для Java заданий пока нет" in result.notes


EXAMPLES = {
    "python_middle": ("middle", ["python", "fastapi", "postgresql", "db_indexes", "rest_api", "http", "asyncio", "git", "docker"], ["kafka", "redis", "clickhouse"]),
    "java_senior": ("senior", ["spring", "microservices", "kafka", "concurrency", "multithreading", "postgresql", "system_design"], ["highload", "redis"]),
    "junior_api": ("junior", ["python", "django", "sql", "sql_joins", "rest_api", "git"], ["http", "postgresql"]),
}


@pytest.mark.parametrize("pulse", [True, False])
@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_need_slots_always_present_and_differ(db: Session, override_settings, name: str, pulse: bool) -> None:
    """`need_slots` заполнено всегда, независимо от `features.pulse`, и для трёх примеров `backend` отличается
    от плана категории хотя бы в одной группе: пример показывает, что описание меняет план (Арх. 5.4)."""
    override_settings(feature_pulse=pulse)
    grade, must, nice = EXAMPLES[name]
    result = service.blueprint_for(db, "backend", grade, must, nice)
    assert result.target.code == f"backend:{grade}" and result.need_slots
    assert sum(s.slots for s in result.standard_slots) == sum(s.slots for s in result.need_slots) == 12
    standard = {s.group.code: s.slots for s in result.standard_slots}
    assert all(s.delta == s.slots - standard.get(s.group.code, 0) for s in result.need_slots)
    assert any(s.delta != 0 for s in result.need_slots) and sum(s.delta for s in result.need_slots) == 0
    assert {c.skill.code for c in result.coverage} == {*must, *nice}
    assert result.sample_items and not keys(result.model_dump()) & HIDDEN
    demo = set(db.scalars(select(VariantRow.id).where(VariantRow.status == "demo")))
    assert {item.id for item in result.sample_items} <= {str(i) for i in demo}


def test_preview_example_matches_appendix(db: Session) -> None:
    """Пример 1 приложения A, §4.5: `algo` и `ds` отдают слоты группе `http`."""
    grade, must, nice = EXAMPLES["python_middle"]
    result = service.blueprint_for(db, "backend", grade, [*must, "django"], [*nice, "rabbitmq"])
    assert {s.group.code: s.slots for s in result.need_slots} == {
        "code": 1, "py": 2, "algo": 0, "ds": 0, "sql": 2, "http": 3, "git": 1, "db": 2, "svc": 1,
    }  # fmt: skip
    coverage = {c.skill.code: (c.relation, c.group.code if c.group else None) for c in result.coverage}
    assert coverage["docker"] == ("untested", None) and coverage["python"] == ("direct", "py")
    assert coverage["fastapi"] == ("related", "http") and coverage["db_indexes"] == ("direct", "db")
    junior = service.blueprint_for(db, "data_ml", "junior", ["sql_window_functions", "pandas"], [])
    assert {c.skill.code: c.relation for c in junior.coverage}["sql_window_functions"] == "above_grade"


def test_preview_endpoint(db: Session, client, make_user, login_as, monkeypatch: pytest.MonkeyPatch, override_settings) -> None:
    from app.modules.textparse.dto import NeedDraft

    drafts = {"grade": NeedDraft(specialization_code="backend", grade_code=None, must_skills=["python", "http", "rest_api"], nice_skills=["redis"])}
    monkeypatch.setattr(preview.textparse, "parse_need_text", lambda text: drafts["grade"])
    text = "Ищем backend-разработчика: Python, REST API, HTTP; будет плюсом Redis." * 2
    guest = client.post(f"{API}/blueprints/preview", json={"text": text})
    assert guest.status_code == 200, guest.text
    body = guest.json()
    assert body["target"]["code"] == "backend:middle" and body["grade_guessed"] is True and body["need_slots"]
    assert not keys(body) & HIDDEN
    assert client.post(f"{API}/blueprints/preview", json={"text": "коротко"}).json()["code"] == "text_too_short"
    assert client.post(f"{API}/blueprints/preview", json={"text": "я" * 5001}).json()["code"] == "text_too_long"
    assert client.post(f"{API}/blueprints/preview", json={}).status_code == 422
    structured = {"specialization_code": "backend", "grade_code": "senior", "must_skills": ["kafka", "nope"], "nice_skills": []}
    reply = client.post(f"{API}/blueprints/preview", json=structured)
    assert reply.status_code == 200 and reply.json()["grade_guessed"] is False
    off = client.post(f"{API}/blueprints/preview", json={**structured, "specialization_code": "qa"})
    assert (off.status_code, off.json()["code"]) == (422, "specialization_unavailable")
    assert login_as(make_user("candidate")).post(f"{API}/blueprints/preview", json=structured).status_code == 403
    employer = login_as(make_user("employer"), client=None)
    assert employer.post(f"{API}/blueprints/preview", json=structured).status_code == 200


def test_preview_requires_login_without_demo_and_is_throttled(db: Session, make_client, make_user, login_as, override_settings, monkeypatch) -> None:
    from app.modules.assessment import router as assessment_router

    structured = {"specialization_code": "backend", "grade_code": "middle", "must_skills": ["sql"], "nice_skills": []}
    monkeypatch.setattr(assessment_router, "PREVIEW_LIMIT_USER_PER_HOUR", 2)
    employer = login_as(make_user("employer"), make_client())
    codes = [employer.post(f"{API}/blueprints/preview", json=structured).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    override_settings(demo_mode=False)
    assert make_client().post(f"{API}/blueprints/preview", json=structured).status_code == 401


def test_methodology_is_public(db: Session, client) -> None:
    body = client.get(f"{API}/methodology").json()
    assert body["constants"]["theta_cut"] == {"junior": -1.5, "middle": 0.0, "senior": 1.5}
    assert body["constants"]["max_sessions_per_30d"] == 3 and body["versions"]["engine"] == get_config().engine_version
    assert body["bank"]["families"] == 70 and body["bank"]["levels"] == 200 and body["bank"]["variants"] == 1000
    assert "backend:middle" in body["bank"]["available_categories"] and len(body["bank"]["groups"]) == 15
    assert "assessment_secret" not in str(body).lower()


def test_dropped_family_disables_one_pair_via_admin(db: Session, client, min_pool_3: None) -> None:
    """Выбывшее семейство выключает пару (специализация, грейд), остальные остаются доступными (Арх. 5.2)."""
    assert client.get("/api/v1/admin/assessment/bank/health").status_code == 403
    health = client.get("/api/v1/admin/assessment/bank/health", headers=ADMIN).json()
    assert len(health["families"]) == 70 and len(health["available_categories"]) == 12
    assert all(f["variants_active"] >= 10 and not f["variants_low"] for f in health["families"])

    before = set(catalog.get_catalog().available_categories)
    # У группы ds в диапазоне senior ровно три семейства — нулевой запас.
    reply = client.post("/api/v1/admin/assessment/families/ds.heap_array/status", json={"status": "quarantined", "reason": "проверка"}, headers=ADMIN)
    assert reply.status_code == 200, reply.text
    after = set(reply.json()["available_categories"])
    lost = before - after
    assert lost and all(code.split(":")[0] in ("backend", "frontend") for code in lost)
    assert {"fullstack:junior", "fullstack:middle", "fullstack:senior", "data_ml:junior"} <= after
    assert set(catalog.get_catalog().available_categories) == after
    assert db.get(FamilyRow, "ds.heap_array").status_reason == "проверка"
    again = client.post("/api/v1/admin/assessment/families/ds.heap_array/status", json={"status": "suspect"}, headers=ADMIN)
    assert (again.status_code, again.json()["code"]) == (422, "invalid_transition")
    back = client.post("/api/v1/admin/assessment/families/ds.heap_array/status", json={"status": "active"}, headers=ADMIN)
    assert set(back.json()["available_categories"]) == before
    assert client.post("/api/v1/admin/assessment/families/no.such/status", json={"status": "active"}, headers=ADMIN).status_code == 404


def test_unavailable_grade_is_rejected(db: Session, client, candidate_ready: Callable[..., Any], login_as) -> None:
    user = candidate_ready("senior")
    client.post("/api/v1/admin/assessment/families/ds.heap_array/status", json={"status": "retired"}, headers=ADMIN)
    if catalog.is_available("backend", "senior"):
        pytest.skip("в учебном банке у пары остался запас")
    reply = login_as(user).post(f"{API}/sessions", json={"grade_code": "senior"})
    assert (reply.status_code, reply.json()["code"]) == (422, "grade_unavailable")
    plans = {p["grade"]["code"]: p["available"] for p in login_as(user).get(f"{API}/blueprints").json()}
    assert plans["senior"] is False


def test_leak_lookup_finds_variant_and_session(db: Session, client, candidate_ready: Callable[..., Any]) -> None:
    user = candidate_ready("middle")
    session = sessions.start_session(db, user.id, "middle", T0)
    item = sessions.session_items(db, session.id)[0]
    variant = db.get(VariantRow, item.variant_id)
    # Утёкший текст целиком: условие, код и варианты ответа (по одному условию варианты семейства не различить).
    options = " ".join(o["text"] for o in variant.payload.get("options") or [])
    text = variant.payload["prompt"] + "\n" + (variant.payload.get("code") or {}).get("text", "") + "\n" + options
    reply = client.post("/api/v1/admin/assessment/leaks/lookup", json={"text": text}, headers=ADMIN)
    assert reply.status_code == 200, reply.text
    matches = reply.json()["matches"]
    found = next((m for m in matches if m["variant_id"] == str(variant.id)), None)
    assert found, (item.family_id, item.level if hasattr(item, "level") else None, text[:300], [(m["family_id"], m["match"]) for m in matches])
    assert found["family_id"] == item.family_id and found["sessions"][0]["session_id"] == str(session.id)
    nothing = client.post("/api/v1/admin/assessment/leaks/lookup", json={"text": "совершенно посторонний текст про погоду и кулинарию"}, headers=ADMIN)
    assert nothing.json()["matches"] == []
