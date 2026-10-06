"""Профиль кандидата: строка профиля и код кандидата, заявленные навыки, условия, проекция для подбора
(Арх. 6.1, 8.4; приложение B, §1.1).

Внутренний файл модуля: другие модули вызывают только `service.py`.
"""

from __future__ import annotations

import secrets
from collections.abc import Collection
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ApiException, field_error, not_found, validation_error
from app.modules.assessment import service as assessment
from app.modules.catalog import service as catalog
from app.modules.catalog.dto import SkillDTO
from app.modules.identity import service as identity
from app.modules.profile import privacy as privacy_store
from app.modules.profile import visibility as visibility_rules
from app.modules.profile.constants import (
    DECLARED_SKILLS_MAX,
    DECLARED_SOFT_SKILLS_MAX,
    PUBLIC_CODE_ATTEMPTS,
    PUBLIC_CODE_DIGITS,
    PUBLIC_CODE_PREFIX,
    SOFT_KIND,
)
from app.modules.profile.dto import ConditionsData, PoolProfile, ProfileData
from app.modules.profile.models import (
    CandidateConditions,
    CandidateDeclaredSkill,
    CandidateProfile,
    ResumeUpload,
)
from app.modules.profile.privacy import in_ids
from app.modules.profile.schemas import (
    CandidateProfileView,
    ConditionsView,
    ProfileCompleteness,
    ProfileDeclaredSkill,
    ProfileHints,
    ProfileResumeBrief,
)
from app.shared.enums import DemoPersona, WorkFormat
from app.shared.salary import is_on_ladder
from app.shared.schemas import Ref

_PUBLIC_CODE_CONSTRAINT = "uq_candidate_profile_public_code"

#: Поля, по которым считается заполненность формы (`CandidateProfileView.completeness`).
COMPLETENESS_FIELDS = (
    "last_name",
    "first_name",
    "city",
    "phone",
    "telegram",
    "link",
    "experience_years",
    "roles",
    "declared_skills",
    "about",
)


# --- строка профиля и код кандидата ----------------------------------------------------------------------------------


def generate_public_code() -> str:
    """Случайный код кандидата: «К-» и пять цифр. Из идентификатора пользователя не выводится."""
    number = secrets.randbelow(10**PUBLIC_CODE_DIGITS)
    return f"{PUBLIC_CODE_PREFIX}{number:0{PUBLIC_CODE_DIGITS}d}"


def get_profile(db: Session, candidate_id: UUID) -> CandidateProfile | None:
    return db.get(CandidateProfile, candidate_id)


def ensure_profile(db: Session, candidate_id: UUID, now: datetime) -> CandidateProfile:
    """Строка профиля; при первом обращении кандидата создаётся с новым кодом (Арх. 8.4).

    Код случайный, поэтому возможна коллизия с уже выданным: вставка идёт в точке сохранения, и при нарушении
    уникальности кода генерация повторяется (до `PUBLIC_CODE_ATTEMPTS` раз) — остальная транзакция запроса не
    страдает. Если строку успел создать параллельный запрос того же кандидата, берётся она.
    """
    row = db.get(CandidateProfile, candidate_id)
    if row is not None:
        return row
    for _ in range(PUBLIC_CODE_ATTEMPTS):
        row = CandidateProfile(
            user_id=candidate_id, public_code=generate_public_code(), roles=[], created_at=now, updated_at=now
        )
        try:
            with db.begin_nested():
                db.add(row)
                db.flush()
        except IntegrityError as exc:
            existing = db.get(CandidateProfile, candidate_id)
            if existing is not None:
                return existing
            constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            if constraint != _PUBLIC_CODE_CONSTRAINT:
                raise  # например, пользователя не существует: это ошибка вызывающего, а не коллизия кода
            continue
        return row
    raise RuntimeError("не удалось подобрать свободный код кандидата")


def set_demo_persona(db: Session, candidate_id: UUID, persona: DemoPersona | str | None, now: datetime) -> None:
    row = ensure_profile(db, candidate_id, now)
    row.demo_persona = DemoPersona(persona).value if persona is not None else None
    db.flush()


def demo_persona(db: Session, candidate_id: UUID) -> str | None:
    return db.scalar(select(CandidateProfile.demo_persona).where(CandidateProfile.user_id == candidate_id))


def is_complete(row: CandidateProfile | None) -> bool:
    """Профиль готов к публикации и к PDF: есть имя и фамилия."""
    return row is not None and bool(row.first_name) and bool(row.last_name)


