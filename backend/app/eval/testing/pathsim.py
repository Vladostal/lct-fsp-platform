"""Симуляция сессии и полного пути кандидата на боевом движке (Арх. 12.2; приложение A, §10.1).

Здесь нет ни одной формулы механики: форма собирается `engine.assemble`, уровень оценивает `engine.model`,
исход решают `engine.decide`, право на тест и смену категории — `engine.rules`. Симулятор добавляет только
то, чего в жизни делает человек: отвечает на задание верно или неверно с вероятностью «истинной» модели.
"""

# ruff: noqa: E501 — вызовы движка с именованными аргументами читаются лучше в одну строку

from __future__ import annotations

import random
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

from app.eval.testing.bank import SimBank
from app.modules.assessment.config import AssessmentConfig, get_config
from app.modules.assessment.dto import SeedItem, SeedSession
from app.modules.assessment.engine import assemble, rules
from app.modules.assessment.engine.decide import Decision, checkpoint, decide, final_outcome
from app.modules.assessment.engine.model import Posterior, Response, estimate
from app.shared.enums import SlotRole, TestOutcome
from app.simulation.population import ItemWorld, VirtualCandidate, WorldParams, item_world, p_correct

__all__ = ["PathResult", "SimItem", "SimSession", "simulate_path", "simulate_session", "to_seed_sessions"]

#: Секрет сборки формы в симуляции: от него зависят только номера выпавших семейств.
SIM_SECRET = "eval-testing"
#: Начало времени симуляции.
EPOCH = datetime(2026, 1, 1, tzinfo=UTC)

ShiftFn = Callable[[str], float]


@dataclass(frozen=True)
class SimItem:
    """Ответ виртуального кандидата на задание формы."""

    family_id: str
    group: str
    level: int
    b: float
    c: float
    score: int
    stage: int
    role: SlotRole
    slot_group: str | None

    def response(self, world: ItemWorld | None = None) -> Response:
        """Ответ глазами движка; с `world` — «всезнающий» движок, знающий истинные параметры (V9)."""
        if world is None:
            return Response(b=self.b, c=self.c, score=self.score)
        return Response(
            b=round(world.b_true[(self.family_id, self.level)], 2),
            c=self.c,
            score=self.score,
            a=round(world.a_true[self.family_id], 2),
        )


@dataclass(frozen=True)
class SimSession:
    grade: str
    lang: str | None
    items: tuple[SimItem, ...]
    outcome: TestOutcome
    decision: Decision
    #: Оценка по всем ответам окна, включая эту сессию.
    post: Posterior
    stage: int

    @property
    def length(self) -> int:
        return len(self.items)


def simulate_session(
    candidate: VirtualCandidate,
    bank: SimBank,
    world: ItemWorld,
    rng: random.Random,
    grade: str,
    *,
    attempt: int = 1,
    window: Sequence[SimItem] = (),
    seen: Collection[str] = (),
    shift: ShiftFn | None = None,
    omniscient: bool = False,
    seed_tag: str = "",
    cfg: AssessmentConfig | None = None,
) -> SimSession:
    """Одна сессия на грейд: базовая форма, добавочные блоки по правилу контрольной точки, итоговый исход.

    `window` — учтённые ответы прошлых сессий окна (накопление); `seen` — их семейства; `shift(family_id)` —
    сдвиг знакомства с семейством в логитах; `omniscient` — движок считает с истинными параметрами заданий.
    """
    cfg = cfg or get_config()
    spec = candidate.specialization
    lang = bank.lang(spec, grade, candidate.lang_module)
    seed = assemble.session_seed(SIM_SECRET, f"{candidate.id}{seed_tag}", spec, grade, attempt)
    truth = world if omniscient else None
    history = [item.response(truth) for item in window]

    def answer(slot: assemble.FormSlot) -> SimItem:
        family = bank.by_id[slot.family_id]
        p = p_correct(
            candidate, world, slot.family_id, slot.group, slot.level, family.c, rng,
            shift=shift(slot.family_id) if shift else 0.0,
        )
        score = 1 if rng.random() < p else 0
        return SimItem(slot.family_id, slot.group, slot.level, slot.b, family.c, score, slot.stage, slot.role, slot.slot_group)

    slots = assemble.assemble_base(bank.pools, seed=seed, specialization=spec, grade=grade, lang=lang, seen=seen, cfg=cfg)
    items = [answer(slot) for slot in slots]
    stage = 0
    while True:
        post = estimate([*history, *(item.response(truth) for item in items)], cfg)
        decision = decide(post, grade, cfg)
        if not checkpoint(decision, stage, cfg):
            break
        try:
            extra = assemble.assemble_ext(
                bank.pools, seed=seed, specialization=spec, grade=grade, lang=lang, stage=stage + 1,
                used={item.family_id for item in items}, seen=seen, cfg=cfg,
            )
        except assemble.BankUnavailable:
            break
        stage += 1
        items.extend(answer(slot) for slot in extra)
    outcome = final_outcome(decision, has_not_shown=False)
    return SimSession(grade=grade, lang=lang, items=tuple(items), outcome=outcome, decision=decision, post=post, stage=stage)


