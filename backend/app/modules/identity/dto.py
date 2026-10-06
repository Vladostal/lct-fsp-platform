"""Типы фасада `identity.service` (Арх. 2.5)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.shared.enums import Role


class UserDTO(BaseModel):
    """Пользователь; `id` — он же `candidate_id` или `employer_id`.

    `is_demo` — признак аккаунта (`app_user.is_demo`): по нему, а не по чипу показа, принимаются решения
    о маскировании и об отправке приглашений (Арх. 10.3, 10.4).
    """

    model_config = ConfigDict(frozen=True)

    id: UUID
    email: str
    role: Role
    is_demo: bool
    email_verified_at: datetime | None
    created_at: datetime


class ConsentDTO(BaseModel):
    """Последнее согласие пользователя одного вида; `revoked_at` задан — согласие отозвано."""

    model_config = ConfigDict(frozen=True)

    version: str
    granted_at: datetime
    revoked_at: datetime | None = None


class ConsentTextDTO(BaseModel):
    """Действующий текст согласия; `sha256` — контрольная сумма `text`, она же пишется в `consent.text_sha256`."""

    model_config = ConfigDict(frozen=True)

    version: str
    title: str
    text: str
    sha256: str
