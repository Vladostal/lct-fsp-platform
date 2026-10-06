"""Модели запросов и ответов эндпоинтов модуля `profile` (Арх. 9.6, 9.11; приложение B, §1.5, §8.2; E, §10.2).

Здесь только схемы собственных эндпоинтов. Типы, которые встречаются в сигнатурах фасада, лежат в `dto.py`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.profile.dto import ConditionsData, PrivacySettingsDTO, ProfileData
from app.shared.enums import AccessKind, DiscloseField, PauseReason, VisibilityState, WorkFormat
from app.shared.schemas import Ref

Confidence = Literal["high", "medium", "low"]

# --- профиль ---------------------------------------------------------------------------------------------------------


class ProfileDeclaredSkill(BaseModel):
    """Заявленный навык в ответе: навык справочника (`custom = false`) либо свой тег."""

    code: str | None
    title: str
    kind: str | None
    custom: bool
    source: Literal["manual", "resume"]


class ProfileHints(BaseModel):
    """Подсказки из резюме: предвыбор в опросе и на шаге грейда; в форму профиля не попадают."""

    grade_hint: str | None
    specialization_hint: str | None


class ProfileCompleteness(BaseModel):
    """Заполненность формы: `missing` — имена незаполненных полей."""

    filled: int
    total: int
    missing: list[str]


class ProfileResumeBrief(BaseModel):
    """Последняя загрузка резюме."""

    upload_id: UUID
    status: Literal["parsed", "failed"]
    created_at: datetime


class CandidateProfileView(BaseModel):
    """Профиль кандидата глазами самого кандидата. Статусы навыков и сила профиля — в `CandidateEvidenceView`."""

    public_code: str
    email: str
    last_name: str | None
    first_name: str | None
    middle_name: str | None
    city: str | None
    phone: str | None
    telegram: str | None
    link: str | None
    experience_years: float | None
    roles: list[Ref]
    about: str | None
    declared_skills: list[ProfileDeclaredSkill]
    hints: ProfileHints
    completeness: ProfileCompleteness
    resume: ProfileResumeBrief | None


class CandidateProfileUpdate(ProfileData):
    """Тело `PUT /candidate/profile`: полная замена редактируемых полей."""


# --- резюме ----------------------------------------------------------------------------------------------------------


class ResumeField(BaseModel):
    """Распознанное поле резюме: значение, уверенность и строка-источник."""

    value: str | float | list[Ref]
    confidence: Confidence
    snippet: str | None = None


class ResumeMeta(BaseModel):
    pages: int
    chars: int
    engine: str
    ms: int
    parser_version: str


class ResumeParseResult(BaseModel):
    """Результат разбора резюме. Сервер ничего не пишет в профиль: значения только предзаполняют форму.

    Ключи `fields`: `last_name`, `first_name`, `middle_name`, `email`, `phone`, `telegram`, `link`, `city`,
    `experience_years`, `roles`, `declared_skills`, `soft_skills`, `about`, `grade_hint`, `specialization_hint`;
    поле без значения отсутствует. `total = 9`: ФИО, e-mail, телефон, город, стаж, роли, стек, софт-скиллы, грейд.
    """

    upload_id: UUID
    status: Literal["parsed"] = "parsed"
    fields: dict[str, ResumeField]
    recognized: int
    total: int
    unknown_terms: list[str]
    meta: ResumeMeta


# --- условия, приватность, показ -------------------------------------------------------------------------------------


class ConditionsView(BaseModel):
    """Условия кандидата. Минимум зарплаты видит только сам кандидат."""

    min_salary: int | None
    work_formats: list[WorkFormat]
    relocation_ready: bool


class ConditionsUpdate(ConditionsData):
    """Тело `PUT /candidate/conditions`."""


class PrivacySettings(PrivacySettingsDTO):
    """Настройки приватности — и тело `PUT`, и ответ. Если `hidden_domains` (P1) в запросе не передан, сохранённый
    список не меняется.
    """


class VisibilityView(BaseModel):
    state: VisibilityState
    pause_reason: PauseReason | None
    auto_paused_until: datetime | None


class ConsentItem(BaseModel):
    granted: bool
    version: str | None
    current_version: str
    granted_at: datetime | None


class ConsentsView(BaseModel):
    processing: ConsentItem
    publication: ConsentItem
    fsp_data: ConsentItem | None
    visibility: VisibilityView


class PublicationConsentRequest(BaseModel):
    action: Literal["grant", "revoke"]
    version: str = Field(max_length=64)


class VisibilityRequest(BaseModel):
    """Ручная пауза показа: `paused` — поставить, `visible` — снять."""

    state: Literal["visible", "paused"]


# --- журнал доступа и контакты ---------------------------------------------------------------------------------------


class AccessLogRef(BaseModel):
    type: Literal["invitation", "application"]
    id: UUID


class AccessLogItem(BaseModel):
    at: datetime
    company_name: str
    kind: AccessKind
    kind_label: str
    ref: AccessLogRef | None


class CandidateContactsView(BaseModel):
    """Контакты кандидата для раскрытой пары: только каналы, выбранные кандидатом.

    `masked = true` — пара «демо-компания — живой кандидат»: во всех полях заглушки (Арх. 4.14).
    """

    candidate_id: UUID
    public_code: str
    first_name: str
    last_name: str
    middle_name: str | None
    email: str | None
    phone: str | None
    telegram: str | None
    link: str | None
    custom_skills: list[str]
    disclosed_fields: list[DiscloseField]
    disclosed_at: datetime
    masked: bool
