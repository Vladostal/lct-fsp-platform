"""Сессия теста в базе: старт, ответы, добавочные блоки, истечение, применение результата (Арх. 5.5, 5.7)."""

# ruff: noqa: E501 — подписи отчёта и длинные проверки читаются лучше в одну строку

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ApiException
from app.modules.assessment import admin, candidate, grading, repo, seeding, service, sessions
from app.modules.assessment.config import get_config
from app.modules.assessment.dto import SeedItem, SeedResult, SeedSession
from app.modules.assessment.models import (
    BlueprintCounter,
    CategoryRow,
    ExposureRow,
    GradeChange,
    SessionItemRow,
    SessionRow,
    SkillEvidenceRow,
    VariantRow,
)
from app.shared.enums import EvidenceSource, ItemStatus, SessionStatus, TestOutcome
from tests.assessment.conftest import T0

pytestmark = pytest.mark.usefixtures("bank")


def play(db: Session, user: Any, session: SessionRow, decide: Callable[[int, SessionItemRow], bool], now=T0, limit: int = 99) -> SessionRow:
    """Отвечать на задания по порядку: `decide(номер, задание)` — верно или «не знаю»."""
    for n in range(limit):
        if session.status != SessionStatus.IN_PROGRESS.value:
            break
        item = next(i for i in sessions.session_items(db, session.id) if i.status == ItemStatus.SHOWN.value)
        variant = db.get(VariantRow, item.variant_id)
        right = decide(n, item)
        session = sessions.submit_answer(
            db, user.id, str(session.id), str(item.id), seeding.correct_raw(variant) if right else None, not right, None, f"k{n}", now
        )
    return session


def test_start_builds_form(db: Session, candidate_ready: Callable[..., Any]) -> None:
    user = candidate_ready("middle")
    session = sessions.start_session(db, user.id, "middle", T0)
    items = sessions.session_items(db, session.id)
    cfg = get_config()
    assert len(items) == cfg.items_min == session.items_total
    assert len({item.family_id for item in items}) == len(items)
    assert [item.status for item in items] == ["shown"] + ["pending"] * 13
    assert session.expires_at == T0 + timedelta(minutes=cfg.time_limit_base_min["middle"])
    assert session.kind == "initial" and session.lang_module == "py" and session.attempt_no == 1
    assert all(item.a_used == 1.0 and -0.5 <= item.b_used <= 1.5 for item in items)
    assert repo.profile(db, user.id).claim_locked is True
    served = db.scalars(select(VariantRow).where(VariantRow.id.in_([i.variant_id for i in items]))).all()
    assert all(v.served_count == 1 and v.status == "active" for v in served)
    counter = db.get(BlueprintCounter, ("backend", "middle"))
    assert counter.sessions_count == 1
    exposure = db.scalars(select(ExposureRow).where(ExposureRow.grade_code == "middle")).all()
    assert {row.family_id for row in exposure} == {item.family_id for item in items}
    view = candidate.session_view(db, session, T0)
    assert view.item is not None and view.item.id == str(items[0].id)
    assert (view.progress.answered, view.progress.min_total, view.progress.max_total) == (0, 14, 26)


def test_two_candidates_get_different_variants(db: Session, candidate_ready: Callable[..., Any]) -> None:
    first = sessions.start_session(db, candidate_ready("middle").id, "middle", T0)
    second = sessions.start_session(db, candidate_ready("middle").id, "middle", T0)
    a = {item.variant_id for item in sessions.session_items(db, first.id)}
    b = {item.variant_id for item in sessions.session_items(db, second.id)}
    assert not a & b


def test_one_active_session(db: Session, candidate_ready: Callable[..., Any]) -> None:
    user = candidate_ready("middle")
    session = sessions.start_session(db, user.id, "middle", T0)
    with pytest.raises(ApiException) as error:
        sessions.start_session(db, user.id, "middle", T0 + timedelta(minutes=1))
    assert (error.value.status, error.value.code, error.value.params) == (409, "session_active", {"session_id": str(session.id)})
    # Частичный уникальный индекс: вторую активную строку не даст вставить и сама база.
    clone = SessionRow(
        candidate_id=user.id, specialization_code="backend", target_grade="middle", kind="retake", attempt_no=2,
        seed="00", status="in_progress", stage=0, started_at=T0, expires_at=T0, blueprint={}, flags={},
        bank_version="x", engine_version="x",
    )  # fmt: skip
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(clone)
        db.flush()


