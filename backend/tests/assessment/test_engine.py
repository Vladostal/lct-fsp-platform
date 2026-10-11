"""Чистое ядро: оценка, решение, сборка формы, правила грейда, вердикты по навыкам (Арх. 5.4–5.7)."""

# ruff: noqa: E501 — подписи отчёта и длинные проверки читаются лучше в одну строку

from __future__ import annotations

import inspect
import itertools
import pkgutil
import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.modules.assessment import blueprints, engine
from app.modules.assessment.config import GRADES, get_config
from app.modules.assessment.engine import assemble, decide, level, model, rules, skills
from app.modules.assessment.engine.model import Response, estimate
from app.modules.assessment.engine.rules import CategoryState, SessionFact, StartContext, apply_result, can_start
from app.modules.assessment.families.registry import REGISTRY
from app.modules.assessment.groups import SKILL_GROUP_MAP, SPECIALIZATIONS
from app.shared.enums import GradeChangeKind, SessionKind, SkillVerdict, TestOutcome
from tests.assessment.fake_families._bank import fake_bank

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
DAY = timedelta(days=1)
DIRECT = {group: item.direct for group, item in SKILL_GROUP_MAP.items()}


# --- границы ядра ----------------------------------------------------------------------------------------------------


def test_engine_does_not_import_sqlalchemy() -> None:
    root = Path(engine.__file__).parent
    for path in root.glob("*.py"):
        assert "sqlalchemy" not in path.read_text(encoding="utf-8"), path.name


def test_engine_functions_have_docstrings_with_rule_and_section() -> None:
    """У функций `engine/`, `can_start`, `apply_result` есть docstring с правилом и номером раздела Арх."""
    missing = []
    for info in pkgutil.iter_modules(engine.__path__):
        module = __import__(f"{engine.__name__}.{info.name}", fromlist=["x"])
        assert module.__doc__ and "Арх. 5" in module.__doc__, info.name
        for name, obj in vars(module).items():
            public = inspect.isfunction(obj) and obj.__module__ == module.__name__ and not name.startswith("_")
            if public and not (obj.__doc__ or "").strip():
                missing.append(f"{info.name}.{name}")
    assert not missing, missing
    for fn in (can_start, apply_result, decide.decide, model.estimate, skills.skill_proofs, assemble.assemble_base):
        assert "Арх. 5" in (fn.__doc__ or ""), fn.__name__


# --- оценка и решение ------------------------------------------------------------------------------------------------


def test_estimate_prior_without_answers() -> None:
    post = estimate([])
    assert post.n == 0 and abs(post.theta) < 1e-6
    assert len(post.points) == 161 and post.points[0] == -4.0 and post.points[-1] == 4.0
    assert abs(sum(post.weights) - 1) < 1e-9


def test_estimate_is_monotone() -> None:
    """Замена неверного ответа верным не уменьшает ни `theta`, ни `p_ge(t)` (приложение A, §10.5)."""
    rng = random.Random(7)
    for _ in range(200):
        answers = [
            Response(b=rng.choice([-2, -1.5, -1, -0.5, 0, 0.5, 1, 1.5, 2]), c=rng.choice([0, 0.25, 0.03]), score=rng.randint(0, 1))
            for _ in range(rng.randint(1, 26))
        ]
        wrong = [i for i, r in enumerate(answers) if r.score == 0]
        if not wrong:
            continue
        i = rng.choice(wrong)
        better = [*answers[:i], Response(answers[i].b, answers[i].c, 1), *answers[i + 1 :]]
        before, after = estimate(answers), estimate(better)
        assert after.theta >= before.theta - 1e-12
        for cut in (-1.5, -0.75, 0.0, 0.75, 1.5, 2.25):
            assert after.p_ge(cut) >= before.p_ge(cut) - 1e-12


def test_decide_four_outcomes() -> None:
    def outcome(right: int, wrong: int, grade: str = "middle") -> TestOutcome:
        answers = [Response(0.0, 0.0, 1)] * right + [Response(0.0, 0.0, 0)] * wrong
        return decide.decide(estimate(answers), grade).outcome

    assert outcome(14, 0) is TestOutcome.CONFIRMED_WITH_MARGIN
    assert outcome(0, 14) is TestOutcome.NOT_CONFIRMED
    assert outcome(7, 7) is TestOutcome.BORDERLINE
    seen = {outcome(right, 14 - right) for right in range(15)}
    assert seen == set(TestOutcome)


