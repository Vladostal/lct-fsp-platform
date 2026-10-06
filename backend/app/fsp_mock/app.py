"""ASGI-приложение демо-ФСП: реестр `/registry/v1`, провайдер `/oidc`, ручки ведущего `/admin` (Арх. 7.3).

Монтируется в `/api/fsp-mock` при `FSP_MOCK_ENABLED=true` (`app.wiring`). У приложения своя схема OpenAPI
(`/api/fsp-mock/openapi.json`): она и публикуется как предлагаемый контракт реестра ФСП. Ошибки —
`application/problem+json` (RFC 9457) с полем `code`. Роутер `/admin` подключён только при
`FSP_MOCK_ADMIN=true` и требует `X-Admin-Token`.
"""

from __future__ import annotations

import uuid
from contextlib import suppress
from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.core import clock
from app.core.config import get_settings
from app.core.deps import require_admin
from app.core.errors import ApiException
from app.fsp_mock import oidc, registry_service, schemas
from app.fsp_mock import reference as ref
from app.fsp_mock.auth import resolve_caller
from app.fsp_mock.models import AccessGrant, Athlete, Competition, Entry, EntryMember
from app.fsp_mock.registry_service import RegistryError, RegistryMalformed, registry_session

PROBLEM = "application/problem+json"
_PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": schemas.Problem, "description": text, "content": {PROBLEM: {}}}
    for status, text in {
        401: "invalid_token",
        403: "insufficient_scope, grant_required, grant_revoked",
        404: "athlete_not_found, competition_not_found",
        422: "validation_error",
        429: "rate_limited",
        503: "registry_unavailable",
    }.items()
}


def _responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    return {status: _PROBLEM_RESPONSES[status] for status in statuses}


def _version_header(response: Response) -> None:
    response.headers["X-Registry-Version"] = ref.REGISTRY_VERSION


VersionHeader = Annotated[None, Depends(_version_header)]

registry = APIRouter(prefix="/registry/v1", tags=["registry"], dependencies=[Depends(_version_header)])


@registry.get("/health", response_model=schemas.Health, responses=_responses(503), summary="R1. Доступность")
def health() -> schemas.Health:
    # Доступность — не выгрузка: режим «некорректный ответ» здоровье не ломает.
    with registry_session() as db, suppress(RegistryMalformed):
        registry_service.check_failure_mode(db, in_process=False)
    return schemas.Health(version=ref.REGISTRY_VERSION)


@registry.get("/dictionaries", response_model=schemas.Dictionaries, summary="R2. Словари")
def dictionaries() -> schemas.Dictionaries:
    return registry_service.dictionaries()


@registry.get(
    "/athletes/{fsp_id}/export",
    response_model=schemas.AthleteExport,
    responses={304: {"description": "Не изменилось (ETag совпал)"}, **_responses(401, 403, 404, 422, 503)},
    summary="R3. Единая выгрузка сведений о спортсмене",
)
def athlete_export(
    fsp_id: UUID,
    request: Request,
    response: Response,
    if_none_match: Annotated[str | None, Header()] = None,
) -> Any:
    caller = resolve_caller(request)
    try:
        with registry_session() as db:
            result = registry_service.export(db, fsp_id, caller, if_none_match=if_none_match)
    except RegistryMalformed:
        return Response(content="<html>not a registry response</html>", media_type="text/html")
    headers = {"ETag": f'"{result.etag}"', "X-Registry-Version": ref.REGISTRY_VERSION}
    if isinstance(result, registry_service.ExportNotModified):
        return Response(status_code=304, headers=headers)
    return JSONResponse(content=result.body, headers=headers)


@registry.delete(
    "/athletes/{fsp_id}/grant",
    status_code=204,
    responses=_responses(401, 403, 422),
    summary="R4. Клиент сообщает об отвязке",
)
def athlete_grant_delete(fsp_id: UUID, request: Request) -> Response:
    caller = resolve_caller(request)
    with registry_session() as db:
        registry_service.revoke_grant(db, fsp_id, caller.client_id, clock.real_now())
    return Response(status_code=204)