def test_all_correct_confirms_with_margin_and_creates_category(db: Session, candidate_ready: Callable[..., Any]) -> None:
    user = candidate_ready("middle")
    session = play(db, user, sessions.start_session(db, user.id, "middle", T0), lambda n, item: True, T0 + timedelta(minutes=20))
    assert session.status == "finished" and session.outcome == TestOutcome.CONFIRMED_WITH_MARGIN.value
    assert session.items_total == 14 and session.items_answered == 14 and session.pooled_items == 14
    category = db.get(CategoryRow, user.id)
    assert (category.specialization_code, category.grade_code, category.verdict) == ("backend", "middle", "confirmed_with_margin")
    assert category.last_grade_change_at is None and category.is_demo_result is False
    assert category.change_available_at == session.finished_at + timedelta(days=90)
    change = db.scalars(select(GradeChange).where(GradeChange.candidate_id == user.id)).one()
    assert (change.kind, change.from_grade, change.to_grade, change.session_id) == ("initial", None, "middle", session.id)

    dto = service.get_category(db, user.id)
    assert dto.category_code == "backend:middle" and dto.level_session_id == session.id and not dto.is_demo_result
    assert service.get_categories(db, [user.id, uuid4()]).keys() == {user.id}
    (level,) = service.get_levels(db, specialization_code="backend", grade_codes=["middle"], now=T0 + timedelta(days=1))
    assert level.candidate_id == user.id and level.cut == 0.0 and level.cut_next == 1.5 and level.width == 1.5
    assert level.se_eff >= level.se and level.age_days == 0 and not level.stale
    assert service.get_levels(db, specialization_code="frontend", now=T0) == []
    view = service.level_views(db, [user.id], T0 + timedelta(days=1))[user.id]
    assert view.lower < view.point <= view.upper and [t.pos for t in view.thresholds] == [25.0, 50.0, 75.0]
    assert view.verdict_label == "Грейд Middle подтверждён с запасом"
    declared = service.survey_declared(db, [user.id])[user.id]
    assert (declared.direction, declared.main_language, declared.industry_domains) == ("development", "python", ["fintech"])

    # Быстрый шаг вверх открыт сразу: подтверждён заявленный грейд с запасом.
    state = candidate.state_view(db, user.id, T0 + timedelta(hours=1))
    actions = {a.kind: a for a in state.next_actions}
    assert actions["take_higher"].available and not actions["retake_same"].available
    assert actions["retake_same"].reason == "retry_same_grade" and actions["take_lower"].reason == "grade_change"
    assert state.category.code == "backend:middle" and state.level is not None and state.last_session.outcome == "confirmed_with_margin"

    result = candidate.result_view(db, user.id, str(session.id), T0 + timedelta(hours=1))
    assert result.outcome_label == "Грейд Middle подтверждён с запасом" and result.category.code == "backend:middle"
    assert result.skills and all(s.items >= 1 for s in result.skills)

    # Доказательства по навыкам: только навыки с тегом решённого задания; full — у подтверждённых групп.
    rows = {r.group_code: r for r in db.scalars(select(SkillEvidenceRow).where(SkillEvidenceRow.candidate_id == user.id))}
    evidence = service.skill_evidence(db, [user.id])[user.id]
    assert evidence and all(e.source is EvidenceSource.TEST for e in evidence)
    for item in evidence:
        row = rows[item.group_code]
        assert item.skill_code in row.tags_correct
        assert item.full == (row.verdict == "confirmed") and item.ref_id == session.id
        assert "решено задание уровня Middle" in item.detail


