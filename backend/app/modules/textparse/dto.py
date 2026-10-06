"""Типы фасада `textparse.service` (Арх. 2.5; приложение B, §1.4, §2.2)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class SkillMention(BaseModel):
    """Упоминание навыка в тексте: код справочника, место и способ распознавания."""

    model_config = ConfigDict(frozen=True)

    skill_code: str
    start: int
    end: int
    surface: str
    method: Literal["exact", "case", "lemma", "fuzzy"]


class NeedDraft(BaseModel):
    """Черновик потребности, разобранный из текста вакансии."""

    title: str | None = None
    team_description: str | None = None
    specialization_code: str | None = None
    grade_code: str | None = None
    #: Другие грейды, названные в тексте.
    grade_alternatives: list[str] = []
    must_skills: list[str] = []
    nice_skills: list[str] = []
    work_formats: list[str] = []
    city: str | None = None
    salary_from: int | None = None
    salary_to: int | None = None
    confidence: dict[str, Literal["high", "medium", "low"]] = {}
    unknown_terms: list[str] = []
    #: Коды: salary_currency, salary_single_bound, no_skills, spec_ambiguous.
    warnings: list[str] = []
    parser: Literal["rules", "llm"] = "rules"
    parser_version: str = ""