def test_checkpoint_and_unfinished_stage_gives_borderline() -> None:
    cfg = get_config()
    borderline = decide.Decision(TestOutcome.BORDERLINE, 0.5, 0.1)
    confirmed = decide.Decision(TestOutcome.CONFIRMED, 0.9, 0.3)
    assert decide.checkpoint(borderline, 0) and decide.checkpoint(borderline, cfg.max_ext_blocks - 1)
    assert not decide.checkpoint(borderline, cfg.max_ext_blocks)
    assert not decide.checkpoint(confirmed, 0)
    # Незавершённый этап: есть непоказанные задания — подтверждающий исход становится `borderline`.
    assert decide.final_outcome(confirmed, has_not_shown=True) is TestOutcome.BORDERLINE
    assert decide.final_outcome(confirmed, has_not_shown=False) is TestOutcome.CONFIRMED
    rejected = decide.Decision(TestOutcome.NOT_CONFIRMED, 0.1, 0.0)
    assert decide.final_outcome(rejected, has_not_shown=True) is TestOutcome.NOT_CONFIRMED


def test_level_scale_and_drift() -> None:
    assert [level.pos(t) for t in (-1.5, 0.0, 1.5)] == [25.0, 50.0, 75.0]
    assert level.pos(-9) == 0.0 and level.pos(9) == 100.0
    assert level.se_eff(0.4, 0) == pytest.approx(0.4)
    assert level.se_eff(0.4, 180) == pytest.approx((0.16 + 0.75**2) ** 0.5)
    assert level.se_eff(0.4, 5000) == get_config().se_eff_max
    numbers = level.level_numbers(0.3, 0.4, "middle", NOW - 200 * DAY, NOW)
    assert numbers.stale and numbers.cut == 0.0 and numbers.cut_next == 1.5 and numbers.width == 1.5
    assert numbers.lower < numbers.point < numbers.upper


# --- сборка формы ----------------------------------------------------------------------------------------------------


def _form(pools, spec: str, grade: str, lang: str | None, attempt: int = 1, **extra):
    seed = assemble.session_seed("secret", "cand-1", spec, grade, attempt)
    return seed, assemble.assemble_base(pools, seed=seed, specialization=spec, grade=grade, lang=lang, **extra)


@pytest.mark.parametrize("source", ["registry", "fake"])
def test_form_is_deterministic_and_has_no_repeats(source: str) -> None:
    families = list(REGISTRY.values()) if source == "registry" else [f.meta for f in fake_bank()]
    pools = blueprints.pool_families(families)
    cfg = get_config()
    for spec, grade in itertools.product(SPECIALIZATIONS, GRADES):
        for lang in blueprints.lang_scenarios(spec):
            seed, first = _form(pools, spec, grade, lang)
            _, again = _form(pools, spec, grade, lang)
            assert first == again
            assert len(first) == cfg.items_min
            used = {slot.family_id for slot in first}
            assert len(used) == len(first)
            # Привязанные слоты соответствуют плану; у каждого задания сложность в диапазоне грейда.
            plan = blueprints.plan_slots(spec, grade, lang)
            bound = [slot for slot in first if slot.slot_group is not None]
            assert {g: sum(1 for s in bound if s.slot_group == g) for g in plan} == plan
            assert all(slot.group == slot.slot_group for slot in bound)
            low, high = blueprints.MAIN_RANGE[grade]
            assert all(low <= slot.b <= high for slot in bound)
            # Разминка: два самых простых задания идут первыми.
            assert sorted(s.b for s in first)[:2] == sorted(s.b for s in first[:2])
            for stage in (1, 2):
                ext = assemble.assemble_ext(
                    pools, seed=seed, specialization=spec, grade=grade, lang=lang, stage=stage, used=used
                )
                assert len(ext) == cfg.ext_block and not used & {slot.family_id for slot in ext}
                assert all(low <= slot.b <= high for slot in ext)
                used |= {slot.family_id for slot in ext}
            assert len(used) == cfg.items_max