def test_all_skipped_not_confirmed_and_lower_grade_opens(db: Session, candidate_ready: Callable[..., Any]) -> None:
    user = candidate_ready("middle")
    session = play(db, user, sessions.start_session(db, user.id, "middle", T0), lambda n, item: False)
    assert session.outcome == "not_confirmed" and db.get(CategoryRow, user.id) is None
    assert service.get_category(db, user.id) is None and service.skill_evidence(db, [user.id]) == {user.id: []}
    state = candidate.state_view(db, user.id, T0 + timedelta(hours=1))
    assert [(a.kind, a.grade.code, a.available) for a in state.next_actions] == [
        ("take_lower", "junior", True),
        ("retake_same", "middle", False),
    ]
    lower = sessions.start_session(db, user.id, "junior", T0 + timedelta(hours=2))
    assert lower.kind == "lower"
    # Семейства прошлой сессии выбираются в последнюю очередь.
    seen = {i.family_id for i in sessions.session_items(db, session.id)}
    fresh = {i.family_id for i in sessions.session_items(db, lower.id)}
    assert len(seen & fresh) <= 6
    result = candidate.result_view(db, user.id, str(session.id), T0 + timedelta(hours=3))
    assert "Профиль публикуется после подтверждения грейда" in result.notes and result.category is None


def test_borderline_adds_blocks_up_to_limit(db: Session, candidate_ready: Callable[..., Any]) -> None:
    user = candidate_ready("middle")
    session = sessions.start_session(db, user.id, "middle", T0)
    base_expiry = session.expires_at
    # Около половины верных на сложности порога — исход остаётся на границе.
    session = play(db, user, session, lambda n, item: n % 2 == 0)
    cfg = get_config()
    assert session.stage >= 1 and session.items_total in (20, 26)
    assert session.expires_at == base_expiry + timedelta(minutes=cfg.time_limit_ext_min["middle"] * session.stage)
    items = sessions.session_items(db, session.id)
    assert len({i.family_id for i in items}) == len(items) == session.items_total
    assert [i.position for i in items] == list(range(len(items)))
    assert all(i.slot_role == "ext" and i.slot_group is None for i in items[14:])
    assert session.status == "finished" and session.stage <= cfg.max_ext_blocks


def test_idempotent_answer(db: Session, candidate_ready: Callable[..., Any]) -> None:
    user = candidate_ready("middle")
    session = sessions.start_session(db, user.id, "middle", T0)
    first = sessions.session_items(db, session.id)[0]
    # Тело своего вида задания: с чужим полем сессия ответит 422 `answer_malformed` и задание не примет.
    field = grading.answer_key(db.get(VariantRow, first.variant_id).payload["kind"])
    args = (db, user.id, str(session.id), str(first.id), {field: "1"}, False, None)
    sessions.submit_answer(*args, "key-1", T0)
    snapshot = (first.status, first.score, first.answer, session.items_answered)
    # Повтор того же запроса с тем же ключом: текущее состояние, ничего не меняется.
    again = sessions.submit_answer(*args, "key-1", T0 + timedelta(seconds=3))
    assert again.id == session.id and (first.status, first.score, first.answer, session.items_answered) == snapshot
    assert candidate.answer_result(db, again, T0).next_item.id == str(sessions.session_items(db, session.id)[1].id)
    for key in ("key-2", None):
        with pytest.raises(ApiException) as error:
            sessions.submit_answer(db, user.id, str(session.id), str(first.id), {field: "2"}, False, None, key, T0)
        assert (error.value.status, error.value.code) == (409, "item_already_answered")
    # Ответ не на текущее, а на будущее задание тоже отклоняется.
    third = sessions.session_items(db, session.id)[2]
    with pytest.raises(ApiException) as error:
        sessions.submit_answer(db, user.id, str(session.id), str(third.id), None, True, None, "key-9", T0)
    assert error.value.code == "item_already_answered"
    with pytest.raises(ApiException) as error:
        sessions.submit_answer(db, uuid4(), str(session.id), str(first.id), None, True, None, None, T0)
    assert error.value.status == 404


