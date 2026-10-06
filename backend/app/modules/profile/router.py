"""Эндпоинты `profile` (Арх. 9.6).

Обработчики тонкие: разбор запроса и вызов сценария. Транзакцию фиксирует `TxRoute` до отправки ответа.
`GET /candidate/profile` создаёт строку профиля при первом обращении кандидата (Арх. 8.4): без неё нет кода кандидата.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, File, Request, Response, UploadFile

from app.core.db import TxRoute
from app.core.deps import Candidate, Db, Employer, Now, Paging
from app.core.errors import ApiException, error_responses, not_found
from app.modules.identity import service as identity
from app.modules.profile import disclosure, profiles, service
from app.modules.profile import privacy as privacy_store
from app.modules.profile import visibility as visibility_rules
from app.modules.profile.constants import RESUME_MAX_BYTES, RESUME_MULTIPART_OVERHEAD
from app.modules.profile.dto import PrivacyData
from app.modules.profile.models import CandidateProfile
from app.modules.profile.resume.parser import ERRORS
from app.modules.profile.resume.upload import upload_resume
from app.modules.profile.schemas import (
    AccessLogItem,
    CandidateContactsView,
    CandidateProfileUpdate,
    CandidateProfileView,
    ConditionsUpdate,
    ConditionsView,
    ConsentItem,
    ConsentsView,
    PrivacySettings,
    PublicationConsentRequest,
    ResumeParseResult,
    VisibilityRequest,
    VisibilityView,
)
from app.shared.enums import AccessKind, ConsentKind
from app.shared.schemas import Page


class _UploadRoute(TxRoute):
    """Маршрут загрузки: размер проверяется по `Content-Length` до чтения тела (Арх. 10.7).

    FastAPI читает multipart-тело раньше, чем выполняется обработчик, поэтому отказ большому файлу даёт сам маршрут.
    Запрос без `Content-Length` (потоковая передача) эту проверку обходит; его размер сверяет обработчик после
    чтения, а перед приложением стоит предел размера тела у `nginx` (Арх. 13).
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            length = request.headers.get("content-length", "")
            if length.isdigit() and int(length) > RESUME_MAX_BYTES + RESUME_MULTIPART_OVERHEAD:
                status, message = ERRORS["resume_too_large"]
                raise ApiException(status, "resume_too_large", message)
            return await original(request)

        return handler


router = APIRouter(route_class=TxRoute)


# --- профиль и резюме ------------------------------------------------------------------------------------------------


@router.get("/candidate/profile", response_model=CandidateProfileView, responses=error_responses(401, 403))
def get_profile(user: Candidate, db: Db, now: Now) -> CandidateProfileView:
    return profiles.profile_view(db, user.id, identity.get_user(db, user.id).email, now)


@router.put("/candidate/profile", response_model=CandidateProfileView, responses=error_responses(401, 403, 404, 422))
def put_profile(body: CandidateProfileUpdate, user: Candidate, db: Db, now: Now) -> CandidateProfileView:
    service.save_profile(db, user.id, body, now)
    return profiles.profile_view(db, user.id, identity.get_user(db, user.id).email, now)


def post_resume(
    file: Annotated[UploadFile, File(description="PDF до 5 МБ")], user: Candidate, db: Db, now: Now
) -> ResumeParseResult:
    # Читаем на один байт больше предела: превышение видно, а файл целиком в память не уходит.
    data = file.file.read(RESUME_MAX_BYTES + 1)
    return upload_resume(db, user.id, data, now)


router.add_api_route(
    "/candidate/profile/resume",
    post_resume,
    methods=["POST"],
    response_model=ResumeParseResult,
    responses=error_responses(401, 403, 413, 415, 422, 429),
    route_class_override=_UploadRoute,  # TxRoute с проверкой размера до чтения тела
)


# --- условия, приватность --------------------------------------------------------------------------------------------


@router.get("/candidate/conditions", response_model=ConditionsView, responses=error_responses(401, 403))
def get_conditions(user: Candidate, db: Db) -> ConditionsView:
    return profiles.conditions_view(db, user.id)


@router.put("/candidate/conditions", response_model=ConditionsView, responses=error_responses(401, 403, 422))
def put_conditions(body: ConditionsUpdate, user: Candidate, db: Db, now: Now) -> ConditionsView:
    service.save_conditions(db, user.id, body, now)
    return profiles.conditions_view(db, user.id)


@router.get("/candidate/settings/privacy", response_model=PrivacySettings, responses=error_responses(401, 403))
def get_privacy(user: Candidate, db: Db) -> PrivacySettings:
    return PrivacySettings(**privacy_store.load(db, user.id).model_dump())