def test_form_depends_on_seed_and_prefers_unseen() -> None:
    pools = blueprints.pool_families(REGISTRY.values())
    _, first = _form(pools, "backend", "middle", "py", attempt=1)
    forms = {tuple(s.family_id for s in _form(pools, "backend", "middle", "py", attempt=n)[1]) for n in range(1, 9)}
    assert len(forms) > 1
    seen = {slot.family_id for slot in first}
    _, second = _form(pools, "backend", "middle", "py", attempt=2, seen=seen)
    _, plain = _form(pools, "backend", "middle", "py", attempt=2)
    assert len(seen & {s.family_id for s in second}) <= len(seen & {s.family_id for s in plain})


def test_form_raises_when_bank_is_short() -> None:
    pools = [f for f in blueprints.pool_families(REGISTRY.values()) if f.group != "sql"]
    with pytest.raises(assemble.BankUnavailable):
        blocked = {(f.id, i + 1) for f in pools for i in range(len(f.bs))}
        _form(pools, "backend", "middle", None, blocked=blocked)


def test_u_is_uniform_enough() -> None:
    seed = assemble.session_seed("s", "c", "backend", "junior", 1)
    values = [assemble.u(seed, f"x:{i}") for i in range(2000)]
    assert all(0 <= v < 1 for v in values) and 0.45 < sum(values) / len(values) < 0.55


# --- can_start: таблица Арх. 5.7 -------------------------------------------------------------------------------------


def ctx(
    claimed: str | None = "middle",
    category: CategoryState | None = None,
    sessions: tuple[SessionFact, ...] = (),
    specialization: str | None = "backend",
    active: str | None = None,
) -> StartContext:
    return StartContext(specialization, claimed, category, sessions, active)


def closed(grade: str, days_ago: float, spec: str = "backend") -> SessionFact:
    start = NOW - days_ago * DAY
    return SessionFact(grade, spec, start, start + timedelta(minutes=30))


def cat(grade: str, verdict: TestOutcome = TestOutcome.CONFIRMED, changed: datetime | None = None, wait: float = 60) -> CategoryState:
    return CategoryState(grade, verdict, changed, NOW + wait * DAY)


def test_can_start_row1_survey_and_claim() -> None:
    assert can_start(ctx(specialization=None), "middle", NOW).code == "survey_required"
    assert can_start(ctx(claimed=None), "middle", NOW).code == "claim_required"
    first = can_start(ctx(), "middle", NOW)
    assert first.ok and first.kind is SessionKind.INITIAL


def test_can_start_row2_active_session() -> None:
    running = SessionFact("middle", "backend", NOW - timedelta(minutes=5), None)
    decision = can_start(ctx(sessions=(running,), active="sid-1"), "middle", NOW)
    assert (decision.status, decision.code, decision.session_id) == (409, "session_active", "sid-1")


def test_can_start_row3_session_limit() -> None:
    sessions = (closed("middle", 29), closed("junior", 20), closed("junior", 3))
    decision = can_start(ctx(sessions=sessions), "junior", NOW)
    assert (decision.code, decision.reason) == ("cooldown_active", "session_limit")
    assert decision.available_at == sessions[0].started_at + 30 * DAY
    # Сессии другой специализации тоже входят в лимит аккаунта.
    other = (closed("middle", 29, "frontend"), closed("junior", 20, "frontend"), closed("junior", 3))
    assert can_start(ctx(sessions=other), "junior", NOW).reason == "session_limit"
    assert can_start(ctx(sessions=(closed("middle", 31), closed("junior", 20), closed("junior", 3))), "junior", NOW).ok


def test_can_start_row4_retry_same_grade() -> None:
    decision = can_start(ctx(sessions=(closed("middle", 5),)), "middle", NOW)
    assert (decision.code, decision.reason) == ("cooldown_active", "retry_same_grade")
    assert can_start(ctx(sessions=(closed("middle", 15),)), "middle", NOW).ok
    # С категорией пауза действует и на нижнем грейде.
    with_category = ctx(claimed="junior", category=cat("junior"), sessions=(closed("junior", 5),))
    assert can_start(with_category, "junior", NOW).reason == "retry_same_grade"


