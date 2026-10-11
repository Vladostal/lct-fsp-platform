"""Эндпоинты `/assessment/*` (Арх. 9.5)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.db import TxRoute
from app.core.deps import Candidate, ClientIp, Db, Now, OptionalUser
from app.core.errors import ApiException, error_responses
from app.modules.assessment import candidate, preview, sessions
from app.modules.assessment.constants import PREVIEW_LIMIT_ANON_PER_HOUR, PREVIEW_LIMIT_USER_PER_HOUR
from app.modules.assessment.schemas import (
    AnswerRequest,
    AnswerResult,
    AssessmentStateView,
    BlueprintPreview,
    BlueprintPreviewRequest,
    ClaimRequest,
    HistoryItem,
    MethodologyView,
    ResultPending,
    SessionCreate,
    SurveySchema,
    SurveyUpdate,
    TestBlueprintView,
    TestResultView,
    TestSessionView,
)
from app.modules.identity import service as identity
from app.shared.enums import Role

router = APIRouter(prefix="/assessment", tags=["assessment"], route_class=TxRoute)


@router.get("/survey", response_model=SurveySchema, responses=error_responses(401, 403))
def get_survey(user: Candidate, db: Db) -> SurveySchema:
    """Схема опроса и сохранённые ответы."""
    return candidate.get_survey(db, user.id)


@router.put("/survey", response_model=SurveySchema, responses=error_responses(401, 403, 409, 422))
def put_survey(payload: SurveyUpdate, user: Candidate, db: Db, now: Now) -> SurveySchema:
    """Сохранить ответы опроса. 409: `survey_version_mismatch`, `session_active`,
    `specialization_change_requires_confirm`, `cooldown_active`; 422 — ошибки полей и
    `specialization_unavailable` (тест по специализации написан, но сейчас недоступен).

    Специализация без теста принимается: категория в ней будет заявленной (`PUT /assessment/claim`).
    """
    return candidate.put_survey(
        db, user.id, payload.version, dict(payload.answers), payload.confirm_specialization_change, now
    )


@router.put("/claim", response_model=AssessmentStateView, responses=error_responses(401, 403, 409, 422))
def put_claim(payload: ClaimRequest, user: Candidate, db: Db, now: Now) -> AssessmentStateView:
    """Заявить грейд. 409: `survey_required`, `claim_locked`, `cooldown_active`; 422: `grade_unavailable`.

    В специализации без теста заявление сразу даёт категорию `basis = declared`. Первую смену заявленного грейда
    можно сделать сразу, следующие — раз в 90 дней: иначе 409 `cooldown_active` с `params.reason = grade_change`
    и `params.available_at`.
    """
    return candidate.put_claim(db, user.id, payload.grade_code, now)


@router.get("/state", response_model=AssessmentStateView, responses=error_responses(401, 403))
def get_state(user: Candidate, db: Db, now: Now) -> AssessmentStateView:
    """Опрос, заявленный грейд, категория, уровень, активная сессия и доступные действия."""
    return candidate.state_view(db, user.id, now)


@router.get("/blueprints", response_model=list[TestBlueprintView], responses=error_responses(401, 403, 409))
def get_blueprints(user: Candidate, db: Db) -> list[TestBlueprintView]:
    """Планы теста по грейдам своей специализации. 409 `survey_required`.

    Пустой список — теста по специализации пока нет.
    """
    return candidate.blueprint_views(db, user.id)


@router.post(
    "/sessions",
    response_model=TestSessionView,
    status_code=201,
    responses=error_responses(401, 403, 409, 422, 503),
)
def create_session(payload: SessionCreate, user: Candidate, db: Db, now: Now) -> TestSessionView:
    """Начать тест. 409: `session_active`, `cooldown_active`, `survey_required`, `claim_required`;
    422: `grade_not_allowed`, `grade_unavailable`; 503 `bank_unavailable`.
    """
    session = sessions.start_session(db, user.id, payload.grade_code, now)
    return candidate.session_view(db, session, now)


@router.get("/sessions/{session_id}", response_model=TestSessionView, responses=error_responses(401, 403, 404))
def get_session(session_id: str, user: Candidate, db: Db, now: Now) -> TestSessionView:
    """Сессия с текущим заданием; закрывает сессию, если время вышло."""
    return candidate.get_session(db, user.id, session_id, now)


@router.post(
    "/sessions/{session_id}/answers",
    response_model=AnswerResult,
    responses=error_responses(401, 403, 404, 409, 410, 422),
)
def post_answer(
    session_id: str,
    payload: AnswerRequest,
    user: Candidate,
    db: Db,
    now: Now,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=200)] = None,
) -> AnswerResult:
    """Ответ на текущее задание. 409: `item_already_answered`, `session_finished`; 410 `session_expired`;
    422 `answer_malformed` — в теле нет поля ответа для задания этого вида (задание остаётся текущим).

    Повтор запроса с тем же `Idempotency-Key` возвращает текущее состояние. Верность ответа не сообщается.
    """
    session = sessions.submit_answer(
        db,
        user.id,
        session_id,
        payload.item_id,
        payload.answer,
        payload.skipped,
        payload.client.model_dump(exclude_none=True) if payload.client else None,
        idempotency_key,
        now,
    )
    return candidate.answer_result(db, session, now)


@router.get(
    "/sessions/{session_id}/result",
    response_model=TestResultView,
    responses={202: {"model": ResultPending, "description": "Сессия ещё не закрыта"}, **error_responses(401, 403, 404)},
)
def get_result(session_id: str, user: Candidate, db: Db, now: Now) -> TestResultView | JSONResponse:
    """Результат закрытой сессии; 202 `{status: "in_progress"}`, пока сессия идёт."""
    view = candidate.result_view(db, user.id, session_id, now)
    if view is None:
        return JSONResponse(status_code=202, content=ResultPending().model_dump())
    return view


@router.get("/history", response_model=list[HistoryItem], responses=error_responses(401, 403))
def get_history(user: Candidate, db: Db, now: Now) -> list[HistoryItem]:
    """Опросы и тесты; без верности заданий."""
    return candidate.history(db, user.id, now)


@router.post(
    "/blueprints/preview",
    response_model=BlueprintPreview,
    responses=error_responses(401, 403, 422, 429),
)
def post_blueprint_preview(
    payload: BlueprintPreviewRequest, user: OptionalUser, db: Db, ip: ClientIp
) -> BlueprintPreview:
    """План теста из описания вакансии. Работодатель; при `features.demo` — без входа.

    422: `text_too_short`, `text_too_long`, `specialization_unavailable`; 429 `rate_limited` — лимит по
    пользователю и по IP для анонимного вызова (тяжёлый разбор текста).
    """
    if user is None:
        if not get_settings().features["demo"]:
            raise ApiException(401, "not_authenticated")
        identity.throttle(db, "blueprint_preview", ip=ip, limit=PREVIEW_LIMIT_ANON_PER_HOUR, window_s=3600)
    else:
        if user.role != Role.EMPLOYER:
            raise ApiException(403, "forbidden")
        identity.throttle(db, "blueprint_preview", user_id=user.id, limit=PREVIEW_LIMIT_USER_PER_HOUR, window_s=3600)
    return preview.preview_request(db, payload)


@router.get("/methodology", response_model=MethodologyView)
def get_methodology(db: Db) -> MethodologyView:
    """Константы механики и состав банка — без входа."""
    return preview.methodology(db)
