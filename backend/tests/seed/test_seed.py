"""Сид (Арх. 13.5): полнота, именованные состояния, идемпотентность, «у жюри не пусто»."""

from __future__ import annotations

from sqlalchemy import func, select

from app.core import db as core_db
from app.modules.assessment.models import CategoryRow
from app.modules.catalog import service as catalog
from app.modules.contact.models import Invitation
from app.modules.fsp.models import ExternalIdentity
from app.modules.identity import service as identity
from app.modules.identity.models import AppUser
from app.modules.matching import service as matching
from app.seed import demo
from tests.seed.support import API, World


def _status_by_key(db) -> dict[tuple[str, str], list[str]]:
    rows = db.execute(
        select(AppUser.demo_key, Invitation.status, Invitation.employer_id)
        .join(Invitation, Invitation.candidate_id == AppUser.id)
        .where(AppUser.demo_key.in_(["anna", "dmitry", "ivan", "gleb", "boris"]))
    ).all()
    result: dict[str, list[str]] = {}
    for key, status, _ in rows:
        result.setdefault(key, []).append(status)
    return {(key, ""): sorted(values) for key, values in result.items()}


def test_seed_is_complete_and_named_accounts_are_in_described_states(seeded: World) -> None:
    assert seeded.first_run["population"] == 150 and seeded.first_run["orbita"] is True
    assert seeded.first_run["declared"] == 9 * 12
    with core_db.session_scope() as db:
        population = db.scalar(select(func.count()).select_from(AppUser).where(AppUser.demo_key.like("cand\\_%")))
        assert population == 150
        counts: dict[str, dict[str, int]] = {}
        for specialization, grade, basis, count in db.execute(
            select(CategoryRow.specialization_code, CategoryRow.grade_code, CategoryRow.basis, func.count()).group_by(
                CategoryRow.specialization_code, CategoryRow.grade_code, CategoryRow.basis
            )
        ):
            # Категорию `backend` даёт только тест; у остальных специализаций грейд заявленный.
            assert basis == ("test" if specialization == "backend" else "declared"), (specialization, basis)
            counts.setdefault(specialization, {})[grade] = count
        grades = counts["backend"]
        assert set(grades) <= {"junior", "middle", "senior"} and min(grades.values()) >= 20
        assert set(counts) == set(catalog.specialization_codes()) and len(counts) == 10
        assert all(catalog.is_available("backend", g) for g in grades)
        for specialization in sorted(set(counts) - {"backend"}):
            assert not catalog.is_available(specialization)
            assert counts[specialization] == {"junior": 4, "middle": 5, "senior": 3}, specialization
        assert len(identity.demo_user_ids(db, ["company_1", "company_2", "company_3", "orbita"])) == 4
        for grade in grades:
            assert matching.demo_need_for(db, f"backend:{grade}") is not None
        states = _status_by_key(db)
        assert states[("dmitry", "")] == ["bounced"]
        assert states[("ivan", "")] == ["sent"] and states[("anna", "")] == ["sent"]
        assert states[("gleb", "")] == ["expired", "sent"]
        assert ("boris", "") not in states
        petr = identity.demo_user_ids(db, ["petr"])[0]
        assert db.scalar(select(CategoryRow.grade_code).where(CategoryRow.candidate_id == petr)) is None
        maria = identity.demo_user_ids(db, ["maria"])[0]
        assert (
            db.scalar(select(CategoryRow.verdict).where(CategoryRow.candidate_id == maria)) == "confirmed_with_margin"
        )


def test_seed_is_idempotent(seeded: World) -> None:
    with core_db.session_scope() as db:
        before = db.scalar(select(func.count()).select_from(AppUser))
        invitations = db.scalar(select(func.count()).select_from(Invitation))
    assert demo.scenario_ready()
    assert demo.run_all() == {"population": 0, "declared": 0, "named": 0, "companies": 0, "orbita": False}
    with core_db.session_scope() as db:
        assert db.scalar(select(func.count()).select_from(AppUser)) == before
        assert db.scalar(select(func.count()).select_from(Invitation)) == invitations


def test_typical_employer_query_has_at_least_ten_candidates_in_shortlist(seeded: World) -> None:
    employer = seeded.login_direct("company_2")
    created = employer.post(
        f"{API}/employer/needs",
        json={
            "title": "Python-разработчик (Middle)",
            "team_description": "Команда из шести человек, платёжное ядро.",
            "specialization_code": "backend",
            "grade_code": "middle",
            "must_skills": ["python"],
            "nice_skills": [],
            "work_formats": ["remote"],
            "salary_from": 220000,
            "salary_to": 280000,
        },
    )
    assert created.status_code == 201, created.text
    snapshot = employer.post(f"{API}/employer/needs/{created.json()['id']}/shortlists")
    assert snapshot.status_code in (200, 201), snapshot.text
    body = snapshot.json()
    exact = [c for c in body["categories"] if c["relation"] == "exact"]
    assert sum(c["count"] for c in exact) >= 10 and len(body["items"]) >= 10


def test_declared_population_fsp_links_and_no_invitations(seeded: World) -> None:
    """Кандидаты с заявленным грейдом: спортсмены ФСП не пересекаются с популяцией, приглашений сид им не шлёт."""
    with core_db.session_scope() as db:
        declared = dict(db.execute(select(AppUser.id, AppUser.demo_key).where(AppUser.demo_key.like("decl\\_%"))).all())
        assert len(declared) == 9 * 12
        links = db.execute(select(ExternalIdentity.user_id, ExternalIdentity.fsp_id)).all()
        assert len({fsp_id for _, fsp_id in links}) == len(links)
        linked: dict[str, int] = {}
        for user_id, _ in links:
            if user_id in declared:
                specialization = declared[user_id].removeprefix("decl_").rsplit("_", 1)[0]
                linked[specialization] = linked.get(specialization, 0) + 1
        # 40 % с историей и 5 % без участий: 5 + 1 из 12 в каждой специализации.
        assert len(linked) == 9 and set(linked.values()) == {6}
        invited = db.scalar(
            select(func.count()).select_from(Invitation).where(Invitation.candidate_id.in_(list(declared)))
        )
        assert invited == 0
        with_declared = db.scalars(select(CategoryRow.candidate_id).where(CategoryRow.basis == "declared")).all()
        assert set(with_declared) == set(declared)


def test_declared_demo_needs_have_shortlists(seeded: World) -> None:
    """Потребности Frontend и QA демо-компаний: версия подборки есть, в ней кандидаты с заявленным грейдом."""
    for category, company_key in (("frontend:middle", "company_1"), ("qa:middle", "company_2")):
        with core_db.session_scope() as db:
            need = matching.demo_need_for(db, category)
            assert need is not None and need.snapshot_id is not None, category
            sent = select(func.count()).select_from(Invitation).where(Invitation.need_id == need.need_id)
            assert db.scalar(sent) == 0
        employer = seeded.login_direct(company_key)
        snapshot = employer.post(f"{API}/employer/needs/{need.need_id}/shortlists")
        assert snapshot.status_code in (200, 201), snapshot.text
        items = snapshot.json()["items"]
        exact = [item for item in items if item["relation"] == "exact"]
        assert len(exact) >= 3, category
        assert all(item["category"]["basis"] == "declared" for item in items), category
        assert all(item["freshness_days"] is None and item["stale"] is False for item in items), category
        assert any(item["must_total"] == 2 for item in exact), category