def test_expired_session_unfinished_stage_is_borderline(db: Session, candidate_ready: Callable[..., Any]) -> None:
    """12 верных из 14, время вышло: показанное задание — `unreached` (0), непоказанное — `not_shown`;
    незавершённый тест грейд не подтверждает, хотя `p_pass` высок."""
    user = candidate_ready("middle")
    session = play(db, user, sessions.start_session(db, user.id, "middle", T0), lambda n, item: True, limit=12)
    late = session.expires_at + timedelta(seconds=get_config().answer_grace_s + 1)
    current = next(i for i in sessions.session_items(db, session.id) if i.status == "shown")
    with pytest.raises(ApiException) as error:
        sessions.submit_answer(db, user.id, str(session.id), str(current.id), None, True, None, "late", late)
    assert (error.value.status, error.value.code, error.value.commit) == (410, "session_expired", True)
    assert session.status == "expired" and session.finished_at == session.expires_at
    statuses = [i.status for i in sessions.session_items(db, session.id)]
    assert statuses == ["answered"] * 12 + ["unreached", "not_shown"]
    assert session.p_pass >= 0.8 and session.outcome == "borderline"
    assert session.pooled_items == 13 and db.get(CategoryRow, user.id) is None
    with pytest.raises(ApiException) as error:
        sessions.submit_answer(db, user.id, str(session.id), str(current.id), None, True, None, "later", late)
    assert error.value.status == 410
    result = candidate.result_view(db, user.id, str(session.id), late)
    assert result.status == "expired" and any("Время теста вышло" in note for note in result.notes)
    # Исход хранится как `borderline`, но подпись называет причину прямо, а не «результат на границе».
    assert result.outcome == "borderline" and result.outcome_label == "Время вышло: грейд Middle не подтверждён"
    assert result.level.verdict_label == result.outcome_label


def test_answer_within_grace_is_accepted_and_get_closes(db: Session, candidate_ready: Callable[..., Any]) -> None:
    user = candidate_ready("middle")
    session = sessions.start_session(db, user.id, "middle", T0)
    first = sessions.session_items(db, session.id)[0]
    sessions.submit_answer(db, user.id, str(session.id), str(first.id), None, True, None, "k", session.expires_at + timedelta(seconds=4))
    assert first.status == "skipped" and session.status == "in_progress"
    view = candidate.get_session(db, user.id, str(session.id), session.expires_at + timedelta(seconds=1))
    assert view.status == "expired" and view.item is None and view.progress.max_total == 14


def test_background_close_and_finished_session_error(db: Session, candidate_ready: Callable[..., Any]) -> None:
    user = candidate_ready("middle")
    session = sessions.start_session(db, user.id, "middle", T0)
    assert service.close_expired_sessions(db, T0 + timedelta(minutes=5)) == 0
    assert service.close_expired_sessions(db, session.expires_at + timedelta(minutes=1)) == 1
    assert session.status == "expired" and session.outcome is not None
    # Ни одного ответа: в результате и в истории — «время вышло», а не оценка «на границе».
    closed_at = session.expires_at + timedelta(minutes=2)
    assert candidate.result_view(db, user.id, str(session.id), closed_at).outcome_label.startswith("Время вышло")
    row = next(h for h in candidate.history(db, user.id, closed_at) if h.session_id == str(session.id))
    assert row.outcome_label == "Время вышло: грейд Middle не подтверждён"
    other = candidate_ready("junior")
    done = play(db, other, sessions.start_session(db, other.id, "junior", T0), lambda n, item: True)
    last = sessions.session_items(db, done.id)[-1]
    with pytest.raises(ApiException) as error:
        sessions.submit_answer(db, other.id, str(done.id), str(last.id), None, True, None, "another", T0)
    assert (error.value.status, error.value.code) == (409, "session_finished")
    assert sessions.submit_answer(db, other.id, str(done.id), str(last.id), None, True, None, last.idempotency_key, T0) is done


