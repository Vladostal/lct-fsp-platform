"""Что модуль `assessment` даёт коротким заданиям (Арх. 5.9): группа по навыку, вариант, проверка, учёт результата.

Сами короткие задания (таблицы, эндпоинты `/pulse/*`) — отложенный модуль `pulse`, в приложении его пока нет.
Грейд, категория, `theta` и `se` короткими заданиями не меняются никогда.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import ApiException, not_found
from app.modules.assessment import blueprints, grading, repo
from app.modules.assessment.config import GRADES, get_config
from app.modules.assessment.dto import GradeResult, PulseItem
from app.modules.assessment.engine.skills import pulse_gives_evidence
from app.modules.assessment.families.registry import REGISTRY
from app.modules.assessment.groups import GROUPS, SKILL_GROUP_MAP
from app.modules.assessment.models import SkillEvidenceRow, VariantRow
from app.modules.assessment.sessions import item_view
from app.shared.enums import EvidenceSource, ItemKind, SkillVerdict, VariantStatus

#: Для коротких заданий — только ввод ответа: единственное задание с выбором угадывается слишком легко.
INPUT_KINDS: frozenset[str] = frozenset({ItemKind.NUMERIC_INPUT.value, ItemKind.TEXT_INPUT.value})


def _group_open(group: str, specialization: str) -> bool:
    rule = blueprints.LANG_RULES.get(specialization)
    if rule is None or group not in GROUPS:
        return False
    if GROUPS[group].is_lang:
        return group == rule.required or group in rule.by_language.values()
    return specialization in GROUPS[group].specializations


def group_for_skill(skill_code: str, specialization_code: str, grade_code: str) -> str | None:
    """Группа, заданием которой можно проверить навык; `None` — навык тестом не проверяется.

    Навык должен входить в `direct` группы, группа — принадлежать специализации, и в реестре должно быть семейство
    этой группы с тегом навыка, вводом ответа и уровнем в основном диапазоне грейда.
    """
    if grade_code not in GRADES:
        return None
    main = blueprints.MAIN_RANGE[grade_code]
    for group, skills in SKILL_GROUP_MAP.items():
        if skill_code not in skills.direct or not _group_open(group, specialization_code):
            continue
        for spec in REGISTRY.values():
            if (
                spec.group == group
                and skill_code in spec.skill_tags
                and spec.kind.value in INPUT_KINDS
                and any(main[0] <= b <= main[1] for b in spec.bs)
            ):
                return group
    return None


def pick_pulse_item(db: Session, candidate_id: UUID, group_code: str, now: datetime) -> PulseItem:
    """Вариант короткого задания: семейство группы с вводом ответа и уровнем грейда кандидата, вариант, которого
    он не видел, с наименьшим `served_count`. Нет категории или подходящего варианта — 503 `bank_unavailable`.
    """
    category = repo.category(db, candidate_id)
    if category is None:
        raise ApiException(503, "bank_unavailable", "Короткое задание доступно после подтверждения грейда")
    low, high = blueprints.MAIN_RANGE[category.grade_code]
    seen = repo.seen_families(db, candidate_id, category.specialization_code, now)
    families = [f for f in repo.load_families(db) if f.group == group_code and f.kind in INPUT_KINDS]
    # Сначала семейства, которых кандидат не видел в тесте: задание должно давать новое подтверждение.
    for family in sorted(families, key=lambda f: (f.id in seen, f.id)):
        levels = [lv for lv in family.levels if low <= lv.b <= high]
        if not levels:
            continue
        variant = db.scalars(
            select(VariantRow)
            .where(
                VariantRow.family_id == family.id,
                VariantRow.level.in_([lv.level for lv in levels]),
                VariantRow.status == VariantStatus.ACTIVE.value,
                VariantRow.id.not_in(repo.seen_variants_subquery(candidate_id)),
            )
            .order_by(VariantRow.served_count, VariantRow.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).first()
        if variant is None:
            continue
        variant.served_count += 1
        level = next(lv for lv in levels if lv.level == variant.level)
        return PulseItem(
            variant_id=variant.id,
            group_code=group_code,
            family_id=family.id,
            level=level.level,
            b_used=level.b,
            skill_tags=list(family.skill_tags),
            time_budget_s=level.time_budget_s,
            item=item_view(str(variant.id), variant),
        )
    raise ApiException(503, "bank_unavailable", "Для этой группы нет подходящего задания")


def grade_pulse_answer(db: Session, variant_id: UUID, raw_answer: Any) -> GradeResult:
    """Проверить ответ на короткое задание той же функцией, что и в тесте (`grading.grade`)."""
    variant = db.get(VariantRow, variant_id)
    if variant is None:
        raise not_found()
    return grading.grade(
        variant.payload["kind"], variant.answer, raw_answer, misconceptions=variant.misconception_answers
    )


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
    """Учесть результат короткого задания (Арх. 5.9).

    Верный ответ сдвигает свежесть: `last_evidence_at = min(now, last_evidence_at + PULSE_CREDIT_DAYS,
    tested_at + PULSE_CREDIT_CAP_DAYS)` — не дальше 90 дней после последнего теста — и добавляет строку
    доказательства `source = pulse` по группе с тегами решённого семейства. Если вердикт группы по тесту —
    `not_confirmed`, строка не создаётся (свежесть засчитывается). Неверный ответ — без последствий.

    `family_id` — семейство решённого задания (`PulseItem.family_id`): без него теги неизвестны и навыки
    доказательства не получают.
    """
    if not correct:
        return
    category = repo.category(db, candidate_id)
    if category is None:
        return
    cfg = get_config()
    credited = min(
        now,
        category.last_evidence_at + timedelta(days=cfg.pulse_credit_days),
        category.level_updated_at + timedelta(days=cfg.pulse_credit_cap_days),
    )
    category.last_evidence_at = max(category.last_evidence_at, credited)

    key = (candidate_id, category.specialization_code, group_code)
    test_row = db.get(SkillEvidenceRow, (*key, EvidenceSource.TEST.value))
    if not pulse_gives_evidence(test_row.verdict if test_row else None):
        db.flush()
        return
    tags: list[str] = []
    if family_id is not None:
        family = next((f for f in repo.load_families(db, statuses=None) if f.id == family_id), None)
        if family is not None and family.group == group_code:
            tags = list(family.skill_tags)
    existing = db.get(SkillEvidenceRow, (*key, EvidenceSource.PULSE.value))
    merged = sorted({*(existing.tags_correct if existing else ()), *tags})
    db.execute(
        insert(SkillEvidenceRow)
        .values(
            candidate_id=candidate_id,
            specialization_code=category.specialization_code,
            group_code=group_code,
            source=EvidenceSource.PULSE.value,
            items=1,
            correct=1,
            verdict=SkillVerdict.PARTIAL.value,
            level_grade=category.grade_code,
            tags_correct=merged,
            ref_id=assignment_id,
            last_at=now,
        )
        .on_conflict_do_update(
            index_elements=["candidate_id", "specialization_code", "group_code", "source"],
            set_={
                "items": SkillEvidenceRow.items + 1,
                "correct": SkillEvidenceRow.correct + 1,
                "tags_correct": merged,
                "ref_id": assignment_id,
                "last_at": now,
                "level_grade": category.grade_code,
            },
        )
    )
    if existing is not None:
        db.expire(existing)
    db.flush()
