"""Фасад модуля `assessment` (Арх. 2.5): всё, что видят другие модули, сид и фоновый цикл.

Сигнатуры нормативны. Внутреннее устройство: чистое ядро — `engine/`; сессии — `sessions.py`; экраны кандидата —
`candidate.py`; план из вакансии — `preview.py`; поддержка коротких заданий — `pulse_support.py`; сид — `seeding.py`.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.assessment import candidate as _candidate
from app.modules.assessment import labels as _labels
from app.modules.assessment import preview as _preview
from app.modules.assessment import pulse_support as _pulse
from app.modules.assessment import seeding as _seeding
from app.modules.assessment import sessions as _sessions
from app.modules.assessment.config import get_config
from app.modules.assessment.dto import (
    BlueprintPreview,
    CategoryDTO,
    GradeResult,
    LevelDTO,
    LevelView,
    PulseItem,
    SeedResult,
    SurveyDeclared,
    TestSkillEvidence,
)
from app.modules.assessment.engine import level as _level
from app.modules.assessment.engine.skills import GroupVerdict, skill_proofs
from app.modules.assessment.groups import SKILL_GROUP_MAP
from app.modules.assessment.models import AssessmentProfile, CategoryRow, SkillEvidenceRow, SurveyResponse
from app.modules.catalog import service as _catalog
from app.shared.enums import EvidenceSource, SkillVerdict, TestOutcome

_DIRECT: dict[str, tuple[str, ...]] = {group: skills.direct for group, skills in SKILL_GROUP_MAP.items()}


def _category_dto(row: CategoryRow) -> CategoryDTO:
    return CategoryDTO(
        specialization_code=row.specialization_code,
        grade_code=row.grade_code,
        category_code=f"{row.specialization_code}:{row.grade_code}",
        verdict=TestOutcome(row.verdict),
        assigned_at=row.assigned_at,
        level_session_id=row.level_session_id,
        change_available_at=row.change_available_at,
        is_demo_result=row.is_demo_result,
    )


def get_category(db: Session, candidate_id: UUID) -> CategoryDTO | None:
    """Действующая категория кандидата; `None` — грейд ещё не подтверждён."""
    row = db.get(CategoryRow, candidate_id)
    return _category_dto(row) if row else None


def get_categories(db: Session, candidate_ids: Collection[UUID]) -> dict[UUID, CategoryDTO]:
    """Категории пачкой; кандидатов без категории в словаре нет."""
    if not candidate_ids:
        return {}
    rows = db.scalars(select(CategoryRow).where(CategoryRow.candidate_id.in_(list(candidate_ids))))
    return {row.candidate_id: _category_dto(row) for row in rows}


def get_levels(
    db: Session,
    *,
    specialization_code: str | None = None,
    grade_codes: Collection[str] | None = None,
    candidate_ids: Collection[UUID] | None = None,
    now: datetime,
) -> list[LevelDTO]:
    """Уровни кандидатов с категорией для подбора (Арх. 5.6): `se_eff` считает только этот модуль."""
    stmt = select(CategoryRow)
    if specialization_code is not None:
        stmt = stmt.where(CategoryRow.specialization_code == specialization_code)
    if grade_codes is not None:
        stmt = stmt.where(CategoryRow.grade_code.in_(list(grade_codes)))
    if candidate_ids is not None:
        if not candidate_ids:
            return []
        stmt = stmt.where(CategoryRow.candidate_id.in_(list(candidate_ids)))
    result = []
    for row in db.scalars(stmt.order_by(CategoryRow.candidate_id)):
        numbers = _level.level_numbers(row.theta, row.se, row.grade_code, row.last_evidence_at, now)
        result.append(
            LevelDTO(
                candidate_id=row.candidate_id,
                specialization_code=row.specialization_code,
                grade_code=row.grade_code,
                verdict=TestOutcome(row.verdict),
                theta=row.theta,
                se=row.se,
                se_eff=numbers.se_eff,
                cut=numbers.cut,
                cut_next=numbers.cut_next,
                width=numbers.width,
                tested_at=row.level_updated_at,
                last_evidence_at=row.last_evidence_at,
                age_days=numbers.age_days,
                stale=numbers.stale,
            )
        )
    return result


def level_views(db: Session, candidate_ids: Collection[UUID], now: datetime) -> dict[UUID, LevelView]:
    """Уровень на шкале экрана для карточек; единиц θ в нём нет."""
    if not candidate_ids:
        return {}
    rows = db.scalars(select(CategoryRow).where(CategoryRow.candidate_id.in_(list(candidate_ids))))
    return {row.candidate_id: _candidate.category_level_view(row, now) for row in rows}


def _detail(skill: str, group: str, row: SkillEvidenceRow, pulse: bool) -> str:
    title = _catalog.skill_ref(skill).title if _catalog.is_skill(skill) else skill
    grade = _labels.grade_ref(row.level_grade).title
    if pulse:
        return f"{title}: решено короткое задание уровня {grade}"
    return f"{title}: решено задание уровня {grade}; {_labels.group_title(group)} — {row.correct} из {row.items}"


def skill_evidence(db: Session, candidate_ids: Collection[UUID]) -> dict[UUID, list[TestSkillEvidence]]:
    """Навыки, подтверждённые тестом или коротким заданием, по правилу Арх. 5.6.

    Навык получает доказательство, только если верно решено задание с его тегом и навык входит в `direct` группы.
    `full = True` — группа подтверждена (вес 1.0); `False` — решено одно задание (вес 0.7). Группа с вердиктом
    `not_confirmed` доказательства не даёт. Считаются строки специализации действующей категории.
    """
    result: dict[UUID, list[TestSkillEvidence]] = {candidate_id: [] for candidate_id in candidate_ids}
    if not candidate_ids:
        return result
    ids = list(candidate_ids)
    spec = {
        row.candidate_id: row.specialization_code
        for row in db.scalars(select(CategoryRow).where(CategoryRow.candidate_id.in_(ids)))
    }
    rows = db.scalars(
        select(SkillEvidenceRow)
        .where(SkillEvidenceRow.candidate_id.in_(ids))
        .order_by(SkillEvidenceRow.candidate_id, SkillEvidenceRow.group_code, SkillEvidenceRow.source)
    )
    for row in rows:
        if spec.get(row.candidate_id) != row.specialization_code:
            continue
        pulse = row.source == EvidenceSource.PULSE.value
        verdict = GroupVerdict(
            group=row.group_code,
            items=row.items,
            correct=row.correct,
            # Короткое задание — всегда одно решённое задание: вес 0.7, сколько бы их ни накопилось.
            verdict=SkillVerdict.PARTIAL if pulse else SkillVerdict(row.verdict),
            tags_correct=tuple(row.tags_correct),
        )
        for proof in skill_proofs([verdict], _DIRECT):
            result[row.candidate_id].append(
                TestSkillEvidence(
                    skill_code=proof.skill,
                    source=EvidenceSource(row.source),
                    full=proof.full,
                    group_code=proof.group,
                    ref_id=row.ref_id,
                    detail=_detail(proof.skill, proof.group, row, pulse),
                    confirmed_at=row.last_at,
                )
            )
    return result


def survey_declared(db: Session, candidate_ids: Collection[UUID]) -> dict[UUID, SurveyDeclared]:
    """Заявленное в опросе: направление, язык, опыт, отрасли (блок «заявлено», на тест не влияет)."""
    if not candidate_ids:
        return {}
    rows = db.execute(
        select(AssessmentProfile.candidate_id, SurveyResponse.answers)
        .join(SurveyResponse, SurveyResponse.id == AssessmentProfile.survey_response_id)
        .where(AssessmentProfile.candidate_id.in_(list(candidate_ids)))
    )
    return {
        candidate_id: SurveyDeclared(
            direction=answers.get("direction"),
            main_language=answers.get("main_language"),
            experience_band=answers.get("experience_band"),
            industry_domains=list(answers.get("industry_domains") or []),
        )
        for candidate_id, answers in rows
    }


def blueprint_for(
    db: Session, specialization_code: str, grade_code: str, must_skills: Collection[str], nice_skills: Collection[str]
) -> BlueprintPreview:
    """План теста под описание вакансии (Арх. 5.4); `sample_items` читаются из банка, поэтому нужен `db`."""
    return _preview.blueprint_for(db, specialization_code, grade_code, must_skills, nice_skills)


def group_for_skill(skill_code: str, specialization_code: str, grade_code: str) -> str | None:
    """Группа плана теста, которая проверяет навык; `None` — навык тестом не проверяется."""
    return _pulse.group_for_skill(skill_code, specialization_code, grade_code)


def pick_pulse_item(db: Session, candidate_id: UUID, group_code: str, now: datetime) -> PulseItem:
    """Вариант короткого задания по группе (Арх. 5.9)."""
    return _pulse.pick_pulse_item(db, candidate_id, group_code, now)


def grade_pulse_answer(db: Session, variant_id: UUID, raw_answer: Any) -> GradeResult:
    """Проверить ответ на короткое задание."""
    return _pulse.grade_pulse_answer(db, variant_id, raw_answer)


def record_pulse_result(
    db: Session,
    candidate_id: UUID,
    group_code: str,
    correct: bool,
    assignment_id: UUID,
    now: datetime,
    *,
    family_id: str | None = None,
) -> None:
    """Учесть результат короткого задания (Арх. 5.9): свежесть и строка доказательства `pulse`.

    `family_id` (необязательное расширение сигнатуры Арх. 2.5) — семейство решённого задания из `PulseItem`:
    по его тегам навыки получают доказательство. При вердикте группы `not_confirmed` строка не создаётся.
    """
    _pulse.record_pulse_result(db, candidate_id, group_code, correct, assignment_id, now, family_id=family_id)


def close_expired_sessions(db: Session, now: datetime) -> int:
    """Фоновая задача (раз в 60 с): закрыть тесты, у которых вышло время. Возвращает число закрытых."""
    return _sessions.close_expired(db, now)


def seed_result(db: Session, result: SeedResult) -> None:
    """Записать готовый результат теста — только для сида."""
    _seeding.seed_result(db, result)


def seed_session_in_progress(db: Session, candidate_id: UUID, grade_code: str, answered: int, now: datetime) -> UUID:
    """Создать идущий тест с `answered` подставленными ответами — сид (`nina`) и быстрый демо-тест."""
    return _seeding.seed_session_in_progress(db, candidate_id, grade_code, answered, now)


__all__ = [
    "blueprint_for",
    "close_expired_sessions",
    "get_categories",
    "get_category",
    "get_config",
    "get_levels",
    "grade_pulse_answer",
    "group_for_skill",
    "level_views",
    "pick_pulse_item",
    "record_pulse_result",
    "seed_result",
    "seed_session_in_progress",
    "skill_evidence",
    "survey_declared",
]
