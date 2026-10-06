"""Правила грейда: кто какой тест может начать и как результат меняет категорию (Арх. 5.7; приложение A, §6)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.modules.assessment.config import GRADES, AssessmentConfig, get_config
from app.modules.assessment.engine.decide import CONFIRMING, decide
from app.modules.assessment.engine.model import Posterior
from app.shared.enums import GradeChangeKind, SessionKind, TestOutcome

__all__ = [
    "Action",
    "CategoryState",
    "CategoryUpdate",
    "SessionFact",
    "StartContext",
    "StartDecision",
    "apply_result",
    "can_start",
    "next_actions",
]


@dataclass(frozen=True)
class SessionFact:
    """Сессия кандидата глазами правил: грейд, специализация, начало и закрытие (`None` — идёт сейчас)."""

    grade: str
    specialization: str
    started_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True)
class CategoryState:
    """Действующая категория в специализации опроса."""

    grade: str
    verdict: TestOutcome
    last_grade_change_at: datetime | None
    change_available_at: datetime


@dataclass(frozen=True)
class StartContext:
    """Всё, что нужно правилам: опрос, заявленный грейд, категория и сессии аккаунта."""

    #: Специализация опроса; `None` — опрос не пройден.
    specialization: str | None
    claimed_grade: str | None
    #: Категория в этой специализации (категория другой специализации правилам не видна).
    category: CategoryState | None
    #: Все сессии аккаунта: лимит на 30 дней считается по аккаунту, остальное — по специализации.
    sessions: tuple[SessionFact, ...] = ()
    active_session_id: str | None = None


@dataclass(frozen=True)
class StartDecision:
    """Ответ `can_start`: разрешение и вид сессии либо HTTP-статус, код ошибки и срок."""

    ok: bool
    kind: SessionKind | None = None
    status: int = 0
    code: str | None = None
    reason: str | None = None
    available_at: datetime | None = None
    session_id: str | None = None


def _deny(status: int, code: str, **extra: object) -> StartDecision:
    return StartDecision(ok=False, status=status, code=code, **extra)  # type: ignore[arg-type]


def can_start(ctx: StartContext, grade: str, now: datetime, cfg: AssessmentConfig | None = None) -> StartDecision:
    """Можно ли начать тест на грейд `g` (таблица Арх. 5.7; проверки идут по порядку).

    1. Опрос не пройден → 409 `survey_required`; грейд не заявлен → 409 `claim_required`.
    2. Есть активная сессия → 409 `session_active`.
    3. За 30 дней начато `MAX_SESSIONS_PER_30D` сессий → 409 `cooldown_active`, `reason = session_limit`.
    4. Последняя сессия на `g` закрыта меньше `RETRY_SAME_GRADE_DAYS` назад → `reason = retry_same_grade`.
       Не применяется, если категории нет и `g` — нижний грейд: иначе у кандидата не остаётся ни одного действия.
    5а. Категории нет: разрешён `g = claimed_grade`; после первой закрытой сессии — любой `g ≤ claimed_grade`.
    5б. Категория на `G`, `g = G` — разрешено.
    5в. `g = G + 1`: `now ≥ change_available_at` или быстрый шаг — `verdict = confirmed_with_margin`,
        `last_grade_change_at IS NULL` и `G = claimed_grade` (быстрого шага с грейда ниже заявленного нет).
    5г. `g = G − 1`: `now ≥ change_available_at`. Иначе в 5в и 5г — `reason = grade_change`.
    5д. Расстояние до `G` больше одного грейда → 422 `grade_not_allowed`.
    """
    cfg = cfg or get_config()
    if ctx.specialization is None:
        return _deny(409, "survey_required")
    if ctx.claimed_grade is None:
        return _deny(409, "claim_required")
    if grade not in GRADES:
        return _deny(422, "grade_not_allowed")
    if ctx.active_session_id is not None or any(s.finished_at is None for s in ctx.sessions):
        return _deny(409, "session_active", session_id=ctx.active_session_id)

    month = timedelta(days=30)
    recent = sorted((s.started_at for s in ctx.sessions if s.started_at > now - month), reverse=True)
    if len(recent) >= cfg.max_sessions_per_30d:
        available_at = recent[cfg.max_sessions_per_30d - 1] + month
        return _deny(409, "cooldown_active", reason="session_limit", available_at=available_at)

    own = [s for s in ctx.sessions if s.specialization == ctx.specialization]
    closed = [s for s in own if s.finished_at is not None]
    lowest = ctx.category is None and grade == GRADES[0]
    same = [s.finished_at for s in closed if s.grade == grade and s.finished_at is not None]
    if same and not lowest:
        available_at = max(same) + timedelta(days=cfg.retry_same_grade_days)
        if now < available_at:
            return _deny(409, "cooldown_active", reason="retry_same_grade", available_at=available_at)

    index = GRADES.index(grade)
    if ctx.category is None:
        claimed = GRADES.index(ctx.claimed_grade)
        if not (index == claimed or (closed and index <= claimed)):
            return _deny(422, "grade_not_allowed")
        reference = claimed
    else:
        category = ctx.category
        reference = GRADES.index(category.grade)
        waited = now >= category.change_available_at
        if index - reference == 1:
            fast_step = (
                category.verdict is TestOutcome.CONFIRMED_WITH_MARGIN
                and category.last_grade_change_at is None
                and category.grade == ctx.claimed_grade
            )
            if not (waited or fast_step):
                return _deny(409, "cooldown_active", reason="grade_change", available_at=category.change_available_at)
        elif index - reference == -1:
            if not waited:
                return _deny(409, "cooldown_active", reason="grade_change", available_at=category.change_available_at)
        elif index != reference:
            return _deny(422, "grade_not_allowed")

    if not own:
        kind = SessionKind.INITIAL
    elif index < reference:
        kind = SessionKind.LOWER
    elif index > reference:
        kind = SessionKind.HIGHER
    else:
        kind = SessionKind.RETAKE
    return StartDecision(ok=True, kind=kind)


@dataclass(frozen=True)
class Action:
    """Действие для экрана состояния: вид, грейд, доступно ли сейчас и когда станет доступно."""

    kind: str
    grade: str
    available: bool
    available_at: datetime | None
    reason: str | None
    recommended: bool


def next_actions(
    ctx: StartContext,
    now: datetime,
    p_ge: Callable[[float], float] | None = None,
    cfg: AssessmentConfig | None = None,
) -> list[Action]:
    """Что кандидат может сделать дальше; доступность каждого действия считает `can_start` (Арх. 5.7).

    * категории нет, сессий не было — `take_claimed` на заявленный грейд;
    * категории нет, сессии были — `take_lower` для каждого грейда ниже заявленного (по убыванию) и `retake_same`
      для заявленного; рекомендован наибольший грейд ниже заявленного, для которого `p_ge(THETA_CUT[g]) ≥ 0.5`,
      иначе наименьший;
    * категория есть — `take_higher` (если грейд не высший), `retake_same`, `take_lower` (если не низший).
    """
    cfg = cfg or get_config()
    if ctx.specialization is None or ctx.claimed_grade is None:
        return []

    def action(kind: str, grade: str, recommended: bool = False) -> Action:
        decision = can_start(ctx, grade, now, cfg)
        cooldown = decision.code == "cooldown_active"
        return Action(
            kind=kind,
            grade=grade,
            available=decision.ok,
            available_at=decision.available_at if cooldown else None,
            reason=decision.reason if cooldown else None,
            recommended=recommended and decision.ok,
        )

    own = [s for s in ctx.sessions if s.specialization == ctx.specialization]
    if ctx.category is not None:
        index = GRADES.index(ctx.category.grade)
        result = []
        if index + 1 < len(GRADES):
            result.append(action("take_higher", GRADES[index + 1]))
        result.append(action("retake_same", GRADES[index]))
        if index > 0:
            result.append(action("take_lower", GRADES[index - 1]))
        return result
    if not own:
        return [action("take_claimed", ctx.claimed_grade, recommended=True)]
    lower = [g for g in reversed(GRADES) if GRADES.index(g) < GRADES.index(ctx.claimed_grade)]
    recommended = None
    if lower:
        likely = [g for g in lower if p_ge is not None and p_ge(cfg.theta_cut[g]) >= 0.5]
        recommended = likely[0] if likely else lower[-1]
    result = [action("take_lower", g, recommended=g == recommended) for g in lower]
    result.append(action("retake_same", ctx.claimed_grade))
    return result


@dataclass(frozen=True)
class CategoryUpdate:
    """Категория после применения результата и то, что в ней изменилось."""

    grade: str
    verdict: TestOutcome
    last_grade_change_at: datetime | None
    change_available_at: datetime
    #: Категория создана этой сессией.
    created: bool
    #: Вид записи `assessment_grade_change`; `None` — грейд не менялся.
    change_kind: GradeChangeKind | None
    from_grade: str | None


def apply_result(
    category: CategoryState | None,
    target_grade: str,
    outcome: TestOutcome,
    post: Posterior,
    now: datetime,
    cfg: AssessmentConfig | None = None,
) -> CategoryUpdate | None:
    """Применить результат сессии к категории (Арх. 5.7). Единственное место, где меняется грейд категории.

    * категории нет и исход подтверждает — создать: `grade = t`, `last_grade_change_at = NULL`,
      `change_available_at = now + GRADE_CHANGE_COOLDOWN_DAYS`;
    * категория есть, `t == G` — грейд не меняется при любом исходе;
    * категория есть, `t != G`, исход подтверждает — `grade = t`, `last_grade_change_at = now`,
      `change_available_at = now + 90 дней`;
    * в конце, если категория есть: `verdict = decide(post, category.grade)` по всем ответам окна.

    Инварианты: грейд присваивается только при подтверждающем исходе, и новое значение всегда равно грейду теста;
    неподтверждённый тест, результат «на границе» и истечение времени грейд не меняют. Возвращает `None`, если
    категории нет и не появилось.
    """
    cfg = cfg or get_config()
    cooldown = timedelta(days=cfg.grade_change_cooldown_days)
    confirms = outcome in CONFIRMING
    if category is None:
        if not confirms:
            return None
        grade, last_change, available = target_grade, None, now + cooldown
        created, kind, from_grade = True, GradeChangeKind.INITIAL, None
    elif target_grade != category.grade and confirms:
        up = GRADES.index(target_grade) > GRADES.index(category.grade)
        grade, last_change, available = target_grade, now, now + cooldown
        created, kind, from_grade = False, (GradeChangeKind.UP if up else GradeChangeKind.DOWN), category.grade
    else:
        grade, last_change, available = category.grade, category.last_grade_change_at, category.change_available_at
        created, kind, from_grade = False, None, None
    return CategoryUpdate(
        grade=grade,
        verdict=decide(post, grade, cfg).outcome,
        last_grade_change_at=last_change,
        change_available_at=available,
        created=created,
        change_kind=kind,
        from_grade=from_grade,
    )