@dataclass(frozen=True)
class PathResult:
    """Полный путь кандидата по правилам грейда: сессии и итоговая категория."""

    candidate: VirtualCandidate
    sessions: tuple[SimSession, ...]
    #: Грейд итоговой категории; `None` — категории нет.
    grade: str | None
    verdict: TestOutcome | None
    #: Оценка по всем ответам пути.
    post: Posterior
    started: tuple[datetime, ...] = field(default=())


def simulate_path(
    candidate: VirtualCandidate,
    bank: SimBank,
    rng: random.Random,
    *,
    world: ItemWorld | None = None,
    max_sessions: int | None = None,
    omniscient: bool = False,
    seed_tag: str = "",
    cfg: AssessmentConfig | None = None,
) -> PathResult:
    """Путь по правилам Арх. 5.7: заявленный грейд → ниже при неподтверждении → выше при запасе.

    Кандидат действует сразу, как только действие разрешено `can_start`: без категории берёт рекомендованный
    тест ниже, с категорией — тест выше, если открыт быстрый шаг. Категорию меняет только `apply_result`.
    Путь заканчивается, когда доступных действий не осталось (лимит сессий, паузы, подтверждённый грейд).
    Без `world` истинные параметры заданий разыгрываются из `rng` (так путь строит сид).
    """
    cfg = cfg or get_config()
    if world is None:
        world = item_world(bank.families, rng, WorldParams())
    limit = max_sessions or cfg.max_sessions_per_30d
    spec = candidate.specialization
    facts: list[rules.SessionFact] = []
    category: rules.CategoryState | None = None
    sessions: list[SimSession] = []
    window: list[SimItem] = []
    started: list[datetime] = []
    post = estimate([], cfg)
    now = EPOCH
    grade: str | None = candidate.claimed_grade
    attempts: dict[str, int] = {}
    while grade is not None and len(sessions) < limit:
        ctx = rules.StartContext(spec, candidate.claimed_grade, category, tuple(facts))
        if not rules.can_start(ctx, grade, now, cfg).ok:
            break
        attempts[grade] = attempts.get(grade, 0) + 1
        session = simulate_session(
            candidate, bank, world, rng, grade,
            attempt=attempts[grade], window=window, seen={item.family_id for item in window},
            omniscient=omniscient, seed_tag=seed_tag, cfg=cfg,
        )
        finished = now + timedelta(minutes=40)
        facts.append(rules.SessionFact(grade, spec, now, finished))
        started.append(now)
        sessions.append(session)
        window.extend(session.items)
        post = session.post
        update = rules.apply_result(category, grade, session.outcome, post, finished, cfg)
        if update is not None:
            category = rules.CategoryState(
                update.grade, update.verdict, update.last_grade_change_at, update.change_available_at
            )
        now = finished + timedelta(minutes=20)
        ctx = rules.StartContext(spec, candidate.claimed_grade, category, tuple(facts))
        actions = rules.next_actions(ctx, now, post.p_ge, cfg)
        if category is None:
            grade = next((a.grade for a in actions if a.kind == "take_lower" and a.recommended), None)
        else:
            grade = next((a.grade for a in actions if a.kind == "take_higher" and a.available), None)
    return PathResult(
        candidate=candidate,
        sessions=tuple(sessions),
        grade=category.grade if category else None,
        verdict=category.verdict if category else None,
        post=post,
        started=tuple(started),
    )


def to_seed_sessions(path: PathResult, last_finished_at: datetime) -> list[SeedSession]:
    """Сессии пути в виде, который принимает `assessment.service.seed_result`; последняя закрыта в `last_finished_at`."""
    if not path.sessions:
        return []
    offset = last_finished_at - (path.started[-1] + timedelta(minutes=40))
    return [
        SeedSession(
            grade_code=session.grade,
            started_at=start + offset,
            finished_at=start + offset + timedelta(minutes=40),
            items=[
                SeedItem(
                    family_id=item.family_id, level=item.level, score=item.score,
                    stage=item.stage, role=item.role, slot_group=item.slot_group,
                )
                for item in session.items
            ],
        )
        for session, start in zip(path.sessions, path.started, strict=True)
    ]


def with_theta(candidate: VirtualCandidate, theta: float, *, claimed: str | None = None, new_id: int | None = None) -> VirtualCandidate:
    """Тот же кандидат с заданным истинным уровнем (для точек «ниже порога на 0.5» и кривых утечки)."""
    from app.simulation.population import true_grade

    return replace(
        candidate,
        id=candidate.id if new_id is None else new_id,
        theta_true=theta,
        true_grade=true_grade(theta),
        claimed_grade=claimed or candidate.claimed_grade,
    )