def test_can_start_row4_quick_demo_test_gives_no_pause() -> None:
    """Быстрый демо-тест не закрывает обычный тест на тот же грейд, но в лимит сессий за 30 дней входит."""
    quick = replace(closed("middle", 0.01), prefilled=True)
    with_demo_category = ctx(category=cat("middle", TestOutcome.CONFIRMED_WITH_MARGIN), sessions=(quick,))
    assert can_start(with_demo_category, "middle", NOW).ok
    # Обычная попытка после демо-теста паузу даёт, как всегда.
    regular = ctx(category=cat("middle"), sessions=(quick, closed("middle", 0.005)))
    assert can_start(regular, "middle", NOW).reason == "retry_same_grade"
    three = tuple(replace(closed("middle", days), prefilled=True) for days in (3, 2, 1))
    assert can_start(ctx(category=cat("middle"), sessions=three), "middle", NOW).reason == "session_limit"


def test_can_start_row4_lowest_grade_without_category_has_no_pause() -> None:
    """Нет категории, нижний грейд → пауза 14 дней не применяется: иначе не остаётся ни одного действия."""
    assert can_start(ctx(claimed="junior", sessions=(closed("junior", 1),)), "junior", NOW).ok
    assert can_start(ctx(claimed="middle", sessions=(closed("middle", 2), closed("junior", 1))), "junior", NOW).ok
    assert can_start(ctx(claimed="middle", sessions=(closed("middle", 2),)), "middle", NOW).reason == "retry_same_grade"


def test_can_start_row5a_without_category() -> None:
    assert can_start(ctx(claimed="middle"), "junior", NOW).code == "grade_not_allowed"
    assert can_start(ctx(claimed="middle"), "senior", NOW).code == "grade_not_allowed"
    after = ctx(claimed="senior", sessions=(closed("senior", 2),))
    lower = can_start(after, "junior", NOW)
    assert lower.ok and lower.kind is SessionKind.LOWER
    assert can_start(after, "middle", NOW).ok
    assert can_start(ctx(claimed="middle", sessions=(closed("middle", 20),)), "senior", NOW).code == "grade_not_allowed"


def test_can_start_row5b_same_grade() -> None:
    decision = can_start(ctx(category=cat("middle"), sessions=(closed("middle", 20),)), "middle", NOW)
    assert decision.ok and decision.kind is SessionKind.RETAKE


def test_can_start_row5c_higher() -> None:
    history = (closed("middle", 20),)
    waiting = can_start(ctx(category=cat("middle"), sessions=history), "senior", NOW)
    assert (waiting.code, waiting.reason, waiting.available_at) == ("cooldown_active", "grade_change", NOW + 60 * DAY)
    assert can_start(ctx(category=cat("middle", wait=-1), sessions=history), "senior", NOW).kind is SessionKind.HIGHER
    # Быстрый шаг: подтверждён заявленный грейд с запасом, грейд ещё не менялся.
    margin = cat("middle", TestOutcome.CONFIRMED_WITH_MARGIN)
    assert can_start(ctx(category=margin, sessions=history), "senior", NOW).ok
    changed = cat("middle", TestOutcome.CONFIRMED_WITH_MARGIN, changed=NOW - 10 * DAY)
    assert can_start(ctx(category=changed, sessions=history), "senior", NOW).reason == "grade_change"


def test_can_start_row5c_no_fast_step_below_claimed() -> None:
    """Категория ниже заявленного + запас → быстрого шага нет (Арх. 5.7, 15.1 № 44)."""
    below = cat("junior", TestOutcome.CONFIRMED_WITH_MARGIN)
    decision = can_start(ctx(claimed="middle", category=below, sessions=(closed("middle", 30), closed("junior", 20))), "middle", NOW)
    assert (decision.ok, decision.code, decision.reason) == (False, "cooldown_active", "grade_change")


