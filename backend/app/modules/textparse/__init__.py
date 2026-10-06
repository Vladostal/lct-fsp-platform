"""Модуль `textparse` (слой 2).

SkillLinker, словари грейдов, ролей и городов, голосование за специализацию, разбор текста потребности.
Чистые функции без базы данных; фасад — `service.py` (Арх. 2.5). У модуля нет эндпоинтов: разбор текста
вакансии отдаёт `matching` (`POST /employer/needs/parse`), разбор резюме — `profile`. Список `ROUTERS` пуст
(Арх. 2.6).
"""

from fastapi import APIRouter

ROUTERS: list[APIRouter] = []