def test_weak_retake_keeps_grade(db: Session, candidate_ready: Callable[..., Any]) -> None:
    """Грейд не понижается автоматически: повтор с худшим результатом меняет только вердикт (Арх. 5.7)."""
    user = candidate_ready("middle")
    first = play(db, user, sessions.start_session(db, user.id, "middle", T0), lambda n, item: n < 11)
    assert first.outcome in ("confirmed", "confirmed_with_margin")
    later = T0 + timedelta(days=20)
    second = play(db, user, sessions.start_session(db, user.id, "middle", later), lambda n, item: False, later)
    category = db.get(CategoryRow, user.id)
    assert second.kind == "retake" and category.grade_code == "middle" and category.last_grade_change_at is None
    assert category.verdict in ("borderline", "not_confirmed") and category.level_session_id == second.id
    assert category.items_count == second.pooled_items == first.items_total + second.items_total
    assert len(db.scalars(select(GradeChange).where(GradeChange.candidate_id == user.id)).all()) == 1


def test_fast_step_up_then_cooldown(db: Session, candidate_ready: Callable[..., Any]) -> None:
    user = candidate_ready("junior")
    play(db, user, sessions.start_session(db, user.id, "junior", T0), lambda n, item: True)
    assert db.get(CategoryRow, user.id).verdict == "confirmed_with_margin"
    when = T0 + timedelta(hours=1)
    higher = play(db, user, sessions.start_session(db, user.id, "middle", when), lambda n, item: True, when)
    category = db.get(CategoryRow, user.id)
    assert higher.kind == "higher" and category.grade_code == "middle" and category.last_grade_change_at == higher.finished_at
    kinds = [c.kind for c in db.scalars(select(GradeChange).where(GradeChange.candidate_id == user.id).order_by(GradeChange.created_at))]
    assert kinds == ["initial", "up"]
    # После смены грейда следующий шаг — только через 90 дней, даже при запасе.
    with pytest.raises(ApiException) as error:
        sessions.start_session(db, user.id, "senior", when + timedelta(days=40))
    assert error.value.params["reason"] == "grade_change"


def test_pulse_support(db: Session, candidate_ready: Callable[..., Any]) -> None:
    """Короткое задание не меняет грейд и уровень; при `not_confirmed` группы строка `pulse` не создаётся."""
    user = candidate_ready("middle")
    # Группа sql решена, группа git провалена, остальное верно.
    session = play(db, user, sessions.start_session(db, user.id, "middle", T0), lambda n, item: not item.family_id.startswith("git."))
    category = db.get(CategoryRow, user.id)
    before = (category.grade_code, category.verdict, category.theta, category.se, category.last_evidence_at)
    rows = {r.group_code: r for r in db.scalars(select(SkillEvidenceRow).where(SkillEvidenceRow.candidate_id == user.id))}
    assert rows["git"].verdict == "not_confirmed"

    assert service.group_for_skill("python", "backend", "middle") == "py"
    assert service.group_for_skill("sql_joins", "backend", "middle") == "sql"
    assert service.group_for_skill("postgresql", "backend", "middle") is None  # только related
    assert service.group_for_skill("css", "backend", "middle") is None  # группа не этой специализации
    assert service.group_for_skill("docker", "backend", "middle") is None

    when = T0 + timedelta(days=45)
    item = service.pick_pulse_item(db, user.id, "sql", when)
    assert item.group_code == "sql" and item.family_id.startswith("sql.") and item.item.kind in ("numeric_input", "text_input")
    assert item.variant_id not in {i.variant_id for i in sessions.session_items(db, session.id)}
    variant = db.get(VariantRow, item.variant_id)
    assert service.grade_pulse_answer(db, item.variant_id, seeding.correct_raw(variant)).score == 1
    assert service.grade_pulse_answer(db, item.variant_id, {"value": "не число"}).score == 0

    assignment = uuid4()
    service.record_pulse_result(db, user.id, "git", True, assignment, when, family_id="git.log_reach")
    assert db.get(SkillEvidenceRow, (user.id, "backend", "git", "pulse")) is None  # группа провалена тестом
    assert category.last_evidence_at == T0 + timedelta(days=30)  # свежесть засчитана: +PULSE_CREDIT_DAYS

    service.record_pulse_result(db, user.id, "sql", False, assignment, when, family_id=item.family_id)
    assert db.get(SkillEvidenceRow, (user.id, "backend", "sql", "pulse")) is None  # неверный ответ — без последствий
    service.record_pulse_result(db, user.id, "sql", True, assignment, when, family_id=item.family_id)
    pulse = db.get(SkillEvidenceRow, (user.id, "backend", "sql", "pulse"))
    assert pulse.ref_id == assignment and set(pulse.tags_correct) == set(item.skill_tags)
    found = [e for e in service.skill_evidence(db, [user.id])[user.id] if e.source is EvidenceSource.PULSE]
    assert found and all(not e.full and e.group_code == "sql" for e in found)
    # Свежесть — не дальше 90 дней после теста; категория и уровень не изменились.
    for _ in range(3):
        service.record_pulse_result(db, user.id, "sql", True, assignment, T0 + timedelta(days=300), family_id=item.family_id)
    assert category.last_evidence_at == category.level_updated_at + timedelta(days=90)
    assert (category.grade_code, category.verdict, category.theta, category.se) == before[:4]


