"""Типы фасада `catalog.service` (Арх. 2.5, 9.11): справочники в памяти и ответ `GET /catalog`."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from app.shared.schemas import Ref


def _all_required(schema: dict[str, Any]) -> None:
    """Схема ответа: поля с умолчанием всегда присутствуют, клиент не должен считать их необязательными."""
    schema["required"] = list(schema.get("properties", {}))


class SpecializationDTO(BaseModel):
    """Специализация справочника."""

    model_config = ConfigDict(frozen=True, json_schema_extra=_all_required)

    code: str
    title: str
    title_short: str
    direction_code: str
    available: bool = False


class GradeDTO(BaseModel):
    """Грейд справочника; `order` — порядок от младшего к старшему."""

    model_config = ConfigDict(frozen=True, json_schema_extra=_all_required)

    code: str
    title: str
    order: int
    description: str = ""
    available: bool = False


class SkillDTO(BaseModel):
    """Навык справочника."""

    model_config = ConfigDict(frozen=True, json_schema_extra=_all_required)

    code: str
    title: str
    kind: str
    aliases: list[str] = []


class CatalogFeatures(BaseModel):
    """Флаги стенда (`Settings.features`)."""

    model_config = ConfigDict(json_schema_extra=_all_required)

    demo: bool = False
    vacancies: bool = False
    pulse: bool = False
    integrations: bool = False


class Catalog(BaseModel):
    """Справочники, публичные лимиты и флаги — ответ `GET /catalog` (Арх. 9.11)."""

    model_config = ConfigDict(json_schema_extra=_all_required)

    directions: list[Ref] = []
    specializations: list[SpecializationDTO] = []
    grades: list[GradeDTO] = []
    skills: list[SkillDTO] = []
    roles: list[Ref] = []
    #: Доступные пары «специализация:грейд» (Арх. 5.2).
    available_categories: list[str] = []
    limits: dict[str, int | float] = {}
    features: CatalogFeatures = CatalogFeatures()


class SkillEntry(BaseModel):
    """Навык со всеми данными справочника (для `textparse` и тестов); в API отдаётся урезанный `SkillDTO`."""

    model_config = ConfigDict(frozen=True)

    code: str
    title: str
    kind: str
    #: Специализации для голосования: первая — основная (голос 1.0), остальные — 0.5 (приложение B, §2.3).
    specializations: tuple[str, ...] = ()
    #: Алиасы в нижнем регистре, `ё` → `е`, пробелы схлопнуты; русские — в именительном падеже.
    aliases: tuple[str, ...] = ()
    #: Алиасы с учётом регистра; срабатывают только в контексте перечисления.
    case_aliases: tuple[str, ...] = ()
    #: Прямые `implies`; замыкание — `catalog.service.implies_closure`.
    implies: tuple[str, ...] = ()


class RoleEntry(BaseModel):
    """Должность из `roles.yaml`: алиасы определяют специализацию текста."""

    model_config = ConfigDict(frozen=True)

    code: str
    title: str
    specialization: str | None = None
    aliases: tuple[str, ...] = ()


class CityEntry(BaseModel):
    """Город из `cities.txt` в нормальной форме и его сокращения."""

    model_config = ConfigDict(frozen=True)

    name: str
    aliases: tuple[str, ...] = ()
