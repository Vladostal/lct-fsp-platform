"""Подключение модуля: список `ROUTERS`, набор путей по таблице Арх. 9.6, схема OpenAPI, лимиты, фоновая задача."""

from __future__ import annotations

from fastapi.routing import APIRoute

from app import wiring
from app.core.db import TxRoute
from app.main import create_app
from app.modules.profile import ROUTERS, constants, service

EXPECTED = {
    ("GET", "/candidate/profile"),
    ("PUT", "/candidate/profile"),
    ("POST", "/candidate/profile/resume"),
    ("GET", "/candidate/conditions"),
    ("PUT", "/candidate/conditions"),
    ("GET", "/candidate/settings/privacy"),
    ("PUT", "/candidate/settings/privacy"),
    ("GET", "/candidate/consents"),
    ("POST", "/candidate/consents/publication"),
    ("POST", "/candidate/visibility"),
    ("GET", "/candidate/access-log"),
    ("GET", "/employer/candidates/{candidate_id}/contacts"),
}


def test_paths_match_table_9_6() -> None:
    assert ROUTERS
    routes = [route for router in ROUTERS for route in router.routes if isinstance(route, APIRoute)]
    assert all(isinstance(route, TxRoute) for route in routes)
    assert {(method, route.path) for route in routes for method in route.methods} == EXPECTED
    assert all(route.response_model is not None for route in routes)


def test_every_route_documents_errors() -> None:
    routes = [route for router in ROUTERS for route in router.routes if isinstance(route, APIRoute)]
    for route in routes:
        assert any(isinstance(code, int) and code >= 400 for code in route.responses), route.path


def test_openapi_builds_with_multipart_resume() -> None:
    schema = create_app().openapi()
    post = schema["paths"]["/api/v1/candidate/profile/resume"]["post"]
    body = post["requestBody"]["content"]["multipart/form-data"]["schema"]
    assert "file" in str(body)
    assert {"413", "415", "422", "429"} <= set(post["responses"])
    assert "ResumeParseResult" in str(post["responses"]["200"])


def test_limits_and_periodic_task_are_wired() -> None:
    assert "app.modules.profile.service:purge_resume_results" in {spec for _, spec in wiring.PERIODIC}
    assert callable(service.purge_resume_results)
    assert constants.PUBLIC_LIMITS["declared_skills_max"] == 30