def test_seed_result_runs_real_engine(db: Session, make_user: Callable[..., Any]) -> None:
    user = make_user("candidate")
    from app.modules.assessment import blueprints
    from app.modules.assessment.engine import assemble

    families = repo.load_families(db)
    slots = assemble.assemble_base(
        blueprints.pool_families(families), seed="ab" * 32, specialization="backend", grade="senior", lang="py"
    )
    items = [SeedItem(family_id=s.family_id, level=s.level, score=1, role=s.role, slot_group=s.slot_group) for s in slots]
    result = SeedResult(
        candidate_id=user.id,
        specialization_code="backend",
        grade_code="senior",
        main_language="python",
        industry_domains=["gamedev"],
        sessions=[SeedSession(grade_code="senior", started_at=T0 - timedelta(days=9), finished_at=T0 - timedelta(days=9) + timedelta(minutes=40), items=items)],
    )
    served_before = sum(v.served_count for v in db.scalars(select(VariantRow)))
    service.seed_result(db, result)
    service.seed_result(db, result)  # повторный вызов ничего не меняет
    assert len(repo.sessions(db, user.id)) == 1
    category = service.get_category(db, user.id)
    assert category.category_code == "backend:senior" and category.verdict is TestOutcome.CONFIRMED_WITH_MARGIN
    assert service.skill_evidence(db, [user.id])[user.id]
    assert service.survey_declared(db, [user.id])[user.id].industry_domains == ["gamedev"]
    assert sum(v.served_count for v in db.scalars(select(VariantRow))) == served_before  # запас вариантов не тратится
    (level,) = service.get_levels(db, candidate_ids=[user.id], now=T0)
    assert level.age_days == 8 and level.tested_at == T0 - timedelta(days=9) + timedelta(minutes=40)


def test_seed_session_in_progress_marks_demo_result(db: Session, make_user: Callable[..., Any], candidate_ready: Callable[..., Any]) -> None:
    nina = make_user("candidate")
    session_id = service.seed_session_in_progress(db, nina.id, "middle", 12, T0)
    session = db.get(SessionRow, session_id)
    items = sessions.session_items(db, session_id)
    assert session.status == "in_progress" and session.items_answered == 12
    assert [i.status for i in items] == ["answered"] * 12 + ["shown", "pending"]
    assert all(i.score == 1 for i in items[:12])
    # Исход не зависит от двух последних ответов: и с двумя пропусками грейд подтверждён.
    done = play(db, nina, session, lambda n, item: False)
    assert done.outcome in ("confirmed", "confirmed_with_margin")
    assert service.get_category(db, nina.id).is_demo_result is True
    # Быстрый демо-тест живого кандидата подчиняется can_start.
    user = candidate_ready("junior")
    service.seed_session_in_progress(db, user.id, "junior", 12, T0)
    with pytest.raises(ApiException) as error:
        service.seed_session_in_progress(db, user.id, "junior", 12, T0)
    assert error.value.code == "session_active"
    with pytest.raises(ApiException) as error:
        service.seed_session_in_progress(db, candidate_ready("junior").id, "senior", 12, T0)
    assert error.value.code == "grade_not_allowed"


