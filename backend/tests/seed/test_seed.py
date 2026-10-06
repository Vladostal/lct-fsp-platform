"""Сид (Арх. 13.5): полнота, именованные состояния, идемпотентность, «у жюри не пусто»."""

from __future__ import annotations

from sqlalchemy import func, select

from app.core import db as core_db
from app.modules.assessment.models import CategoryRow
from app.modules.catalog import service as catalog
from app.modules.contact.models import Invitation
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
    with core_db.session_scope() as db:
        population = db.scalar(select(func.count()).select_from(AppUser).where(AppUser.demo_key.like("cand\\_%")))
        assert population == 150
        grades = dict(db.execute(select(CategoryRow.grade_code, func.count()).group_by(CategoryRow.grade_code)).all())
        assert set(grades) <= {"junior", "middle", "senior"} and min(grades.values()) >= 20
        specializations = set(db.scalars(select(CategoryRow.specialization_code)))
        assert specializations == {"backend"} and all(catalog.is_available("backend", g) for g in grades)
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
    assert demo.run_all() == {"population": 0, "named": 0, "companies": 0, "orbita": False}
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
