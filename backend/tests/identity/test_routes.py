"""Набор путей модулей `identity`, `company`, `reports` совпадает с таблицей Арх. 9.4; ошибки описаны в OpenAPI."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.db import TxRoute

EXPECTED = {
    ("POST", "/auth/signup"),
    ("POST", "/auth/resend-verification"),
    ("POST", "/auth/verify-email"),
    ("POST", "/auth/login"),
    ("POST", "/auth/logout"),
    ("GET", "/auth/me"),
    ("POST", "/auth/password"),
    ("POST", "/auth/password/forgot"),
    ("POST", "/auth/password/reset"),
    ("POST", "/auth/account/delete"),
    ("GET", "/legal/{doc}"),
    ("GET", "/validation/summary"),
    ("GET", "/employer/company"),
    ("PUT", "/employer/company"),
}


def _routers() -> list[APIRouter]:
    from app.modules import company, identity, reports

    return [*identity.ROUTERS, *company.ROUTERS, *reports.ROUTERS]


def test_paths_match_the_api_table():
    found = {(method, route.path) for router in _routers() for route in router.routes for method in route.methods}  # type: ignore[attr-defined]
    assert found == EXPECTED


def test_routers_use_tx_route():
    assert all(router.route_class is TxRoute for router in _routers())


def test_openapi_describes_errors(app):
    schema = app.openapi()
    for method, path in EXPECTED:
        operation = schema["paths"][f"/api/v1{path}"][method.lower()]
        codes = set(operation["responses"])
        assert any(code.startswith("2") for code in codes), (method, path)
        if path not in ("/validation/summary",):
            assert any(code.startswith("4") for code in codes), (method, path)
    me = schema["paths"]["/api/v1/auth/login"]["post"]["responses"]
    assert {"401", "403", "429"} <= set(me)