# --- справочник ------------------------------------------------------------------------------------------------------


def _catalog_index() -> tuple[dict[str, SkillDTO], dict[str, Ref]]:
    data = catalog.get_catalog()
    return {skill.code: skill for skill in data.skills}, {role.code: role for role in data.roles}


# --- сохранение формы ------------------------------------------------------------------------------------------------


def _resume_skill_codes(upload: ResumeUpload | None) -> set[str]:
    """Коды навыков, распознанных в резюме: при сохранении они получают `source = resume`."""
    if upload is None or not upload.result:
        return set()
    codes: set[str] = set()
    fields = upload.result.get("fields") or {}
    for name in ("declared_skills", "soft_skills"):
        for item in (fields.get(name) or {}).get("value") or []:
            if isinstance(item, dict) and isinstance(item.get("code"), str):
                codes.add(item["code"])
    return codes


def _resume_hint(upload: ResumeUpload, name: str) -> str | None:
    value = ((upload.result or {}).get("fields") or {}).get(name, {}).get("value")
    return value if isinstance(value, str) and value else None


def save_profile(db: Session, candidate_id: UUID, data: ProfileData, now: datetime) -> None:
    """Полная замена редактируемых полей и заявленных навыков.

    Формат полей уже проверен моделью `ProfileData`. Здесь — то, для чего нужен справочник: коды ролей и навыков
    существуют; навыков с `kind != soft` вместе со своими тегами не больше 30, с `kind = soft` — не больше 10.
    Чужой либо несуществующий `resume_upload_id` — 404 (стороны эти случаи не различают).
    """
    skills_index, roles_index = _catalog_index()
    errors = []
    unknown_roles = [code for code in data.roles if code not in roles_index]
    if unknown_roles:
        errors.append(field_error("roles", "role_unknown", f"Роли нет в справочнике: {', '.join(unknown_roles)}"))
    hard = soft = 0
    for index, item in enumerate(data.declared_skills):
        if item.code is None:
            hard += 1
            continue
        skill = skills_index.get(item.code)
        if skill is None:
            errors.append(
                field_error(f"declared_skills.{index}.code", "skill_unknown", f"Навыка нет в справочнике: {item.code}")
            )
        elif skill.kind == SOFT_KIND:
            soft += 1
        else:
            hard += 1
    if hard > DECLARED_SKILLS_MAX:
        errors.append(
            field_error("declared_skills", "declared_skills_limit", f"Не больше {DECLARED_SKILLS_MAX} навыков и тегов")
        )
    if soft > DECLARED_SOFT_SKILLS_MAX:
        errors.append(
            field_error("declared_skills", "soft_skills_limit", f"Не больше {DECLARED_SOFT_SKILLS_MAX} софт-скиллов")
        )
    if errors:
        raise validation_error(*errors)

    upload: ResumeUpload | None = None
    if data.resume_upload_id is not None:
        upload = db.get(ResumeUpload, data.resume_upload_id)
        if upload is None or upload.user_id != candidate_id:
            raise not_found()

    row = ensure_profile(db, candidate_id, now)
    row.last_name = data.last_name
    row.first_name = data.first_name
    row.middle_name = data.middle_name
    row.city = data.city
    row.phone = data.phone
    row.telegram = data.telegram
    row.link = data.link
    row.experience_years = Decimal(str(data.experience_years)) if data.experience_years is not None else None
    row.roles = list(data.roles)
    row.about = data.about
    row.updated_at = now

    # Источник навыка: распознан в этом резюме либо уже был сохранён как «из резюме»; иначе введён вручную.
    previous = {
        (skill.skill_code, (skill.custom_label or "").lower()): skill.source
        for skill in db.scalars(select(CandidateDeclaredSkill).where(CandidateDeclaredSkill.user_id == candidate_id))
    }
    from_resume = _resume_skill_codes(upload)
    db.execute(delete(CandidateDeclaredSkill).where(CandidateDeclaredSkill.user_id == candidate_id))
    for position, item in enumerate(data.declared_skills):
        key = (item.code, (item.custom_label or "").lower())
        source = "resume" if item.code in from_resume else previous.get(key, "manual")
        db.add(
            CandidateDeclaredSkill(
                user_id=candidate_id,
                skill_code=item.code,
                custom_label=item.custom_label,
                source=source,
                position=position,
            )
        )

    if upload is not None:
        # Подсказки грейда и специализации переходят в профиль, а сам результат разбора обнуляется:
        # разобранные ФИО и контакты не хранятся второй копией (Арх. 6.14).
        if upload.result:
            row.grade_hint = _resume_hint(upload, "grade_hint") or row.grade_hint
            row.specialization_hint = _resume_hint(upload, "specialization_hint") or row.specialization_hint
        upload.accepted_fields = list(data.resume_accepted_fields)
        upload.result = None
    db.flush()


