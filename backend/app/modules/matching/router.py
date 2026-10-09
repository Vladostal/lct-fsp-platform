"""Эндпоинты модуля `matching` (Арх. 9.8). Каждый работает только с данными текущего пользователя."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.core.db import TxRoute
from app.core.deps import Candidate, Db, Employer, Now
from app.core.errors import error_responses
from app.modules.matching import bank, cards, needs, snapshots
from app.modules.matching import constants as C
from app.modules.matching.dto import NeedData
from app.modules.matching.schemas import (
    BankPage,
    CandidateCardEmployerView,
    CandidateEvidenceView,
    NeedCreate,
    NeedParseRequest,
    NeedUpdate,
    NeedView,
    ShortlistCreate,
    ShortlistSnapshotView,
    ShortlistVersionBrief,
    SnapshotDiffView,
)
from app.modules.textparse.dto import NeedDraft

router = APIRouter(route_class=TxRoute, tags=["matching"])

_PDF_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"content": {"application/pdf": {}}, "description": "PDF-профиль"}
}


def _pdf(content: bytes, file_name: str) -> Response:
    # Код кандидата содержит кириллическую «К»: заголовки HTTP — latin-1, поэтому имя передаётся по RFC 5987,
    # а в `filename` — запасной вариант из ASCII.
    fallback = file_name.encode("ascii", "ignore").decode("ascii").replace('"', "") or "profile.pdf"
    disposition = f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(file_name)}"
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": disposition, "Cache-Control": "no-store"},
    )


# --- потребности ----------------------------------------------------------------------------------------------------


@router.post("/employer/needs/parse", response_model=NeedDraft, responses=error_responses(401, 403, 422))
def parse_need(body: NeedParseRequest, user: Employer, db: Db) -> NeedDraft:
    """Разобрать текст вакансии в черновик потребности; в базу потребностей ничего не пишет."""
    return needs.parse_text(db, body.text)


@router.get("/employer/needs", response_model=list[NeedView], responses=error_responses(401, 403))
def list_needs(user: Employer, db: Db) -> list[NeedView]:
    """Потребности работодателя: активные и архивные."""
    return needs.list_views(db, user.id)


@router.post("/employer/needs", response_model=NeedView, status_code=201, responses=error_responses(401, 403, 409, 422))
def create_need(body: NeedCreate, user: Employer, db: Db, now: Now) -> NeedView:
    """Создать потребность: специализация, грейд, навыки, форматы и обязательная вилка в рублях."""
    need = needs.create(db, user.id, NeedData.model_validate(body.model_dump()), now)
    return needs.views(db, [need])[0]


@router.get("/employer/needs/{need_id}", response_model=NeedView, responses=error_responses(401, 403, 404))
def get_need(need_id: UUID, user: Employer, db: Db) -> NeedView:
    """Потребность по идентификатору."""
    return needs.views(db, [needs.get_owned(db, user.id, need_id)])[0]


@router.put("/employer/needs/{need_id}", response_model=NeedView, responses=error_responses(401, 403, 404, 409, 422))
def update_need(need_id: UUID, body: NeedUpdate, user: Employer, db: Db, now: Now) -> NeedView:
    """Изменить потребность; прежние версии подборки сохраняются."""
    need = needs.update(db, user.id, need_id, NeedData.model_validate(body.model_dump()), now)
    return needs.views(db, [need])[0]


@router.post("/employer/needs/{need_id}/archive", response_model=NeedView, responses=error_responses(401, 403, 404))
def archive_need(need_id: UUID, user: Employer, db: Db, now: Now) -> NeedView:
    """Перенести потребность в архив."""
    return needs.views(db, [needs.archive(db, user.id, need_id, now)])[0]


# --- версии подборки ------------------------------------------------------------------------------------------------


@router.get(
    "/employer/needs/{need_id}/shortlists",
    response_model=list[ShortlistVersionBrief],
    responses=error_responses(401, 403, 404),
)
def list_shortlists(need_id: UUID, user: Employer, db: Db) -> list[ShortlistVersionBrief]:
    """Версии подборки потребности — для переключателя версий."""
    return snapshots.versions(db, user.id, need_id)


@router.post(
    "/employer/needs/{need_id}/shortlists",
    response_model=ShortlistSnapshotView,
    status_code=201,
    responses={
        200: {"model": ShortlistSnapshotView, "description": "Повтор запроса: возвращена последняя версия"},
        **error_responses(401, 403, 404, 409, 422, 429),
    },
)
def create_shortlist(
    need_id: UUID, user: Employer, db: Db, now: Now, response: Response, body: ShortlistCreate | None = None
) -> ShortlistSnapshotView:
    """Создать версию подборки; повтор того же запроса в пределах 10 минут возвращает прежнюю с кодом 200."""
    body = body or ShortlistCreate()
    snapshot, created = snapshots.create(
        db, user.id, need_id, now, parent_id=body.parent_id, refinement=body.refinement
    )
    if not created:
        response.status_code = 200
    return snapshots.view(db, user.id, snapshot.id, now)


@router.get(
    "/employer/shortlists/{snapshot_id}",
    response_model=ShortlistSnapshotView,
    responses=error_responses(401, 403, 404),
)
def get_shortlist(snapshot_id: UUID, user: Employer, db: Db, now: Now) -> ShortlistSnapshotView:
    """Версия подборки: строки с объяснением, воронка и подсказки; прежние версии доступны всегда."""
    return snapshots.view(db, user.id, snapshot_id, now)


@router.get(
    "/employer/shortlists/{snapshot_id}/diff",
    response_model=SnapshotDiffView,
    responses=error_responses(401, 403, 404, 409),
)
def diff_shortlists(
    snapshot_id: UUID, base: Annotated[UUID, Query()], user: Employer, db: Db, now: Now
) -> SnapshotDiffView:
    """Различия двух версий подборки одной потребности."""
    return snapshots.diff_view(db, user.id, snapshot_id, base, now)


@router.put(
    "/employer/needs/{need_id}/pins/{candidate_id}",
    status_code=204,
    response_class=Response,
    responses=error_responses(401, 403, 404, 409),
)
def pin_candidate(need_id: UUID, candidate_id: UUID, user: Employer, db: Db, now: Now) -> Response:
    """Закрепить кандидата за потребностью; закрепление переживает уточнения запроса."""
    snapshots.pin(db, user.id, need_id, candidate_id, now)
    return Response(status_code=204)


@router.delete(
    "/employer/needs/{need_id}/pins/{candidate_id}",
    status_code=204,
    response_class=Response,
    responses=error_responses(401, 403, 404),
)
def unpin_candidate(need_id: UUID, candidate_id: UUID, user: Employer, db: Db) -> Response:
    """Снять закрепление кандидата."""
    snapshots.unpin(db, user.id, need_id, candidate_id)
    return Response(status_code=204)


# --- банк и карточка ------------------------------------------------------------------------------------------------


@router.get("/employer/candidates", response_model=BankPage, responses=error_responses(401, 403, 422, 429))
def list_candidates(
    user: Employer,
    db: Db,
    now: Now,
    category: Annotated[str | None, Query(max_length=130)] = None,
    specialization: Annotated[str | None, Query(max_length=64)] = None,
    grade: Annotated[str | None, Query(max_length=200, description="Коды грейдов через запятую")] = None,
    skills: Annotated[str | None, Query(max_length=600, description="Коды навыков через запятую, не больше 8")] = None,
    skills_confirmed_only: bool = False,
    has_fsp: bool = False,
    code: Annotated[str | None, Query(max_length=16, description="Точный код кандидата «К-12345»")] = None,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
    limit: Annotated[int, Query(ge=1, le=C.BANK_PAGE_MAX)] = 20,
) -> BankPage:
    """Банк кандидатов: все видимые кандидаты; потребность не нужна, версия не создаётся."""
    filters = bank.parse_filters(
        category=category,
        specialization=specialization,
        grade=grade,
        skills=skills,
        skills_confirmed_only=skills_confirmed_only,
        has_fsp=has_fsp,
        code=code,
    )
    return bank.page(db, user.id, filters, bank.parse_cursor(cursor), limit, now)


@router.get(
    "/employer/candidates/{candidate_id}",
    response_model=CandidateCardEmployerView,
    responses=error_responses(401, 403, 404, 429),
)
def get_candidate_card(
    candidate_id: UUID,
    user: Employer,
    db: Db,
    now: Now,
    need_id: UUID | None = None,
    snapshot_id: UUID | None = None,
) -> CandidateCardEmployerView:
    """Карточка кандидата; скрытый кандидат нераскрытой пары — 404."""
    return cards.employer_card(db, user.id, candidate_id, now, need_id=need_id, snapshot_id=snapshot_id)


@router.get(
    "/employer/candidates/{candidate_id}/pdf",
    response_class=Response,
    responses={**_PDF_RESPONSES, **error_responses(401, 403, 429)},
)
def get_candidate_pdf(candidate_id: UUID, user: Employer, db: Db, now: Now) -> Response:
    """PDF-профиль раскрытой пары; пишет `pdf_downloaded` в журнал доступа кандидата."""
    return _pdf(*cards.employer_pdf(db, user.id, candidate_id, now))


# --- кабинет кандидата ----------------------------------------------------------------------------------------------


@router.get(
    "/candidate/profile/preview",
    response_model=CandidateCardEmployerView,
    responses=error_responses(401, 403, 409),
)
def preview_profile(
    user: Candidate, db: Db, now: Now, state: Literal["before", "after"] = "before"
) -> CandidateCardEmployerView:
    """Карточка глазами работодателя: до и после раскрытия контактов."""
    return cards.preview(db, user.id, state, now)


@router.get("/candidate/evidence", response_model=CandidateEvidenceView, responses=error_responses(401, 403))
def get_own_evidence(user: Candidate, db: Db, now: Now) -> CandidateEvidenceView:
    """Подтверждённые и заявленные навыки кандидата с источником каждого."""
    return cards.own_evidence(db, user.id, now)


@router.get(
    "/candidate/profile/pdf",
    response_class=Response,
    responses={**_PDF_RESPONSES, **error_responses(401, 403, 409, 429)},
)
def get_own_pdf(user: Candidate, db: Db, now: Now) -> Response:
    """Стандартизированный PDF-профиль кандидата."""
    return _pdf(*cards.own_pdf(db, user.id, now))
