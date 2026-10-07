"""Типы фасада `contact.service` (Арх. 2.5, 4.2, 4.8; приложение C, §5.3).

Здесь только то, что стоит в сигнатурах функций фасада: входные данные функций записи (их строят роутер модуля,
сид и модуль `demo`) и результаты для верхнего модуля `demo`. Схемы ответов эндпоинтов — в `schemas.py`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.shared.enums import (
    ConditionKind,
    DeclineReason,
    EventActor,
    EventCode,
    FitBand,
    InvitationStatus,
    WorkFormat,
)
from app.shared.schemas import ContactMethod


class DeclineCondition(BaseModel):
    """Условие отказа: «от {value}» при причине `salary` либо формат работы при причине `format` (Арх. 4.8).

    Соответствие вида и значения проверяет сервис (`rules.decline_condition_ok`): нарушение — 422 `condition_invalid`.
    """

    kind: ConditionKind
    value: int | WorkFormat


class InvitationData(BaseModel):
    """Входные данные `send_invitation`: условия предложения и адресат (приложение C: `InvitationCreate`).

    При пересмотре (`revises_id`) кандидат, потребность и версия подборки берутся из исходного приглашения;
    `candidate_id` обязан совпадать с адресатом исходного (поправка R3-data-api-security-1).
    """

    candidate_id: UUID
    title: str
    description: str
    salary_from: int
    salary_to: int
    work_format: WorkFormat
    city: str | None = None
    contact_method: ContactMethod
    message: str | None = None
    need_id: UUID | None = None
    snapshot_id: UUID | None = None
    #: Пересмотренное приглашение: идентификатор исходного (Арх. 4.8).
    revises_id: UUID | None = None


class InvitationDTO(BaseModel):
    """Приглашение — результат функций записи фасада. Минимума кандидата и текста условий здесь нет."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    employer_id: UUID
    candidate_id: UUID
    need_id: UUID | None = None
    snapshot_id: UUID | None = None
    revises_id: UUID | None = None
    #: Фактический (материализованный) статус.
    status: InvitationStatus
    is_demo: bool = False
    fit_band_at_send: FitBand | None = None
    created_at: datetime
    expires_at: datetime
    viewed_at: datetime | None = None
    resolved_at: datetime | None = None
    slot_release_at: datetime | None = None
    pair_block_until: datetime | None = None
    decline_reason: DeclineReason | None = None
    updated_at: datetime


class InvitationEventDTO(BaseModel):
    """Событие истории приглашения для исходящих вебхуков (P2): без персональных данных.

    `payload` несёт только служебные признаки события (`fields` — виды раскрытых каналов, `reason` — код причины,
    `revision_id`, `demo`); значений контактов, комментариев и сумм в нём нет.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    invitation_id: UUID
    employer_id: UUID
    code: EventCode
    actor: EventActor
    at: datetime
    payload: dict[str, Any] = {}


class InvitationExportDTO(BaseModel):
    """Приглашение для выгрузки кандидата после согласия (P2): статус и снимок условий работодателя."""

    id: UUID
    employer_id: UUID
    candidate_id: UUID
    need_id: UUID | None = None
    status: InvitationStatus
    created_at: datetime
    resolved_at: datetime | None = None
    title: str
    salary_from: int
    salary_to: int
    work_format: WorkFormat
    city: str | None = None
