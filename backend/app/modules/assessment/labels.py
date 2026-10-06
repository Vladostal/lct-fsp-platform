"""Подписи и ссылки на справочники для ответов модуля (тексты для пользователя — на русском)."""

from __future__ import annotations

from app.modules.assessment.groups import GROUPS
from app.modules.catalog import service as catalog
from app.shared.enums import TestOutcome
from app.shared.schemas import CategoryRef, Ref

OUTCOME_TEMPLATES: dict[TestOutcome, str] = {
    TestOutcome.CONFIRMED_WITH_MARGIN: "Грейд {grade} подтверждён с запасом",
    TestOutcome.CONFIRMED: "Грейд {grade} подтверждён",
    TestOutcome.BORDERLINE: "Результат на границе грейда {grade}",
    TestOutcome.NOT_CONFIRMED: "Грейд {grade} не подтверждён",
}

OUTCOME_TITLES: dict[TestOutcome, str] = {
    TestOutcome.CONFIRMED_WITH_MARGIN: "Подтверждён с запасом",
    TestOutcome.CONFIRMED: "Подтверждён",
    TestOutcome.BORDERLINE: "На границе",
    TestOutcome.NOT_CONFIRMED: "Не подтверждён",
}


def grade_ref(code: str) -> Ref:
    for grade in catalog.grades_ordered():
        if grade.code == code:
            return Ref(code=grade.code, title=grade.title)
    return Ref(code=code, title=code.capitalize())


def category_ref(specialization: str, grade: str) -> CategoryRef:
    return catalog.category_ref(f"{specialization}:{grade}")


def outcome_label(outcome: TestOutcome | str, grade: str) -> str:
    return OUTCOME_TEMPLATES[TestOutcome(outcome)].format(grade=grade_ref(grade).title)


def group_title(code: str) -> str:
    group = GROUPS.get(code)
    return group.title if group else code


def group_ref(code: str) -> Ref:
    return Ref(code=code, title=group_title(code))
