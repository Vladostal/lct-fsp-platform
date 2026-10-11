"""Общие типы API (Арх. 9.11, 9.2): используются схемами и DTO нескольких модулей.

Модуль включает такой тип как поле своей схемы, не копируя его (Арх. 2.4, п. 1).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.shared.enums import CategoryBasis, ContactKind, EvidenceKind


class Ref(BaseModel):
    """Ссылка на элемент справочника: код и подпись."""

    model_config = ConfigDict(frozen=True)

    code: str
    title: str


class CategoryRef(BaseModel):
    """Категория «специализация × грейд»: `code` — «backend:middle», `title` — «Backend · Middle»."""

    model_config = ConfigDict(frozen=True)

    code: str
    title: str
    specialization: Ref
    grade: Ref
    #: Основание категории кандидата; `None` — это не категория кандидата (цель потребности, справочник).
    basis: CategoryBasis | None = None


class ContactMethod(BaseModel):
    """Способ связи: вид и значение (проверка — `app.shared.contact_method`)."""

    kind: ContactKind
    value: str


class EvidenceItem(BaseModel):
    """Навык или требование вместе с видом доказательства (Арх. 1.2, п. 2; 6.2)."""

    skill: Ref
    priority: Literal["must", "nice"] | None = None
    kind: EvidenceKind
    kind_label: str
    via_skill: Ref | None = None
    detail: str | None = None
    confirmed_at: datetime | None = None


class Contribution(BaseModel):
    """Вклад в покрытие требований или в силу профиля (Арх. 6.10)."""

    group: Literal["coverage", "strength"]
    code: str
    label: str
    points: float
    max_points: float


class Page[T](BaseModel):
    """Страница списка с продолжением (Арх. 9.3). `next_cursor = None` — список закончился."""

    items: list[T]
    next_cursor: str | None = None


class ApiErrorField(BaseModel):
    """Ошибка поля формы; `name` совпадает с именем поля (вложенные — через точку)."""

    name: str
    code: str
    message: str


class ApiError(BaseModel):
    """Единый формат ошибки API (Арх. 9.2). Клиент берёт текст по `code`, параметры — из `params`."""

    code: str
    message: str
    params: dict[str, str | int | float] | None = Field(default=None)
    fields: list[ApiErrorField] | None = Field(default=None)