def test_can_start_row5d_lower_and_5e_distance() -> None:
    history = (closed("senior", 20),)
    assert can_start(ctx(claimed="senior", category=cat("senior"), sessions=history), "middle", NOW).reason == "grade_change"
    ready = can_start(ctx(claimed="senior", category=cat("senior", wait=-1), sessions=history), "middle", NOW)
    assert ready.ok and ready.kind is SessionKind.LOWER
    far = can_start(ctx(claimed="senior", category=cat("senior", wait=-1), sessions=history), "junior", NOW)
    assert (far.status, far.code) == (422, "grade_not_allowed")
    assert can_start(ctx(claimed="junior", category=cat("junior", wait=-1), sessions=history), "senior", NOW).status == 422


def test_next_actions() -> None:
    first = rules.next_actions(ctx(), NOW)
    assert [(a.kind, a.grade, a.available, a.recommended) for a in first] == [("take_claimed", "middle", True, True)]
    failed = rules.next_actions(ctx(claimed="senior", sessions=(closed("senior", 1),)), NOW, lambda cut: 0.9 if cut < 0 else 0.1)
    assert [(a.kind, a.grade) for a in failed] == [("take_lower", "middle"), ("take_lower", "junior"), ("retake_same", "senior")]
    assert [a.recommended for a in failed] == [False, True, False]
    assert failed[2].available is False and failed[2].reason == "retry_same_grade"
    with_category = rules.next_actions(ctx(category=cat("middle"), sessions=(closed("middle", 20),)), NOW)
    assert [(a.kind, a.grade, a.available) for a in with_category] == [
        ("take_higher", "senior", False),
        ("retake_same", "middle", True),
        ("take_lower", "junior", False),
    ]
    assert with_category[0].reason == "grade_change" and with_category[0].available_at == NOW + 60 * DAY
    assert rules.next_actions(ctx(claimed=None), NOW) == []


# --- apply_result: инварианты грейда ---------------------------------------------------------------------------------


def post_for(right: int, wrong: int, b: float = 0.0):
    return estimate([Response(b, 0.0, 1)] * right + [Response(b, 0.0, 0)] * wrong)


def test_apply_result_creates_category_only_on_confirm() -> None:
    assert apply_result(None, "middle", TestOutcome.BORDERLINE, post_for(7, 7), NOW) is None
    assert apply_result(None, "middle", TestOutcome.NOT_CONFIRMED, post_for(0, 14), NOW) is None
    created = apply_result(None, "middle", TestOutcome.CONFIRMED, post_for(12, 2), NOW)
    assert created is not None and created.created and created.grade == "middle"
    assert created.last_grade_change_at is None and created.change_kind is GradeChangeKind.INITIAL
    assert created.change_available_at == NOW + get_config().grade_change_cooldown_days * DAY


def test_apply_result_grade_invariants() -> None:
    """I1: грейд меняется только при подтверждающем исходе; I2: новое значение равно грейду теста."""
    confirming = {TestOutcome.CONFIRMED, TestOutcome.CONFIRMED_WITH_MARGIN}
    posts = [post_for(14, 0, 1.5), post_for(7, 7), post_for(0, 14, -1.5)]
    for current, target, outcome, post in itertools.product(GRADES, GRADES, TestOutcome, posts):
        state = cat(current, TestOutcome.CONFIRMED, wait=10)
        update = apply_result(state, target, outcome, post, NOW)
        assert update is not None and not update.created
        if outcome in confirming and target != current:
            assert update.grade == target and update.last_grade_change_at == NOW
            assert update.change_available_at == NOW + 90 * DAY
            expected = GradeChangeKind.UP if GRADES.index(target) > GRADES.index(current) else GradeChangeKind.DOWN
            assert update.change_kind is expected and update.from_grade == current
        else:
            assert update.grade == current and update.change_kind is None
            assert update.last_grade_change_at is None and update.change_available_at == state.change_available_at
        # Вердикт считается по всем ответам окна для итогового грейда категории.
        assert update.verdict is decide.decide(post, update.grade).outcome


