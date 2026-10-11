"""Экраны кандидата: опрос, заявленный грейд, состояние, планы, результат, история (Арх. 5.2, 5.6, 5.7, 9.5)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiException, validation_error
from app.modules.assessment import blueprints, labels, repo, sessions, survey_schema
from app.modules.assessment.config import GRADES, get_config
from app.modules.assessment.dto import LevelThreshold, LevelView
from app.modules.assessment.engine import level as level_math
from app.modules.assessment.engine import rules
from app.modules.assessment.groups import TESTED_SPECIALIZATIONS
from app.modules.assessment.models import (
    AssessmentProfile,
    CategoryRow,
    GradeClaim,
    SessionRow,
    SkillEvidenceRow,
    SurveyResponse,
)
from app.modules.assessment.schemas import (
    ActiveSessionBrief,
    AnswerResult,
    AssessmentStateView,
    BlueprintSkill,
    HistoryItem,
    LastSessionBrief,
    NextAction,
    ResultSkill,
    StateCategory,
    SurveySchema,
    TestBlueprintView,
    TestProgress,
    TestResultView,
    TestSessionView,
)
from app.modules.catalog import service as catalog
from app.shared.enums import CategoryBasis, ClaimSource, EvidenceSource, SessionStatus, TestOutcome
from app.shared.schemas import Ref

# --------------------------------------------------------------------------------------------------------------------
# Опрос и заявленный грейд
# --------------------------------------------------------------------------------------------------------------------


def _answers(db: Session, profile: AssessmentProfile | None) -> dict[str, Any] | None:
    if profile is None:
        return None
    row = db.get(SurveyResponse, profile.survey_response_id)
    return dict(row.answers) if row else None


def get_survey(db: Session, candidate_id: UUID) -> SurveySchema:
    return SurveySchema(
        version=get_config().survey_version,
        questions=survey_schema.questions(),
        answers=_answers(db, repo.profile(db, candidate_id)),
    )


def put_survey(
    db: Session, candidate_id: UUID, version: str, answers: dict[str, Any], confirm_change: bool, now: datetime
) -> SurveySchema:
    """Сохранить ответы опроса (Арх. 5.2): новая строка ответов, история не перезаписывается.

    Смена специализации после первой сессии или при действующей категории требует подтверждения и возможна раз в
    `SPECIALIZATION_CHANGE_COOLDOWN_DAYS`; заявленный грейд при ней сбрасывается, а прежняя категория сохраняется,
    пока не подтверждён (или, где теста нет, не заявлен) грейд в новой. Опрос запрещён при активной сессии.
    Специализация без теста допустима: категория в ней будет заявленной (`put_claim`). Специализация, тест
    по которой написан, но сейчас недоступен, — 422 `specialization_unavailable`.
    """
    cfg = get_config()
    if version != cfg.survey_version:
        raise ApiException(409, "survey_version_mismatch", "Опрос обновился. Обновите страницу")
    sessions.close_expired_for(db, candidate_id, now)
    rows = repo.sessions(db, candidate_id)
    active = next((row for row in rows if row.status == SessionStatus.IN_PROGRESS.value), None)
    if active is not None:
        raise ApiException(
            409, "session_active", labels.ERROR_MESSAGES["session_active"], params={"session_id": str(active.id)}
        )
    parsed, errors = survey_schema.validate(answers)
    if parsed is None:
        raise validation_error(*errors)
    if parsed.specialization in TESTED_SPECIALIZATIONS and not catalog.is_available(parsed.specialization):
        # Тест написан, но банк не собран или специализация выключена: заявленной категории здесь не бывает.
        raise ApiException(422, "specialization_unavailable", "Тест по этой специализации временно недоступен")

    profile = repo.profile(db, candidate_id)
    changing = profile is not None and profile.specialization_code != parsed.specialization
    category = repo.category(db, candidate_id)
    # «История» в прежней специализации — сессии теста либо действующая категория (в том числе заявленная).
    had_sessions = profile is not None and (
        any(r.specialization_code == profile.specialization_code for r in rows)
        or (category is not None and category.specialization_code == profile.specialization_code)
    )
    if changing and had_sessions:
        assert profile is not None
        if not confirm_change:
            target_has_test = not sessions.declared_allowed(parsed.specialization)
            replaces_confirmed = (
                category is not None and category.basis == CategoryBasis.TEST.value and not target_has_test
            )
            raise ApiException(
                409,
                "specialization_change_requires_confirm",
                (
                    "Тест по новой специализации готовится: подтверждённая категория будет заменена заявленным грейдом"
                    if replaces_confirmed
                    else "Смена специализации сбросит заявленный грейд"
                ),
                params={"target_has_test": target_has_test, "replaces_confirmed_category": replaces_confirmed},
            )
        if profile.specialization_changed_at is not None:
            available_at = profile.specialization_changed_at + timedelta(days=cfg.specialization_change_cooldown_days)
            if now < available_at:
                raise ApiException(
                    409,
                    "cooldown_active",
                    params={"reason": "specialization_change", "available_at": available_at.isoformat()},
                )
    response = SurveyResponse(
        candidate_id=candidate_id,
        survey_version=version,
        answers=parsed.answers,
        specialization_code=parsed.specialization,
        lang_module=parsed.lang_module,
        created_at=now,
    )
    db.add(response)
    db.flush()
    if profile is None:
        profile = AssessmentProfile(candidate_id=candidate_id, claim_locked=False)
        db.add(profile)
    elif changing:
        # Заявленный грейд относится к специализации: в новой его нужно заявить заново.
        profile.claimed_grade = None
        profile.claim_locked = False
        if had_sessions:
            profile.specialization_changed_at = now
    profile.survey_response_id = response.id
    profile.specialization_code = parsed.specialization
    profile.lang_module = parsed.lang_module
    profile.updated_at = now
    db.flush()
    return get_survey(db, candidate_id)


def put_claim(db: Session, candidate_id: UUID, grade: str, now: datetime) -> AssessmentStateView:
    """Заявить грейд; после первой сессии заявление заблокировано (`claim_locked`, Арх. 5.7).

    В специализации без теста заявление сразу даёт категорию `basis = declared` (`sessions.declare_category`):
    блокировки `claim_locked` там нет, смену грейда ограничивает срок — 409 `cooldown_active`.
    """
    profile = repo.profile(db, candidate_id)
    if profile is None:
        raise ApiException(409, "survey_required", "Сначала пройдите опрос")
    has_test = not sessions.declared_allowed(profile.specialization_code)
    if grade not in GRADES or (has_test and not catalog.is_available(profile.specialization_code, grade)):
        raise ApiException(422, "grade_unavailable", "Тест на этот грейд пока недоступен")
    if not has_test:
        sessions.declare_category(db, candidate_id, profile.specialization_code, grade, now)
    elif profile.claim_locked and profile.claimed_grade != grade:
        raise ApiException(409, "claim_locked", "Заявленный грейд нельзя изменить после начала теста")
    if profile.claimed_grade != grade:
        answers = _answers(db, profile) or {}
        preselected = survey_schema.EXPERIENCE_GRADE.get(str(answers.get("experience_band")))
        profile.claimed_grade = grade
        profile.updated_at = now
        db.add(
            GradeClaim(
                candidate_id=candidate_id,
                specialization_code=profile.specialization_code,
                grade_code=grade,
                source=(ClaimSource.SURVEY if preselected == grade else ClaimSource.MANUAL).value,
                created_at=now,
            )
        )
        db.flush()
    return state_view(db, candidate_id, now)


# --------------------------------------------------------------------------------------------------------------------
# Уровень, состояние, планы
# --------------------------------------------------------------------------------------------------------------------


def level_view(
    theta: float,
    se: float,
    grade: str,
    verdict: str,
    tested_at: datetime,
    last_evidence_at: datetime,
    now: datetime,
    *,
    expired: bool = False,
) -> LevelView:
    """`LevelView` (Арх. 5.6): точка и интервал на шкале экрана; единиц θ клиент не получает."""
    numbers = level_math.level_numbers(theta, se, grade, last_evidence_at, now)
    return LevelView(
        point=round(numbers.point, 1),
        lower=round(numbers.lower, 1),
        upper=round(numbers.upper, 1),
        thresholds=[LevelThreshold(grade=labels.grade_ref(g), pos=p) for g, p in level_math.thresholds()],
        verdict=TestOutcome(verdict),
        verdict_label=labels.outcome_label(verdict, grade, expired=expired),
        stale=numbers.stale,
        tested_at=tested_at,
        last_evidence_at=last_evidence_at,
    )


def category_level_view(row: CategoryRow, now: datetime) -> LevelView | None:
    """Уровень категории на шкале экрана; `None` — грейд заявлен, тестом уровень не измерен."""
    if (
        row.basis != CategoryBasis.TEST.value
        or row.theta is None
        or row.se is None
        or row.verdict is None
        or row.level_updated_at is None
        or row.last_evidence_at is None
    ):
        return None
    return level_view(row.theta, row.se, row.grade_code, row.verdict, row.level_updated_at, row.last_evidence_at, now)


def actions(db: Session, candidate_id: UUID, now: datetime) -> list[NextAction]:
    ctx = sessions.start_context(db, candidate_id)
    if ctx.specialization is None or sessions.declared_allowed(ctx.specialization):
        # Теста по специализации нет: действий с тестом тоже нет, грейд заявляется (`put_claim`).
        return []
    # Подставленные ответы быстрого демо-теста учитываются, только пока действующая категория получена им же.
    category = repo.category(db, candidate_id)
    demo_category = bool(category is not None and category.is_demo_result)
    post = sessions.window_posterior(db, candidate_id, ctx.specialization, now, include_prefilled=demo_category)
    result = []
    for action in rules.next_actions(ctx, now, post.p_ge):
        open_now = action.available and catalog.is_available(ctx.specialization, action.grade)
        result.append(
            NextAction(
                kind=action.kind,
                grade=labels.grade_ref(action.grade),
                available=open_now,
                available_at=action.available_at,
                reason=action.reason,
                recommended=action.recommended and open_now,
            )
        )
    return result


def state_view(db: Session, candidate_id: UUID, now: datetime) -> AssessmentStateView:
    """`GET /assessment/state`; заодно закрывает сессию, если время вышло."""
    sessions.close_expired_for(db, candidate_id, now)
    profile = repo.profile(db, candidate_id)
    if profile is None:
        return AssessmentStateView(survey_completed=False)
    answers = _answers(db, profile) or {}
    spec = catalog.specialization(profile.specialization_code)
    cat = catalog.get_catalog()
    direction = next((d for d in cat.directions if d.code == spec.direction_code), None)
    language = answers.get("main_language")
    rows = repo.sessions(db, candidate_id)
    active = next((row for row in rows if row.status == SessionStatus.IN_PROGRESS.value), None)
    closed = [row for row in rows if row.status != SessionStatus.IN_PROGRESS.value and row.outcome]
    last = closed[-1] if closed else None
    category = repo.category(db, candidate_id)
    return AssessmentStateView(
        survey_completed=True,
        direction=direction,
        specialization=Ref(code=spec.code, title=spec.title),
        main_language=(
            Ref(code=language, title=survey_schema.LANGUAGE_TITLES.get(language, language)) if language else None
        ),
        claimed_grade=labels.grade_ref(profile.claimed_grade) if profile.claimed_grade else None,
        claim_locked=profile.claim_locked,
        category=(
            StateCategory(
                **labels.category_ref(
                    category.specialization_code, category.grade_code, category.basis
                ).model_dump(),
                assigned_at=category.assigned_at,
                change_available_at=category.change_available_at,
                level_session_id=str(category.level_session_id) if category.level_session_id else None,
                is_demo_result=bool(category.is_demo_result),
            )
            if category
            else None
        ),
        level=category_level_view(category, now) if category else None,
        active_session=(
            ActiveSessionBrief(
                id=str(active.id),
                target=labels.category_ref(active.specialization_code, active.target_grade),
                expires_at=active.expires_at,
            )
            if active
            else None
        ),
        last_session=(
            LastSessionBrief(
                id=str(last.id),
                target=labels.category_ref(last.specialization_code, last.target_grade),
                outcome=TestOutcome(last.outcome or TestOutcome.BORDERLINE.value),
                finished_at=last.finished_at or last.started_at,
            )
            if last
            else None
        ),
        next_actions=actions(db, candidate_id, now),
    )


def blueprint_views(db: Session, candidate_id: UUID) -> list[TestBlueprintView]:
    """Планы теста по грейдам специализации кандидата: число заданий, время, группы (Арх. 5.4)."""
    profile = repo.profile(db, candidate_id)
    if profile is None:
        raise ApiException(409, "survey_required", "Сначала пройдите опрос")
    cfg = get_config()
    families = repo.load_families(db)
    spec = profile.specialization_code
    if sessions.declared_allowed(spec):
        # Теста нет — планов нет (у части специализаций нет и групп заданий в `groups.SPECIALIZATIONS`).
        return []
    result = []
    for grade in GRADES:
        lang = profile.lang_module
        if lang is not None and not blueprints.lang_module_available(families, spec, grade, lang):
            lang = None
        skills = [
            BlueprintSkill(group_code=group, label=labels.group_title(group), slots=slots)
            for group, slots in blueprints.plan_slots(spec, grade, lang).items()
        ]
        skills.append(BlueprintSkill(group_code="any", label="Задания из любых групп", slots=cfg.base_stretch))
        result.append(
            TestBlueprintView(
                grade=labels.grade_ref(grade),
                available=catalog.is_available(spec, grade),
                items_min=cfg.items_min,
                items_max=cfg.items_max,
                time_limit_min=cfg.time_limit_base_min[grade],
                time_limit_max_min=cfg.time_limit_base_min[grade] + cfg.time_limit_ext_min[grade] * cfg.max_ext_blocks,
                skills=skills,
            )
        )
    return result


# --------------------------------------------------------------------------------------------------------------------
# Сессия, результат, история
# --------------------------------------------------------------------------------------------------------------------


def session_view(db: Session, session: SessionRow, now: datetime) -> TestSessionView:
    return TestSessionView(
        id=str(session.id),
        status=SessionStatus(session.status),
        target=labels.category_ref(session.specialization_code, session.target_grade),
        expires_at=session.expires_at,
        server_now=now,
        progress=TestProgress(**sessions.progress(session)),
        item=sessions.current_item(db, session),
    )


def get_session(db: Session, candidate_id: UUID, session_id: str, now: datetime) -> TestSessionView:
    session = sessions.owned_session(db, candidate_id, session_id, lock=True)
    if session.status == SessionStatus.IN_PROGRESS.value and now > session.expires_at:
        sessions.finalize(db, session, now, by_time=True)
    return session_view(db, session, now)


def answer_result(db: Session, session: SessionRow, now: datetime) -> AnswerResult:
    return AnswerResult(
        finished=session.status != SessionStatus.IN_PROGRESS.value,
        next_item=sessions.current_item(db, session),
        progress=TestProgress(**sessions.progress(session)),
        expires_at=session.expires_at,
        server_now=now,
    )


def result_view(db: Session, candidate_id: UUID, session_id: str, now: datetime) -> TestResultView | None:
    """`TestResultView` закрытой сессии; `None` — сессия ещё идёт (роутер отвечает 202)."""
    session = sessions.owned_session(db, candidate_id, session_id, lock=True)
    if session.status == SessionStatus.IN_PROGRESS.value:
        if now <= session.expires_at:
            return None
        sessions.finalize(db, session, now, by_time=True)
    assert session.outcome is not None and session.finished_at is not None
    category = repo.category(db, candidate_id)
    own = category is not None and category.specialization_code == session.specialization_code
    expired = session.status == SessionStatus.EXPIRED.value
    level = category_level_view(category, now) if own and category is not None else None
    if level is None:
        level = level_view(
            session.theta or 0.0,
            session.se or get_config().prior_sd,
            session.target_grade,
            session.outcome,
            session.finished_at,
            session.finished_at,
            now,
            expired=expired,
        )
    evidence = db.scalars(
        select(SkillEvidenceRow)
        .where(
            SkillEvidenceRow.candidate_id == candidate_id,
            SkillEvidenceRow.specialization_code == session.specialization_code,
            SkillEvidenceRow.source == EvidenceSource.TEST.value,
        )
        .order_by(SkillEvidenceRow.group_code)
    )
    notes: list[str] = []
    if session.flags.get(sessions.FLAG_NO_LANG):
        language = (_answers(db, repo.profile(db, candidate_id)) or {}).get("main_language")
        title = survey_schema.LANGUAGE_TITLES.get(str(language), "выбранного языка")
        notes.append(f"Языковой модуль не проверялся: для {title} заданий пока нет")
    if expired:
        notes.append("Время теста вышло: незавершённый тест не подтверждает грейд")
    if session.flags.get(sessions.FLAG_PREFILLED):
        notes.append("Быстрый демо-тест: часть ответов подставлена, результат помечен как демо")
    if session.flags.get(sessions.FLAG_SPEED_SUSPECT) and not session.flags.get(sessions.FLAG_PREFILLED):
        notes.append(
            "Большинство верных ответов дано быстрее, чем обычно читается условие. На результат это не влияет: "
            "попытка отмечена, чтобы проверить задания на утечку"
        )
    if category is None:
        notes.append("Профиль публикуется после подтверждения грейда")
    return TestResultView(
        session_id=str(session.id),
        status=session.status,
        target=labels.category_ref(session.specialization_code, session.target_grade),
        outcome=TestOutcome(session.outcome),
        outcome_label=labels.outcome_label(session.outcome, session.target_grade, expired=expired),
        finished_at=session.finished_at,
        category=(
            labels.category_ref(category.specialization_code, category.grade_code, category.basis)
            if category
            else None
        ),
        level=level,
        skills=[
            ResultSkill(
                group_code=row.group_code,
                label=labels.group_title(row.group_code),
                verdict=row.verdict,
                items=row.items,
            )
            for row in evidence
        ],
        notes=notes,
        items_answered=session.items_answered,
        duration_s=max(0, int((session.finished_at - session.started_at).total_seconds())),
        next_actions=actions(db, candidate_id, now),
    )


def history(db: Session, candidate_id: UUID, now: datetime) -> list[HistoryItem]:
    """Опросы и тесты от новых к старым; верности отдельных заданий нет."""
    sessions.close_expired_for(db, candidate_id, now)
    items: list[HistoryItem] = []
    for response in db.scalars(select(SurveyResponse).where(SurveyResponse.candidate_id == candidate_id)):
        items.append(HistoryItem(kind="survey", at=response.created_at, title="Опрос"))
    for row in repo.sessions(db, candidate_id):
        grade_title = labels.grade_ref(row.target_grade).title
        finished = row.status != SessionStatus.IN_PROGRESS.value and row.finished_at is not None
        items.append(
            HistoryItem(
                kind="test",
                at=row.started_at,
                title=f"Тест на {grade_title}",
                session_id=str(row.id),
                target=labels.category_ref(row.specialization_code, row.target_grade),
                status=SessionStatus(row.status),
                outcome=TestOutcome(row.outcome) if row.outcome else None,
                outcome_label=labels.outcome_label(
                    row.outcome, row.target_grade, expired=row.status == SessionStatus.EXPIRED.value
                )
                if row.outcome
                else None,
                items=row.items_total,
                duration_s=int((row.finished_at - row.started_at).total_seconds())
                if finished and row.finished_at
                else None,
            )
        )
    return sorted(items, key=lambda item: (item.at, item.kind == "test"), reverse=True)
