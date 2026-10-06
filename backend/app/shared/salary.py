"""Общие правила вилки и лестницы минимума (Арх. 4.3, 4.6).

Все суммы — целые рубли в месяц до вычета налога. Правила вилки одни для потребности, приглашения и вакансии.
Сравнение вилки с минимумом кандидата здесь не выполняется: его единственное место — `contact/rules.py: salary_ok`.
"""

from __future__ import annotations

from math import floor

from app.core.errors import ApiException, field_error

SALARY_MIN = 10_000
SALARY_MAX = 3_000_000
#: Верх вилки не больше `floor(salary_from * SALARY_MAX_RATIO)`.
SALARY_MAX_RATIO = 1.5

#: Лестница минимума кандидата: «не задан» либо ступень от LOW до HIGH с шагом STEP.
MIN_SALARY_LOW = 40_000
MIN_SALARY_HIGH = 600_000
MIN_SALARY_STEP = 20_000

#: Числа для `Catalog.limits`: интерфейс проверяет вилку теми же значениями (приложение E, §4.2).
PUBLIC_SALARY_LIMITS: dict[str, int | float] = {
    "salary_min": SALARY_MIN,
    "salary_max": SALARY_MAX,
    "salary_max_ratio": SALARY_MAX_RATIO,
    "min_salary_low": MIN_SALARY_LOW,
    "min_salary_high": MIN_SALARY_HIGH,
    "min_salary_step": MIN_SALARY_STEP,
}


def max_salary_to(salary_from: int) -> int:
    """Допустимый верх вилки при данном «от»: `min(floor(from * 1.5), SALARY_MAX)`."""
    return min(floor(salary_from * SALARY_MAX_RATIO), SALARY_MAX)


def range_error(salary_from: int, salary_to: int) -> tuple[str, dict[str, int], str] | None:
    """Проверить вилку без исключения: `None` либо (код ошибки, параметры, имя поля).

    Порядок проверок совпадает с интерфейсом: границы → порядок → ширина.

    * `SALARY_MIN <= salary_from` и `salary_to <= SALARY_MAX`, иначе `salary_out_of_bounds`;
    * `salary_from <= salary_to`, иначе `salary_order`;
    * `salary_to <= floor(salary_from * SALARY_MAX_RATIO)`, иначе `salary_range_too_wide`
      с `params.max_to` — допустимым верхом.
    """
    bounds = {"salary_min": SALARY_MIN, "salary_max": SALARY_MAX}
    if salary_from < SALARY_MIN or salary_from > SALARY_MAX:
        return "salary_out_of_bounds", bounds, "salary_from"
    if salary_to < SALARY_MIN or salary_to > SALARY_MAX:
        return "salary_out_of_bounds", bounds, "salary_to"
    if salary_from > salary_to:
        return "salary_order", {}, "salary_to"
    limit = max_salary_to(salary_from)
    if salary_to > limit:
        return "salary_range_too_wide", {"max_to": limit}, "salary_to"
    return None


def validate_range(salary_from: int, salary_to: int) -> None:
    """Проверить вилку; при нарушении — 422 с кодом правила (`salary_order`, `salary_out_of_bounds`,
    `salary_range_too_wide`). Ошибка ширины несёт `params.max_to`, чтобы текст называл допустимый верх.
    """
    error = range_error(salary_from, salary_to)
    if error is None:
        return
    code, params, field_name = error
    exc = ApiException(422, code, params=params or None)
    exc.fields = [field_error(field_name, code, exc.message)]
    raise exc


def min_salary_ladder() -> list[int]:
    """Ступени лестницы минимума: 40 000, 60 000, … 600 000 (29 ступеней)."""
    return list(range(MIN_SALARY_LOW, MIN_SALARY_HIGH + 1, MIN_SALARY_STEP))


def is_on_ladder(value: int | None) -> bool:
    """`None` («не задан») и любая ступень лестницы — допустимый минимум; иначе 422 `min_salary_not_on_ladder`."""
    if value is None:
        return True
    return MIN_SALARY_LOW <= value <= MIN_SALARY_HIGH and (value - MIN_SALARY_LOW) % MIN_SALARY_STEP == 0
