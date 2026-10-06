"""План теста из описания вакансии и методика для экрана «Как это работает» (Арх. 5.4, 9.5)."""

from __future__ import annotations

from collections.abc import Collection

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ApiException, field_error, validation_error
from app.modules.assessment import blueprints, labels, repo
from app.modules.assessment.config import GRADES, get_config
from app.modules.assessment.constants import PUBLIC_LIMITS
from app.modules.assessment.dto import (
    BlueprintCoverageItem,
    BlueprintNeedSlots,
    BlueprintPreview,
    BlueprintSlots,
    TestItemView,
)
from app.modules.assessment.groups import GROUP_ORDER, GROUPS, LANG_GROUPS, SPECIALIZATIONS
from app.modules.assessment.models import FamilyRow, VariantRow
from app.modules.assessment.schemas import (
    BlueprintPreviewRequest,
    MethodologyBank,
    MethodologyGroup,
    MethodologyView,
)
from app.modules.assessment.sessions import item_view
from app.modules.catalog import service as catalog
from app.modules.textparse import service as textparse
from app.shared.enums import TestOutcome, VariantStatus
from app.shared.schemas import Ref

#: Сколько примеров заданий отдаёт предпросмотр.
SAMPLE_ITEMS = 6
_ORDER = {group: index for index, group in enumerate(GROUP_ORDER)}


def preview_lang(specialization: str, skills: Collection[str]) -> str | None:
    """Языковой модуль предпросмотра: обязательный модуль специализации, иначе — по языку из требований."""
    rule = blueprints.LANG_RULES[specialization]
    if rule.required is not None:
        return rule.required
    wanted = {"python": "python", "nodejs": "nodejs", "javascript": "nodejs"}
    for skill, language in wanted.items():
        if skill in skills and language in rule.by_language:
            return rule.by_language[language]
    return None


def _sort_groups(groups: Collection[str]) -> list[str]:
    return sorted(groups, key=lambda g: (_ORDER.get("lang" if g in LANG_GROUPS else g, 99), g))


def _samples(db: Session, families: list[repo.BankFamily], plan: dict[str, int], grade: str) -> list[TestItemView]:
    """Примеры заданий — только варианты со статусом `demo`: в сессии они не попадают (Арх. 5.3)."""
    low, high = blueprints.MAIN_RANGE[grade]
    result: list[TestItemView] = []
    for group in _sort_groups([g for g, n in plan.items() if n > 0]):
        for family in families:
            levels = [lv.level for lv in family.levels if low <= lv.b <= high]
            if family.group != group or not levels:
                continue
            variant = db.scalars(
                select(VariantRow)
                .where(
                    VariantRow.family_id == family.id,
                    VariantRow.level.in_(levels),
                    VariantRow.status == VariantStatus.DEMO.value,
                )
                .order_by(VariantRow.level, VariantRow.seed)
                .limit(1)
            ).first()
            if variant is not None:
                result.append(item_view(str(variant.id), variant))
                break
        if len(result) >= SAMPLE_ITEMS:
            break
    return result


def blueprint_for(
    db: Session,
    specialization_code: str,
    grade_code: str,
    must_skills: Collection[str],
    nice_skills: Collection[str],
    *,
    grade_guessed: bool = False,
) -> BlueprintPreview:
    """Как описание вакансии превращается в задания (Арх. 5.4).

    `standard_slots` и `sample_items` — тест, который получит каждый кандидат категории; `coverage` — что из
    требований он проверяет; `need_slots` — индикативный план под это описание. `need_slots` считается всегда
    и от флагов не зависит.
    """
    if (
        specialization_code not in SPECIALIZATIONS
        or grade_code not in GRADES
        or not catalog.is_available(specialization_code, grade_code)
    ):
        raise ApiException(422, "specialization_unavailable", "Тест по этой специализации и грейду пока недоступен")
    families = repo.load_families(db)
    must = [s for s in dict.fromkeys(must_skills) if catalog.is_skill(s)]
    nice = [s for s in dict.fromkeys(nice_skills) if catalog.is_skill(s) and s not in must]
    lang = preview_lang(specialization_code, {*must, *nice})
    if lang is not None and not blueprints.lang_module_available(families, specialization_code, grade_code, lang):
        lang = None
    plan = blueprints.need_plan(families, specialization_code, grade_code, lang, must, nice)
    groups = _sort_groups({*plan.standard, *plan.need})
    return BlueprintPreview(
        target=labels.category_ref(specialization_code, grade_code),
        grade_guessed=grade_guessed,
        coverage=[
            BlueprintCoverageItem(
                skill=catalog.skill_ref(row.skill),
                priority=row.priority,
                group=labels.group_ref(row.group) if row.group else None,
                relation=row.relation,
                slots=row.slots,
            )
            for row in plan.coverage
        ],
        standard_slots=[
            BlueprintSlots(group=labels.group_ref(g), slots=plan.standard[g]) for g in groups if plan.standard.get(g)
        ],
        need_slots=[
            BlueprintNeedSlots(
                group=labels.group_ref(g),
                slots=plan.need.get(g, 0),
                delta=plan.need.get(g, 0) - plan.standard.get(g, 0),
            )
            for g in groups
        ],
        sample_items=_samples(db, families, plan.standard, grade_code),
    )


