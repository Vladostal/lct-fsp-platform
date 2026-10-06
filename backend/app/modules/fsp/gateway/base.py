"""Интерфейс шлюза `FspGateway`, модели контракта реестра и исключения (Арх. 7.2, 7.3; приложение D, §2.3–2.4).

Модели разбора ответа — со стороны платформы: `extra="ignore"` (клиент игнорирует неизвестные поля), поля-перечисления
объявлены строками, сопоставление с известными значениями идёт на шаге нормализации. Новое значение на стороне ФСП
поэтому не роняет синхронизацию. Эти модели не зависят от `app.fsp_mock`: платформа и «ФСП» связаны только контрактом.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, NamedTuple, Protocol

from pydantic import BaseModel, ConfigDict


class _Contract(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Competition(_Contract):
    """Соревнование ЕКП (R5, R6 и вложено в участие)."""

    competition_id: str
    title: str
    ekp_number: str | None = None
    discipline_code: str
    level: str
    kind: str = "other"
    stage: str = "single"
    series_code: str | None = None
    age_group: str = "adults"
    participation: str = "individual"
    team_size_min: int | None = None
    team_size_max: int | None = None
    format: str = "onsite"
    status: str
    protocol_status: str = "none"
    date_start: date | None = None
    date_end: date | None = None
    registration_deadline: date | None = None
    city: str | None = None
    region_code: str | None = None
    organizer: str | None = None
    entries_count: int | None = None
    athletes_count: int | None = None
    regions_count: int | None = None
    registration_url: str | None = None
    protocol_url: str | None = None


class EntryInfo(_Contract):
    kind: str = "individual"
    team_name: str | None = None
    team_size: int | None = None
    region_code: str | None = None


class ResultInfo(_Contract):
    status: str
    place: int | None = None
    place_to: int | None = None
    score: float | None = None
    score_max: float | None = None
    solved: int | None = None
    problems_total: int | None = None
    penalty: int | None = None


class Anonymity(_Contract):
    period: str
    k_a: int
    k_b: int


class ParticipationRecord(_Contract):
    entry_id: str
    member_role: str
    is_captain: bool = False
    entry: EntryInfo
    competition: Competition
    result: ResultInfo
    anonymity: Anonymity | None = None


class RankRecord(_Contract):
    rank_id: str
    rank_code: str
    assigned_on: date | None = None
    valid_until: date | None = None
    order_number: str | None = None
    assigned_by: str | None = None
    discipline_code: str | None = None
    revoked_on: date | None = None


class AthleteInfo(_Contract):
    fsp_id: str
    is_adult: bool
    region_code: str | None = None
    status: str = "active"


class AthleteExport(_Contract):
    """Единая выгрузка о спортсмене (R3). Поля `norm`, `judge`, `national_team`, `rating` игнорируются."""

    schema_version: str
    generated_at: datetime | None = None
    athlete: AthleteInfo
    participations: list[ParticipationRecord] = []
    ranks: list[RankRecord] = []


# --- исключения -------------------------------------------------------------------------------------------------------


class FspError(Exception):
    """Общий предок исключений шлюза."""


class FspAuthError(FspError):
    """Код недействителен, PKCE не сошёлся, подпись или поля ID-токена, 401/403 без кода разрешения."""


class FspGrantRevoked(FspError):
    """403 `grant_required` или `grant_revoked`: спортсмен снял разрешение на стороне ФСП."""


class FspUnavailable(FspError):
    """Таймаут, ошибка соединения, 429, 5xx."""

    def __init__(self, message: str = "реестр недоступен", retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class FspContractError(FspError):
    """Невалидный JSON, тело не по схеме, `schema_version` не `1.x`, чужой `fsp_id`, тело больше 2 МБ."""


# --- данные шлюза -----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AuthorizationRequest:
    state: str
    nonce: str
    code_challenge: str
    redirect_uri: str
    scope: str


@dataclass(frozen=True)
class FspIdentity:
    issuer: str
    subject: str
    #: Утверждение `fsp_id`, иначе `sub`.
    fsp_id: str
    #: Токен пользователя живёт только внутри запроса callback и нигде не сохраняется.
    user_token: str | None


class ExportOk(NamedTuple):
    export: AthleteExport
    etag: str | None
    #: Тело ответа как есть: по нему считается `payload_sha256` и сохраняется снимок.
    raw: dict[str, Any]
    api_version: str


class ExportNotModified(NamedTuple):
    """304: выгрузка не изменилась."""


class ExportNotRegistered(NamedTuple):
    """404 `athlete_not_found`: у ФСП ID нет записи спортсмена."""


ExportResult = ExportOk | ExportNotModified | ExportNotRegistered


class FspGateway(Protocol):
    """Единый интерфейс двух адаптеров: демо-провайдера (`mock`) и Keycloak (`keycloak`, P1)."""

    mode: Literal["mock", "keycloak"]

    def authorization_url(self, req: AuthorizationRequest) -> str: ...

    def exchange_code(self, *, code: str, code_verifier: str, redirect_uri: str, nonce: str) -> FspIdentity: ...

    def fetch_export(self, fsp_id: str, *, user_token: str | None = None, etag: str | None = None) -> ExportResult: ...

    def revoke_grant(self, fsp_id: str) -> None: ...

    def list_competitions(self, *, statuses: Sequence[str], date_from: date, limit: int = 50) -> list[Competition]: ...

    def health(self) -> bool: ...

    @property
    def issuer(self) -> str:
        """Издатель ID-токенов: записывается в `external_identity.issuer`."""
        ...

    @property
    def registry_url(self) -> str:
        """Базовый адрес реестра для снимка (`fsp_snapshot.registry_url`)."""
        ...
