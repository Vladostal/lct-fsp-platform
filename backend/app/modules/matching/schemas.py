"""Схемы эндпоинтов модуля `matching` (Арх. 9.8, 9.11; приложение B, §2.1, §8.2).

Типы фасада (`ShortlistQuery`, `ShortlistRefinement`, `RelaxationHint`, `ShortlistItemView`) лежат в `dto.py`
и включаются сюда полями, без копирования (Арх. 2.4, п. 1). Каналов связи кандидата нет ни в одной схеме
модуля: их отдают только `GET …/contacts` (модуль `profile`) и PDF (Арх. 10.4).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.modules.assessment.dto import LevelView
from app.modules.fsp.dto import FspEmployerBlock
from app.modules.matching import constants as C
from app.modules.matching.dto import RelaxationHint, ShortlistItemView, ShortlistQuery, ShortlistRefinement
from app.shared.enums import DiffMark, FitBand, NeedStatus, Relation, WorkFormat
from app.shared.schemas import CategoryRef, Contribution, EvidenceItem, Page, Ref

StrengthLabel = Literal["high", "medium", "base"]


# --------------------------------------------------------------------------------------------------------------------
# Потребность
# --------------------------------------------------------------------------------------------------------------------


class NeedParseRequest(BaseModel):
    """Текст вакансии для разбора в черновик потребности. Длина проверяется сервисом: коды ошибок свои."""

    text: str


class NeedCreate(BaseModel):
    """Тело создания потребности (Арх. 6.14). Правила полей, которым нужны свои коды ошибок (навыки из
    справочника, доступность пары, вилка, город при офисе), проверяет сервис.
    """

    title: str = Field(min_length=C.NEED_TITLE_MIN, max_length=C.NEED_TITLE_MAX)
    source_text: str | None = Field(default=None, max_length=C.NEED_TEXT_MAX)
    team_description: str = Field(min_length=C.TEAM_DESCRIPTION_MIN, max_length=C.TEAM_DESCRIPTION_MAX)
    specialization_code: str = Field(min_length=1, max_length=64)
    grade_code: str = Field(min_length=1, max_length=64)
    must_skills: list[str] = Field(default_factory=list, max_length=C.MUST_SKILLS_MAX)
    nice_skills: list[str] = Field(default_factory=list, max_length=C.NICE_SKILLS_MAX)
    work_formats: list[WorkFormat] = Field(min_length=1)
    city: str | None = Field(default=None, max_length=100)
    salary_from: int
    salary_to: int
    #: Сведения разборщика текста (`parser`, `parser_version`, `confidence`), если форма заполнена из текста.
    parse_meta: dict[str, Any] | None = None

    @field_validator("title", "team_description", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("city", "source_text", mode="before")
    @classmethod
    def _blank_is_none(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class NeedUpdate(NeedCreate):
    """Тело правки потребности: полная замена редактируемых полей. Версии подборки правка не меняет."""


class LatestSnapshotBrief(BaseModel):
    """Последняя версия подборки потребности — для списка потребностей."""

    id: UUID
    version_no: int
    created_at: datetime
    items_count: int


class NeedView(BaseModel):
    """Потребность работодателя (Арх. 9.11)."""

    id: UUID
    title: str
    status: NeedStatus
    target: CategoryRef
    must_skills: list[Ref]
    nice_skills: list[Ref]
    work_formats: list[WorkFormat]
    city: str | None
    salary_from: int
    salary_to: int
    team_description: str
    source_text: str | None
    latest_snapshot: LatestSnapshotBrief | None
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------------------------------------------------
# Версии подборки
# --------------------------------------------------------------------------------------------------------------------


class ShortlistCreate(BaseModel):
    """Тело создания версии подборки: без полей — запрос из потребности; с `refinement` — уточнение версии
    `parent_id` (обязателен вместе с `refinement`: иначе 422 `parent_required`).
    """

    parent_id: UUID | None = None
    refinement: ShortlistRefinement | None = None


class ShortlistVersionBrief(BaseModel):
    """Версия подборки без строк — для переключателя версий (Арх. 9.11)."""

    id: UUID
    version_no: int
    created_at: datetime
    items_count: int
    query_changes: str | None
    is_latest: bool


class SnapshotCategory(BaseModel):
    """Раздел версии: рекомендованная категория и число её кандидатов (Арх. 6.3)."""

    category: CategoryRef
    relation: Relation
    relation_label: str
    count: int


class SnapshotFunnel(BaseModel):
    """Как сформирована подборка (раздел `exact`). `must_ok` — справочное число, не фильтр (Арх. 6.11)."""

    category_total: int = 0
    available: int = 0
    format_ok: int = 0
    must_ok: int = 0
    shown: int = 0


class DiffCounts(BaseModel):
    """Счётчики различий с базовой версией: числа без идентификаторов (Арх. 6.11)."""

    added: int = 0
    dropped: int = 0
    moved_up: int = 0
    moved_down: int = 0


class DroppedItem(BaseModel):
    """Кандидат, выпавший из подборки относительно родительской версии."""

    candidate_id: UUID
    public_code: str
    category: CategoryRef
    reason_code: str
    reason_text: str


class ShortlistSnapshotView(BaseModel):
    """Версия подборки с живыми полями поверх неизменяемых (Арх. 6.11, 9.11)."""

    id: UUID
    need_id: UUID
    version_no: int
    parent_id: UUID | None
    is_latest: bool
    created_at: datetime
    scorer_version: str
    query: ShortlistQuery
    query_changes: str | None
    categories: list[SnapshotCategory]
    funnel: SnapshotFunnel
    items: list[ShortlistItemView]
    pinned_outside: list[ShortlistItemView]
    #: Строки скрытых сейчас кандидатов не отдаются вовсе — только их число.
    hidden_count: int
    diff: DiffCounts | None
    #: Без скрытых сейчас кандидатов.
    dropped: list[DroppedItem]
    hints: list[RelaxationHint]


class DiffRow(BaseModel):
    """Строка сравнения двух версий: кандидат, его метка и позиции в обеих версиях."""

    candidate_id: UUID
    public_code: str
    category: CategoryRef
    diff_mark: DiffMark
    diff_delta: int | None = None
    #: Позиция в сравниваемой версии; `None` у выпавших.
    position: int | None = None
    #: Позиция в базовой версии; `None` у новых.
    base_position: int | None = None
    #: Только у выпавших.
    reason_code: str | None = None
    reason_text: str | None = None


class SnapshotDiffView(BaseModel):
    """Сравнение двух версий одной потребности (Арх. 9.8). Строк скрытых сейчас кандидатов в списках нет."""

    snapshot_id: UUID
    base_id: UUID
    diff: DiffCounts
    query_changes: str | None
    added: list[DiffRow]
    dropped: list[DiffRow]
    moved: list[DiffRow]
    hidden_count: int


# --------------------------------------------------------------------------------------------------------------------
# Банк и карточка
# --------------------------------------------------------------------------------------------------------------------


class BankItemView(BaseModel):
    """Строка банка кандидатов (Арх. 6.9, 9.11): потребности нет, поэтому совпадения и доводов тоже нет."""

    candidate_id: UUID
    public_code: str
    display_name: str | None = None
    is_demo: bool = False
    category: CategoryRef
    grade_margin: bool = False
    strength_label: StrengthLabel
    level: LevelView
    confirmed_skills: list[EvidenceItem] = []
    confirmed_more: int = 0
    fsp_summary: str | None = None
    work_formats: list[WorkFormat] = []
    relocation_ready: bool = False
    freshness_days: int = 0
    stale: bool = False


class BankSection(BaseModel):
    """Категория банка и число кандидатов в ней при текущих фильтрах."""

    category: CategoryRef
    count: int


class BankPage(Page[BankItemView]):
    """Страница банка кандидатов."""

    sections: list[BankSection] = []
    total: int = 0
    #: Сколько кандидатов скрыл фильтр `has_fsp`; `None`, если фильтр выключен.
    hidden_by_fsp: int | None = None


class CoverageView(BaseModel):
    """Покрытие требований в карточке (единственное место, где работодатель видит процент)."""

    pct: int | None
    must_total: int
    must_covered: int
    must_confirmed: int
    nice_total: int
    nice_covered: int


class EvidenceRefView(BaseModel):
    """Ссылка довода на источник: вид и идентификатор (сессия теста, задание, факт ФСП, профиль)."""

    type: str
    id: str | None = None


class ReasonView(BaseModel):
    """Довод «за»: код, готовый текст и источник."""

    code: str
    text: str
    evidence: EvidenceRefView


class RiskView(BaseModel):
    """Риск: код и готовый текст."""

    code: str
    text: str


class MatchExplanationEmployerView(BaseModel):
    """Объяснение совпадения с потребностью — проекция работодателя (Арх. 6.10, 9.11)."""

    fit_band: FitBand | None
    relation: Relation
    position: int | None
    #: `False` — кандидата нет в версиях потребности: объяснение построено на лету и не сохранено.
    in_snapshot: bool
    coverage: CoverageView
    reasons: list[ReasonView]
    risk: RiskView | None
    formats_common: list[WorkFormat]
    requirements: list[EvidenceItem]
    contributions: list[Contribution]
    scorer_version: str


class DeclaredView(BaseModel):
    """Заявленное кандидатом — по настройкам приватности; «О себе» до раскрытия всегда `None`."""

    city: str | None = None
    experience_years: float | None = None
    roles: list[Ref] = []
    about: str | None = None
    industry_domains: list[Ref] = []


class StrengthView(BaseModel):
    """Сила подтверждённого профиля: подпись с абсолютными порогами и вклады (тест, давность, ФСП)."""

    label: StrengthLabel
    contributions: list[Contribution]


class CandidateCardEmployerView(BaseModel):
    """Карточка кандидата глазами работодателя (Арх. 6.9, 9.11). Контактов и минимума зарплаты в ней нет."""

    candidate_id: UUID
    public_code: str
    #: Имя — только у раскрытой пары.
    display_name: str | None = None
    disclosed: bool
    available: bool
    is_demo: bool
    #: `None` вне контекста потребности.
    pinned: bool | None = None
    category: CategoryRef
    level: LevelView
    fsp: FspEmployerBlock
    work_formats: list[WorkFormat]
    relocation_ready: bool
    declared: DeclaredView | None
    #: Свои теги навыков вне справочника; пусто до раскрытия.
    custom_skills: list[str] = []
    #: `None` вне контекста потребности.
    match: MatchExplanationEmployerView | None = None
    strength: StrengthView
    skills: list[EvidenceItem]


class CandidateEvidenceView(BaseModel):
    """Собственные навыки кандидата с источниками и вклады в силу (Арх. 6.10); сравнений с другими нет."""

    skills: list[EvidenceItem]
    #: `None`, пока нет категории.
    strength: StrengthView | None