@registry.get(
    "/competitions",
    response_model=schemas.CompetitionPage,
    responses=_responses(422, 503),
    summary="R5. Календарь соревнований",
)
def competitions(
    status: Annotated[str | None, Query(description="Статусы через запятую")] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    discipline: str | None = None,
    level: str | None = None,
    age_group: str | None = None,
    region: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> Any:
    try:
        with registry_session() as db:
            registry_service.check_failure_mode(db, in_process=False)
            return registry_service.list_competitions(
                db,
                statuses=[item for item in (status or "").split(",") if item],
                date_from=date_from,
                date_to=date_to,
                discipline=discipline,
                level=level,
                age_group=age_group,
                region=region,
                limit=limit,
                cursor=cursor,
            )
    except RegistryMalformed:
        return Response(content="<html>not a registry response</html>", media_type="text/html")


@registry.get(
    "/competitions/{competition_id}",
    response_model=schemas.Competition,
    responses=_responses(404),
    summary="R6. Карточка соревнования",
)
def competition_card(competition_id: str) -> schemas.Competition:
    with registry_session() as db:
        return registry_service.get_competition(db, competition_id)


# --- провайдер ФСП ID -------------------------------------------------------------------------------------------

provider = APIRouter(prefix="/oidc", tags=["oidc"], include_in_schema=True)

_NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def _error_page(message: str) -> HTMLResponse:
    return HTMLResponse(oidc.render_error(message), status_code=400, headers=_NO_STORE)


@provider.get("/authorize", response_class=HTMLResponse, summary="Страница входа демо-провайдера")
def authorize(request: Request, all: Annotated[int, Query(description="1 — показать скрытых персонажей")] = 0) -> Any:
    try:
        params = oidc.validate_authorize_params(dict(request.query_params))
    except oidc.AuthorizeError as exc:
        return _error_page(str(exc))
    with registry_session() as db:
        return HTMLResponse(oidc.render_authorize(db, params, show_all=bool(all)), headers=_NO_STORE)


@provider.post("/authorize/decision", summary="Решение пользователя на странице входа", response_class=RedirectResponse)
async def authorize_decision(request: Request) -> Any:
    form = await request.form()
    try:
        params = oidc.validate_authorize_params({key: str(value) for key, value in form.items()})
    except oidc.AuthorizeError as exc:
        return _error_page(str(exc))
    redirect_uri = params["redirect_uri"]
    state = params["state"]
    decision = str(form.get("decision") or ("allow" if form.get("pick") else ""))
    if decision != "allow":
        return RedirectResponse(
            oidc.redirect_url(redirect_uri, error="access_denied", state=state), status_code=302, headers=_NO_STORE
        )
    pick = str(form.get("pick") or "")
    raw_id = str(form.get("fsp_id") or "")
    with registry_session() as db:
        try:
            if pick:
                if pick not in oidc.PICKS:
                    return _error_page("Неизвестный быстрый выбор")
                fsp_id = oidc.pick_fsp_id(db, pick)
            else:
                fsp_id = uuid.UUID(raw_id)
                if db.get(Athlete, fsp_id) is None:
                    return _error_page("Такого участника нет в демо-реестре")
        except oidc.AuthorizeError as exc:
            return _error_page(str(exc))
        except ValueError:
            return _error_page("Выберите участника")
        code = oidc.issue_code(db, fsp_id=fsp_id, params=params, now=clock.real_now())
    return RedirectResponse(oidc.redirect_url(redirect_uri, code=code, state=state), status_code=302, headers=_NO_STORE)


# --- служебные ручки ведущего (только при FSP_MOCK_ADMIN=true и с X-Admin-Token) -------------------------------

admin = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
    responses={403: {"description": "forbidden"}},
)


@admin.post("/control", response_model=schemas.ControlView, summary="Режим отказа реестра")
def admin_control(body: schemas.ControlRequest) -> schemas.ControlView:
    with registry_session() as db:
        registry_service.set_failure_mode(db, body.failure_mode)
    return schemas.ControlView(failure_mode=body.failure_mode)


