"""Типы модуля `demo`: ответы эндпоинтов `/demo/*` (Арх. 9.10, 13.5).

В сигнатурах фасада `demo.service` собственных типов нет; эти модели — схемы эндпоинтов.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.shared.enums import Role


class DemoAccount(BaseModel):
    """Строка таблицы демо-аккаунтов на `/demo`: ключ входа, название, роль и описание состояния."""

    key: str
    title: str
    role: Role
    state_label: str


class DemoLoginRequest(BaseModel):
    account_key: str


class DemoMe(BaseModel):
    """Вошедший демо-пользователь (те же поля, что у `MeView` модуля `identity`)."""

    id: UUID
    email: str
    role: Role
    is_demo: bool
    server_now: datetime


class RestartResult(BaseModel):
    restarted_at: datetime


class QuickSessionRequest(BaseModel):
    """Быстрый демо-тест: грейд, на который кандидат начинает тест."""

    grade_code: str = Field(min_length=1, max_length=32)


class QuickSessionResult(BaseModel):
    session_id: UUID


class DemoClock(BaseModel):
    """Часы сервиса: текущее время сервиса и накопленный демо-сдвиг."""

    now: datetime
    offset_seconds: int


class ClockAdvance(BaseModel):
    """Сдвиг часов вперёд; `force` — сдвинуть, даже если есть идущие тесты (их время выйдет)."""

    hours: int = Field(ge=1, le=24 * 31)
    force: bool = False


class ResetResult(BaseModel):
    reset_at: datetime
