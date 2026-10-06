"""Типы фасада `fsp.service` и блока ФСП для работодателя (Арх. 2.5, 7.6, 7.7; приложение D, §5.7–5.9, §10.2, §10.3)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

UnlinkReason = Literal["user", "revoked", "minor", "account_deleted", "demo_reset"]


class FspSubject(BaseModel):
    """Кандидат, для которого запрашивается сигнал: настройки приватности передаёт вызывающий."""

    model_config = ConfigDict(frozen=True)

    user_id: UUID
    #: Код специализации текущей категории кандидата.
    specialization: str | None
    #: Настройка приватности `show_fsp_summary`.
    show_summary: bool


class FspLinkBrief(BaseModel):
    """Кратко о привязке — для строки «Усилить профиль»."""

    model_config = ConfigDict(frozen=True)

    status: Literal["not_linked", "linked"]
    history_status: str | None = None
    #: Число зачтённых результатов.
    counted: int = 0


class FspPublicSummary(BaseModel):
    """Обобщённая строка достижений, видимая до раскрытия."""

    level: Literal[1, 2, 3]
    headline: str
    short: str
    more: bool = False
    shortened: bool = False


class FspContribution(BaseModel):
    fact_id: UUID
    p: float
    base_points: float
    decay: float
    relevance: float
    order_weight: float


class FspSignal(BaseModel):
    """Сигнал ФСП для подбора (приложение D, §5.9). Без привязки или при `show_summary = false` — нулевой."""

    user_id: UUID
    #: `fsp_signal`, 0..1.
    value: float = 0.0
    results_value: float = 0.0
    floor_value: float = 0.0
    floor_source: Literal["rank", "national_team"] | None = None
    #: Число зачтённых фактов.
    counted: int = 0
    contributions: list[FspContribution] = []
    leadership_level: Literal["none", "basic", "strong"] = "none"
    band: Literal["none", "low", "medium", "high"] = "none"
    visible: bool = False
    #: `visible` и есть подтверждённые факты: фильтр «есть достижения ФСП».
    verified: bool = False
    public: FspPublicSummary | None = None
    version: str = ""


class FspSkillEvidence(BaseModel):
    """Навык, подтверждённый фактом ФСП."""

    skill_code: str
    source: Literal["discipline", "role"]
    #: `fsp_achievement.id` или `fsp_credential.id`.
    fact_id: UUID
    confirmed_at: date
    #: До раскрытия: «достижение ФСП · алгоритмическое программирование».
    detail_public: str
    #: После раскрытия; в версиях подборок не сохраняется.
    detail_full: str


class FspNormView(BaseModel):
    """Зарезервировано: метка норматива разряда (Арх. 15.1, № 47: в MVP не моделируется, поле всегда `None`)."""

    rank_code: str
    rank_label: str
    source: Literal["platform", "registry"]
    norms_version: str
    note: str


class FspAchievementView(BaseModel):
    """Достижение, как его видит кандидат и — после раскрытия — работодатель (приложение D, §10.2)."""

    id: UUID
    competition_title: str
    discipline_code: str
    discipline_label: str
    level: str
    level_label: str
    stage_label: str | None = None
    date_end: date | None = None
    city: str | None = None
    format_label: str | None = None
    member_role: str
    role_label: str
    is_captain: bool = False
    team_name: str | None = None
    team_size: int | None = None
    place: int | None = None
    place_to: int | None = None
    field_size: int | None = None
    #: «2 место из 16» | «2–3 место из 10» | «участие».
    place_label: str
    #: «решено 9 из 12» | «87,5 из 100 баллов».
    score_label: str | None = None
    counted: bool
    uncounted_reason: str | None = None
    uncounted_label: str | None = None
    #: `round(100 · decay)`, только у зачтённых.
    recency_percent: int | None = None
    norm: FspNormView | None = None
    protocol_url: str | None = None


class FspCredentialView(BaseModel):
    """Разряд или звание (остальные виды — вторая фаза, Арх. 15.1, № 47)."""

    id: UUID
    kind: Literal["rank", "national_team", "judge_category", "judge_assignment"] = "rank"
    code: str
    label: str
    discipline_label: str | None = None
    assigned_on: date | None = None
    valid_until: date | None = None
    active: bool
    #: «действует до 10.02.2029» | «срок действия истёк 01.06.2025».
    status_label: str | None = None


class FspLeadership(BaseModel):
    level: Literal["basic", "strong"]
    label: str


class FspSource(BaseModel):
    label: str
    checked_at: datetime


class FspEmployerBlock(BaseModel):
    """Блок ФСП в карточке кандидата и в PDF (приложение D, §10.2)."""

    mode: Literal["none", "summary", "detailed"] = "none"
    #: Только при `none`.
    neutral_text: str | None = None
    #: При `summary` и `detailed`.
    summary: FspPublicSummary | None = None
    note: str | None = None
    #: Только при `detailed`.
    achievements: list[FspAchievementView] = []
    credentials: list[FspCredentialView] = []
    leadership: FspLeadership | None = None
    source: FspSource | None = None


class DemoAthlete(BaseModel):
    """Свободный взрослый спортсмен демо-реестра для раздачи синтетическим кандидатам (приложение D, §8.4)."""

    model_config = ConfigDict(frozen=True)

    fsp_id: str
    #: Скрытая сила спортсмена: сид связывает её с уровнем кандидата (`FSP_SKILL_CORR`).
    latent_skill: float
