"""Зависимости роутеров: роли, служебный токен, флаги, адрес клиента (Арх. 9.2, 10.1, 10.3)."""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import APIRouter, Depends

from app.core.deps import (
    Admin,
    AnyUser,
    Candidate,
    ClientIp,
    Employer,
    Now,
    OptionalUser,
    Paging,
    require_feature,
)
from app.shared.enums import Role


@pytest.fixture
def api(probe, tx_router: APIRouter):
    @tx_router.get("/me")
    def me(user: AnyUser) -> dict[str, str]:
        return {"id": str(user.id), "role": user.role, "email": user.email}

    @tx_router.get("/maybe")
    def maybe(user: OptionalUser) -> dict[str, bool]:
        return {"signed_in": user is not None}

    @tx_router.get("/candidate/home")
    def candidate_home(user: Candidate) -> dict[str, str]:
        return {"role": user.role}

    @tx_router.get("/employer/home")
    def employer_home(user: Employer) -> dict[str, str]:
        return {"role": user.role}

    @tx_router.post("/admin/action")
    def admin_action(_: Admin) -> dict[str, bool]:
        return {"ok": True}

    @tx_router.get("/pulse/tasks", dependencies=[Depends(require_feature("pulse"))])
    def pulse_tasks() -> list[str]:
        return []

    @tx_router.get("/ip")
    def ip(address: ClientIp) -> dict[str, str]:
        return {"ip": address}

    @tx_router.get("/now")
    def now(moment: Now) -> dict[str, datetime]:
        return {"now": moment}

    @tx_router.get("/list")
    def listing(paging: Paging) -> dict[str, object]:
        return {"position": paging.position, "limit": paging.limit}

    return lambda **kwargs: probe(tx_router, **kwargs)


def test_no_session_is_401(api):
    client = api()
    for path in ("/api/v1/me", "/api/v1/candidate/home", "/api/v1/employer/home"):
        response = client.get(path)
        assert response.status_code == 401, path
        assert response.json()["code"] == "not_authenticated"
    assert client.get("/api/v1/maybe").json() == {"signed_in": False}


def test_garbage_cookie_is_401(api):
    client = api()
    client.cookies.set("sid", "not-a-real-token")
    assert client.get("/api/v1/me").status_code == 401


def test_foreign_role_is_403_and_own_role_is_200(api, make_user, login_as):
    candidate, employer = make_user("candidate"), make_user("employer")

    client = login_as(candidate, api())
    assert client.get("/api/v1/candidate/home").json() == {"role": "candidate"}
    forbidden = client.get("/api/v1/employer/home")
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "forbidden"

    client = login_as(employer, api())
    assert client.get("/api/v1/employer/home").status_code == 200
    assert client.get("/api/v1/candidate/home").status_code == 403
    me = client.get("/api/v1/me").json()
    assert me == {"id": str(employer.id), "role": Role.EMPLOYER, "email": employer.email}


def test_two_clients_keep_separate_sessions(make_client, make_user, login_as):
    """`make_client` даёт независимые cookie: два пользователя в одном тесте не мешают друг другу."""
    first, second = make_client(), make_client()
    login_as(make_user("candidate"), first)
    assert "sid" in first.cookies and "sid" not in second.cookies


def test_admin_token(api, settings):
    client = api()
    assert client.post("/api/v1/admin/action").status_code == 403
    assert client.post("/api/v1/admin/action", headers={"X-Admin-Token": "wrong"}).status_code == 403
    assert client.post("/api/v1/admin/action", headers={"X-Admin-Token": settings.admin_token}).json() == {"ok": True}


def test_admin_action_does_not_accept_user_session(api, make_user, login_as):
    client = login_as(make_user("employer"), api())
    assert client.post("/api/v1/admin/action").status_code == 403


def test_feature_flag_gives_404_feature_disabled(api, override_settings):
    client = api()
    assert client.get("/api/v1/pulse/tasks").status_code == 200
    override_settings(feature_pulse=False)
    response = client.get("/api/v1/pulse/tasks")
    assert response.status_code == 404
    assert response.json()["code"] == "feature_disabled"


def test_unknown_feature_name_is_a_programming_error():
    with pytest.raises(ValueError):
        require_feature("teleport")


def test_x_real_ip_trusted_only_from_proxy_network(api):
    """Арх. 10.1: заголовок принимается только от соединения из TRUSTED_PROXY_CIDRS (подсеть compose)."""
    spoof = {"X-Real-IP": "203.0.113.7"}

    from_proxy = api(client=("172.28.5.4", 51000))
    assert from_proxy.get("/api/v1/ip", headers=spoof).json() == {"ip": "203.0.113.7"}
    assert from_proxy.get("/api/v1/ip").json() == {"ip": "172.28.5.4"}
    assert from_proxy.get("/api/v1/ip", headers={"X-Real-IP": "not-an-address"}).json() == {"ip": "172.28.5.4"}

    from_outside = api(client=("198.51.100.20", 51000))
    assert from_outside.get("/api/v1/ip", headers=spoof).json() == {"ip": "198.51.100.20"}

    # X-Forwarded-For не участвует вовсе: uvicorn запущен без --proxy-headers.
    assert from_proxy.get("/api/v1/ip", headers={"X-Forwarded-For": "203.0.113.9"}).json() == {"ip": "172.28.5.4"}


def test_now_dependency_is_service_time(api, db, freeze_now):
    from app.core import clock

    frozen = freeze_now("2026-10-05T12:00:00+00:00")
    clock.advance(db, 3600)
    moment = datetime.fromisoformat(api().get("/api/v1/now").json()["now"])
    assert (moment - frozen).total_seconds() == 3600


def test_paging_dependency(api):
    from app.core.pagination import encode_cursor

    client = api()
    assert client.get("/api/v1/list").json() == {"position": None, "limit": 20}
    cursor = encode_cursor({"id": "42"})
    assert client.get("/api/v1/list", params={"cursor": cursor, "limit": 50}).json() == {
        "position": {"id": "42"},
        "limit": 50,
    }
    assert client.get("/api/v1/list", params={"limit": 51}).status_code == 422
    broken = client.get("/api/v1/list", params={"cursor": "!!!"})
    assert broken.status_code == 422
    assert broken.json()["code"] == "cursor_invalid"