# --- проекция для самого кандидата -----------------------------------------------------------------------------------


def declared_rows(db: Session, candidate_id: UUID) -> list[CandidateDeclaredSkill]:
    query = (
        select(CandidateDeclaredSkill)
        .where(CandidateDeclaredSkill.user_id == candidate_id)
        .order_by(CandidateDeclaredSkill.position)
    )
    return list(db.scalars(query))


def profile_view(db: Session, candidate_id: UUID, email: str, now: datetime) -> CandidateProfileView:
    """Профиль для экрана кандидата. Строка профиля создаётся при первом обращении (вместе с кодом кандидата)."""
    row = ensure_profile(db, candidate_id, now)
    skills_index, roles_index = _catalog_index()
    declared: list[ProfileDeclaredSkill] = []
    for skill in declared_rows(db, candidate_id):
        source = "resume" if skill.source == "resume" else "manual"
        if skill.skill_code is None:
            item = ProfileDeclaredSkill(
                code=None, title=skill.custom_label or "", kind=None, custom=True, source=source
            )
        else:
            known = skills_index.get(skill.skill_code)
            item = ProfileDeclaredSkill(
                code=skill.skill_code,
                title=known.title if known else skill.skill_code,
                kind=known.kind if known else None,
                custom=False,
                source=source,
            )
        declared.append(item)

    filled = {
        "last_name": bool(row.last_name),
        "first_name": bool(row.first_name),
        "city": bool(row.city),
        "phone": bool(row.phone),
        "telegram": bool(row.telegram),
        "link": bool(row.link),
        "experience_years": row.experience_years is not None,
        "roles": bool(row.roles),
        "declared_skills": bool(declared),
        "about": bool(row.about),
    }
    missing = [name for name in COMPLETENESS_FIELDS if not filled[name]]

    last_upload = db.scalars(
        select(ResumeUpload)
        .where(ResumeUpload.user_id == candidate_id)
        .order_by(ResumeUpload.created_at.desc(), ResumeUpload.id)
        .limit(1)
    ).first()

    return CandidateProfileView(
        public_code=row.public_code,
        email=email,
        last_name=row.last_name,
        first_name=row.first_name,
        middle_name=row.middle_name,
        city=row.city,
        phone=row.phone,
        telegram=row.telegram,
        link=row.link,
        experience_years=float(row.experience_years) if row.experience_years is not None else None,
        roles=[roles_index.get(code) or Ref(code=code, title=code) for code in row.roles],
        about=row.about,
        declared_skills=declared,
        hints=ProfileHints(grade_hint=row.grade_hint, specialization_hint=row.specialization_hint),
        completeness=ProfileCompleteness(
            filled=len(COMPLETENESS_FIELDS) - len(missing), total=len(COMPLETENESS_FIELDS), missing=missing
        ),
        resume=(
            ProfileResumeBrief(
                upload_id=last_upload.id,
                status="parsed" if last_upload.status == "parsed" else "failed",
                created_at=last_upload.created_at,
            )
            if last_upload is not None
            else None
        ),
    )


# --- условия ---------------------------------------------------------------------------------------------------------


def _default_formats() -> list[WorkFormat]:
    return list(WorkFormat)


def conditions_view(db: Session, candidate_id: UUID) -> ConditionsView:
    """Условия кандидата; строки нет — значения по умолчанию (минимум не задан, все три формата)."""
    row = db.get(CandidateConditions, candidate_id)
    if row is None:
        return ConditionsView(min_salary=None, work_formats=_default_formats(), relocation_ready=False)
    return ConditionsView(
        min_salary=row.min_salary,
        work_formats=[WorkFormat(item) for item in row.work_formats],
        relocation_ready=row.relocation_ready,
    )


