"""Типы модуля `demo`: ответы эндпоинтов `/demo/*` (Арх. 9.10, 13.5).

В сигнатурах фасада `demo.service` собственных типов нет; эти модели — схемы эндпоинтов.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

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
