"""Модуль `company`: профиль компании работодателя и уровень доверия (слой 2).

Публичная поверхность — `service.py` и `dto.py` (Арх. 2.4, 2.5). Модуль подключается к приложению списком
`ROUTERS` (Арх. 2.6).
"""

from fastapi import APIRouter

from app.modules.company.router import router

ROUTERS: list[APIRouter] = [router]
