"""Сессия теста в базе: старт, ответ, закрытие, применение результата (Арх. 5.5, 5.7).

Правила и формулы живут в `engine/`; здесь — чтение и запись строк и порядок шагов. Закрытие сессии
(`finalize`) — единственное место, где меняется категория: оно вызывает `engine.rules.apply_result`.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ApiException, field_error, not_found
from app.modules.assessment import blueprints, grading, labels, repo
from app.modules.assessment.config import GRADES, get_config
from app.modules.assessment.dto import TestItemView
from app.modules.assessment.engine import assemble, rules
from app.modules.assessment.engine.decide import checkpoint, decide, final_outcome
from app.modules.assessment.engine.model import Posterior, estimate
from app.modules.assessment.engine.skills import SkillAnswer, group_verdicts
from app.modules.assessment.models import (
    AssessmentProfile,
    BlueprintCounter,
    CategoryRow,
    ExposureRow,
    FamilyLevelRow,
    GradeChange,
    SessionItemRow,
    SessionRow,
    SkillEvidenceRow,
    VariantRow,
)
from app.modules.catalog import service as catalog
from app.shared.enums import (
    EvidenceSource,
    GradeChangeKind,
    ItemStatus,
    SessionStatus,
    TestOutcome,
    VariantStatus,
)

#: Пометка сессии, часть ответов которой подставлена (быстрый демо-тест и сид, Арх. 13.5).
FLAG_PREFILLED = "demo_prefilled"
#: Пометка: языковой модуль не выдан, слоты `lang` ушли в группу `code` (Арх. 5.2).
FLAG_NO_LANG = "lang_module_missing"
#: Пометка задания: ответ дан быстрее `FAST_FACTOR` расчётного времени уровня — условие за это время не прочитать.
ITEM_FLAG_FAST = "fast"
#: Пометки сессии: сколько верных ответов дано «быстро» и признак «таких большинство». На исход теста не влияют
#: (кандидату это обещано на экране перед тестом): это сигнал для разбора утечек — готовый ответ вводят быстрее,
#: чем читают условие.
FLAG_FAST_CORRECT = "fast_correct"
FLAG_SPEED_SUSPECT = "speed_suspect"
#: С какого числа быстрых верных ответов и с какой их доли среди учтённых ответов сессия помечается.
SPEED_SUSPECT_MIN = 6
SPEED_SUSPECT_SHARE = 0.6

_ANSWERED = (ItemStatus.ANSWERED.value, ItemStatus.SKIPPED.value)


# --------------------------------------------------------------------------------------------------------------------
# Контекст правил
# --------------------------------------------------------------------------------------------------------------------


def category_state(row: CategoryRow | None, specialization: str | None) -> rules.CategoryState | None:
    """Категория глазами правил: только если она в специализации опроса."""
    if row is None or row.specialization_code != specialization:
        return None
    return rules.CategoryState(
        grade=row.grade_code,
        verdict=TestOutcome(row.verdict),
        last_grade_change_at=row.last_grade_change_at,
        change_available_at=row.change_available_at,
    )


def start_context(db: Session, candidate_id: UUID) -> rules.StartContext:
    """Собрать вход `can_start` и `next_actions` из базы."""
    profile = repo.profile(db, candidate_id)
    rows = repo.sessions(db, candidate_id)
    active = next((row for row in rows if row.status == SessionStatus.IN_PROGRESS.value), None)
    specialization = profile.specialization_code if profile else None
    return rules.StartContext(
        specialization=specialization,
        claimed_grade=profile.claimed_grade if profile else None,
        category=category_state(repo.category(db, candidate_id), specialization),
        sessions=tuple(
            rules.SessionFact(
                grade=row.target_grade,
                specialization=row.specialization_code,
                started_at=row.started_at,
                finished_at=row.finished_at if row.status != SessionStatus.IN_PROGRESS.value else None,
            )
            for row in rows
        ),
        active_session_id=str(active.id) if active else None,
    )


def start_error(decision: rules.StartDecision) -> ApiException:
    """Отказ `can_start` как ошибка API: `params.session_id`, `params.reason`, `params.available_at`."""
    params: dict[str, str | int | float] = {}
    if decision.session_id:
        params["session_id"] = decision.session_id
    if decision.reason:
        params["reason"] = decision.reason
    if decision.available_at:
        params["available_at"] = decision.available_at.isoformat()
    code = decision.code or "grade_not_allowed"
    return ApiException(decision.status, code, labels.ERROR_MESSAGES.get(code), params=params or None)


def window_posterior(db: Session, candidate_id: UUID, specialization: str, now: datetime) -> Posterior:
    """Оценка уровня по всем учтённым ответам окна в специализации (Арх. 5.5)."""
    return estimate(repo.responses(repo.window_items(db, candidate_id, specialization, now)))


# --------------------------------------------------------------------------------------------------------------------
# Старт
# --------------------------------------------------------------------------------------------------------------------


def pick_variant(db: Session, candidate_id: UUID, family_id: str, level: int, seed: str) -> VariantRow:
    """Вариант для задания (Арх. 5.4): активный, не показанный этому кандидату, с наименьшим `served_count`.

    Ничья разрешается порядком `HMAC_SHA256(session.seed, variant_id)`. Строки блокируются
    `FOR UPDATE SKIP LOCKED`: два одновременных старта не получат один и тот же вариант, пока пул не исчерпан.
    """
    rows = list(
        db.scalars(
            select(VariantRow)
            .where(
                VariantRow.family_id == family_id,
                VariantRow.level == level,
                VariantRow.status == VariantStatus.ACTIVE.value,
                VariantRow.id.not_in(repo.seen_variants_subquery(candidate_id)),
            )
            .order_by(VariantRow.served_count, VariantRow.id)
            .limit(8)
            .with_for_update(skip_locked=True)
        )
    )
    if not rows:
        raise assemble.BankUnavailable(f"нет свободного варианта {family_id} L{level}")
    least = min(row.served_count for row in rows)
    key = bytes.fromhex(seed)
    chosen = min(
        (row for row in rows if row.served_count == least),
        key=lambda row: hmac.new(key, str(row.id).encode(), hashlib.sha256).digest(),
    )
    chosen.served_count += 1
    return chosen


def _add_items(
    db: Session, session: SessionRow, slots: list[assemble.FormSlot], *, first_position: int, now: datetime
) -> list[SessionItemRow]:
    cfg = get_config()
    items = []
    for offset, slot in enumerate(slots):
        variant = pick_variant(db, session.candidate_id, slot.family_id, slot.level, session.seed)
        item = SessionItemRow(
            session_id=session.id,
            position=first_position + offset,
            stage=slot.stage,
            slot_role=slot.role.value,
            slot_group=slot.slot_group,
            family_id=slot.family_id,
            level=slot.level,
            variant_id=variant.id,
            a_used=cfg.a_assumed,
            b_used=slot.b,
            c_used=float(variant.guess),
            status=ItemStatus.PENDING.value,
            flags=[],
        )
        db.add(item)
        items.append(item)
    if items:
        items[0].status = ItemStatus.SHOWN.value
        items[0].shown_at = now
    session.items_total = first_position + len(items)
    _count_exposure(db, session, [slot.family_id for slot in slots], new_session=first_position == 0)
    return items


def _count_exposure(db: Session, session: SessionRow, family_ids: list[str], *, new_session: bool) -> None:
    """Счётчики экспозиции (Арх. 5.8): сессий пары и сессий, в которых встретилось семейство."""
    pair = {"specialization_code": session.specialization_code, "grade_code": session.target_grade}
    if new_session:
        db.execute(
            insert(BlueprintCounter)
            .values(**pair, sessions_count=1)
            .on_conflict_do_update(
                index_elements=["specialization_code", "grade_code"],
                set_={"sessions_count": BlueprintCounter.sessions_count + 1},
            )
        )
    for family_id in sorted(family_ids):
        db.execute(
            insert(ExposureRow)
            .values(**pair, family_id=family_id, served_count=1)
            .on_conflict_do_update(
                index_elements=["specialization_code", "grade_code", "family_id"],
                set_={"served_count": ExposureRow.served_count + 1},
            )
        )


def create_session(
    db: Session,
    profile: AssessmentProfile,
    grade: str,
    kind: str,
    now: datetime,
    *,
    flags: Mapping[str, Any] | None = None,
) -> SessionRow:
    """Создать сессию и собрать базовую форму (Арх. 5.5, `start_session`, шаги 2–5). Право на старт уже проверено."""
    cfg = get_config()
    candidate_id, specialization = profile.candidate_id, profile.specialization_code
    families = repo.load_families(db)
    lang = profile.lang_module
    session_flags = dict(flags or {})
    if lang is not None and not blueprints.lang_module_available(families, specialization, grade, lang):
        lang = None
    if lang is None:
        session_flags[FLAG_NO_LANG] = True
    attempt_no = 1 + sum(
        1
        for row in repo.sessions(db, candidate_id)
        if row.specialization_code == specialization and row.target_grade == grade
    )
    seed = assemble.session_seed(get_settings().assessment_secret, candidate_id, specialization, grade, attempt_no)
    try:
        slots = assemble.assemble_base(
            blueprints.pool_families(families),
            seed=seed,
            specialization=specialization,
            grade=grade,
            lang=lang,
            seen=repo.seen_families(db, candidate_id, specialization, now),
            blocked=repo.blocked_levels(db, candidate_id),
        )
    except assemble.BankUnavailable as exc:
        raise ApiException(503, "bank_unavailable", "Банк заданий временно недоступен. Повторите позже") from exc
    session = SessionRow(
        candidate_id=candidate_id,
        specialization_code=specialization,
        target_grade=grade,
        lang_module=lang,
        kind=kind,
        attempt_no=attempt_no,
        seed=seed,
        status=SessionStatus.IN_PROGRESS.value,
        stage=0,
        started_at=now,
        expires_at=now + timedelta(minutes=cfg.time_limit_base_min[grade]),
        blueprint={"slots": blueprints.plan_slots(specialization, grade, lang), "lang": lang},
        flags=session_flags,
        bank_version=cfg.bank_version,
        engine_version=cfg.engine_version,
    )
    try:
        with db.begin_nested():
            db.add(session)
            db.flush()
    except IntegrityError as exc:  # частичный уникальный индекс: одна активная сессия на кандидата
        raise ApiException(409, "session_active", labels.ERROR_MESSAGES["session_active"]) from exc
    try:
        _add_items(db, session, slots, first_position=0, now=now)
    except assemble.BankUnavailable as exc:
        raise ApiException(503, "bank_unavailable", "Банк заданий временно недоступен. Повторите позже") from exc
    profile.claim_locked = True
    db.flush()
    return session


def start_session(db: Session, candidate_id: UUID, grade: str, now: datetime) -> SessionRow:
    """`POST /assessment/sessions`: проверить право (`can_start`, Арх. 5.7) и начать тест."""
    close_expired_for(db, candidate_id, now)
    ctx = start_context(db, candidate_id)
    decision = rules.can_start(ctx, grade, now)
    if not decision.ok:
        raise start_error(decision)
    profile = repo.profile(db, candidate_id)
    assert profile is not None and decision.kind is not None
    if not catalog.is_available(profile.specialization_code, grade):
        raise ApiException(422, "grade_unavailable", "Тест на этот грейд пока недоступен")
    return create_session(db, profile, grade, decision.kind.value, now)


# --------------------------------------------------------------------------------------------------------------------
# Ответ
# --------------------------------------------------------------------------------------------------------------------


def session_items(db: Session, session_id: UUID) -> list[SessionItemRow]:
    stmt = select(SessionItemRow).where(SessionItemRow.session_id == session_id).order_by(SessionItemRow.position)
    return list(db.scalars(stmt))


def owned_session(db: Session, candidate_id: UUID, session_id: str | UUID, *, lock: bool = False) -> SessionRow:
    """Сессия владельца; чужая или несуществующая — 404 (стороны эти случаи не различают)."""
    try:
        key = session_id if isinstance(session_id, UUID) else UUID(str(session_id))
    except ValueError as exc:
        raise not_found() from exc
    stmt = select(SessionRow).where(SessionRow.id == key, SessionRow.candidate_id == candidate_id)
    if lock:
        stmt = stmt.with_for_update()
    session = db.scalars(stmt).first()
    if session is None:
        raise not_found()
    return session


def submit_answer(
    db: Session,
    candidate_id: UUID,
    session_id: str,
    item_id: str,
    answer: Mapping[str, Any] | None,
    skipped: bool,
    client: Mapping[str, Any] | None,
    idempotency_key: str | None,
    now: datetime,
) -> SessionRow:
    """Принять ответ на текущее задание (Арх. 5.5, `submit_answer`). Возврата к заданию и изменения ответа нет.

    0. Сессия блокируется `FOR UPDATE`.
    1. `now > expires_at + ANSWER_GRACE_S` → закрытие по времени и 410 `session_expired`.
    2. `item_id` — не текущее задание: тот же ключ идемпотентности → текущее состояние; иначе 409.
    2а. В теле ответа нет поля своего вида задания (`grading.answer_key`) → 422 `answer_malformed`, задание
       остаётся текущим.
    3. Балл 0 при пропуске, иначе `grading.grade`; ответ, время и телеметрия сохраняются.
    4. Есть следующее задание → оно показывается.
    5. Контрольная точка: `decide(estimate(окно + сессия))`; `borderline` и `stage < MAX_EXT_BLOCKS` → добавочный
       блок и `expires_at += TIME_LIMIT_EXT_MIN[grade]`; иначе закрытие.
    """
    cfg = get_config()
    session = owned_session(db, candidate_id, session_id, lock=True)
    items = session_items(db, session.id)
    target = next((item for item in items if str(item.id) == item_id), None)
    if target is None:
        raise not_found()
    repeated = idempotency_key is not None and target.status in _ANSWERED and target.idempotency_key == idempotency_key
    if session.status != SessionStatus.IN_PROGRESS.value:
        if repeated:
            return session
        if session.status == SessionStatus.EXPIRED.value:
            raise ApiException(410, "session_expired", "Время теста вышло")
        raise ApiException(409, "session_finished", "Тест уже завершён")
    if now > session.expires_at + timedelta(seconds=cfg.answer_grace_s):
        finalize(db, session, now, by_time=True)
        # Закрытие сессии должно остаться в базе, хотя запрос завершается ошибкой.
        raise ApiException(410, "session_expired", "Время теста вышло", commit=True)
    current = next((item for item in items if item.status == ItemStatus.SHOWN.value), None)
    if current is None or current.id != target.id:
        if repeated:
            return session
        raise ApiException(409, "item_already_answered", "На это задание ответ уже принят")

    variant = db.get(VariantRow, current.variant_id)
    assert variant is not None
    if not skipped and answer is not None:
        expected = grading.answer_key(variant.payload["kind"])
        if expected not in answer:
            # Тело не того вида — сбой клиента, а не ответ: задание остаётся текущим, попытка не тратится.
            message = f"В ответе нет поля «{expected}»: обновите страницу и ответьте ещё раз"
            raise ApiException(
                422, "answer_malformed", message, fields=[field_error("answer", "answer_malformed", message)]
            )
    if skipped or answer is None:
        current.status = ItemStatus.SKIPPED.value
        current.score, current.parse_ok, current.error_tag, current.answer = 0, True, None, None
    else:
        kind = variant.payload["kind"]
        result = grading.grade(kind, variant.answer, answer, misconceptions=variant.misconception_answers)
        current.status = ItemStatus.ANSWERED.value
        current.score, current.parse_ok, current.error_tag = result.score, result.parse_ok, result.error_tag
        current.answer = dict(answer)
    current.answered_at = now
    current.idempotency_key = idempotency_key
    current.client = dict(client) if client else None
    if current.shown_at is not None:
        current.time_spent_ms_server = max(0, int((now - current.shown_at).total_seconds() * 1000))
        if current.status == ItemStatus.ANSWERED.value and _is_fast(db, current, cfg.fast_factor):
            current.flags = [*current.flags, ITEM_FLAG_FAST]
    session.items_answered += 1

    following = next((item for item in items if item.status == ItemStatus.PENDING.value), None)
    if following is not None:
        following.status, following.shown_at = ItemStatus.SHOWN.value, now
        db.flush()
        return session

    db.flush()
    post = window_posterior(db, candidate_id, session.specialization_code, now)
    if checkpoint(decide(post, session.target_grade), session.stage):
        try:
            slots = assemble.assemble_ext(
                blueprints.pool_families(repo.load_families(db)),
                seed=session.seed,
                specialization=session.specialization_code,
                grade=session.target_grade,
                lang=session.lang_module,
                stage=session.stage + 1,
                used={item.family_id for item in items},
                seen=repo.seen_families(db, candidate_id, session.specialization_code, now),
                blocked=repo.blocked_levels(db, candidate_id),
            )
            with db.begin_nested():
                _add_items(db, session, slots, first_position=len(items), now=now)
                db.flush()
        except assemble.BankUnavailable:
            # Нехватка банка для добавочного блока — тест завершается с текущим исходом (приложение A, §5.5).
            finalize(db, session, now, by_time=False)
            return session
        session.stage += 1
        session.expires_at += timedelta(minutes=cfg.time_limit_ext_min[session.target_grade])
        db.flush()
        return session
    finalize(db, session, now, by_time=False)
    return session


# --------------------------------------------------------------------------------------------------------------------
# Закрытие и применение результата
# --------------------------------------------------------------------------------------------------------------------


def _is_fast(db: Session, item: SessionItemRow, fast_factor: float) -> bool:
    """Ответ дан быстрее `fast_factor` расчётного времени уровня семейства (`assessment_family_level`)."""
    level = db.get(FamilyLevelRow, (item.family_id, item.level))
    if level is None or item.time_spent_ms_server is None:
        return False
    return item.time_spent_ms_server < fast_factor * level.time_budget_s * 1000


def speed_flags(items: list[SessionItemRow]) -> dict[str, Any]:
    """Пометки скорости сессии по её заданиям (чистая функция).

    `fast_correct` — верных ответов с пометкой `fast`; `speed_suspect` — их не меньше `SPEED_SUSPECT_MIN`
    и не меньше `SPEED_SUSPECT_SHARE` всех учтённых ответов. Пропуск («не знаю») быстрым не считается: он не
    говорит о знании ответа.
    """
    counted = [item for item in items if item.status in _ANSWERED]
    fast_correct = sum(1 for item in counted if item.score == 1 and ITEM_FLAG_FAST in (item.flags or ()))
    flags: dict[str, Any] = {}
    if fast_correct:
        flags[FLAG_FAST_CORRECT] = fast_correct
    if fast_correct >= SPEED_SUSPECT_MIN and fast_correct >= SPEED_SUSPECT_SHARE * len(counted):
        flags[FLAG_SPEED_SUSPECT] = True
    return flags


def finalize(db: Session, session: SessionRow, now: datetime, *, by_time: bool) -> None:
    """Закрыть сессию и применить результат (Арх. 5.5, `finalize`; 5.7, `apply_result`).

    Показанное без ответа задание → `unreached`, балл 0 (учитывается); непоказанные → `not_shown` (не учитываются).
    Исход считается по всем учтённым ответам окна; при непоказанных заданиях подтверждающий исход заменяется на
    `borderline`. Затем обновляются категория, вердикты по группам и теги верно решённых семейств.
    """
    items = session_items(db, session.id)
    has_not_shown = False
    for item in items:
        if item.status == ItemStatus.SHOWN.value:
            item.status, item.score = ItemStatus.UNREACHED.value, 0
        elif item.status == ItemStatus.PENDING.value:
            item.status, has_not_shown = ItemStatus.NOT_SHOWN.value, True
    finished_at = min(now, session.expires_at)
    session.status = SessionStatus.EXPIRED.value if by_time else SessionStatus.FINISHED.value
    session.finished_at = finished_at
    db.flush()

    # Окно считается от момента закрытия: ответы просроченной сессии остаются её ответами.
    counted = repo.window_items(db, session.candidate_id, session.specialization_code, finished_at)
    post = estimate(repo.responses(counted))
    decision = decide(post, session.target_grade)
    outcome = final_outcome(decision, has_not_shown=has_not_shown)
    session.outcome = outcome.value
    session.theta, session.se = post.theta, post.se
    session.p_pass, session.p_margin = decision.p_pass, decision.p_margin
    session.items_answered = sum(1 for item in items if item.status in _ANSWERED)
    session.pooled_items = post.n
    # Новый словарь, а не правка на месте: так ORM видит изменение столбца JSONB.
    session.flags = {**session.flags, **speed_flags(items)}

    row = repo.category(db, session.candidate_id)
    foreign = row is not None and row.specialization_code != session.specialization_code
    state = category_state(row, session.specialization_code)
    update = rules.apply_result(state, session.target_grade, outcome, post, finished_at)
    prefilled = bool(session.flags.get(FLAG_PREFILLED))
    ref_grade = session.target_grade
    if update is not None:
        ref_grade = update.grade
        if row is None:
            row = CategoryRow(candidate_id=session.candidate_id, assigned_at=finished_at)
            db.add(row)
        if update.created:
            row.assigned_at = finished_at
            row.is_demo_result = prefilled
        elif update.change_kind is not None:
            row.is_demo_result = prefilled
        else:
            # Обычный тест на тот же грейд снимает пометку демо-результата; подставленные ответы её сохраняют.
            row.is_demo_result = bool(row.is_demo_result) and prefilled
        row.specialization_code = session.specialization_code
        row.grade_code = update.grade
        row.verdict = update.verdict.value
        row.theta, row.se, row.items_count = post.theta, post.se, post.n
        row.level_session_id = session.id
        row.level_updated_at = finished_at
        row.last_grade_change_at = update.last_grade_change_at
        row.change_available_at = update.change_available_at
        row.last_evidence_at = finished_at
        if update.change_kind is not None:
            # Категория другой специализации заменяется только сейчас, при подтверждении грейда в новой (Арх. 5.2).
            kind = GradeChangeKind.SPECIALIZATION_CHANGE if foreign and update.created else update.change_kind
            db.add(
                GradeChange(
                    candidate_id=session.candidate_id,
                    specialization_code=session.specialization_code,
                    from_grade=update.from_grade,
                    to_grade=update.grade,
                    kind=kind.value,
                    session_id=session.id,
                    created_at=finished_at,
                )
            )
    _store_skill_evidence(db, session, counted, ref_grade, finished_at)
    db.flush()


def _store_skill_evidence(
    db: Session, session: SessionRow, counted: list[SessionItemRow], ref_grade: str, at: datetime
) -> None:
    """Пересчитать вердикты по группам по ответам окна и заменить строки `source = test` (Арх. 5.6)."""
    families = {family.id: family for family in repo.load_families(db, statuses=None)}
    answers = []
    for item in counted:
        family = families.get(item.family_id)
        group = family.group if family else item.family_id.split(".", 1)[0]
        tags = family.skill_tags if family else ()
        answers.append(SkillAnswer(group=group, b=item.b_used, score=int(item.score or 0), tags=tags))
    db.execute(
        delete(SkillEvidenceRow).where(
            SkillEvidenceRow.candidate_id == session.candidate_id,
            SkillEvidenceRow.specialization_code == session.specialization_code,
            SkillEvidenceRow.source == EvidenceSource.TEST.value,
        )
    )
    for verdict in group_verdicts(answers, ref_grade).values():
        db.add(
            SkillEvidenceRow(
                candidate_id=session.candidate_id,
                specialization_code=session.specialization_code,
                group_code=verdict.group,
                source=EvidenceSource.TEST.value,
                items=verdict.items,
                correct=verdict.correct,
                verdict=verdict.verdict.value,
                level_grade=ref_grade,
                tags_correct=list(verdict.tags_correct),
                ref_id=session.id,
                last_at=at,
            )
        )


def close_expired_for(db: Session, candidate_id: UUID, now: datetime) -> None:
    """Закрыть активную сессию кандидата, если время вышло: «первое обращение после `expires_at`» (Арх. 5.5)."""
    stmt = (
        select(SessionRow)
        .where(
            SessionRow.candidate_id == candidate_id,
            SessionRow.status == SessionStatus.IN_PROGRESS.value,
            SessionRow.expires_at < now,
        )
        .with_for_update()
    )
    for session in db.scalars(stmt):
        finalize(db, session, now, by_time=True)


def close_expired(db: Session, now: datetime) -> int:
    """Фоновое закрытие просроченных сессий; возвращает их число."""
    cutoff = now - timedelta(seconds=get_config().answer_grace_s)
    stmt = (
        select(SessionRow)
        .where(SessionRow.status == SessionStatus.IN_PROGRESS.value, SessionRow.expires_at < cutoff)
        .with_for_update(skip_locked=True)
    )
    closed = 0
    for session in db.scalars(stmt):
        finalize(db, session, now, by_time=True)
        closed += 1
    return closed


# --------------------------------------------------------------------------------------------------------------------
# Представление задания
# --------------------------------------------------------------------------------------------------------------------


def item_view(item_id: str, variant: VariantRow) -> TestItemView:
    """`TestItemView` из `assessment_variant.payload`: ответа, балла и разбора в нём нет."""
    payload = variant.payload
    return TestItemView(
        id=item_id,
        kind=payload["kind"],
        skill_label=labels.group_title(variant.family_id.split(".", 1)[0]),
        prompt=payload["prompt"],
        code=payload.get("code"),
        tables=payload.get("tables"),
        options=payload.get("options"),
        blocks=payload.get("blocks"),
        input=payload.get("input"),
    )


def current_item(db: Session, session: SessionRow) -> TestItemView | None:
    if session.status != SessionStatus.IN_PROGRESS.value:
        return None
    item = db.scalars(
        select(SessionItemRow).where(
            SessionItemRow.session_id == session.id, SessionItemRow.status == ItemStatus.SHOWN.value
        )
    ).first()
    if item is None:
        return None
    variant = db.get(VariantRow, item.variant_id)
    assert variant is not None
    return item_view(str(item.id), variant)


def progress(session: SessionRow) -> dict[str, int]:
    """`min_total` — запланировано сейчас (14, 20 или 26); `max_total` — предел, пока возможен ещё блок."""
    cfg = get_config()
    total = session.items_total
    if session.status == SessionStatus.IN_PROGRESS.value:
        maximum = total + cfg.ext_block * max(0, cfg.max_ext_blocks - session.stage)
    else:
        maximum = total
    return {"answered": session.items_answered, "min_total": total, "max_total": maximum}


__all__ = [
    "FLAG_FAST_CORRECT",
    "FLAG_NO_LANG",
    "FLAG_PREFILLED",
    "FLAG_SPEED_SUSPECT",
    "GRADES",
    "ITEM_FLAG_FAST",
    "close_expired",
    "close_expired_for",
    "create_session",
    "current_item",
    "finalize",
    "item_view",
    "owned_session",
    "progress",
    "start_context",
    "start_session",
    "submit_answer",
    "window_posterior",
]
