"""Эндпоинты `/demo/*` (Арх. 9.10, 13.5): демо-аккаунты, вход «как…», перезапуск сценария, быстрый демо-тест,
часы сервиса и сброс демо-данных (последние два — только с `X-Admin-Token`).

Без `DEMO_MODE` роутер отвечает 404 `feature_disabled` (зависимость `require_feature("demo")`; при выключенном
флаге `app.wiring` его не подключает вовсе).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from app.core import security
from app.core.config import get_settings
from app.core.db import TxRoute
from app.core.deps import Admin, Candidate, ClientIp, Db, Now, OptionalUser, is_admin, require_feature
from app.core.errors import ApiException, error_responses
from app.modules.demo import service
from app.modules.demo.dto import (
    ClockAdvance,
    DemoAccount,
    DemoClock,
    DemoLoginRequest,
    DemoMe,
    QuickSessionRequest,
    QuickSessionResult,
    ResetResult,
    RestartResult,
)
from app.modules.identity import service as identity

router = APIRouter(route_class=TxRoute, dependencies=[Depends(require_feature("demo"))])

#: Перезапуск сценария для посетителя: раз в 10 минут с одного IP и раз в 2 минуты на стенд (Арх. 13.5).
RESTART_IP_WINDOW_S = 600
RESTART_GLOBAL_WINDOW_S = 120


@router.get(
    "/demo/accounts",
    response_model=list[DemoAccount],
    responses=error_responses(404),
    summary="Именованные демо-аккаунты сценария",
)
def list_accounts(db: Db) -> list[DemoAccount]:
    return service.accounts(db)


@router.post(
    "/demo/login",
    response_model=DemoMe,
    responses=error_responses(404, 422),
    summary="Вход «как…» в именованный демо-аккаунт",
)
def demo_login(body: DemoLoginRequest, response: Response, db: Db, now: Now) -> DemoMe:
    """Открывает сессию и ставит cookie; 404 — нет такого аккаунта (в том числе `nina`: клонов в сборке нет)."""
    user_id = service.login_user_id(db, body.account_key)
    user = identity.get_user(db, user_id)
    security.set_session_cookie(response, identity.create_session(db, user_id))
    return DemoMe(id=user.id, email=user.email, role=user.role, is_demo=user.is_demo, server_now=now)


@router.post(
    "/demo/scenario/restart",
    response_model=RestartResult,
    responses=error_responses(401, 403, 404, 429),
    summary="Начать сценарий заново",
)
def restart(request: Request, db: Db, now: Now, user: OptionalUser, ip: ClientIp) -> RestartResult:
    """Сессия именованного демо-аккаунта либо `X-Admin-Token` (без лимитов).

    401 — нет сессии; 403 — живой пользователь, не аккаунт сценария либо `DEMO_PUBLIC_RESTART=false`;
    429 — раз в 10 минут с одного IP и раз в 2 минуты на стенд (`params.retry_after`).
    """
    if not is_admin(request):
        if user is None:
            raise ApiException(401, "not_authenticated")
        if not user.is_demo or not service.is_scenario_user(db, user.id) or not get_settings().demo_public_restart:
            raise ApiException(403, "forbidden")
        identity.throttle(db, "demo_restart", ip=ip, limit=1, window_s=RESTART_IP_WINDOW_S)
        identity.throttle(db, "demo_restart", limit=1, window_s=RESTART_GLOBAL_WINDOW_S)
    # Сид пишет в своих транзакциях и удаляет в том числе сессию вызывающего: свою сначала фиксируем.
    db.commit()
    service.restart_scenario()
    return RestartResult(restarted_at=now)


@router.post(
    "/demo/assessment/quick-session",
    response_model=QuickSessionResult,
    responses=error_responses(401, 403, 404, 409, 422),
    summary="Быстрый демо-тест: 12 ответов из 14 подставлены",
)
def quick_session(body: QuickSessionRequest, user: Candidate, db: Db, now: Now) -> QuickSessionResult:
    """Начать тест, в котором кандидат отвечает только на последние задания; результат помечается как демо.

    Право на старт — как у обычного теста. 409: `session_active`, `cooldown_active`, `survey_required`,
    `claim_required`; 422: `grade_not_allowed`, `grade_unavailable`.
    """
    return QuickSessionResult(session_id=service.quick_session(db, user.id, body.grade_code, now))


@router.get(
    "/demo/clock",
    response_model=DemoClock,
    responses=error_responses(403, 404),
    summary="Часы сервиса: время и демо-сдвиг",
)
def clock_state(_: Admin, db: Db) -> DemoClock:
    return service.clock_state(db)


@router.post(
    "/demo/clock/advance",
    response_model=DemoClock,
    responses=error_responses(403, 404, 409, 422),
    summary="Сдвинуть время сервиса вперёд",
)
def advance_clock(body: ClockAdvance, _: Admin, db: Db) -> DemoClock:
    """Показ истечения сроков: приглашения, паузы теста. Только вперёд; 409 `sessions_in_progress` — идут тесты,
    их время выйдет (повтор с `force = true` сдвигает всё равно). Сессии входа сдвиг не затрагивает.
    """
    return service.advance_clock(db, body.hours, force=body.force)


@router.post(
    "/demo/reset",
    response_model=ResetResult,
    responses=error_responses(403, 404, 503),
    summary="Сбросить демо-данные",
)
def reset(_: Admin, db: Db, now: Now) -> ResetResult:
    """Удалить все демо-аккаунты с их данными и создать сид заново. Живых пользователей не трогает."""
    # Сид пишет в своих транзакциях: свою сначала фиксируем (как при перезапуске сценария).
    db.commit()
    service.reset_all()
    return ResetResult(reset_at=now)