def preview_request(db: Session, payload: BlueprintPreviewRequest) -> BlueprintPreview:
    """`POST /assessment/blueprints/preview`: текст разбирает `textparse`; не найденный грейд → `middle`."""
    if payload.text is None:
        if not payload.specialization_code or not payload.grade_code:
            raise validation_error(field_error("text", "required", "Вставьте текст вакансии или задайте категорию"))
        return blueprint_for(
            db, payload.specialization_code, payload.grade_code, payload.must_skills, payload.nice_skills
        )
    text = payload.text.strip()
    if len(text) < PUBLIC_LIMITS["blueprint_preview_text_min"]:
        raise ApiException(422, "text_too_short", "Текст слишком короткий: добавьте требования вакансии")
    if len(text) > PUBLIC_LIMITS["blueprint_preview_text_max"]:
        raise ApiException(422, "text_too_long", "Текст слишком длинный: оставьте требования вакансии")
    draft = textparse.parse_need_text(text)
    if not draft.specialization_code:
        raise ApiException(422, "specialization_unavailable", "Не удалось определить специализацию по тексту")
    return blueprint_for(
        db,
        draft.specialization_code,
        draft.grade_code or "middle",
        draft.must_skills,
        draft.nice_skills,
        grade_guessed=draft.grade_code is None,
    )


def methodology(db: Session) -> MethodologyView:
    """Константы механики и состав банка (Арх. 9.5). Числа валидации отдаёт `/validation/summary`."""
    cfg = get_config()
    counts = {
        (family_id, level): count
        for family_id, level, count in db.execute(
            select(VariantRow.family_id, VariantRow.level, func.count())
            .where(VariantRow.status == VariantStatus.ACTIVE.value)
            .group_by(VariantRow.family_id, VariantRow.level)
        )
    }
    families = repo.load_families(db)
    groups = []
    for code in GROUPS:
        members = [f for f in families if f.group == code]
        if not members:
            continue
        groups.append(
            MethodologyGroup(
                group=labels.group_ref(code),
                families=len(members),
                levels=sum(len(f.levels) for f in members),
                variants=sum(counts.get((f.id, lv.level), 0) for f in members for lv in f.levels),
            )
        )
    total_families = db.scalar(select(func.count()).select_from(FamilyRow)) or 0
    constants = cfg.model_dump(exclude={"bank_version", "engine_version", "survey_version"})
    constants["main_range"] = {g: list(r) for g, r in blueprints.MAIN_RANGE.items()}
    constants["stretch_range"] = {g: (list(r) if r else None) for g, r in blueprints.STRETCH_RANGE.items()}
    constants["items_min"], constants["items_max"] = cfg.items_min, cfg.items_max
    return MethodologyView(
        constants=constants,
        versions={"bank": cfg.bank_version, "engine": cfg.engine_version, "survey": cfg.survey_version},
        grades=[labels.grade_ref(g) for g in GRADES],
        outcomes=[Ref(code=o.value, title=labels.OUTCOME_TITLES[o]) for o in TestOutcome],
        bank=MethodologyBank(
            families=len(families) if families else total_families,
            levels=sum(len(f.levels) for f in families),
            variants=sum(counts.values()),
            groups=groups,
            available_categories=catalog.get_catalog().available_categories,
        ),
    )
