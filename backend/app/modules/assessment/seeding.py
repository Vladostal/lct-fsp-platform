"""Функции записи для сида и демо-режима (Арх. 2.5, 13.5): готовый путь кандидата и идущий тест.

Обе функции пишут ответы и вызывают тот же код закрытия сессии, что и живой тест: исходы, категория, уровень
и вердикты по навыкам считаются движком, а не подставляются.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ApiException
from app.modules.assessment import blueprints, repo, sessions
from app.modules.assessment.config import GRADES, get_config
from app.modules.assessment.dto import SeedResult, SeedSession
from app.modules.assessment.engine import assemble, rules
from app.modules.assessment.families._lib.contract import raw_answer_for
from app.modules.assessment.models import (
    AssessmentProfile,
    GradeClaim,
    SessionItemRow,
    SessionRow,
    SurveyResponse,
    VariantRow,
)
from app.modules.catalog import service as catalog
from app.shared.enums import ClaimSource, ItemKind, ItemStatus, SessionKind, SessionStatus, VariantStatus

_DEFAULT_LANGUAGE = {"backend": "python", "frontend": "javascript", "fullstack": "javascript", "data_ml": "python"}
_DEFAULT_EXPERIENCE = {"junior": "1_2", "middle": "2_4", "senior": "4_plus"}


def _ensure_profile(
    db: Session,
    candidate_id: UUID,
    specialization: str,
    grade: str,
    now: datetime,
    *,
    main_language: str | None = None,
    experience_band: str | None = None,
    industry_domains: list[str] | None = None,
) -> AssessmentProfile:
    """Опрос и заявленный грейд синтетического кандидата, если их ещё нет."""
    profile = repo.profile(db, candidate_id)
    if profile is not None:
        if profile.claimed_grade is None:
            profile.claimed_grade = grade
        return profile
    language = main_language or _DEFAULT_LANGUAGE.get(specialization, "other")
    module = blueprints.lang_module(specialization, language) if specialization in blueprints.LANG_RULES else None
    response = SurveyResponse(
        candidate_id=candidate_id,
        survey_version=get_config().survey_version,
        answers={
            "direction": catalog.specialization(specialization).direction_code,
            "specialization": specialization,
            "main_language": language,
            "experience_band": experience_band or _DEFAULT_EXPERIENCE[grade],
            "industry_domains": list(industry_domains or []),
        },
        specialization_code=specialization,
        lang_module=module,
        created_at=now,
    )
    db.add(response)
    db.flush()
    profile = AssessmentProfile(
        candidate_id=candidate_id,
        survey_response_id=response.id,
        specialization_code=specialization,
        lang_module=module,
        claimed_grade=grade,
        claim_locked=False,
        updated_at=now,
    )
    db.add(profile)
    db.add(
        GradeClaim(
            candidate_id=candidate_id,
            specialization_code=specialization,
            grade_code=grade,
            source=ClaimSource.SURVEY.value,
            created_at=now,
        )
    )
    db.flush()
    return profile


def _seed_variant(
    db: Session, family_id: str, level: int, seed: str, cache: dict[tuple[str, int], list[VariantRow]]
) -> VariantRow:
    """Вариант для записи сида: выбирается по seed сессии и НЕ увеличивает `served_count`.

    Синтетические кандидаты не должны расходовать запас ни разу не показанных вариантов: он нужен живым.
    """
    key = (family_id, level)
    if key not in cache:
        cache[key] = list(
            db.scalars(
                select(VariantRow)
                .where(
                    VariantRow.family_id == family_id,
                    VariantRow.level == level,
                    VariantRow.status == VariantStatus.ACTIVE.value,
                )
                .order_by(VariantRow.id)
            )
        )
    rows = cache[key]
    if not rows:
        raise ValueError(f"seed_result: в банке нет вариантов семейства {family_id}, уровень {level}")
    digest = hmac.new(bytes.fromhex(seed), f"seed:{family_id}:{level}".encode(), hashlib.sha256).digest()
    return rows[int.from_bytes(digest[:8], "big") % len(rows)]


def _write_session(
    db: Session,
    profile: AssessmentProfile,
    data: SeedSession,
    prefilled: bool,
    cache: dict[tuple[str, int], list[VariantRow]],
) -> None:
    cfg = get_config()
    families = {family.id: family for family in repo.load_families(db, statuses=None)}
    ctx = sessions.start_context(db, profile.candidate_id)
    decision = rules.can_start(ctx, data.grade_code, data.started_at)
    kind = decision.kind or SessionKind.RETAKE
    attempt_no = 1 + sum(
        1
        for row in repo.sessions(db, profile.candidate_id)
        if row.specialization_code == profile.specialization_code and row.target_grade == data.grade_code
    )
    seed = assemble.session_seed(
        get_settings().assessment_secret, profile.candidate_id, profile.specialization_code, data.grade_code, attempt_no
    )
    session = SessionRow(
        candidate_id=profile.candidate_id,
        specialization_code=profile.specialization_code,
        target_grade=data.grade_code,
        lang_module=profile.lang_module,
        kind=kind.value,
        attempt_no=attempt_no,
        seed=seed,
        status=SessionStatus.IN_PROGRESS.value,
        stage=max((item.stage for item in data.items), default=0),
        started_at=data.started_at,
        expires_at=data.finished_at,
        items_total=len(data.items),
        items_answered=len(data.items),
        blueprint={"slots": blueprints.plan_slots(profile.specialization_code, data.grade_code, profile.lang_module)},
        flags={sessions.FLAG_PREFILLED: True, "seed": True} if prefilled else {"seed": True},
        bank_version=cfg.bank_version,
        engine_version=cfg.engine_version,
    )
    db.add(session)
    db.flush()
    step = (data.finished_at - data.started_at) / max(len(data.items), 1)
    for position, item in enumerate(data.items):
        family = families.get(item.family_id)
        if family is None:
            raise ValueError(f"seed_result: семейства {item.family_id} нет в банке")
        variant = _seed_variant(db, item.family_id, item.level, seed, cache)
        at = data.started_at + step * (position + 1)
        db.add(
            SessionItemRow(
                session_id=session.id,
                position=position,
                stage=item.stage,
                slot_role=item.role.value,
                slot_group=item.slot_group,
                family_id=item.family_id,
                level=item.level,
                variant_id=variant.id,
                a_used=cfg.a_assumed,
                b_used=family.b(item.level),
                c_used=float(variant.guess),
                status=ItemStatus.ANSWERED.value,
                shown_at=at - step,
                answered_at=at,
                score=item.score,
                parse_ok=True,
                flags=[],
            )
        )
    profile.claim_locked = True
    db.flush()
    sessions.finalize(db, session, data.finished_at, by_time=False)


def seed_result(db: Session, result: SeedResult) -> None:
    """Записать путь синтетического кандидата: опрос, заявленный грейд, сессии с ответами — и применить результат.

    Идемпотентна: если у кандидата уже есть сессии, ничего не делает. Банк должен быть собран (шаг инициализации
    идёт раньше сида), а ответы — относиться к его семействам.
    """
    if result.grade_code not in GRADES:
        raise ValueError(f"seed_result: неизвестный грейд {result.grade_code}")
    if repo.sessions(db, result.candidate_id):
        return
    first = result.sessions[0].started_at if result.sessions else None
    profile = _ensure_profile(
        db,
        result.candidate_id,
        result.specialization_code,
        result.grade_code,
        first or get_now(db),
        main_language=result.main_language,
        experience_band=result.experience_band,
        industry_domains=result.industry_domains,
    )
    cache: dict[tuple[str, int], list[VariantRow]] = {}
    for data in result.sessions:
        _write_session(db, profile, data, result.is_demo_result, cache)


def get_now(db: Session) -> datetime:
    from app.core import clock

    return clock.now(db)


def correct_raw(variant: VariantRow) -> dict[str, Any]:
    """Тело верного ответа на вариант — для подставленных ответов демо-теста."""
    kind = ItemKind(variant.payload["kind"])
    answer = variant.answer
    if kind in (ItemKind.NUMERIC_INPUT, ItemKind.TEXT_INPUT):
        value: Any = answer["value"]
    elif kind is ItemKind.SINGLE_CHOICE:
        value = answer["option_id"]
    elif kind is ItemKind.MULTI_CHOICE:
        value = answer["option_ids"]
    elif kind is ItemKind.PICK_LINE:
        value = answer["lines"][0]
    else:
        value = answer["order"]
    return raw_answer_for(kind, value)


def seed_session_in_progress(db: Session, candidate_id: UUID, grade_code: str, answered: int, now: datetime) -> UUID:
    """Идущий тест, в котором первые `answered` ответов подставлены верными (аккаунт `nina`, быстрый демо-тест).

    Право на старт проверяется обычным `can_start` (Арх. 5.7). Сессия помечается `demo_prefilled`: категория,
    полученная по ней, записывается с `is_demo_result = true`. Последнее задание всегда остаётся кандидату.
    У кандидата без опроса создаётся опрос `backend` с заявленным грейдом `grade_code` (демо-аккаунты сида).
    """
    if grade_code not in GRADES:
        raise ApiException(422, "grade_not_allowed")
    profile = _ensure_profile(db, candidate_id, "backend", grade_code, now)
    sessions.close_expired_for(db, candidate_id, now)
    decision = rules.can_start(sessions.start_context(db, candidate_id), grade_code, now)
    if not decision.ok or decision.kind is None:
        raise sessions.start_error(decision)
    if not catalog.is_available(profile.specialization_code, grade_code):
        raise ApiException(422, "grade_unavailable", "Тест на этот грейд пока недоступен")
    session = sessions.create_session(
        db, profile, grade_code, decision.kind.value, now, flags={sessions.FLAG_PREFILLED: True}
    )
    items = sessions.session_items(db, session.id)
    for item in items[: max(0, min(answered, len(items) - 1))]:
        variant = db.get(VariantRow, item.variant_id)
        assert variant is not None
        raw = correct_raw(variant)
        sessions.submit_answer(db, candidate_id, str(session.id), str(item.id), raw, False, None, None, now)
    return session.id
