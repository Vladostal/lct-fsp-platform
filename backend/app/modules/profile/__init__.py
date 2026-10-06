"""Модуль `profile` (слой 4).

Профиль и резюме, PDF-профиль, приватность, условия кандидата, состояние показа, раскрытие контактов, журнал
доступа. Другие модули пользуются только `service.py` и `dto.py`; модуль подключается к приложению списком
`ROUTERS` (Арх. 2.6).
"""

from fastapi import APIRouter

from app.modules.profile.router import router

ROUTERS: list[APIRouter] = [router]