@router.put("/candidate/settings/privacy", response_model=PrivacySettings, responses=error_responses(401, 403, 422))
def put_privacy(body: PrivacySettings, user: Candidate, db: Db, now: Now) -> PrivacySettings:
    # `hidden_domains` не передан — сохранённый список не меняется (экран P0 этого поля не знает).
    data = PrivacyData.model_validate(body.model_dump(exclude_unset=True))
    service.save_privacy(db, user.id, data, now)
    return PrivacySettings(**privacy_store.load(db, user.id).model_dump())


# --- согласие на публикацию и показ ----------------------------------------------------------------------------------


def _visibility_view(state: Any) -> VisibilityView:
    return VisibilityView(state=state.state, pause_reason=state.pause_reason, auto_paused_until=state.auto_paused_until)


def _consent_item(consent: Any, current_version: str | None) -> ConsentItem:
    granted = consent is not None and consent.revoked_at is None
    return ConsentItem(
        granted=granted,
        version=consent.version if granted else None,
        current_version=current_version or (consent.version if consent else ""),
        granted_at=consent.granted_at if granted else None,
    )


@router.get("/candidate/consents", response_model=ConsentsView, responses=error_responses(401, 403))
def get_consents(user: Candidate, db: Db, now: Now) -> ConsentsView:
    given = identity.consents(db, user.id)
    fsp = given.get(ConsentKind.FSP_DATA)
    return ConsentsView(
        processing=_consent_item(
            given.get(ConsentKind.PROCESSING), identity.current_consent(ConsentKind.PROCESSING).version
        ),
        publication=_consent_item(
            given.get(ConsentKind.PUBLICATION), identity.current_consent(ConsentKind.PUBLICATION).version
        ),
        # Текст `fsp_data` принадлежит модулю `fsp`: действующую версию профиль не знает, показывает выданную.
        fsp_data=_consent_item(fsp, None) if fsp is not None else None,
        visibility=_visibility_view(service.visibility(db, user.id, now)),
    )


@router.post(
    "/candidate/consents/publication", response_model=VisibilityView, responses=error_responses(401, 403, 409, 422)
)
def post_publication(body: PublicationConsentRequest, user: Candidate, db: Db, now: Now) -> VisibilityView:
    state = service.set_publication(db, user.id, granted=body.action == "grant", version=body.version, now=now)
    return _visibility_view(state)


@router.post("/candidate/visibility", response_model=VisibilityView, responses=error_responses(401, 403, 409, 422))
def post_visibility(body: VisibilityRequest, user: Candidate, db: Db, now: Now) -> VisibilityView:
    return _visibility_view(visibility_rules.set_manual_pause(db, user.id, paused=body.state == "paused", now=now))


# --- журнал доступа и контакты ---------------------------------------------------------------------------------------


@router.get("/candidate/access-log", response_model=Page[AccessLogItem], responses=error_responses(401, 403, 422))
def get_access_log(user: Candidate, db: Db, paging: Paging) -> Page[AccessLogItem]:
    return disclosure.access_log_page(db, user.id, paging)


@router.get(
    "/employer/candidates/{candidate_id}/contacts",
    response_model=CandidateContactsView,
    responses=error_responses(401, 403, 404),
)
def get_contacts(candidate_id: UUID, user: Employer, db: Db, now: Now) -> CandidateContactsView:
    """Каналы связи раскрытой пары — только те, что выбрал кандидат; запись `contacts_viewed` — раз в сутки на пару."""
    if db.get(CandidateProfile, candidate_id) is None or candidate_id in service.hidden_from_employer(
        db, user.id, [candidate_id]
    ):
        raise not_found()
    contacts = service.contacts_for_pair(db, user.id, candidate_id)
    if contacts is None:
        raise ApiException(403, "not_disclosed", "Контакты откроются, когда кандидат примет приглашение")
    if not contacts.masked:
        service.log_access(db, candidate_id, user.id, AccessKind.CONTACTS_VIEWED, None, now)
    assert contacts.disclosed_at is not None
    return CandidateContactsView(
        candidate_id=contacts.candidate_id,
        public_code=contacts.public_code,
        first_name=contacts.first_name,
        last_name=contacts.last_name,
        middle_name=contacts.middle_name,
        email=contacts.email,
        phone=contacts.phone,
        telegram=contacts.telegram,
        link=contacts.link,
        custom_skills=contacts.custom_skills,
        disclosed_fields=contacts.disclosed_fields,
        disclosed_at=contacts.disclosed_at,
        masked=contacts.masked,
    )
