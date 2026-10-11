"""Типы фасада `assessment.service` (Арх. 2.5, 5.6, 9.11).

`TestItemView` — задание, как его видит кандидат: ответа, балла и разбора в нём нет. `SeedResult` и `PulseItem`
архитектура по полям не расписывает; их состав задан здесь.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.shared.enums import CategoryBasis, EvidenceSource, ItemKind, SlotRole, TestOutcome
from app.shared.schemas import CategoryRef, Ref


class CategoryDTO(BaseModel):
    """Действующая категория кандидата «специализация × грейд».

    `basis = test` — грейд подтверждён тестом; `declared` — грейд заявлен кандидатом (тест по специализации
    готовится): `verdict` и `level_session_id` тогда `None`.
    """

    specialization_code: str
    grade_code: str
    #: «backend:middle».
    category_code: str
    basis: CategoryBasis = CategoryBasis.TEST
    verdict: TestOutcome | None = None
    assigned_at: datetime
    level_session_id: UUID | None = None
    change_available_at: datetime | None = None
    #: Категория получена быстрым демо-тестом (Арх. 13.5): в отчётах платформы не учитывается.
    is_demo_result: bool = False


class LevelDTO(BaseModel):
    """Уровень кандидата для подбора (Арх. 5.6): оценка на общей шкале и пороги грейда.

    Для заявленного грейда (`basis = declared`) теста не было: `verdict`, `theta`, `se`, `se_eff`, `tested_at`,
    `last_evidence_at` и `age_days` равны `None`, `stale = False`; пороги грейда заполнены из конфигурации.
    """

    candidate_id: UUID
    specialization_code: str
    grade_code: str
    basis: CategoryBasis = CategoryBasis.TEST
    verdict: TestOutcome | None = None
    theta: float | None = None
    se: float | None = None
    #: Неопределённость с учётом давности: `min(sqrt(se² + DRIFT² · d / 180), SE_EFF_MAX)`.
    se_eff: float | None = None
    #: Порог грейда `THETA_CUT[grade]`, порог следующего грейда и ширина грейда.
    cut: float
    cut_next: float
    width: float
    tested_at: datetime | None = None
    last_evidence_at: datetime | None = None
    #: Давность подтверждения в сутках; `None` — подтверждения тестом не было (не «только что»).
    age_days: int | None = None
    stale: bool = False


class LevelThreshold(BaseModel):
    grade: Ref
    pos: float


class LevelView(BaseModel):
    """Уровень на шкале экрана 0–100 с интервалом (Арх. 5.6, 9.11)."""

    point: float
    lower: float
    upper: float
    thresholds: list[LevelThreshold]
    verdict: TestOutcome
    verdict_label: str
    stale: bool
    tested_at: datetime
    last_evidence_at: datetime


class TestSkillEvidence(BaseModel):
    """Навык, подтверждённый тестом или коротким заданием (Арх. 5.6)."""

    __test__ = False  # не тестовый класс для pytest

    skill_code: str
    source: EvidenceSource
    #: Группа подтверждена целиком — вес 1.0; иначе одно задание — 0.7.
    full: bool
    group_code: str
    ref_id: UUID | None = None
    detail: str | None = None
    confirmed_at: datetime


class SurveyDeclared(BaseModel):
    """Заявленное в опросе."""

    direction: str | None = None
    main_language: str | None = None
    experience_band: str | None = None
    industry_domains: list[str] = []


class ItemCode(BaseModel):
    language: str
    text: str


class ItemTable(BaseModel):
    title: str
    columns: list[str]
    rows: list[list[str]]


class ItemOption(BaseModel):
    id: str
    text: str


class ItemInput(BaseModel):
    placeholder: str | None = None
    unit: str | None = None
    max_length: int | None = None


class TestItemView(BaseModel):
    """Задание теста, как его видит кандидат (приложение E, §10.2). Ответа и балла в нём нет."""

    __test__ = False

    #: Идентификатор строки задания сессии (у примеров предпросмотра — идентификатор варианта).
    id: str
    kind: ItemKind
    #: Название группы заданий.
    skill_label: str
    prompt: str
    code: ItemCode | None = None
    tables: list[ItemTable] | None = None
    options: list[ItemOption] | None = None
    #: Блоки задания на порядок; в банке MVP таких семейств нет.
    blocks: list[ItemOption] | None = None
    input: ItemInput | None = None


class BlueprintCoverageItem(BaseModel):
    skill: Ref
    priority: Literal["must", "nice"]
    group: Ref | None = None
    relation: Literal["direct", "related", "untested", "above_grade"]
    slots: int


class BlueprintSlots(BaseModel):
    group: Ref
    slots: int


class BlueprintNeedSlots(BlueprintSlots):
    #: Разница со `slots` плана категории.
    delta: int


class BlueprintPreview(BaseModel):
    """Как описание вакансии превращается в план теста (Арх. 5.4, 9.11)."""

    target: CategoryRef
    grade_guessed: bool = False
    coverage: list[BlueprintCoverageItem] = []
    #: План теста категории: его получит кандидат.
    standard_slots: list[BlueprintSlots] = []
    #: Индикативный план под это описание: есть всегда, кандидату не выдаётся.
    need_slots: list[BlueprintNeedSlots] = []
    #: Только варианты со статусом `demo`.
    sample_items: list[TestItemView] = []


class PulseItem(BaseModel):
    """Вариант для короткого задания (Арх. 5.9): то, что модуль `pulse` пишет в `pulse_assignment`."""

    variant_id: UUID
    group_code: str
    family_id: str
    level: int
    b_used: float
    #: Теги навыков семейства: по ним строится доказательство `pulse` (Арх. 5.6).
    skill_tags: list[str] = []
    time_budget_s: int
    item: TestItemView


class GradeResult(BaseModel):
    """Результат проверки ответа (`grading.grade`, Арх. 5.3): балл бинарный."""

    score: int
    parse_ok: bool
    normalized: Any = None
    error_tag: str | None = None


class SeedItem(BaseModel):
    """Ответ синтетического кандидата на задание: семейство, уровень и балл (содержание ответа не моделируется)."""

    family_id: str
    level: int
    score: int = Field(ge=0, le=1)
    stage: int = 0
    role: SlotRole = SlotRole.MAIN
    #: Группа, к которой привязан слот плана; `None` — свободный слот.
    slot_group: str | None = None


class SeedSession(BaseModel):
    """Закрытая сессия синтетического кандидата; задания — в порядке показа."""

    grade_code: str
    started_at: datetime
    finished_at: datetime
    items: list[SeedItem]


class SeedResult(BaseModel):
    """Путь синтетического кандидата по тесту для записи сидом (`seed_result`, Арх. 13.5).

    Сид передаёт ответы симулятора (`app.eval.testing.pathsim`), а исходы, категорию, уровень и вердикты по навыкам
    считает и записывает сам модуль тем же кодом, что и для живой сессии.
    """

    candidate_id: UUID
    specialization_code: str
    #: Заявленный грейд.
    grade_code: str
    main_language: str | None = None
    experience_band: str | None = None
    industry_domains: list[str] = []
    #: Сессии в порядке прохождения; пустой список — опрос пройден и грейд заявлен, теста не было.
    sessions: list[SeedSession] = []
    is_demo_result: bool = False
