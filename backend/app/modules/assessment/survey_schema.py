"""Схема опроса по отрасли и специализации (Арх. 5.2; приложение A, §1.4).

Пять вопросов; три определяют состав теста: направление, специализация, основной язык. Списки направлений
и специализаций берутся из каталога, остальное задано здесь. Версия схемы — `SURVEY_VERSION`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.core.errors import ApiErrorField, field_error
from app.modules.assessment.blueprints import LANG_RULES, lang_module
from app.modules.catalog import service as catalog

LANGUAGE_TITLES: dict[str, str] = {
    "python": "Python",
    "java": "Java",
    "go": "Go",
    "csharp": "C#",
    "nodejs": "Node.js",
    "php": "PHP",
    "cpp": "C++",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "r": "R",
    "sql_only": "Только SQL",
    "other": "Другой",
}

#: Основной язык по специализации; у специализаций без теста вопрос сводится к «Другой».
LANGUAGES: dict[str, tuple[str, ...]] = {
    "backend": ("python", "java", "go", "csharp", "nodejs", "php", "cpp", "other"),
    "frontend": ("javascript", "typescript"),
    "fullstack": ("javascript", "typescript"),
    "data_ml": ("python", "r", "sql_only", "other"),
}
DEFAULT_LANGUAGES: tuple[str, ...] = ("other",)

EXPERIENCE: dict[str, str] = {"lt1": "Меньше года", "1_2": "1–2 года", "2_4": "2–4 года", "4_plus": "Больше 4 лет"}
#: Предвыбор грейда по опыту; решает кандидат.
EXPERIENCE_GRADE: dict[str, str] = {"lt1": "junior", "1_2": "junior", "2_4": "middle", "4_plus": "senior"}

INDUSTRIES: dict[str, str] = {
    "fintech": "Финтех",
    "ecommerce": "Электронная коммерция",
    "telecom": "Телеком",
    "gov": "Госсектор",
    "industry": "Промышленность",
    "gamedev": "Разработка игр",
    "edtech": "Образование",
    "medtech": "Медицина",
    "media": "Медиа",
    "other": "Другое",
}
MAX_INDUSTRIES = 3


def _option(code: str, title: str, *, available: bool = True, parent: str | None = None) -> dict[str, Any]:
    return {"code": code, "title": title, "available": available, "parent": parent}


def questions() -> list[dict[str, Any]]:
    """Вопросы опроса в порядке показа; `available` у специализаций — из каталога (доступность теста, Арх. 5.2)."""
    cat = catalog.get_catalog()
    languages = [
        _option(code, LANGUAGE_TITLES[code], parent=spec.code)
        for spec in cat.specializations
        for code in LANGUAGES.get(spec.code, DEFAULT_LANGUAGES)
    ]
    return [
        {
            "id": "direction",
            "kind": "single",
            "title": "Направление",
            "required": True,
            "max": None,
            "depends_on": None,
            "options": [_option(d.code, d.title) for d in cat.directions],
        },
        {
            "id": "specialization",
            "kind": "single",
            "title": "Специализация",
            "required": True,
            "max": None,
            "depends_on": "direction",
            "options": [
                _option(s.code, s.title, available=s.available, parent=s.direction_code) for s in cat.specializations
            ],
        },
        {
            "id": "main_language",
            "kind": "single",
            "title": "Основной язык",
            "required": True,
            "max": None,
            "depends_on": "specialization",
            "options": languages,
        },
        {
            "id": "experience_band",
            "kind": "single",
            "title": "Коммерческий опыт",
            "required": True,
            "max": None,
            "depends_on": None,
            "options": [_option(code, title) for code, title in EXPERIENCE.items()],
        },
        {
            "id": "industry_domains",
            "kind": "multi",
            "title": "В каких отраслях есть опыт",
            "required": False,
            "max": MAX_INDUSTRIES,
            "depends_on": None,
            "options": [_option(code, title) for code, title in INDUSTRIES.items()],
        },
    ]


@dataclass(frozen=True)
class SurveyAnswers:
    """Проверенные ответы и то, что из них следует для теста."""

    answers: dict[str, Any]
    direction: str
    specialization: str
    main_language: str
    experience_band: str
    industry_domains: tuple[str, ...]
    lang_module: str | None


def validate(raw: Mapping[str, Any]) -> tuple[SurveyAnswers | None, list[ApiErrorField]]:
    """Проверить ответы по схеме: обязательность, коды вариантов, зависимости, предел множественного выбора."""
    errors: list[ApiErrorField] = []
    values: dict[str, Any] = {}
    for question in questions():
        qid = question["id"]
        value = raw.get(qid)
        codes = {option["code"]: option for option in question["options"]}
        if question["kind"] == "multi":
            items = [] if value is None else value
            if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
                errors.append(field_error(f"answers.{qid}", "invalid", "Выберите варианты из списка"))
                continue
            items = list(dict.fromkeys(items))
            if any(item not in codes for item in items):
                errors.append(field_error(f"answers.{qid}", "invalid", "Выберите варианты из списка"))
            elif question["max"] is not None and len(items) > question["max"]:
                errors.append(field_error(f"answers.{qid}", "too_many", f"Не больше {question['max']} вариантов"))
            values[qid] = items
            continue
        if value is None or value == "":
            if question["required"]:
                errors.append(field_error(f"answers.{qid}", "required", "Ответьте на вопрос"))
            continue
        if not isinstance(value, str) or value not in codes:
            errors.append(field_error(f"answers.{qid}", "invalid", "Выберите вариант из списка"))
            continue
        parent_q = question["depends_on"]
        if parent_q is not None and parent_q in values:
            allowed = {o["code"] for o in question["options"] if o["parent"] == values[parent_q]}
            if value not in allowed:
                errors.append(field_error(f"answers.{qid}", "invalid", "Вариант не подходит к предыдущему ответу"))
                continue
        values[qid] = value
    if errors or not {"direction", "specialization", "main_language", "experience_band"} <= set(values):
        return None, errors or [field_error("answers", "required", "Ответьте на обязательные вопросы")]
    spec = values["specialization"]
    module = lang_module(spec, values["main_language"]) if spec in LANG_RULES else None
    return (
        SurveyAnswers(
            answers=values,
            direction=values["direction"],
            specialization=spec,
            main_language=values["main_language"],
            experience_band=values["experience_band"],
            industry_domains=tuple(values.get("industry_domains", ())),
            lang_module=module,
        ),
        [],
    )
