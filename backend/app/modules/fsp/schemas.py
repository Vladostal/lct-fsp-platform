"""Схемы API модуля `fsp` (Арх. 9.7, 9.11; приложение D, §10.2). Блок для работодателя и его части — в `dto.py`."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.fsp.dto import FspAchievementView, FspCredentialView, FspPublicSummary

SyncOutcomeValue = Literal[
    "ok_changed",
    "ok_unchanged",
    "in_progress",
    "failed_unavailable",
    "failed_contract",
    "failed_auth",
    "failed_timeout",
    "unlinked_revoked",
    "unlinked_minor",
]


class FspConsentView(BaseModel):
    version: str
    text: str
    text_sha256: str
    data_items: list[str]


class FspLinkStartRequest(BaseModel):
    """Тело `POST /fsp/link/start`: согласие записывается до запроса данных."""

    accept: bool
    consent_version: str = Field(max_length=64)


class FspLinkStartView(BaseModel):
    authorize_url: str
    expires_at: datetime


class FspConsentBrief(BaseModel):
    version: str
    granted_at: datetime


class FspRefresh(BaseModel):
    checked_at: datetime | None = None
    fetched_at: datetime | None = None
    source_label: str | None = None
    #: `checked_at` старше `SNAPSHOT_STALE_DAYS`.
    stale: bool = False
    last_outcome: SyncOutcomeValue | None = None
    last_attempt_at: datetime | None = None
    #: Раньше этого момента `POST /fsp/sync` вернёт 429.
    can_sync_at: datetime | None = None


class FspSignalBrief(BaseModel):
    band: Literal["none", "low", "medium", "high"]
    counted: int
    leadership_level: Literal["none", "basic", "strong"]


class FspLinkView(BaseModel):
    status: Literal["not_linked", "linked"]
    provider_mode: Literal["mock", "keycloak"]
    linked_at: datetime | None = None
    #: «…a41f» — последние 4 символа `fsp_id`.
    subject_hint: str | None = None
    history_status: Literal["has_history", "no_history", "sync_pending", "sync_failed"] | None = None
    no_history_reason: Literal["athlete_not_found", "no_results", "no_counted_results"] | None = None
    notice: Literal["unlinked_revoked", "unlinked_minor"] | None = None
    consent: FspConsentBrief | None = None
    refresh: FspRefresh = FspRefresh()
    last_sync_at: datetime | None = None
    signal: FspSignalBrief | None = None
    achievements: list[FspAchievementView] = []
    credentials: list[FspCredentialView] = []
    employer_preview: FspPublicSummary | None = None


class FspCalendarItem(BaseModel):
    competition_id: str
    title: str
    discipline_label: str
    level_label: str
    age_group_label: str
    date_start: date
    date_end: date
    format_label: str
    city: str | None = None
    status: Literal["registration_open", "scheduled"]
    registration_deadline: date | None = None
    registration_url: str | None = None


class FspCalendarView(BaseModel):
    items: list[FspCalendarItem]
    fetched_at: datetime | None = None
    stale: bool = False
    source_label: str