# --------------------------------------------------------------------------------------------------------------------
# Пометки скорости: сигнал утечки, на исход не влияют
# --------------------------------------------------------------------------------------------------------------------


def play_timed(db: Session, user: Any, session: SessionRow, seconds: int) -> SessionRow:
    """Отвечать верно, тратя на каждое задание `seconds` секунд по часам сервера."""
    now = T0
    for n in range(99):
        if session.status != SessionStatus.IN_PROGRESS.value:
            break
        item = next(i for i in sessions.session_items(db, session.id) if i.status == ItemStatus.SHOWN.value)
        now = now + timedelta(seconds=seconds)
        variant = db.get(VariantRow, item.variant_id)
        session = sessions.submit_answer(db, user.id, str(session.id), str(item.id), seeding.correct_raw(variant), False, None, f"t{n}", now)
    return session


def test_instant_correct_answers_are_flagged_but_outcome_is_the_same(db: Session, candidate_ready: Callable[..., Any]) -> None:
    """Верные ответы за секунду: задания помечены `fast`, сессия — `speed_suspect`, исход тот же, что у обычной."""
    fast_user, slow_user = candidate_ready("junior"), candidate_ready("junior")
    fast = play_timed(db, fast_user, sessions.start_session(db, fast_user.id, "junior", T0), seconds=1)
    slow = play_timed(db, slow_user, sessions.start_session(db, slow_user.id, "junior", T0), seconds=60)

    fast_items = sessions.session_items(db, fast.id)
    assert all(item.flags == [sessions.ITEM_FLAG_FAST] for item in fast_items if item.status == "answered")
    assert fast.flags[sessions.FLAG_FAST_CORRECT] == fast.items_answered
    assert fast.flags[sessions.FLAG_SPEED_SUSPECT] is True
    assert all(item.flags == [] for item in sessions.session_items(db, slow.id))
    assert sessions.FLAG_SPEED_SUSPECT not in slow.flags and sessions.FLAG_FAST_CORRECT not in slow.flags

    # На результат пометка не влияет: это обещано кандидату перед тестом.
    assert fast.outcome == slow.outcome and fast.outcome in ("confirmed", "confirmed_with_margin")
    assert db.get(CategoryRow, fast_user.id) is not None
    fast_notes = candidate.result_view(db, fast_user.id, str(fast.id), T0 + timedelta(hours=1)).notes
    slow_notes = candidate.result_view(db, slow_user.id, str(slow.id), T0 + timedelta(hours=1)).notes
    assert any("быстрее" in note and "не влияет" in note for note in fast_notes)
    assert not any("быстрее" in note for note in slow_notes)

    # Служебная сводка банка показывает долю «быстрых» верных ответов по семействам.
    health = {row.id: row for row in admin.bank_health(db).families}
    touched = {item.family_id for item in fast_items}
    assert all(health[family].fast_correct_share is not None and 0 < health[family].fast_correct_share <= 1 for family in touched)


def test_skips_are_not_fast_answers(db: Session, candidate_ready: Callable[..., Any]) -> None:
    """«Не знаю» за секунду — не признак готового ответа: пометок нет."""
    user = candidate_ready("junior")
    session = play(db, user, sessions.start_session(db, user.id, "junior", T0), lambda n, item: False)
    assert all(item.flags == [] for item in sessions.session_items(db, session.id))
    assert sessions.FLAG_SPEED_SUSPECT not in session.flags


