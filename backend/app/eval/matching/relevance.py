"""Метки релевантности из латентной истины (приложение B, §9.4).

Функция и её пороги зафиксированы этим файлом: его sha256 печатается в паспорте отчёта. Скорер этот файл
не импортирует и латентных полей не видит.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

#: «Релевантен» для P@k и MRR.
RELEVANT_MIN = 2


def level_fit(theta_true: float, cut: float, width: float) -> float:
    """`L`: уровень в окне целевого грейда — 1.0; в расширенном окне — 0.5; иначе 0."""
    if cut - 0.25 * width <= theta_true < cut + 1.5 * width:
        return 1.0
    if cut - 0.75 * width <= theta_true < cut + 2.0 * width:
        return 0.5
    return 0.0


def relevance(
    *,
    same_specialization: bool,
    theta_true: float,
    cut: float,
    width: float,
    skills: Mapping[str, int],
    must_skills: Sequence[str],
    nice_skills: Sequence[str],
) -> int:
    """Релевантность пары «потребность — кандидат» по шкале 0–3.

    `M` — доля обязательных с уровнем владения `lat ≥ 2` (рабочий уровень); `N` — доля желательных с `lat ≥ 1`.
    """
    if not same_specialization:
        return 0
    level = level_fit(theta_true, cut, width)
    must = sum(1 for skill in must_skills if skills.get(skill, 0) >= 2) / len(must_skills) if must_skills else 1.0
    nice = sum(1 for skill in nice_skills if skills.get(skill, 0) >= 1) / len(nice_skills) if nice_skills else 1.0
    if level == 1.0 and must == 1.0 and nice >= 0.5:
        return 3
    if level >= 0.5 and must >= 0.67:
        return 2
    if level >= 0.5 and must >= 0.34:
        return 1
    return 0