def save_conditions(db: Session, candidate_id: UUID, data: ConditionsData, now: datetime) -> None:
    """Сохранить условия. Минимум — только «не задан» либо ступень лестницы (Арх. 4.6): произвольное значение
    позволило бы точнее восстановить его перебором вилок.
    """
    if not is_on_ladder(data.min_salary):
        error = ApiException(422, "min_salary_not_on_ladder", "Выберите значение из списка")
        error.fields = [field_error("min_salary", "min_salary_not_on_ladder", error.message)]
        raise error
    row = db.get(CandidateConditions, candidate_id)
    if row is None:
        row = CandidateConditions(candidate_id=candidate_id, updated_at=now)
        db.add(row)
    row.min_salary = data.min_salary
    row.work_formats = [item.value for item in data.work_formats]
    row.relocation_ready = data.relocation_ready
    row.updated_at = now
    db.flush()


def min_salary(db: Session, candidate_id: UUID) -> int | None:
    return db.scalar(select(CandidateConditions.min_salary).where(CandidateConditions.candidate_id == candidate_id))


# --- проекция для подбора --------------------------------------------------------------------------------------------


def pool_view(db: Session, candidate_ids: Collection[UUID], now: datetime) -> dict[UUID, PoolProfile]:
    """Профили пачкой для подбора: по одному запросу на таблицу и по одному вызову фасадов нижних модулей.

    В ответе только кандидаты, у которых есть строка профиля (без неё нет кода кандидата; такой кандидат не мог
    дать согласие на публикацию и в пул не входит). Ничего не пишет.
    """
    ids = list(dict.fromkeys(candidate_ids))
    if not ids:
        return {}
    rows = {
        row.user_id: row for row in db.scalars(select(CandidateProfile).where(in_ids(CandidateProfile.user_id, ids)))
    }
    if not rows:
        return {}
    present = list(rows)

    conditions = {
        row.candidate_id: row
        for row in db.scalars(select(CandidateConditions).where(in_ids(CandidateConditions.candidate_id, present)))
    }
    settings = privacy_store.load_many(db, present)
    declared: dict[UUID, list[str]] = {}
    custom: dict[UUID, list[str]] = {}
    skills_query = (
        select(
            CandidateDeclaredSkill.user_id,
            CandidateDeclaredSkill.skill_code,
            CandidateDeclaredSkill.custom_label,
        )
        .where(in_ids(CandidateDeclaredSkill.user_id, present))
        .order_by(CandidateDeclaredSkill.user_id, CandidateDeclaredSkill.position)
    )
    for user_id, skill_code, custom_label in db.execute(skills_query):
        if skill_code is not None:
            declared.setdefault(user_id, []).append(skill_code)
        elif custom_label:
            custom.setdefault(user_id, []).append(custom_label)

    categories = assessment.get_categories(db, present)
    published = identity.publication_consent_active(db, present)
    users = identity.users(db, present)

    result: dict[UUID, PoolProfile] = {}
    for candidate_id, row in rows.items():
        category = categories.get(candidate_id)
        state = visibility_rules.compute(
            has_category=category is not None,
            consent_active=candidate_id in published,
            paused_at=row.paused_at,
            auto_paused_until=row.auto_paused_until,
            now=now,
        )
        own = settings[candidate_id]
        terms = conditions.get(candidate_id)
        user = users.get(candidate_id)
        show_stack = own.show_declared_stack
        result[candidate_id] = PoolProfile(
            public_code=row.public_code,
            visible=state.state.value == "visible",
            visibility=state,
            privacy=own,
            work_formats=[WorkFormat(item) for item in terms.work_formats] if terms else _default_formats(),
            relocation_ready=terms.relocation_ready if terms else False,
            # Скрытое настройкой не только не показывается, но и не используется в подборе (Арх. 10.4).
            declared_skills=declared.get(candidate_id, []) if show_stack else [],
            custom_skills=custom.get(candidate_id, []) if show_stack else [],
            city=row.city if own.show_city else None,
            experience_years=(
                float(row.experience_years) if own.show_experience and row.experience_years is not None else None
            ),
            roles=list(row.roles) if own.show_experience else [],
            # Только чип показа: аккаунт демо либо категория получена быстрым демо-тестом (Арх. 13.5).
            is_demo=bool(user and user.is_demo) or bool(category and category.is_demo_result),
        )
    return result


def count_profiles(db: Session) -> int:
    """Число строк профиля (для самопроверок и тестов)."""
    return int(db.scalar(select(func.count()).select_from(CandidateProfile)) or 0)
