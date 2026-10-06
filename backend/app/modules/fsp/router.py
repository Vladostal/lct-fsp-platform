"""Эндпоинты `fsp` (Арх. 9.7; приложение D, §10.4): привязка ФСП ID, обновление, отвязка, календарь.

Все — только для кандидата и только про текущего пользователя: параметров `user_id` и `fsp_id` в запросах нет.
Роль `employer` на `/fsp/*` получает 403. У работодателя своих эндпоинтов ФСП нет: данные приходят в карточке
кандидата и строках подборки. Callback отвечает только 302 и JSON-ошибок не отдаёт.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Query, Response
from fastapi.responses import RedirectResponse

from app.core import clock
from app.core.db import TxRoute, session_scope
from app.core.deps import Candidate, Db, OptionalUser
from app.core.errors import ApiException, error_responses
from app.modules.assessment import service as assessment
from app.modules.fsp import consent_text, linking, screen, sync
from app.modules.fsp import constants as c
from app.modules.fsp.schemas import (
    FspCalendarView,
    FspConsentView,
    FspLinkStartRequest,
    FspLinkStartView,
    FspLinkView,
)
from app.shared.enums import Role

log = logging.getLogger("app.fsp")
router = APIRouter(route_class=TxRoute)

_NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def _specialization(db: Db, user_id: UUID) -> str | None:
    """Код специализации текущей категории кандидата (`assessment.get_category`); категории нет — `None`."""
    try:
        category = assessment.get_category(db, user_id)
    except NotImplementedError:  # модуль тестирования ещё не подключён: показ без переноса «дисциплина → специализация»
        return None
    return category.specialization_code if category is not None else None


def _link_view(db: Db, user_id: UUID) -> tuple[FspLinkView, bool]:
    now = clock.real_now()
    return screen.build_link_view(
        db, user_id, now=now, as_of=clock.today(db), specialization=_specialization(db, user_id)
    )


def background_sync(user_id: UUID) -> None:
    """Ленивое обновление (`stale`) после ответа: своя сессия, сбой не показывается и данных не меняет."""
    try:
        with session_scope() as db:
            sync.run_sync(db, user_id, "stale")
    except sync.NotLinked:
        pass
    except Exception as exc:
        log.warning("фоновое обновление ФСП не удалось: %s", type(exc).__name__)


@router.get(
    "/fsp/consent",
    response_model=FspConsentView,
    responses=error_responses(401, 403),
    summary="Текст и версия согласия на получение сведений ФСП",
)
def get_consent(user: Candidate) -> FspConsentView:
    return consent_text.consent_view()


@router.get(
    "/fsp/link",
    response_model=FspLinkView,
    responses=error_responses(401, 403),
    summary="Состояние привязки ФСП ID, свои достижения, строка «как видит работодатель»",
)
def get_link(user: Candidate, db: Db, background: BackgroundTasks) -> FspLinkView:
    """При устаревшем снимке ставит фоновое обновление: ответ отдаёт имеющиеся данные."""
    view, refresh = _link_view(db, user.id)
    if refresh:
        background.add_task(background_sync, user.id)
    return view


@router.post(
    "/fsp/link/start",
    response_model=FspLinkStartView,
    responses=error_responses(401, 403, 409, 422, 429, 503),
    summary="Запись согласия и начало потока OIDC",
)
def start_link(body: FspLinkStartRequest, user: Candidate, db: Db) -> FspLinkStartView:
    return linking.start_link(db, user.id, body)


@router.get(
    "/fsp/link/callback",
    status_code=302,
    response_class=RedirectResponse,
    responses={302: {"description": "Переход на /candidate/settings/fsp?result=…"}},
    summary="Возврат из ФСП ID (всегда 302)",
)
def link_callback(
    user: OptionalUser,
    db: Db,
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
) -> Response:
    """Всегда 302. Нет сессии — на `/login?next=…`, пользователь начнёт заново; иначе — на экран ФСП с `result`."""
    session_user = user.id if user is not None and user.role == Role.CANDIDATE else None
    if user is not None and session_user is None:
        outcome = linking.LinkOutcome("error", "state")  # сессия работодателя: привязывать некому
    else:
        outcome = linking.finish_link(db, session_user, code=code, state=state, error=error)
    if outcome.result == "login":
        target = f"{c.LOGIN_PATH}?next=%2Fcandidate%2Fsettings%2Ffsp"
    else:
        target = f"{c.SETTINGS_PATH}?{outcome.query()}"
    return RedirectResponse(target, status_code=302, headers=_NO_STORE)


@router.post(
    "/fsp/sync",
    response_model=FspLinkView,
    responses=error_responses(401, 403, 404, 429),
    summary="Ручное обновление данных из реестра",
)
def post_sync(user: Candidate, db: Db) -> FspLinkView:
    """Исход — в `refresh.last_outcome`, в том числе неуспешный: данные при этом не меняются."""
    try:
        sync.run_sync(db, user.id, "manual")
    except sync.NotLinked:
        raise ApiException(404, "fsp_not_linked") from None
    view, _ = _link_view(db, user.id)
    return view


@router.delete(
    "/fsp/link",
    status_code=204,
    response_class=Response,
    responses=error_responses(401, 403),
    summary="Отвязка ФСП ID и удаление полученных сведений (идемпотентно)",
)
def delete_link(user: Candidate, db: Db) -> Response:
    linking.unlink(db, user.id, reason="user")
    return Response(status_code=204)


@router.get(
    "/fsp/calendar",
    response_model=FspCalendarView,
    responses=error_responses(401, 403, 422),
    summary="Ближайшие соревнования ФСП (привязка не нужна)",
)
def get_calendar(
    user: Candidate,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=c.CALENDAR_LIMIT_MAX)] = c.CALENDAR_LIMIT_DEFAULT,
) -> Any:
    now = clock.real_now()
    return screen.build_calendar(
        db, now=now, today=clock.to_local_date(now), specialization=_specialization(db, user.id), limit=limit
    )
