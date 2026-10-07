"""Типы фасада `matching.service` (Арх. 2.5, 4.9, 6.11, 6.12, 9.11).

Здесь лежит всё, что стоит в сигнатурах фасада и что включает в свои схемы верхний модуль `contact`:
`InvitationWhy`, `RelaxationHint`, `ShortlistItemView`, `NeedRefDTO`.
Схемы собственных эндпоинтов модуля — в `schemas.py`.

Файл не импортирует SQLAlchemy: `ShortlistQuery` читают чистые ядра `scoring.py` и `ranking.py`.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from app.shared.enums import DiffMark, FitBand, Relation, WorkFormat
from app.shared.schemas import CategoryRef, EvidenceItem, Ref


class ShortlistRefinement(BaseModel):
    """Уточнение запроса подборки (Арх. 6.11): все поля необязательны.

    `None` — «взять у родителя». Исключение — `grade_codes`: пустой список возвращает автоматический набор
    разделов (Арх. 6.3). `specialization_code` и `grade_code` принимаются для совместимости со схемой и не
    применяются: специализация и целевой грейд — всегда из потребности.
    """

    specialization_code: str | None = None
    grade_code: str | None = None
    grade_codes: list[str] | None = None
    must_skills: list[str] | None = None
    nice_skills: list[str] | None = None
    work_formats: list[WorkFormat] | None = None
    salary_from: int | None = None
    salary_to: int | None = None
    require_fsp: bool | None = None


class ShortlistQuery(BaseModel):
    """Запрос подборки; хранится в версии целиком, в каноническом виде (Арх. 6.11).

    Канонический вид: списки без дублей и отсортированы; навык из обоих списков остаётся в `must_skills`.
    """

    specialization_code: str
    grade_code: str
    #: `None` — автоматический набор разделов (Арх. 6.3); список только сужает его.
    grade_codes: list[str] | None = None
    must_skills: list[str] = []
    nice_skills: list[str] = []
    work_formats: list[WorkFormat] = []
    #: На результат не влияют.
    salary_from: int | None = None
    salary_to: int | None = None
    require_fsp: bool = False


class NeedRefDTO(BaseModel):
    """Потребность работодателя — в объёме, нужном приглашению и вакансии."""

    need_id: UUID
    employer_id: UUID
    title: str
    category_code: str
    work_formats: list[WorkFormat]
    city: str | None = None
    salary_from: int
    salary_to: int
    team_description: str = ""
    snapshot_id: UUID | None = None


class NeedData(BaseModel):
    """Входные данные `create_need` и правки потребности (Арх. 6.14)."""

    title: str
    source_text: str | None = None
    team_description: str = ""
    specialization_code: str
    grade_code: str
    must_skills: list[str] = []
    nice_skills: list[str] = []
    work_formats: list[WorkFormat]
    city: str | None = None
    salary_from: int
    salary_to: int
    #: Сведения разборщика текста: `parser`, `parser_version`, `confidence` по полям.
    parse_meta: dict[str, Any] | None = None


class UnconfirmedSkill(BaseModel):
    """Обязательный навык, который у кандидата только заявлен."""

    skill: Ref


class InterestRef(BaseModel):
    """Сигнал интереса кандидата к вакансии (P2)."""

    vacancy_title: str


class InvitationWhy(BaseModel):
    """«Почему вас пригласили» — публичная проекция для кандидата (Арх. 4.9).

    Позиции, полосы совпадения, доводов, риска и вкладов здесь нет по построению.
    """

    source: Literal["need", "bank"]
    #: Кого искал работодатель (в банке — категория кандидата).
    target: CategoryRef
    #: Требования, подкреплённые `test | pulse | fsp | declared`; из банка — до шести сильнейших подтверждённых.
    matched: list[EvidenceItem] = []
    #: Первый обязательный навык с `kind = declared`.
    unconfirmed: UnconfirmedSkill | None = None
    interest: InterestRef | None = None
    #: Что было видно работодателю до согласия.
    employer_saw: list[str] = []


class InvitationExplain(BaseModel):
    """Объяснение для приглашения: проекция кандидату, полоса совпадения на момент отправки, версия оценщика."""

    why: InvitationWhy
    fit_band: FitBand | None = None
    scorer_version: str


class RelaxationHint(BaseModel):
    """Подсказка-контрфакт: что ослабить в потребности и сколько кандидатов это добавит (Арх. 6.12)."""

    code: Literal["move_must_to_nice", "add_format", "drop_require_fsp"]
    #: Код навыка или формата.
    value: str | None = None
    text: str
    gain: int
    #: Готовое уточнение для кнопки «Применить».
    refinement: ShortlistRefinement


class ExposureStats(BaseModel):
    """Показы кандидата за окно — для воронки (Арх. 4.12, 6.13).

    `unconfirmed_must` — обязательные навыки, которые в потребностях с этим кандидатом были у него `declared`
    или `none`: по одному элементу на пару «потребность — навык» (навык повторяется столько раз, в скольких
    потребностях он не подтверждён), по убыванию частоты.
    """

    needs_shown: int = 0
    employers_opened: int = 0
    unconfirmed_must: list[str] = []


class ShortlistItemView(BaseModel):
    """Строка подборки (Арх. 9.11). В списках нет процентов и баллов."""

    candidate_id: UUID
    public_code: str
    display_name: str | None = None
    is_demo: bool = False
    category: CategoryRef
    relation: Relation
    grade_margin: bool = False
    position: int
    fit_band: FitBand | None = None
    strength_label: Literal["high", "medium", "base"]
    must_covered: int = 0
    must_total: int = 0
    top_evidence: list[EvidenceItem] = []
    evidence_more: int = 0
    fsp_summary: str | None = None
    formats_common: list[WorkFormat] = []
    freshness_days: int = 0
    stale: bool = False
    risk: str | None = None
    diff_mark: DiffMark = DiffMark.SAME
    diff_delta: int | None = None
    pinned: bool = False
    #: `False` — только у раскрытой пары со скрытым профилем.
    available: bool = True
    unavailable_reason: Literal["paused", "withdrawn"] | None = None
