"""Подбор через API и фасад: потребность, версии, скрытые кандидаты, банк, карточка, лимиты (Арх. 6.9–6.13, 9.8)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import ApiException
from app.modules.matching import constants as C
from app.modules.matching import service
from app.modules.matching.dto import ShortlistQuery, ShortlistRefinement
from app.modules.matching.models import ExposureEvent, Need, ShortlistItem, ShortlistSnapshot
from app.modules.matching.schemas import ShortlistSnapshotView, SnapshotDiffView
from app.shared.enums import VisibilityState, WorkFormat

API = "/api/v1"


@pytest.fixture
def employer(make_user: Callable[..., Any]) -> Any:
    return make_user("employer")


@pytest.fixture
def api(employer: Any, login_as: Callable[..., TestClient]) -> TestClient:
    return login_as(employer)


def make_need(db: Session, world: Any, employer_id: UUID, **changes: Any) -> UUID:
    return service.create_need(db, employer_id, world.need_data(**changes), clock.now(db))


def populate(world: Any) -> dict[str, Any]:
    """Шесть кандидатов backend:middle с разной силой и доказательствами, один junior с запасом, один frontend."""
    return {
        "top": world.add(theta=2.4, test={"python": True, "postgresql": True}, declared=["docker"]),
        "mid": world.add(theta=1.2, test={"python": True}, declared=["postgresql", "kafka"]),
        "declared": world.add(theta=1.2, declared=["python", "postgresql", "docker"]),
        "empty": world.add(theta=1.2),
        "fsp": world.add(theta=0.1, fsp_value=0.8, fsp_band="high", fsp_skills=["algorithms"], test={"python": False}),
        "office": world.add(theta=1.6, formats=("office",), test={"python": True}),
        "junior": world.add(
            grade="junior", verdict="confirmed_with_margin", theta=-0.2, cut=-1.5, test={"python": True}
        ),
        "frontend": world.add(spec="frontend", test={"react": True}),
    }


def ids_with_candidate(payload: Any) -> list[tuple[str, str]]:
    """Все места ответа, где есть поле `candidate_id`: (путь, значение)."""
    found: list[tuple[str, str]] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "candidate_id":
                    found.append((path, str(value)))
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for value in node:
                walk(value, f"{path}[]")

    walk(payload, "")
    return found


def schema_lists_with_candidate(model: type) -> set[str]:
    """Поля-списки схемы, элементы которых содержат `candidate_id` (по JSON-схеме модели)."""
    schema = model.model_json_schema()
    defs = schema.get("$defs", {})
    result = set()
    for name, prop in schema["properties"].items():
        ref = prop.get("items", {}).get("$ref", "")
        if ref and "candidate_id" in defs[ref.rsplit("/", 1)[-1]].get("properties", {}):
            result.add(name)
    return result


# --------------------------------------------------------------------------------------------------------------------
# Потребность
# --------------------------------------------------------------------------------------------------------------------


def test_need_crud_and_errors(api: TestClient, world: Any, db: Session, employer: Any) -> None:
    body = world.need_data().model_dump(mode="json")
    created = api.post(f"{API}/employer/needs", json=body)
    assert created.status_code == 201, created.text
    need = created.json()
    assert need["target"]["code"] == "backend:middle" and need["latest_snapshot"] is None
    assert [item["code"] for item in need["must_skills"]] == ["python", "postgresql"]
    assert [item["id"] for item in api.get(f"{API}/employer/needs").json()] == [need["id"]]

    unavailable = api.post(f"{API}/employer/needs", json={**body, "specialization_code": "mobile"})
    assert (unavailable.status_code, unavailable.json()["code"]) == (422, "specialization_unavailable")
    unknown = api.post(f"{API}/employer/needs", json={**body, "must_skills": ["python", "cobol"]})
    assert (unknown.status_code, unknown.json()["code"]) == (422, "skill_unknown")
    assert unknown.json()["fields"][0]["name"] == "must_skills"
    wide = api.post(f"{API}/employer/needs", json={**body, "salary_to": 900_000})
    assert (wide.status_code, wide.json()["code"]) == (422, "salary_range_too_wide")
    no_city = api.post(f"{API}/employer/needs", json={**body, "work_formats": ["office"]})
    assert no_city.status_code == 422 and no_city.json()["fields"][0]["name"] == "city"
    world.company_complete = False
    blocked = api.post(f"{API}/employer/needs", json=body)
    assert (blocked.status_code, blocked.json()["code"]) == (409, "company_profile_incomplete")
    world.company_complete = True

    updated = api.put(f"{API}/employer/needs/{need['id']}", json={**body, "title": "Python-разработчик"})
    assert updated.status_code == 200 and updated.json()["title"] == "Python-разработчик"
    archived = api.post(f"{API}/employer/needs/{need['id']}/archive")
    assert archived.json()["status"] == "archived"
    assert api.put(f"{API}/employer/needs/{need['id']}", json=body).json()["code"] == "need_archived"
    assert api.post(f"{API}/employer/needs/{need['id']}/shortlists").json()["code"] == "need_archived"
    assert api.get(f"{API}/employer/needs/{uuid4()}").status_code == 404


def test_need_parse(api: TestClient, world: Any) -> None:
    assert api.post(f"{API}/employer/needs/parse", json={"text": "мало"}).json()["code"] == "text_too_short"
    assert api.post(f"{API}/employer/needs/parse", json={"text": "я" * 5001}).json()["code"] == "text_too_long"
    draft = api.post(f"{API}/employer/needs/parse", json={"text": "Ищем backend-разработчика на Python и Kafka"})
    assert draft.status_code == 200 and draft.json()["must_skills"] == ["python"]


def test_foreign_need_is_404(api: TestClient, world: Any, db: Session, make_user: Callable[..., Any]) -> None:
    other = make_user("employer")
    need_id = make_need(db, world, other.id)
    snapshot_id = service.create_snapshot(db, other.id, need_id, clock.now(db))
    assert api.get(f"{API}/employer/needs/{need_id}").status_code == 404
    assert api.post(f"{API}/employer/needs/{need_id}/shortlists").status_code == 404
    assert api.get(f"{API}/employer/shortlists/{snapshot_id}").status_code == 404
    assert api.put(f"{API}/employer/needs/{need_id}/pins/{uuid4()}").status_code == 404
    with pytest.raises(ApiException) as error:
        service.need_ref(db, other.id, uuid4())
    assert error.value.status == 404
    ref = service.need_ref(db, other.id, need_id, snapshot_id)
    assert (ref.category_code, ref.snapshot_id, ref.salary_from) == ("backend:middle", snapshot_id, 200_000)


# --------------------------------------------------------------------------------------------------------------------
# Версии подборки
# --------------------------------------------------------------------------------------------------------------------


def test_snapshot_create_order_and_dedup(api: TestClient, world: Any, db: Session, employer: Any) -> None:
    people = populate(world)
    need_id = make_need(db, world, employer.id)
    created = api.post(f"{API}/employer/needs/{need_id}/shortlists")
    assert created.status_code == 201, created.text
    view = created.json()
    order = [item["candidate_id"] for item in view["items"]]
    # Закрытые обязательные → подтверждённое покрытие → сила → заявленное: `fsp` закрыл один обязательный из двух
    # и стоит выше пустого профиля, хотя тот сильнее; пустой остаётся с риском; junior с запасом — отдельно.
    expected = ["top", "mid", "declared", "fsp", "empty", "junior"]
    assert order == [str(people[name].id) for name in expected]
    assert [item["position"] for item in view["items"]] == [1, 2, 3, 4, 5, 6]
    assert view["items"][-1]["relation"] == "lower_with_margin" and view["items"][-1]["grade_margin"] is True
    assert view["funnel"] == {"category_total": 6, "available": 6, "format_ok": 5, "must_ok": 3, "shown": 5}
    empty_row = view["items"][4]
    assert empty_row["risk"].startswith("Нет данных по обязательным навыкам") and empty_row["fit_band"] == "partial"
    assert view["items"][2]["fit_band"] == "partial"  # одними заявлениями не выше «частичного»
    assert "pct" not in json.dumps(view["items"]) and view["version_no"] == 1 and view["is_latest"] is True
    assert view["scorer_version"] == "match-2+fsp-signal-test+skills-test"
    assert [row["relation"] for row in view["categories"]] == ["exact", "lower_with_margin", "higher"]

    again = api.post(f"{API}/employer/needs/{need_id}/shortlists")
    assert again.status_code == 200 and again.json()["id"] == view["id"]
    briefs = api.get(f"{API}/employer/needs/{need_id}/shortlists").json()
    assert [(row["version_no"], row["items_count"], row["is_latest"]) for row in briefs] == [(1, 6, True)]
    exposed = db.scalars(select(ExposureEvent.candidate_id).where(ExposureEvent.employer_id == employer.id)).all()
    assert set(map(str, exposed)) == set(order)


def test_salary_refinement_keeps_composition_and_order(api: TestClient, world: Any, db: Session, employer: Any) -> None:
    populate(world)
    need_id = make_need(db, world, employer.id)
    first = api.post(f"{API}/employer/needs/{need_id}/shortlists").json()
    body = {"parent_id": first["id"], "refinement": {"salary_from": 100_000, "salary_to": 140_000}}
    second = api.post(f"{API}/employer/needs/{need_id}/shortlists", json=body)
    assert second.status_code == 201
    view = second.json()
    assert [row["candidate_id"] for row in view["items"]] == [row["candidate_id"] for row in first["items"]]
    assert view["diff"] == {"added": 0, "dropped": 0, "moved_up": 0, "moved_down": 0}
    assert view["query_changes"].startswith("вилка: 200–280 → 100–140") and view["hints"] == first["hints"]


def test_versions_are_immutable_and_pin_survives_refinement(
    api: TestClient, world: Any, db: Session, employer: Any
) -> None:
    people = populate(world)
    need_id = make_need(db, world, employer.id)
    first = api.post(f"{API}/employer/needs/{need_id}/shortlists").json()
    stored = db.execute(select(ShortlistItem.candidate_id, ShortlistItem.position, ShortlistItem.explanation)).all()
    assert api.put(f"{API}/employer/needs/{need_id}/pins/{people['fsp'].id}").status_code == 204
    assert api.put(f"{API}/employer/needs/{need_id}/pins/{people['fsp'].id}").status_code == 204
    missing = api.put(f"{API}/employer/needs/{need_id}/pins/{people['frontend'].id}")
    assert (missing.status_code, missing.json()["code"]) == (404, "candidate_not_in_need")

    # Пул изменился: сильнейший стал слабее, появился новый кандидат.
    people["top"].theta = -0.5
    world.add(theta=2.9, test={"python": True})
    reread = api.get(f"{API}/employer/shortlists/{first['id']}").json()
    assert [(row["candidate_id"], row["position"]) for row in reread["items"]] == [
        (row["candidate_id"], row["position"]) for row in first["items"]
    ]
    refined = api.post(
        f"{API}/employer/needs/{need_id}/shortlists",
        json={"parent_id": first["id"], "refinement": {"require_fsp": True}},
    ).json()
    assert [row["candidate_id"] for row in refined["items"]] == [str(people["fsp"].id)]
    assert refined["items"][0]["pinned"] is True and refined["parent_id"] == first["id"]
    assert refined["diff"]["dropped"] == 5 and {row["reason_code"] for row in refined["dropped"]} == {"require_fsp"}
    assert refined["query_changes"] == "только с ФСП: включено"
    parent_rows = db.execute(
        select(ShortlistItem.candidate_id, ShortlistItem.position, ShortlistItem.explanation).where(
            ShortlistItem.snapshot_id == UUID(first["id"])
        )
    ).all()
    assert sorted(parent_rows, key=lambda row: row[1]) == sorted(stored, key=lambda row: row[1])

    # Закрепление принадлежит потребности: кандидат вне открытой версии виден в `pinned_outside`.
    assert api.put(f"{API}/employer/needs/{need_id}/pins/{people['mid'].id}").status_code == 204
    outside = api.get(f"{API}/employer/shortlists/{refined['id']}").json()["pinned_outside"]
    assert [row["candidate_id"] for row in outside] == [str(people["mid"].id)] and outside[0]["pinned"] is True
    assert api.delete(f"{API}/employer/needs/{need_id}/pins/{people['mid'].id}").status_code == 204
    assert api.get(f"{API}/employer/shortlists/{refined['id']}").json()["pinned_outside"] == []

    orphan = api.post(f"{API}/employer/needs/{need_id}/shortlists", json={"refinement": {"require_fsp": False}})
    assert (orphan.status_code, orphan.json()["code"]) == (422, "parent_required")
    assert "parent_id" in orphan.json()["message"]
    foreign = api.post(
        f"{API}/employer/needs/{need_id}/shortlists",
        json={"parent_id": "00000000-0000-0000-0000-000000000001", "refinement": {"require_fsp": False}},
    )
    assert (foreign.status_code, foreign.json()["code"]) == (409, "parent_mismatch")
    bad = api.post(
        f"{API}/employer/needs/{need_id}/shortlists",
        json={"parent_id": first["id"], "refinement": {"must_skills": ["cobol"]}},
    )
    assert (bad.status_code, bad.json()["code"]) == (422, "skill_unknown")


def test_diff_between_versions(api: TestClient, world: Any, db: Session, employer: Any, make_user: Any) -> None:
    people = populate(world)
    need_id = make_need(db, world, employer.id)
    first = api.post(f"{API}/employer/needs/{need_id}/shortlists").json()
    people["empty"].test = {"python": True, "postgresql": True}  # полоса подтверждённого покрытия выросла
    body = {"parent_id": first["id"], "refinement": {"work_formats": ["remote", "office"], "grade_codes": ["middle"]}}
    second = api.post(f"{API}/employer/needs/{need_id}/shortlists", json=body).json()
    forward = api.get(f"{API}/employer/shortlists/{second['id']}/diff", params={"base": first["id"]}).json()
    backward = api.get(f"{API}/employer/shortlists/{first['id']}/diff", params={"base": second["id"]}).json()
    assert forward["diff"] == second["diff"] == {"added": 1, "dropped": 1, "moved_up": 1, "moved_down": 0}
    assert backward["diff"] == {"added": 1, "dropped": 1, "moved_up": 0, "moved_down": 1}
    assert [row["candidate_id"] for row in forward["added"]] == [str(people["office"].id)]
    assert [(row["candidate_id"], row["reason_code"]) for row in forward["dropped"]] == [
        (str(people["junior"].id), "category_excluded")
    ]
    assert [row["candidate_id"] for row in forward["moved"]] == [str(people["empty"].id)]
    assert "формат: + офис" in forward["query_changes"] and "− грейд: Junior" in forward["query_changes"]

    other_need = make_need(db, world, employer.id, title="Вторая потребность")
    other = api.post(f"{API}/employer/needs/{other_need}/shortlists").json()
    different = api.get(f"{API}/employer/shortlists/{second['id']}/diff", params={"base": other["id"]})
    assert (different.status_code, different.json()["code"]) == (409, "different_need")


def test_snapshot_rate_limit(api: TestClient, world: Any, db: Session, employer: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(C, "SNAPSHOT_RATE_PER_HOUR", 2)
    monkeypatch.setattr(C, "SNAPSHOT_DEDUP_MINUTES", 0)
    world.add()
    need_id = make_need(db, world, employer.id)
    assert api.post(f"{API}/employer/needs/{need_id}/shortlists").status_code == 201
    assert api.post(f"{API}/employer/needs/{need_id}/shortlists").status_code == 201
    limited = api.post(f"{API}/employer/needs/{need_id}/shortlists")
    assert (limited.status_code, limited.json()["code"]) == (429, "shortlist_rate_limited")


# --------------------------------------------------------------------------------------------------------------------
# Скрытый кандидат (Арх. 6.9, 6.11)
# --------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("state", [VisibilityState.PAUSED, VisibilityState.UNPUBLISHED])
def test_hidden_candidate_is_absent_everywhere(
    api: TestClient, world: Any, db: Session, employer: Any, state: VisibilityState
) -> None:
    people = populate(world)
    need_id = make_need(db, world, employer.id)
    first = api.post(f"{API}/employer/needs/{need_id}/shortlists").json()
    for name in ("mid", "junior", "fsp"):
        assert api.put(f"{API}/employer/needs/{need_id}/pins/{people[name].id}").status_code == 204
    # Вторая версия: junior выпадает (dropped), fsp остаётся закреплённым вне версии, office — новый.
    body = {"parent_id": first["id"], "refinement": {"grade_codes": ["middle"], "work_formats": ["remote", "office"]}}
    second = api.post(f"{API}/employer/needs/{need_id}/shortlists", json=body).json()
    third = api.post(
        f"{API}/employer/needs/{need_id}/shortlists",
        json={"parent_id": second["id"], "refinement": {"require_fsp": True, "grade_codes": []}},
    ).json()
    assert str(people["junior"].id) in {row["candidate_id"] for row in second["dropped"]}
    assert str(people["mid"].id) in {row["candidate_id"] for row in third["pinned_outside"]}

    hidden = [people["mid"], people["junior"], people["office"]]
    hidden_ids = {str(item.id) for item in hidden}
    secrets = {item.public_code for item in hidden}
    for item in hidden:
        item.state = state

    views = {
        "v1": api.get(f"{API}/employer/shortlists/{first['id']}").json(),
        "v2": api.get(f"{API}/employer/shortlists/{second['id']}").json(),
        "v3": api.get(f"{API}/employer/shortlists/{third['id']}").json(),
    }
    diffs = {
        "d21": api.get(f"{API}/employer/shortlists/{second['id']}/diff", params={"base": first["id"]}).json(),
        "d12": api.get(f"{API}/employer/shortlists/{first['id']}/diff", params={"base": second["id"]}).json(),
        "d32": api.get(f"{API}/employer/shortlists/{third['id']}/diff", params={"base": second["id"]}).json(),
    }
    # Один обход всех полей схем с `candidate_id`: ни в `items`, ни в `pinned_outside`, ни в `dropped`,
    # ни в строках `SnapshotDiffView`.
    assert schema_lists_with_candidate(ShortlistSnapshotView) == {"items", "pinned_outside", "dropped"}
    assert schema_lists_with_candidate(SnapshotDiffView) == {"added", "dropped", "moved"}
    for name, payload in {**views, **diffs}.items():
        leaked = [(path, value) for path, value in ids_with_candidate(payload) if value in hidden_ids]
        assert not leaked, (name, leaked)
        raw = json.dumps(payload, ensure_ascii=False)
        assert not any(code in raw for code in secrets), name
    assert views["v1"]["hidden_count"] == 2 and len(views["v1"]["items"]) == len(first["items"]) - 2
    assert views["v2"]["hidden_count"] == 3 and views["v3"]["hidden_count"] == 2
    assert views["v2"]["diff"] == second["diff"]  # счётчики остаются числами
    assert diffs["d21"]["hidden_count"] == 3 and diffs["d21"]["diff"]["added"] == 1 and diffs["d21"]["added"] == []

    for item in hidden:
        card = api.get(f"{API}/employer/candidates/{item.id}", params={"snapshot_id": first["id"]})
        assert card.status_code == 404
        assert api.get(f"{API}/employer/candidates/{item.id}").status_code == 404
    bank = api.get(f"{API}/employer/candidates").json()
    assert not hidden_ids & {row["candidate_id"] for row in bank["items"]}
    pin = api.put(f"{API}/employer/needs/{need_id}/pins/{people['office'].id}")
    assert (pin.status_code, pin.json()["code"]) == (404, "candidate_not_in_need")

    # Кандидат вернулся: строка появляется на прежней позиции, версия не менялась.
    for item in hidden:
        item.state = VisibilityState.VISIBLE
    back = api.get(f"{API}/employer/shortlists/{first['id']}").json()
    assert [(row["candidate_id"], row["position"]) for row in back["items"]] == [
        (row["candidate_id"], row["position"]) for row in first["items"]
    ]
    assert back["hidden_count"] == 0


def test_disclosed_pair_keeps_row_when_hidden(api: TestClient, world: Any, db: Session, employer: Any) -> None:
    people = populate(world)
    need_id = make_need(db, world, employer.id)
    first = api.post(f"{API}/employer/needs/{need_id}/shortlists").json()
    people["mid"].disclosed[employer.id] = frozenset({"email"})
    world.pause(people["mid"])
    world.unpublish(people["top"])
    people["top"].disclosed[employer.id] = frozenset({"email"})
    view = api.get(f"{API}/employer/shortlists/{first['id']}").json()
    rows = {row["candidate_id"]: row for row in view["items"]}
    assert view["hidden_count"] == 0 and len(rows) == len(first["items"])
    mid, top = rows[str(people["mid"].id)], rows[str(people["top"].id)]
    assert (mid["available"], mid["unavailable_reason"], mid["display_name"]) == (False, "paused", "Тест Кандидатов")
    assert (top["available"], top["unavailable_reason"]) == (False, "withdrawn")
    card = api.get(f"{API}/employer/candidates/{people['mid'].id}", params={"need_id": str(need_id)})
    assert card.status_code == 200
    body = card.json()
    assert (body["disclosed"], body["available"], body["display_name"]) == (True, False, "Тест Кандидатов")
    assert body["declared"]["about"] == "Пишу сервисы" and "email" not in json.dumps(body)


def test_declared_hidden_after_snapshot_created(api: TestClient, world: Any, db: Session, employer: Any) -> None:
    cand = world.add(declared=["python", "postgresql", "docker"], age_days=60)
    need_id = make_need(db, world, employer.id)
    first = api.post(f"{API}/employer/needs/{need_id}/shortlists").json()
    row = first["items"][0]
    assert {item["kind"] for item in row["top_evidence"]} == {"declared"}
    assert "заявлено кандидатом" in row["risk"] and row["must_covered"] == 2
    card = api.get(f"{API}/employer/candidates/{cand.id}", params={"snapshot_id": first["id"]}).json()
    assert "declared_match" in [reason["code"] for reason in card["match"]["reasons"]]

    cand.privacy = cand.privacy.model_copy(update={"show_declared_stack": False})
    row = api.get(f"{API}/employer/shortlists/{first['id']}").json()["items"][0]
    assert {item["kind"] for item in row["top_evidence"]} == {"none"}
    assert row["risk"].startswith("Нет данных по обязательным навыкам: PostgreSQL и Python")
    assert row["must_covered"] == 0 and row["fit_band"] == first["items"][0]["fit_band"]
    card = api.get(f"{API}/employer/candidates/{cand.id}", params={"snapshot_id": first["id"]}).json()
    match = card["match"]
    assert match["risk"]["code"] == "must_missing" and match["in_snapshot"] is True and match["position"] == 1
    assert "declared_match" not in [reason["code"] for reason in match["reasons"]]
    assert {item["kind"] for item in match["requirements"]} == {"none"} and card["skills"] == []


def test_fsp_details_only_for_disclosed_pair(api: TestClient, world: Any, db: Session, employer: Any) -> None:
    cand = world.add(fsp_value=0.8, fsp_band="high", fsp_skills=["algorithms"])
    need_id = make_need(db, world, employer.id, must_skills=["algorithms"], nice_skills=[])
    first = api.post(f"{API}/employer/needs/{need_id}/shortlists").json()
    # В `shortlist_item.explanation` — только идентификатор факта и обобщённый текст.
    stored = json.dumps(db.scalars(select(ShortlistItem.explanation)).all(), ensure_ascii=False)
    assert str(cand.fact_id) in stored and "Кубок" not in stored and "detail_full" not in stored
    assert "Кубок" not in json.dumps(first, ensure_ascii=False)
    assert first["items"][0]["top_evidence"][0]["kind"] == "fsp"

    def card() -> dict[str, Any]:
        response = api.get(f"{API}/employer/candidates/{cand.id}", params={"snapshot_id": first["id"]})
        assert response.status_code == 200, response.text
        return response.json()

    def fsp_reason(body: dict[str, Any]) -> str | None:
        return next((reason["text"] for reason in body["match"]["reasons"] if reason["code"] == "fsp"), None)

    assert fsp_reason(card()) == "Достижение ФСП: призёр всероссийских соревнований"
    cand.disclosed[employer.id] = frozenset({"email"})
    assert "Кубок" not in json.dumps(card(), ensure_ascii=False)
    cand.disclosed[employer.id] = frozenset({"email", "fsp_details"})
    detailed = card()
    assert "Кубок России" in (fsp_reason(detailed) or "")
    assert "Кубок России" in detailed["match"]["requirements"][0]["detail"]
    assert "Кубок России" in detailed["skills"][0]["detail"]

    # Кандидат скрыл достижения: довод не выводится, требование отдаётся как «нет данных».
    cand.privacy = cand.privacy.model_copy(update={"show_fsp_summary": False})
    hidden = card()
    assert fsp_reason(hidden) is None and hidden["match"]["requirements"][0]["kind"] == "none"
    row = api.get(f"{API}/employer/shortlists/{first['id']}").json()["items"][0]
    assert row["fsp_summary"] is None and row["top_evidence"][0]["kind"] == "none"


# --------------------------------------------------------------------------------------------------------------------
# Банк и карточка
# --------------------------------------------------------------------------------------------------------------------


def test_bank_filters_order_and_cursor(api: TestClient, world: Any, db: Session, employer: Any) -> None:
    people = populate(world)
    page = api.get(f"{API}/employer/candidates", params={"limit": 3})
    assert page.status_code == 200, page.text
    body = page.json()
    assert body["total"] == 8 and body["hidden_by_fsp"] is None and body["next_cursor"]
    # Специализации в порядке каталога, грейды от старшего к младшему, внутри категории — по силе.
    assert [row["category"]["code"] for row in body["sections"]] == [
        "backend:middle",
        "backend:junior",
        "frontend:middle",
    ]
    assert [row["candidate_id"] for row in body["items"][:2]] == [str(people["top"].id), str(people["office"].id)]
    assert body["items"][0]["strength_label"] == "high" and "fit_band" not in body["items"][0]
    rest = api.get(f"{API}/employer/candidates", params={"limit": 3, "cursor": body["next_cursor"]}).json()
    assert not {row["candidate_id"] for row in rest["items"]} & {row["candidate_id"] for row in body["items"]}
    stale = api.get(f"{API}/employer/candidates", params={"limit": 3, "cursor": body["next_cursor"], "has_fsp": True})
    assert (stale.status_code, stale.json()["code"]) == (422, "cursor_invalid")
    assert api.get(f"{API}/employer/candidates", params={"cursor": "мусор"}).json()["code"] == "cursor_invalid"

    with_fsp = api.get(f"{API}/employer/candidates", params={"category": "backend:middle", "has_fsp": True}).json()
    assert [row["candidate_id"] for row in with_fsp["items"]] == [str(people["fsp"].id)]
    assert with_fsp["hidden_by_fsp"] == 5 and with_fsp["items"][0]["fsp_summary"] == "призёр, всеросс."

    by_code = api.get(f"{API}/employer/candidates", params={"code": people["declared"].public_code}).json()
    assert [row["candidate_id"] for row in by_code["items"]] == [str(people["declared"].id)] and by_code["total"] == 1
    latin = api.get(f"{API}/employer/candidates", params={"code": "K-" + people["declared"].public_code[2:]}).json()
    assert latin["total"] == 1

    sql = api.get(f"{API}/employer/candidates", params={"skills": "sql"}).json()  # postgresql закрывает sql
    assert {row["candidate_id"] for row in sql["items"]} == {
        str(people["top"].id),
        str(people["mid"].id),
        str(people["declared"].id),
    }
    confirmed = api.get(f"{API}/employer/candidates", params={"skills": "sql", "skills_confirmed_only": True}).json()
    assert [row["candidate_id"] for row in confirmed["items"]] == [str(people["top"].id)]
    assert [item["skill"]["code"] for item in confirmed["items"][0]["confirmed_skills"]] == ["postgresql", "python"]

    for params in (
        {"skills": "cobol"},
        {"category": "backend"},
        {"grade": "lead"},
        {"code": "12345"},
        {"specialization": "x"},
    ):
        invalid = api.get(f"{API}/employer/candidates", params=params)
        assert (invalid.status_code, invalid.json()["code"]) == (422, "filter_invalid"), params


def test_bank_page_limit(api: TestClient, world: Any, employer: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(C, "BANK_PAGES_LIMIT_PER_DAY", 3)
    world.add()
    for _ in range(3):
        assert api.get(f"{API}/employer/candidates").status_code == 200
    limited = api.get(f"{API}/employer/candidates")
    assert (limited.status_code, limited.json()["code"]) == (429, "bank_page_limit")
    assert limited.json()["params"]["retry_after"] > 0


def test_card_view_and_open_limit(api: TestClient, world: Any, db: Session, employer: Any, monkeypatch: Any) -> None:
    people = populate(world)
    need_id = make_need(db, world, employer.id)
    card = api.get(f"{API}/employer/candidates/{people['top'].id}")
    assert card.status_code == 200, card.text
    body = card.json()
    assert body["match"] is None and body["pinned"] is None and body["disclosed"] is False
    assert body["display_name"] is None and body["custom_skills"] == [] and body["declared"]["about"] is None
    assert body["declared"]["city"] == "Казань" and body["category"]["code"] == "backend:middle"
    assert [row["code"] for row in body["strength"]["contributions"]] == ["test", "freshness"]
    assert [item["skill"]["code"] for item in body["skills"]] == ["postgresql", "python", "docker"]
    opened = db.scalar(select(ExposureEvent.opened).where(ExposureEvent.candidate_id == people["top"].id))
    assert opened is True

    # Вне версии: объяснение считается на лету и не сохраняется.
    on_the_fly = api.get(f"{API}/employer/candidates/{people['mid'].id}", params={"need_id": str(need_id)}).json()
    assert on_the_fly["match"]["in_snapshot"] is False and on_the_fly["match"]["position"] is None
    assert on_the_fly["match"]["coverage"]["pct"] == 52 and on_the_fly["pinned"] is False
    outside = api.get(f"{API}/employer/candidates/{people['frontend'].id}", params={"need_id": str(need_id)}).json()
    assert outside["match"] is None
    assert api.get(f"{API}/employer/candidates/{people['top'].id}", params={"need_id": str(uuid4())}).status_code == 404
    assert api.get(f"{API}/employer/candidates/{uuid4()}").status_code == 404

    monkeypatch.setattr(C, "CARD_OPEN_LIMIT_PER_DAY", 2)
    assert api.get(f"{API}/employer/candidates/{people['top'].id}").status_code == 200  # повтор лимит не расходует
    limited = api.get(f"{API}/employer/candidates/{people['empty'].id}")
    assert (limited.status_code, limited.json()["code"]) == (429, "card_open_limit")


def test_demo_employer_sees_only_demo_candidates(
    world: Any, db: Session, make_user: Callable[..., Any], login_as: Callable[..., TestClient], monkeypatch: Any
) -> None:
    """R3-tz-compliance-1: демо-работодатель не видит живого кандидата в банке, версии подборки и карточке."""
    monkeypatch.setattr(C, "BANK_PAGES_LIMIT_PER_DAY", 1)
    demo_employer = make_user("employer", is_demo=True)
    live = world.add(theta=2.5, test={"python": True, "postgresql": True})
    synthetic = world.add(theta=1.0, is_demo=True)
    api = login_as(demo_employer)
    need_id = make_need(db, world, demo_employer.id)
    view = api.post(f"{API}/employer/needs/{need_id}/shortlists").json()
    assert [row["candidate_id"] for row in view["items"]] == [str(synthetic.id)]
    assert view["funnel"]["category_total"] == 1
    for _ in range(3):  # суточный лимит страниц банка к общим демо-аккаунтам не применяется
        bank = api.get(f"{API}/employer/candidates").json()
        assert [row["candidate_id"] for row in bank["items"]] == [str(synthetic.id)] and bank["total"] == 1
    assert api.get(f"{API}/employer/candidates", params={"code": live.public_code}).json()["total"] == 0
    assert api.get(f"{API}/employer/candidates/{live.id}").status_code == 404
    assert api.get(f"{API}/employer/candidates/{synthetic.id}").status_code == 200
    # Даже раскрытая (маскируемая) пара отвечает как нераскрытая.
    live.disclosed[demo_employer.id] = frozenset({"email"})
    assert api.get(f"{API}/employer/candidates/{live.id}").status_code == 404
    assert live.public_code not in api.get(f"{API}/employer/shortlists/{view['id']}").text
    with pytest.raises(ApiException) as error:
        service.explain_for_invitation(db, demo_employer.id, live.id, None, None, clock.now(db))
    assert error.value.status == 404

    real_employer = make_user("employer")
    real = login_as(real_employer, client=None)
    assert real.get(f"{API}/employer/candidates").json()["total"] == 2


def test_pdf_requires_disclosure(api: TestClient, world: Any, db: Session, employer: Any) -> None:
    cand = world.add(test={"python": True}, declared=["docker"], custom_skills=["свой тег"])
    denied = api.get(f"{API}/employer/candidates/{cand.id}/pdf")
    assert (denied.status_code, denied.json()["code"]) == (403, "not_disclosed") and world.access_log == []
    cand.disclosed[employer.id] = frozenset({"email"})
    ok = api.get(f"{API}/employer/candidates/{cand.id}/pdf")
    assert ok.status_code == 200 and ok.headers["content-type"] == "application/pdf" and ok.content.startswith(b"%PDF")
    assert world.access_log == [(cand.id, employer.id, "pdf_downloaded")]
    model = world.last_pdf_model
    assert model.full_name == "Кандидатов Тест" and model.contacts.email.endswith("@example.com")
    assert [item.skill.code for item in model.skills] == ["python"] and model.declared.skills == ["Docker"]
    assert "salary" not in json.dumps(model.model_dump(mode="json"))
    export = service.candidate_export(db, employer.id, cand.id, clock.now(db))
    assert export["card"]["disclosed"] is True and export["contacts"]["email"].endswith("@example.com")


def test_candidate_cabinet(world: Any, db: Session, login_as: Callable[..., TestClient], make_user: Any) -> None:
    cand = world.add(test={"python": True}, declared=["docker"], state=VisibilityState.UNPUBLISHED)
    user = type("U", (), {"id": cand.id})()
    api = login_as(user)
    evidence = api.get(f"{API}/candidate/evidence")
    assert evidence.status_code == 200, evidence.text
    body = evidence.json()
    assert [(item["skill"]["code"], item["kind"]) for item in body["skills"]] == [
        ("python", "test"),
        ("docker", "declared"),
    ]
    assert body["skills"][1]["detail"] == "указано вами в профиле" and body["strength"]["label"] in ("high", "medium")
    before = api.get(f"{API}/candidate/profile/preview").json()
    after = api.get(f"{API}/candidate/profile/preview", params={"state": "after"}).json()
    assert (before["disclosed"], before["display_name"], before["declared"]["about"]) == (False, None, None)
    assert (after["disclosed"], after["display_name"], after["declared"]["about"]) == (
        True,
        "Тест Кандидатов",
        "Пишу сервисы",
    )
    pdf = api.get(f"{API}/candidate/profile/pdf")
    assert pdf.status_code == 200 and pdf.headers["content-disposition"].startswith('attachment; filename="profile_')

    newcomer = make_user("candidate")
    fresh = login_as(newcomer, client=None)
    assert fresh.get(f"{API}/candidate/evidence").json() == {"skills": [], "strength": None}
    assert fresh.get(f"{API}/candidate/profile/preview").json()["code"] == "no_category"
    assert fresh.get(f"{API}/candidate/profile/pdf").json()["code"] == "profile_incomplete"
    assert fresh.get(f"{API}/employer/needs").status_code == 403


# --------------------------------------------------------------------------------------------------------------------
# Фасад для верхних модулей
# --------------------------------------------------------------------------------------------------------------------


def test_relaxation_hints_return_ready_refinement(api: TestClient, world: Any, db: Session, employer: Any) -> None:
    for _ in range(4):
        world.add(test={"python": True})  # закрывают всё, кроме kafka
    for _ in range(3):
        world.add(test={"python": True}, formats=("office",))
    need_id = make_need(db, world, employer.id, must_skills=["python", "kafka"], nice_skills=[])
    view = api.post(f"{API}/employer/needs/{need_id}/shortlists").json()
    hints = {hint["code"]: hint for hint in view["hints"]}
    move = hints["move_must_to_nice"]
    assert (move["value"], move["gain"]) == ("kafka", 4)
    assert move["refinement"]["must_skills"] == ["python"] and move["refinement"]["nice_skills"] == ["kafka"]
    assert (
        move["text"].replace("\u00a0", " ")
        == "Возможно, стоит перенести Kafka в желательные: +4 кандидата закрывают все обязательные"
    )
    assert hints["add_format"]["value"] == "office" and hints["add_format"]["gain"] == 3
    assert set(hints["add_format"]["refinement"]["work_formats"]) == {"office", "remote"}

    facade = service.relaxation_hints(db, employer.id, need_id, ["move_must_to_nice"], clock.now(db))
    assert [(hint.code, hint.value, hint.gain) for hint in facade] == [("move_must_to_nice", "kafka", 4)]
    assert isinstance(facade[0].refinement, ShortlistRefinement)
    applied = api.post(
        f"{API}/employer/needs/{need_id}/shortlists",
        json={"parent_id": view["id"], "refinement": move["refinement"]},
    ).json()
    # Перенос навыка состав подборки не меняет, но у кандидатов больше нет пробела в обязательных.
    assert {row["candidate_id"] for row in applied["items"]} == {row["candidate_id"] for row in view["items"]}
    assert applied["funnel"]["must_ok"] == 4 and view["funnel"]["must_ok"] == 0
    assert applied["query"]["must_skills"] == ["python"] and applied["query"]["nice_skills"] == ["kafka"]


def test_explain_for_invitation_and_exposure_stats(api: TestClient, world: Any, db: Session, employer: Any) -> None:
    people = populate(world)
    need_id = make_need(db, world, employer.id)
    now = clock.now(db)
    snapshot_id = service.create_snapshot(db, employer.id, need_id, now)
    explain = service.explain_for_invitation(db, employer.id, people["mid"].id, need_id, snapshot_id, now)
    why = explain.why
    assert (why.source, why.target.code, explain.fit_band) == ("need", "backend:middle", "good")
    assert [(item.skill.code, item.kind) for item in why.matched] == [("python", "test"), ("postgresql", "declared")]
    assert why.unconfirmed is not None and why.unconfirmed.skill.code == "postgresql"
    assert "категория и уровень по тесту" in why.employer_saw and explain.scorer_version.startswith("match-2+")
    dumped = json.dumps(explain.model_dump(mode="json"), ensure_ascii=False)
    assert "position" not in dumped and "risk" not in dumped and "contributions" not in dumped

    from_bank = service.explain_for_invitation(db, employer.id, people["top"].id, None, None, now)
    assert from_bank.why.source == "bank" and from_bank.fit_band is None
    assert [item.skill.code for item in from_bank.why.matched] == ["postgresql", "python"]

    api.get(f"{API}/employer/candidates/{people['mid'].id}")
    stats = service.exposure_stats(db, people["mid"].id, now.replace(year=now.year - 1), clock.now(db))
    assert (stats.needs_shown, stats.employers_opened, stats.unconfirmed_must) == (1, 1, ["postgresql"])
    refs = service.needs_with_candidate(db, people["mid"].id)
    assert [(ref.need_id, ref.snapshot_id) for ref in refs] == [(need_id, snapshot_id)]
    assert service.needs_with_candidate(db, people["frontend"].id) == []

    query = ShortlistQuery(
        specialization_code="backend", grade_code="middle", must_skills=["python"], work_formats=[WorkFormat.REMOTE]
    )
    scored = service.score_for_query(
        db, employer.id, query, [people["top"].id, people["office"].id, people["frontend"].id], now
    )
    assert list(scored) == [people["top"].id] and scored[people["top"].id].fit_band == "strong"


def test_demo_need_for(world: Any, db: Session, make_user: Callable[..., Any]) -> None:
    orbita = make_user("employer", is_demo=True, demo_key="orbita")
    company = make_user("employer", is_demo=True, demo_key="demo-company-1")
    now = clock.now(db)
    service.create_need(db, orbita.id, world.need_data(), now, is_demo=True)
    assert service.demo_need_for(db, "backend:middle") is None
    need_id = service.create_need(db, company.id, world.need_data(), now, is_demo=True)
    service.create_need(db, company.id, world.need_data(), now)  # не демо-потребность
    found = service.demo_need_for(db, "backend:middle")
    assert found is not None and found.need_id == need_id and found.employer_id == company.id
    assert service.demo_need_for(db, "backend:senior") is None
    assert db.scalar(select(Need.is_demo).where(Need.id == need_id)) is True
    assert db.scalar(select(ShortlistSnapshot.id)) is None
