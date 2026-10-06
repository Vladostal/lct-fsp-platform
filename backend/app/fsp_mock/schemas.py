"""Схемы контракта реестра ФСП (Арх. 7.2; приложение D, §2.3) — то, что публикуется как `fsp-registry-openapi.json`.

Правила расширения контракта: добавление полей и значений перечислений не меняет мажорную версию; клиент обязан
игнорировать неизвестные поля и переносить неизвестные значения перечислений без падения. Поэтому перечисления
объявлены строками, а их известные значения отдаёт `GET /dictionaries`.

Выгрузка **не содержит** ФИО, дату рождения, пол, контакты, документы и составы чужих команд. Поля `norm`, `judge`,
`national_team`, `rating` зарезервированы под вторую фазу: в версии 1.0 демо-реестр отдаёт их пустыми.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Competition(BaseModel):
    """Соревнование ЕКП."""

    competition_id: str
    title: str
    ekp_number: str | None = None
    discipline_code: str
    level: str
    kind: str
    stage: str
    series_code: str | None = None
    age_group: str
    participation: str
    team_size_min: int | None = None
    team_size_max: int | None = None
    format: str
    status: str
    protocol_status: str
    date_start: date
    date_end: date
    registration_deadline: date | None = None
    city: str | None = None
    region_code: str | None = None
    organizer: str | None = None
    entries_count: int | None = Field(default=None, description="Размер поля: число строк итогового протокола")
    athletes_count: int | None = None
    regions_count: int | None = None
    registration_url: str | None = None
    protocol_url: str | None = None


class CompetitionPage(BaseModel):
    """Страница календаря."""

    items: list[Competition]
    next_cursor: str | None = None


class EntryInfo(BaseModel):
    """Строка протокола без состава: размер команды — числом."""

    kind: str
    team_name: str | None = None
    team_size: int | None = None
    region_code: str | None = None


class ResultInfo(BaseModel):
    """Результат строки протокола."""

    status: str
    place: int | None = None
    place_to: int | None = None
    score: float | None = None
    score_max: float | None = None
    solved: int | None = None
    problems_total: int | None = None
    penalty: int | None = None


class Anonymity(BaseModel):
    """Счётчики анонимности: сколько спортсменов реестра имеют зачётный результат с теми же признаками."""

    period: Literal["recent", "mid", "old"]
    k_a: int = Field(description="та же дисциплина, уровень (огрублённый), период и корзина результата")
    k_b: int = Field(description="та же дисциплина и уровень (огрублённый)")


class NormInfo(BaseModel):
    """Зарезервировано: норматив разряда, посчитанный реестром."""

    rank_code: str
    norms_version: str


class ParticipationRecord(BaseModel):
    """Участие самого спортсмена: роль, строка протокола, соревнование, результат."""

    entry_id: str
    member_role: str
    is_captain: bool
    entry: EntryInfo
    competition: Competition
    result: ResultInfo
    norm: NormInfo | None = Field(default=None, description="зарезервировано; в версии 1.0 всегда null")
    anonymity: Anonymity | None = None


class RankRecord(BaseModel):
    """Разряд или звание."""

    rank_id: str
    rank_code: str
    assigned_on: date
    valid_until: date | None = None
    order_number: str | None = None
    assigned_by: str | None = None
    discipline_code: str | None = None
    revoked_on: date | None = None


class AthleteInfo(BaseModel):
    """Спортсмен: возраст — только признаком `is_adult`."""

    fsp_id: str
    is_adult: bool
    region_code: str | None = None
    status: str


class SourceInfo(BaseModel):
    registry: str = "fsp"
    environment: str = "mock"


class AthleteExport(BaseModel):
    """Единая выгрузка сведений об одном спортсмене (R3)."""

    schema_version: str
    generated_at: datetime
    source: SourceInfo
    athlete: AthleteInfo
    participations: list[ParticipationRecord]
    ranks: list[RankRecord]
    judge: dict[str, Any] | None = Field(default=None, description="зарезервировано; в версии 1.0 всегда null")
    national_team: list[dict[str, Any]] = Field(default_factory=list, description="зарезервировано; всегда пусто")
    rating: dict[str, Any] | None = Field(default=None, description="зарезервировано; в версии 1.0 всегда null")


class DictionaryItem(BaseModel):
    code: str
    title: str


class DisciplineItem(DictionaryItem):
    participation: list[str]
    team_size_min: int | None = None
    team_size_max: int | None = None
    result_model: str


class RankItem(DictionaryItem):
    validity_years: int | None = Field(default=None, description="срок действия; null — бессрочно")


class Dictionaries(BaseModel):
    """Словари реестра (R2)."""

    schema_version: str
    disciplines: list[DisciplineItem]
    levels: list[DictionaryItem]
    kinds: list[DictionaryItem]
    stages: list[DictionaryItem]
    age_groups: list[DictionaryItem]
    ranks: list[RankItem]


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    version: str


class Problem(BaseModel):
    """Ошибка реестра: `application/problem+json` (RFC 9457) с полем `code`."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    code: str
    request_id: str | None = None


# --- служебные ручки ведущего -----------------------------------------------------------------------------------------


class ControlRequest(BaseModel):
    failure_mode: Literal["none", "unavailable", "slow", "malformed"]


class ControlView(BaseModel):
    failure_mode: str


class AddParticipationRequest(BaseModel):
    """Добавить спортсмену результат в существующее завершённое соревнование."""

    competition_id: str
    place: int = Field(ge=1, le=1000)
    team_name: str | None = Field(default=None, max_length=80)


class AddParticipationView(BaseModel):
    entry_id: str
    competition_id: str
    place: int


class ResetView(BaseModel):
    athletes: int
    competitions: int
    entries: int
