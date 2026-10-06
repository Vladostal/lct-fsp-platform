"""Схемы эндпоинтов `identity` (Арх. 9.4, 9.11).

Имена полей совпадают с именами полей форм: ошибка разбора уходит клиенту как 422 `validation_error`
с `fields[].name` из набора `email`, `password`, `new_password`, `current_password`, `token`, `role`,
`consent_processing`, `consent_version`, `is_adult`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, field_validator
from pydantic_core import PydanticCustomError

from app.modules.identity.constants import EMAIL_MAX_LENGTH, PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH
from app.modules.identity.emails import normalize_email
from app.shared.enums import Role

_TOKEN_MAX_LENGTH = 200

#: Новый пароль: 8–128 знаков (Арх. 10.1). Пробелы по краям не обрезаются — это часть пароля.
NewPassword = Annotated[str, StringConstraints(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)]
#: Пароль, который только сверяется: длина ограничена, правила состава не проверяются.
PasswordToCheck = Annotated[str, StringConstraints(min_length=1, max_length=PASSWORD_MAX_LENGTH)]
Token = Annotated[str, StringConstraints(min_length=1, max_length=_TOKEN_MAX_LENGTH)]
#: Адрес для поиска аккаунта: приводится к нижнему регистру, формат не проверяется — ответ и так одинаков
#: для существующего и несуществующего адреса, а демо-аккаунты живут на `demo.test`.
LookupEmail = Annotated[
    str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=1, max_length=EMAIL_MAX_LENGTH)
]


def _must_be_true(value: Any, code: str, message: str) -> Any:
    if value is not True:
        raise PydanticCustomError(code, message)
    return value


class SignupRequest(BaseModel):
    """Регистрация (Арх. 9.11): оба флажка обязаны быть отмечены, версия согласия — действующая."""

    email: str = Field(max_length=EMAIL_MAX_LENGTH, json_schema_extra={"format": "email"})
    password: NewPassword
    role: Role
    consent_processing: Literal[True]
    consent_version: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    is_adult: Literal[True]

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        normalized = normalize_email(value)
        if normalized is None:
            raise PydanticCustomError("email_invalid", "Укажите адрес почты, например name@example.com")
        return normalized

    @field_validator("consent_processing", mode="before")
    @classmethod
    def _consent(cls, value: Any) -> Any:
        return _must_be_true(value, "consent_required", "Нужно согласие на обработку персональных данных")

    @field_validator("is_adult", mode="before")
    @classmethod
    def _adult(cls, value: Any) -> Any:
        return _must_be_true(value, "adult_required", "Регистрация доступна с 18 лет")


class LoginRequest(BaseModel):
    """Вход по адресу и паролю."""

    email: LookupEmail
    password: PasswordToCheck


class EmailRequest(BaseModel):
    """Тело запросов, где нужен только адрес: повторная отправка письма, запрос сброса пароля."""

    email: LookupEmail


class VerifyEmailRequest(BaseModel):
    """Подтверждение адреса. `password` нужен, только если ссылку открыли не в браузере регистрации (Арх. 10.2)."""

    token: Token
    password: PasswordToCheck | None = None


class PasswordChangeRequest(BaseModel):
    """Смена пароля вошедшим пользователем."""

    current_password: PasswordToCheck
    new_password: NewPassword


class PasswordResetRequest(BaseModel):
    """Новый пароль по ссылке из письма."""

    token: Token
    new_password: NewPassword


class AccountDeleteRequest(BaseModel):
    """Отзыв согласия на обработку и удаление аккаунта: подтверждается паролем."""

    password: PasswordToCheck


class MeView(BaseModel):
    """Текущий пользователь. `server_now` — время сервиса (с демо-сдвигом): по нему клиент считает сроки."""

    id: UUID
    email: str
    role: Role
    is_demo: bool
    server_now: datetime


class LegalDocView(BaseModel):
    """Текст согласия или политики; `sha256` — контрольная сумма `text`."""

    doc: str
    version: str
    title: str
    text: str
    sha256: str