def test_apply_result_weak_retake_keeps_grade_and_weakens_verdict() -> None:
    update = apply_result(cat("middle"), "middle", TestOutcome.NOT_CONFIRMED, post_for(2, 26), NOW)
    assert update is not None and update.grade == "middle" and update.verdict is TestOutcome.NOT_CONFIRMED


# --- навыки ----------------------------------------------------------------------------------------------------------


def answer(group: str, score: int, tags: tuple[str, ...], b: float = 0.0) -> skills.SkillAnswer:
    return skills.SkillAnswer(group, b, score, tags)


def test_group_verdict_thresholds() -> None:
    verdicts = skills.group_verdicts(
        [
            answer("sql", 1, ("sql",)), answer("sql", 1, ("sql_joins",)), answer("sql", 0, ("sql_window_functions",)),
            answer("git", 1, ("git",)),
            answer("db", 1, ("db_indexes",)), answer("db", 0, ("db_transactions",)),
            answer("svc", 0, ("concurrency",)),
            answer("code", 1, ("code_reading",), b=-2.0),  # ниже уровня грейда: не считается
        ],
        "middle",
    )  # fmt: skip
    assert {g: (v.items, v.correct, v.verdict) for g, v in verdicts.items()} == {
        "sql": (3, 2, SkillVerdict.CONFIRMED),
        "git": (1, 1, SkillVerdict.PARTIAL),
        "db": (2, 1, SkillVerdict.PARTIAL),
        "svc": (1, 0, SkillVerdict.NOT_CONFIRMED),
    }
    assert verdicts["sql"].tags_correct == ("sql", "sql_joins")


def test_skill_needs_tag() -> None:
    """Подтверждённая группа без решённого семейства с тегом навыка не даёт доказательства по этому навыку."""
    verdicts = skills.group_verdicts(
        [
            answer("sql", 1, ("sql", "sql_joins")), answer("sql", 1, ("sql", "sql_aggregation")),
            answer("sql", 0, ("sql_window_functions",)),
            answer("web", 1, ("dom",)), answer("web", 1, ("dom", "frontend_performance")),
        ],
        "middle",
    )  # fmt: skip
    proofs = {p.skill: p for p in skills.skill_proofs(verdicts.values(), DIRECT)}
    assert verdicts["sql"].verdict is SkillVerdict.CONFIRMED and verdicts["web"].verdict is SkillVerdict.CONFIRMED
    assert set(proofs) == {"sql", "sql_joins", "sql_aggregation", "dom", "frontend_performance"}
    assert "sql_window_functions" not in proofs and "react" not in proofs
    assert "postgresql" not in proofs  # связь related доказательства не даёт


def test_two_weights_of_test_evidence() -> None:
    """Группа `confirmed` + решённое задание с тегом → full; `partial` (один слот или одна ошибка из двух) → не full;
    `not_confirmed` — доказательства нет (Арх. 5.6, 15.1 № 54)."""
    verdicts = skills.group_verdicts(
        [
            answer("sql", 1, ("sql",)), answer("sql", 1, ("sql",)),
            answer("py", 1, ("python",)),  # один слот в плане
            answer("db", 1, ("db_indexes",)), answer("db", 0, ("db_transactions",)),  # одна ошибка из двух
            answer("git", 0, ("git",)),
        ],
        "senior" if False else "middle",
    )  # fmt: skip
    proofs = {p.skill: p.full for p in skills.skill_proofs(verdicts.values(), DIRECT)}
    assert proofs == {"sql": True, "python": False, "db_indexes": False}
    assert verdicts["git"].verdict is SkillVerdict.NOT_CONFIRMED and "git" not in proofs


def test_tag_outside_direct_gives_nothing_and_pulse_rule() -> None:
    verdicts = skills.group_verdicts([answer("py", 1, ("python", "asyncio")), answer("py", 1, ("python",))], "middle")
    assert {p.skill for p in skills.skill_proofs(verdicts.values(), DIRECT)} == {"python"}
    assert skills.pulse_gives_evidence(None) and skills.pulse_gives_evidence("partial")
    assert skills.pulse_gives_evidence(SkillVerdict.CONFIRMED)
    assert not skills.pulse_gives_evidence("not_confirmed")