def test_malformed_answer_body_is_rejected_and_keeps_the_item(db: Session, candidate_ready: Callable[..., Any]) -> None:
    """Тело без поля своего вида задания — сбой клиента: 422, задание не потрачено. Неразборчивое значение — ответ."""
    user = candidate_ready("junior")
    session = sessions.start_session(db, user.id, "junior", T0)
    first = sessions.session_items(db, session.id)[0]
    with pytest.raises(ApiException) as error:
        sessions.submit_answer(db, user.id, str(session.id), str(first.id), {"foo": 1}, False, None, "bad", T0)
    assert (error.value.status, error.value.code) == (422, "answer_malformed")
    assert error.value.fields and error.value.fields[0].name == "answer"
    db.refresh(first)
    assert first.status == "shown" and first.answer is None and session.items_answered == 0

    # То же задание принимает ответ нужного вида; заведомо неразборчивое значение — это уже ответ (балл 0).
    variant = db.get(VariantRow, first.variant_id)
    body = {grading.answer_key(variant.payload["kind"]): "не число и не вариант"}
    sessions.submit_answer(db, user.id, str(session.id), str(first.id), body, False, None, "ok", T0)
    assert first.status == "answered" and first.score == 0 and session.items_answered == 1


QA_SURVEY = {"direction": "quality_infra", "specialization": "qa", "main_language": "other", "experience_band": "2_4"}


def test_declared_replaces_and_is_replaced_by_test(db: Session, candidate_ready: Callable[..., Any]) -> None:
    """Подтверждённая категория → специализация без теста (через подтверждение) → обратно в тест: `basis` следует за фактом."""
    user = candidate_ready("junior")
    version = get_config().survey_version
    done = play(db, user, sessions.start_session(db, user.id, "junior", T0), lambda n, item: True)
    tested = repo.category(db, user.id)
    assert tested is not None and tested.basis == "test" and tested.level_session_id == done.id
    changes = db.scalar(select(func.count()).select_from(GradeChange).where(GradeChange.candidate_id == user.id))

    later = T0 + timedelta(days=1)
    with pytest.raises(Exception) as error:
        candidate.put_survey(db, user.id, version, QA_SURVEY, False, later)
    assert error.value.code == "specialization_change_requires_confirm"
    assert error.value.params == {"target_has_test": False, "replaces_confirmed_category": True}
    assert "заявленным грейдом" in error.value.message
    candidate.put_survey(db, user.id, version, QA_SURVEY, True, later)
    state = candidate.state_view(db, user.id, later)
    # До заявления грейда в новой специализации действует прежняя подтверждённая категория.
    assert state.category.code == "backend:junior" and state.category.basis == "test" and state.next_actions == []
    state = candidate.put_claim(db, user.id, "middle", later)
    assert (state.category.code, state.category.basis, state.level) == ("qa:middle", "declared", None)
    row = repo.category(db, user.id)
    db.refresh(row)
    assert (row.verdict, row.theta, row.se, row.items_count, row.level_session_id, row.level_updated_at, row.last_evidence_at) == (None,) * 7
    # История смен грейда не удаляется и для заявленной категории не пополняется.
    assert db.scalar(select(func.count()).select_from(GradeChange).where(GradeChange.candidate_id == user.id)) == changes
    assert service.level_views(db, [user.id], later) == {}

    # Уход из заявленной категории тоже требует подтверждения; тест в новой специализации делает строку подтверждённой.
    back = {"direction": "development", "specialization": "frontend", "main_language": "typescript", "experience_band": "lt1"}
    much_later = later + timedelta(days=100)
    with pytest.raises(Exception) as error:
        candidate.put_survey(db, user.id, version, back, False, much_later)
    assert error.value.code == "specialization_change_requires_confirm" and error.value.params["replaces_confirmed_category"] is False
    candidate.put_survey(db, user.id, version, back, True, much_later)
    candidate.put_claim(db, user.id, "junior", much_later)
    assert repo.category(db, user.id).basis == "declared"  # qa:middle остаётся до результата теста
    front = play(db, user, sessions.start_session(db, user.id, "junior", much_later), lambda n, item: True, now=much_later)
    state = candidate.state_view(db, user.id, much_later)
    assert (state.category.code, state.category.basis) == ("frontend:junior", "test")
    assert state.level is not None and state.category.level_session_id == str(front.id)
    result = candidate.result_view(db, user.id, str(front.id), much_later)
    assert result is not None and result.category.basis == "test"
    (level,) = service.get_levels(db, candidate_ids=[user.id], now=much_later)
    assert level.basis == "test" and level.theta is not None and level.age_days == 0
