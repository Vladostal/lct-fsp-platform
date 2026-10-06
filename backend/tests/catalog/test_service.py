"""Фасад `catalog.service` и `GET /catalog`."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import Settings
from app.modules.catalog import service
from app.modules.catalog.models import SkillMissLog
from app.shared.schemas import CategoryRef, Ref

ALL_PAIRS = {(s, g) for s in ("backend", "frontend", "fullstack", "data_ml") for g in ("junior", "middle", "senior")}


def test_catalog_before_publication_everything_unavailable() -> None:
    catalog = service.get_catalog()
    assert catalog.available_categories == []
    assert not any(spec.available for spec in catalog.specializations)
    assert not any(grade.available for grade in catalog.grades)
    assert len(catalog.skills) == len(service.skill_entries())
    assert not service.is_available("backend") and not service.is_available("backend", "middle")


def test_availability_is_per_pair() -> None:
    service.publish_availability({("backend", "junior"), ("backend", "middle"), ("data_ml", "senior")})
    catalog = service.get_catalog()
    assert catalog.available_categories == ["backend:junior", "backend:middle", "data_ml:senior"]
    available = {spec.code for spec in catalog.specializations if spec.available}
    assert available == {"backend", "data_ml"}
    assert {grade.code: grade.available for grade in catalog.grades} == {"junior": True, "middle": True, "senior": True}
    assert service.is_available("backend", "middle") and not service.is_available("backend", "senior")
    assert service.specialization("data_ml").available and not service.specialization("frontend").available
    service.publish_availability(ALL_PAIRS)
    assert len(service.get_catalog().available_categories) == 12
    service.publish_availability(set())
    assert service.get_catalog().available_categories == []


def test_limits_have_salary_rules_and_cooldown(override_settings: Callable[..., Settings]) -> None:
    """Запросы № 3 и № 4 пакета F00: имена ключей вилки и срок повторной регистрации."""
    override_settings(reregister_cooldown_days=0.007)
    limits = service.get_catalog().limits
    assert limits["salary_min"] == 10_000 and limits["salary_max"] == 3_000_000
    assert limits["salary_max_ratio"] == 1.5
    assert limits["reregister_cooldown_days"] == 0.007


def test_published_limits_are_added_and_win() -> None:
    service.publish_limits(max_active_needs=5, salary_min=15_000)
    limits = service.get_catalog().limits
    assert limits["max_active_needs"] == 5 and limits["salary_min"] == 15_000
    assert limits["salary_max"] == 3_000_000


def test_features_come_from_settings(override_settings: Callable[..., Settings]) -> None:
    override_settings(feature_vacancies=True, feature_pulse=False, demo_mode=False)
    features = service.get_catalog().features
    assert features.vacancies is True and features.pulse is False and features.demo is False


def test_category_ref() -> None:
    ref = service.category_ref("backend:middle")
    assert isinstance(ref, CategoryRef)
    assert ref.title == "Backend · Middle" and ref.specialization.code == "backend" and ref.grade.title == "Middle"
    assert service.category_ref("data_ml:junior").title == "Data/ML · Junior"
    for bad in ("backend", "backend:expert", "cook:junior", ""):
        with pytest.raises(KeyError):
            service.category_ref(bad)


def test_skill_ref_and_is_skill() -> None:
    assert service.skill_ref("postgresql") == Ref(code="postgresql", title="PostgreSQL")
    assert service.is_skill("cpp") and not service.is_skill("COBOL")
    with pytest.raises(KeyError):
        service.skill_ref("COBOL")


def test_grades_ordered_and_specialization() -> None:
    assert [grade.code for grade in service.grades_ordered()] == ["junior", "middle", "senior"]
    spec = service.specialization("backend")
    assert spec.title_short == "Backend" and spec.direction_code == "development"
    with pytest.raises(KeyError):
        service.specialization("cook")


def test_catalog_endpoint_is_public(client: TestClient) -> None:
    service.publish_availability({("backend", "middle")})
    response = client.get("/api/v1/catalog")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "directions", "specializations", "grades", "skills", "roles", "available_categories", "limits", "features",
    }  # fmt: skip
    assert body["available_categories"] == ["backend:middle"]
    assert {"code", "title", "kind", "aliases"} == set(body["skills"][0])
    assert {"code", "title", "title_short", "direction_code", "available"} == set(body["specializations"][0])
    assert body["limits"]["salary_min"] == 10_000
    assert set(body["features"]) == {"demo", "vacancies", "pulse", "integrations"}


# ---------------------------------------------------------------------------------------------------------------------
# skill_miss_log
# ---------------------------------------------------------------------------------------------------------------------


def _rows(db: Session) -> dict[tuple[str, str], int]:
    return {(row.term, row.source): row.cnt for row in db.scalars(select(SkillMissLog))}


def test_log_miss_accumulates_counts(db: Session) -> None:
    service.log_miss(db, ["Tarantool", "Neo4j"], "need")
    service.log_miss(db, ["tarantool", "Tarantool"], "need")
    assert _rows(db) == {("tarantool", "need"): 2, ("neo4j", "need"): 1}


def test_log_miss_never_writes_resume_terms(db: Session) -> None:
    """Поправка R3-data-api-security-5: резюме с телефоном и e-mail не оставляет строк."""
    service.log_miss(db, ["+7-999-123-45-67", "ivan@example.com", "Tarantool", "Иванов"], "resume")
    assert _rows(db) == {}


def test_log_miss_filters_terms_that_do_not_look_like_skills(db: Session) -> None:
    junk = [
        "+7-999-123-45-67", "89991234567", "ivan@example.com", "https://example.com/ivan", "www.example.com",
        "x" * 31, "12345", "", "   ", "a", "a1b2c3d4",
    ]  # fmt: skip
    service.log_miss(db, [*junk, "scikit-learn", "C++", "Node.js"], "need")
    assert set(_rows(db)) == {("scikit-learn", "need"), ("c++", "need"), ("node.js", "need")}


def test_log_miss_takes_limited_number_of_terms(db: Session) -> None:
    service.log_miss(db, [f"tool{chr(97 + i)}x" for i in range(20)], "need")
    assert len(_rows(db)) == service.MISS_LOG_MAX_TERMS


def test_log_miss_rejects_unknown_source(db: Session) -> None:
    with pytest.raises(ValueError):
        service.log_miss(db, ["Tarantool"], "chat")


def test_log_miss_purges_old_rows(db: Session, freeze_now: Any) -> None:
    freeze_now("2026-01-01T12:00:00+00:00")
    service.log_miss(db, ["Oldtool"], "need")
    freeze_now.tick(days=service.MISS_LOG_RETENTION_DAYS - 1)
    service.log_miss(db, ["Midtool"], "need")
    assert set(_rows(db)) == {("oldtool", "need"), ("midtool", "need")}
    freeze_now.tick(days=2)
    service.log_miss(db, ["Newtool"], "need")
    assert set(_rows(db)) == {("midtool", "need"), ("newtool", "need")}
    assert service.purge_miss_log(db, clock.now(db) + timedelta(days=service.MISS_LOG_RETENTION_DAYS + 1)) == 2
