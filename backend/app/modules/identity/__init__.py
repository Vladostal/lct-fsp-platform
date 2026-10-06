"""Модуль `identity`: пользователи, подтверждение e-mail, сессии, согласия, аудит, тексты согласий (слой 1).

Публичная поверхность — `service.py` и `dto.py` (Арх. 2.4, 2.5). Модуль подключается к приложению списком
`ROUTERS` (Арх. 2.6); лимиты для интерфейса — `constants.PUBLIC_LIMITS`.
"""

from fastapi import APIRouter

from app.modules.identity.router import router

ROUTERS: list[APIRouter] = [router]