@admin.post(
    "/athletes/{fsp_id}/participations",
    response_model=schemas.AddParticipationView,
    status_code=201,
    responses={
        404: {"description": "athlete_not_found, competition_not_found"},
        422: {"description": "validation_error"},
    },
    summary="Добавить спортсмену результат в завершённое соревнование",
)
def admin_add_participation(fsp_id: UUID, body: schemas.AddParticipationRequest) -> schemas.AddParticipationView:
    with registry_session() as db:
        athlete = db.get(Athlete, fsp_id)
        competition = db.get(Competition, body.competition_id)
        if athlete is None:
            raise RegistryError(404, "athlete_not_found")
        if competition is None:
            raise RegistryError(404, "competition_not_found")
        if competition.status != "finished":
            raise RegistryError(422, "validation_error", "результат можно добавить только в завершённое соревнование")
        entry_id = f"{competition.competition_id}-demo-{uuid.uuid4().hex[:8]}"
        team = competition.participation == "team"
        db.add(
            Entry(
                entry_id=entry_id,
                competition_id=competition.competition_id,
                kind=competition.participation,
                team_name=(body.team_name or "Демо-команда") if team else None,
                region_code=athlete.region_code,
                result_status="ok",
                place=body.place,
            )
        )
        db.flush()
        db.add(EntryMember(entry_id=entry_id, fsp_id=fsp_id, role="athlete", is_captain=team))
        competition.entries_count = max(competition.entries_count or 0, body.place)
        db.flush()
    return schemas.AddParticipationView(entry_id=entry_id, competition_id=body.competition_id, place=body.place)


@admin.post(
    "/athletes/{fsp_id}/grant/revoke",
    status_code=204,
    summary="Отозвать разрешение «со стороны спортсмена»",
)
def admin_revoke_grant(fsp_id: UUID) -> Response:
    with registry_session() as db:
        for grant in db.query(AccessGrant).filter(AccessGrant.fsp_id == fsp_id, AccessGrant.revoked_at.is_(None)):
            grant.revoked_at = clock.real_now()
    return Response(status_code=204)


@admin.post("/reset", response_model=schemas.ResetView, summary="Вернуть реестр к состоянию сида")
def admin_reset() -> schemas.ResetView:
    from app.fsp_mock import generator

    with registry_session() as db:
        return generator.reset(db)


# --- сборка приложения ------------------------------------------------------------------------------------------


def _problem(
    status: int, code: str, title: str, detail: str | None = None, headers: dict[str, str] | None = None
) -> Any:
    body = schemas.Problem(
        title=title, status=status, detail=detail, code=code, request_id=uuid.uuid4().hex[:12]
    ).model_dump(exclude_none=True)
    return JSONResponse(body, status_code=status, media_type=PROBLEM, headers=headers)


async def _registry_error(_: Request, exc: Exception) -> Any:
    assert isinstance(exc, RegistryError)
    headers = {"X-Registry-Version": ref.REGISTRY_VERSION}
    if exc.retry_after is not None:
        headers["Retry-After"] = str(exc.retry_after)
    return _problem(exc.status, exc.code, exc.code.replace("_", " "), exc.detail, headers)


async def _api_error(_: Request, exc: Exception) -> Any:
    assert isinstance(exc, ApiException)
    return _problem(exc.status, "insufficient_scope" if exc.status == 403 else exc.code, exc.message, None)


async def _validation_error(_: Request, exc: Exception) -> Any:
    assert isinstance(exc, RequestValidationError)
    where = ", ".join(".".join(str(part) for part in error["loc"]) for error in exc.errors())
    return _problem(422, "validation_error", "validation error", f"неверные параметры: {where}")


def create_app() -> FastAPI:
    settings = get_settings()
    mock = FastAPI(
        title="Реестр ФСП (демонстрационный)",
        version=ref.REGISTRY_VERSION,
        description=(
            "Предлагаемый контракт API реестра Федерации спортивного программирования, как его видит платформа "
            "подбора специалистов. Данные синтетические. Ошибки — application/problem+json (RFC 9457) с полем `code`. "
            "ФИО, дата рождения и пол спортсмена в API не отдаются."
        ),
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    mock.add_exception_handler(RegistryError, _registry_error)
    mock.add_exception_handler(ApiException, _api_error)
    mock.add_exception_handler(RequestValidationError, _validation_error)
    mock.include_router(registry)
    mock.include_router(provider)
    if settings.fsp_mock_admin:
        mock.include_router(admin)
    return mock


app = create_app()
