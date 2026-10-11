"""Схемы API модуля `assessment` (Арх. 9.5, 9.11; приложение E, §10.2).

Ни в одной схеме нет полей `answer` (ключ варианта), `score` и `error_tag`: верность ответа кандидату не
показывается никогда (Арх. 5.3, 8.5).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.assessment.dto import (
    BlueprintPreview,
    LevelView,
    TestItemView,
)
from app.shared.enums import SessionStatus, SkillVerdict, TestOutcome
from app.shared.schemas import CategoryRef, Ref

__all__ = [
    "AnswerRequest",
    "AnswerResult",
    "AssessmentStateView",
    "BankHealthView",
    "BlueprintPreview",
    "BlueprintPreviewRequest",
    "ClaimRequest",
    "FamilyStatusRequest",
    "FamilyStatusView",
    "HistoryItem",
    "LeakLookupRequest",
    "LeakLookupResult",
    "MethodologyView",
    "NextAction",
    "ResultPending",
    "SessionCreate",
    "SurveySchema",
    "SurveyUpdate",
    "TestBlueprintView",
    "TestItemView",
    "TestProgress",
    "TestResultView",
    "TestSessionView",
]

# --- опрос и заявленный грейд ---------------------------------------------------------------------------------------


class SurveyOption(BaseModel):
    code: str
    title: str
    available: bool
    parent: str | None = None


class SurveyQuestion(BaseModel):
    id: str
    kind: Literal["single", "multi"]
    title: str
    required: bool
    max: int | None = None
    depends_on: str | None = None
    options: list[SurveyOption]


class SurveySchema(BaseModel):
    version: str
    questions: list[SurveyQuestion]
    answers: dict[str, str | list[str]] | None = None


class SurveyUpdate(BaseModel):
    version: str
    answers: dict[str, str | list[str]]
    confirm_specialization_change: bool = False


class ClaimRequest(BaseModel):
    grade_code: str


# --- состояние ------------------------------------------------------------------------------------------------------


class NextAction(BaseModel):
    kind: Literal["take_claimed", "take_lower", "take_higher", "retake_same"]
    grade: Ref
    available: bool
    available_at: datetime | None = None
    reason: Literal["grade_change", "retry_same_grade", "session_limit"] | None = None
    recommended: bool = False


class StateCategory(CategoryRef):
    assigned_at: datetime
    change_available_at: datetime
    #: Сессия, по которой определён уровень; `None` — грейд заявлен (`basis = declared`), теста не было.
    level_session_id: str | None = None


class ActiveSessionBrief(BaseModel):
    id: str
    target: CategoryRef
    expires_at: datetime


class LastSessionBrief(BaseModel):
    id: str
    target: CategoryRef
    outcome: TestOutcome
    finished_at: datetime


class AssessmentStateView(BaseModel):
    survey_completed: bool
    direction: Ref | None = None
    specialization: Ref | None = None
    main_language: Ref | None = None
    claimed_grade: Ref | None = None
    claim_locked: bool = False
    category: StateCategory | None = None
    level: LevelView | None = None
    active_session: ActiveSessionBrief | None = None
    last_session: LastSessionBrief | None = None
    next_actions: list[NextAction] = []


class BlueprintSkill(BaseModel):
    group_code: str
    label: str
    slots: int


class TestBlueprintView(BaseModel):
    """План теста на грейд: число заданий, время и группы. `time_limit_max_min` — предел с добавочными блоками."""

    __test__ = False

    grade: Ref
    available: bool
    items_min: int
    items_max: int
    time_limit_min: int
    time_limit_max_min: int
    skills: list[BlueprintSkill]


# --- сессия ---------------------------------------------------------------------------------------------------------


class SessionCreate(BaseModel):
    grade_code: str


class TestProgress(BaseModel):
    __test__ = False

    answered: int
    min_total: int
    max_total: int


class TestSessionView(BaseModel):
    __test__ = False

    id: str
    status: SessionStatus
    target: CategoryRef
    expires_at: datetime
    server_now: datetime
    progress: TestProgress
    item: TestItemView | None = None


class ClientInfo(BaseModel):
    """Телеметрия клиента: только для разбора аномалий (P2), на балл не влияет."""

    model_config = ConfigDict(extra="ignore")

    time_spent_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    focus_lost: int | None = Field(default=None, ge=0, le=100_000)
    pasted: bool | None = None


class AnswerRequest(BaseModel):
    item_id: str
    #: Тело ответа по виду задания: `{"value": "42"}`, `{"option_id": "o3"}`, `{"option_ids": [...]}`, `{"line": 7}`.
    answer: dict[str, Any] | None = None
    skipped: bool = False
    client: ClientInfo | None = None


class AnswerResult(BaseModel):
    finished: bool
    next_item: TestItemView | None = None
    progress: TestProgress
    expires_at: datetime
    server_now: datetime


class ResultSkill(BaseModel):
    group_code: str
    label: str
    verdict: SkillVerdict
    items: int


class TestResultView(BaseModel):
    __test__ = False

    session_id: str
    status: Literal["finished", "expired"]
    target: CategoryRef
    outcome: TestOutcome
    outcome_label: str
    finished_at: datetime
    #: Действующая категория после применения результата.
    category: CategoryRef | None = None
    level: LevelView
    skills: list[ResultSkill]
    notes: list[str]
    items_answered: int
    duration_s: int
    next_actions: list[NextAction]


class ResultPending(BaseModel):
    status: Literal["in_progress"] = "in_progress"


class HistoryItem(BaseModel):
    """Строка истории: опрос или тест. Верности отдельных заданий здесь нет."""

    kind: Literal["survey", "test"]
    at: datetime
    title: str
    session_id: str | None = None
    target: CategoryRef | None = None
    status: SessionStatus | None = None
    outcome: TestOutcome | None = None
    outcome_label: str | None = None
    items: int | None = None
    duration_s: int | None = None


# --- предпросмотр плана и методика ----------------------------------------------------------------------------------


class BlueprintPreviewRequest(BaseModel):
    """Либо `text`, либо структура `{specialization_code, grade_code, must_skills, nice_skills}`."""

    text: str | None = None
    specialization_code: str | None = None
    grade_code: str | None = None
    must_skills: list[str] = Field(default_factory=list, max_length=60)
    nice_skills: list[str] = Field(default_factory=list, max_length=60)


class MethodologyGroup(BaseModel):
    group: Ref
    families: int
    levels: int
    variants: int


class MethodologyBank(BaseModel):
    families: int
    levels: int
    variants: int
    groups: list[MethodologyGroup]
    available_categories: list[str]


class MethodologyView(BaseModel):
    """Константы механики и состав банка для экрана «Как это работает» (Арх. 9.5, 15.1 № 25)."""

    constants: dict[str, Any]
    versions: dict[str, str]
    grades: list[Ref]
    outcomes: list[Ref]
    bank: MethodologyBank


# --- служебные ------------------------------------------------------------------------------------------------------


class FamilyHealth(BaseModel):
    id: str
    title: str
    group_code: str
    status: str
    status_reason: str | None = None
    priority: str
    levels: int
    variants_active: int
    #: Наименьший остаток ни разу не показанных вариантов среди уровней семейства.
    variants_unserved_min: int
    variants_low: bool
    #: Наибольшая доля сессий пары (специализация, грейд), в которых встретилось семейство.
    exposure_max: float
    exposure_high: bool
    answers: int
    correct_share: float | None = None
    #: Доля верных ответов семейства, данных быстрее `FAST_FACTOR` расчётного времени: готовый ответ вводят
    #: быстрее, чем читают условие, поэтому высокая доля — признак утечки вариантов.
    fast_correct_share: float | None = None
    fast_high: bool = False


class BankHealthView(BaseModel):
    bank_version: str
    families: list[FamilyHealth]
    available_categories: list[str]
    #: Мониторинг сдвига решаемости — P2: в MVP только счётчики экспозиции и ответов.
    monitoring: Literal["counters_only"] = "counters_only"


class FamilyStatusRequest(BaseModel):
    status: Literal["active", "suspect", "quarantined", "retired"]
    reason: str = Field(default="", max_length=500)


class FamilyStatusView(BaseModel):
    id: str
    status: str
    status_reason: str | None = None
    available_categories: list[str]


class LeakLookupRequest(BaseModel):
    text: str = Field(min_length=10, max_length=5000)


class LeakMatch(BaseModel):
    variant_id: str
    family_id: str
    level: int
    match: Literal["exact", "fuzzy"]
    similarity: float
    #: Сессии, которым вариант выдавался: источник утечки (Арх. 5.8).
    sessions: list[dict[str, Any]]


class LeakLookupResult(BaseModel):
    matches: list[LeakMatch]
