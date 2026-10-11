"""Подписи и ссылки на справочники для ответов модуля (тексты для пользователя — на русском)."""

from __future__ import annotations

from app.modules.assessment.groups import GROUPS
from app.modules.catalog import service as catalog
from app.shared.enums import CategoryBasis, TestOutcome
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


#: Запасные тексты ошибок запуска теста (клиент берёт свой текст по `code`, Арх. 9.2).
ERROR_MESSAGES: dict[str, str] = {
    "survey_required": "Сначала пройдите опрос",
    "claim_required": "Сначала выберите грейд, который хотите подтвердить",
    "grade_not_allowed": "Тест на этот грейд сейчас пройти нельзя: доступен заявленный грейд или соседний",
    "session_active": "У вас уже идёт тест: сначала завершите его",
    "cooldown_active": "Следующая попытка станет доступна позже",
}


def grade_ref(code: str) -> Ref:
    for grade in catalog.grades_ordered():
        if grade.code == code:
            return Ref(code=grade.code, title=grade.title)
    return Ref(code=code, title=code.capitalize())


def category_ref(specialization: str, grade: str, basis: CategoryBasis | str | None = None) -> CategoryRef:
    """Ссылка на категорию; `basis` задаётся только для категории кандидата (подтверждена тестом или заявлена)."""
    ref = catalog.category_ref(f"{specialization}:{grade}")
    return ref if basis is None else ref.model_copy(update={"basis": CategoryBasis(basis)})


#: Тест закрыт по времени и грейд не подтверждён: «на границе» здесь означало бы оценку, которой кандидат не дал.
EXPIRED_TEMPLATE = "Время вышло: грейд {grade} не подтверждён"
_CONFIRMING = frozenset({TestOutcome.CONFIRMED, TestOutcome.CONFIRMED_WITH_MARGIN})


def outcome_label(outcome: TestOutcome | str, grade: str, *, expired: bool = False) -> str:
    """Подпись исхода. `expired` — сессия закрыта по времени: неподтверждающий исход назван прямо."""
    value = TestOutcome(outcome)
    template = EXPIRED_TEMPLATE if expired and value not in _CONFIRMING else OUTCOME_TEMPLATES[value]
    return template.format(grade=grade_ref(grade).title)


def group_title(code: str) -> str:
    group = GROUPS.get(code)
    return group.title if group else code


def group_ref(code: str) -> Ref:
    return Ref(code=code, title=group_title(code))
