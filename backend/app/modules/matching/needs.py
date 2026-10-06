"""Потребность работодателя: создание, правка, архив, чтение, канонический запрос подборки (Арх. 6.11, 6.14)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ApiException, field_error, not_found
from app.modules.catalog import service as catalog
from app.modules.company import service as company
from app.modules.matching import constants as C
from app.modules.matching import support
from app.modules.matching.dto import NeedData, NeedRefDTO, ShortlistQuery, ShortlistRefinement
from app.modules.matching.models import Need, ShortlistItem, ShortlistSnapshot
from app.modules.matching.schemas import LatestSnapshotBrief, NeedView
from app.modules.textparse import service as textparse
from app.modules.textparse.dto import NeedDraft
from app.shared import salary
from app.shared.enums import NeedStatus, WorkFormat

_NEEDS_CITY = {WorkFormat.OFFICE, WorkFormat.HYBRID}


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _check_skills(must: list[str], nice: list[str]) -> None:
    """Навыки — только из справочника; пределы 8 и 12; списки не пересекаются (Арх. 6.14)."""
    fields = []
    for name, codes, limit in (("must_skills", must, C.MUST_SKILLS_MAX), ("nice_skills", nice, C.NICE_SKILLS_MAX)):
        if len(codes) > limit:
            fields.append(field_error(name, "too_many", f"Не больше {limit} навыков"))
    if fields:
        raise ApiException(422, "validation_error", fields=fields)
    unknown = [
        field_error(name, "skill_unknown", f"Навыка «{code}» нет в справочнике")
        for name, codes in (("must_skills", must), ("nice_skills", nice))
        for code in codes
        if not catalog.is_skill(code)
    ]
    if unknown:
        raise ApiException(422, "skill_unknown", support.MESSAGES["skill_unknown"], fields=unknown)
    if set(must) & set(nice):
        raise ApiException(
            422,
            "validation_error",
            fields=[field_error("nice_skills", "skills_overlap", "Навык уже есть в обязательных")],
        )


def normalize(data: NeedData) -> NeedData:
    """Проверить поля потребности и вернуть их в сохранённом виде. Одни правила для роутера и сида."""
    title = data.title.strip()
    team = data.team_description.strip()
    fields = []
    if not C.NEED_TITLE_MIN <= len(title) <= C.NEED_TITLE_MAX:
        fields.append(field_error("title", "length", f"Название: от {C.NEED_TITLE_MIN} до {C.NEED_TITLE_MAX} знаков"))
    if not C.TEAM_DESCRIPTION_MIN <= len(team) <= C.TEAM_DESCRIPTION_MAX:
        fields.append(
            field_error(
                "team_description",
                "length",
                f"Описание команды: от {C.TEAM_DESCRIPTION_MIN} до {C.TEAM_DESCRIPTION_MAX} знаков",
            )
        )
    if data.source_text is not None and len(data.source_text) > C.NEED_TEXT_MAX:
        fields.append(field_error("source_text", "length", f"Текст: не больше {C.NEED_TEXT_MAX} знаков"))
    formats = [item for item in WorkFormat if item in set(data.work_formats)]
    if not formats:
        fields.append(field_error("work_formats", "required", "Выберите хотя бы один формат работы"))
    city = (data.city or "").strip() or None
    if city is None and _NEEDS_CITY & set(formats):
        fields.append(field_error("city", "city_required", "Для офиса и гибрида укажите город"))
    if fields:
        raise ApiException(422, "validation_error", fields=fields)
    if not catalog.is_available(data.specialization_code, data.grade_code):
        raise support.api_error(422, "specialization_unavailable", field="specialization_code")
    must, nice = _unique(data.must_skills), _unique(data.nice_skills)
    _check_skills(must, nice)
    salary.validate_range(data.salary_from, data.salary_to)
    return data.model_copy(
        update={
            "title": title,
            "team_description": team,
            "must_skills": must,
            "nice_skills": nice,
            "work_formats": formats,
            "city": city,
        }
    )


def get_owned(db: Session, employer_id: UUID, need_id: UUID, *, lock: bool = False) -> Need:
    """Потребность работодателя; чужая или несуществующая — 404 (стороны эти случаи не различают)."""
    statement = select(Need).where(Need.id == need_id, Need.employer_id == employer_id)
    need = db.scalar(statement.with_for_update() if lock else statement)
    if need is None:
        raise not_found()
    return need


def create(db: Session, employer_id: UUID, data: NeedData, now: datetime, *, is_demo: bool = False) -> Need:
    if not company.is_complete(db, employer_id):
        raise support.api_error(409, "company_profile_incomplete")
    data = normalize(data)
    need = Need(
        id=uuid4(),
        employer_id=employer_id,
        title=data.title,
        source_text=data.source_text,
        team_description=data.team_description,
        specialization_code=data.specialization_code,
        grade_code=data.grade_code,
        must_skills=data.must_skills,
        nice_skills=data.nice_skills,
        work_formats=[str(item.value) for item in data.work_formats],
        city=data.city,
        salary_from=data.salary_from,
        salary_to=data.salary_to,
        status=NeedStatus.ACTIVE.value,
        parse_meta=data.parse_meta,
        latest_snapshot_id=None,
        is_demo=is_demo,
        created_at=now,
        updated_at=now,
    )
    db.add(need)
    db.flush()
    return need


def update(db: Session, employer_id: UUID, need_id: UUID, data: NeedData, now: datetime) -> Need:
    """Правка потребности; версии подборки она не меняет (Арх. 6.14)."""
    need = get_owned(db, employer_id, need_id, lock=True)
    if need.status == NeedStatus.ARCHIVED:
        raise support.api_error(409, "need_archived")
    data = normalize(data)
    need.title = data.title
    need.source_text = data.source_text
    need.team_description = data.team_description
    need.specialization_code = data.specialization_code
    need.grade_code = data.grade_code
    need.must_skills = data.must_skills
    need.nice_skills = data.nice_skills
    need.work_formats = [str(item.value) for item in data.work_formats]
    need.city = data.city
    need.salary_from = data.salary_from
    need.salary_to = data.salary_to
    if data.parse_meta is not None:
        need.parse_meta = data.parse_meta
    need.updated_at = now
    db.flush()
    return need


def archive(db: Session, employer_id: UUID, need_id: UUID, now: datetime) -> Need:
    need = get_owned(db, employer_id, need_id, lock=True)
    if need.status != NeedStatus.ARCHIVED:
        need.status = NeedStatus.ARCHIVED.value
        need.updated_at = now
        db.flush()
    return need


def views(db: Session, needs: list[Need]) -> list[NeedView]:
    latest_ids = [need.latest_snapshot_id for need in needs if need.latest_snapshot_id]
    briefs: dict[UUID, LatestSnapshotBrief] = {}
    if latest_ids:
        rows = db.execute(
            select(
                ShortlistSnapshot.id,
                ShortlistSnapshot.version_no,
                ShortlistSnapshot.created_at,
                func.count(ShortlistItem.candidate_id),
            )
            .outerjoin(ShortlistItem, ShortlistItem.snapshot_id == ShortlistSnapshot.id)
            .where(ShortlistSnapshot.id.in_(latest_ids))
            .group_by(ShortlistSnapshot.id)
        ).all()
        briefs = {
            row[0]: LatestSnapshotBrief(id=row[0], version_no=row[1], created_at=row[2], items_count=row[3])
            for row in rows
        }
    return [
        NeedView(
            id=need.id,
            title=need.title,
            status=NeedStatus(need.status),
            target=support.category_ref(need.specialization_code, need.grade_code),
            must_skills=support.skill_refs(list(need.must_skills)),
            nice_skills=support.skill_refs(list(need.nice_skills)),
            work_formats=[WorkFormat(item) for item in need.work_formats],
            city=need.city,
            salary_from=need.salary_from,
            salary_to=need.salary_to,
            team_description=need.team_description,
            source_text=need.source_text,
            latest_snapshot=briefs.get(need.latest_snapshot_id) if need.latest_snapshot_id else None,
            created_at=need.created_at,
            updated_at=need.updated_at,
        )
        for need in needs
    ]


def list_views(db: Session, employer_id: UUID) -> list[NeedView]:
    """Потребности работодателя: действующие раньше архивных, внутри — новые раньше."""
    rows = list(
        db.scalars(select(Need).where(Need.employer_id == employer_id).order_by(Need.status, Need.created_at.desc()))
    )
    return views(db, rows)


def parse_text(db: Session, text: str) -> NeedDraft:
    """Разобрать текст вакансии в черновик (Арх. 6.14). В таблицы подбора ничего не пишет."""
    text = text.strip()
    if len(text) < C.NEED_TEXT_MIN:
        raise support.api_error(422, "text_too_short", params={"min": C.NEED_TEXT_MIN}, field="text")
    if len(text) > C.NEED_TEXT_MAX:
        raise support.api_error(422, "text_too_long", params={"max": C.NEED_TEXT_MAX}, field="text")
    draft = textparse.parse_need_text(text)
    if draft.unknown_terms:
        catalog.log_miss(db, draft.unknown_terms, "need")
    return draft


def to_ref(need: Need, snapshot_id: UUID | None = None) -> NeedRefDTO:
    return NeedRefDTO(
        need_id=need.id,
        employer_id=need.employer_id,
        title=need.title,
        category_code=support.category_code(need.specialization_code, need.grade_code),
        work_formats=[WorkFormat(item) for item in need.work_formats],
        city=need.city,
        salary_from=need.salary_from,
        salary_to=need.salary_to,
        team_description=need.team_description,
        snapshot_id=snapshot_id,
    )


# --------------------------------------------------------------------------------------------------------------------
# Запрос подборки
# --------------------------------------------------------------------------------------------------------------------


def canonical(query: ShortlistQuery) -> ShortlistQuery:
    """Канонический вид (Арх. 6.11): списки без дублей и отсортированы; навык из обоих списков остаётся в
    обязательных; пустой `grade_codes` означает автоматический набор разделов.
    """
    must = sorted(set(query.must_skills))
    return query.model_copy(
        update={
            "must_skills": must,
            "nice_skills": sorted(set(query.nice_skills) - set(must)),
            "work_formats": sorted(set(query.work_formats), key=lambda item: item.value),
            "grade_codes": sorted(set(query.grade_codes)) if query.grade_codes else None,
        }
    )


def query_hash(query: ShortlistQuery) -> str:
    """`sha256` канонического JSON запроса."""
    raw = json.dumps(canonical(query).model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def query_from_need(need: Need) -> ShortlistQuery:
    return canonical(
        ShortlistQuery(
            specialization_code=need.specialization_code,
            grade_code=need.grade_code,
            must_skills=list(need.must_skills),
            nice_skills=list(need.nice_skills),
            work_formats=[WorkFormat(item) for item in need.work_formats],
            salary_from=need.salary_from,
            salary_to=need.salary_to,
        )
    )


def refine(parent: ShortlistQuery, refinement: ShortlistRefinement, need: Need) -> ShortlistQuery:
    """Запрос родителя с наложенными полями уточнения; специализация и целевой грейд — всегда из потребности."""
    changes = refinement.model_dump(exclude_none=True, exclude={"specialization_code", "grade_code"})
    merged = parent.model_dump()
    merged.update(changes)
    merged["specialization_code"] = need.specialization_code
    merged["grade_code"] = need.grade_code
    query = ShortlistQuery.model_validate(merged)
    if refinement.must_skills is not None and refinement.nice_skills is None:
        # Навык, перенесённый в обязательные, из желательных родителя уходит (а не наоборот).
        query.nice_skills = [code for code in query.nice_skills if code not in set(query.must_skills)]
    return canonical(query)


def validate_query(query: ShortlistQuery) -> None:
    """Проверки запроса подборки — 422 с `fields[]` (Арх. 6.11, шаг 3)."""
    _check_skills(list(query.must_skills), list(query.nice_skills))
    fields = []
    if not query.work_formats:
        fields.append(field_error("work_formats", "required", "Выберите хотя бы один формат работы"))
    known = set(support.grade_codes())
    if query.grade_codes and not set(query.grade_codes) <= known:
        fields.append(field_error("grade_codes", "grade_unknown", "Такого грейда нет в справочнике"))
    if fields:
        raise ApiException(422, "validation_error", fields=fields)
    if query.salary_from is not None and query.salary_to is not None:
        salary.validate_range(query.salary_from, query.salary_to)
