"""Модуль `assessment` (слой 3).

Опрос, заявленный грейд, банк семейств, сессии теста, оценка уровня, категория, правила грейда.
Подключается к приложению списком `ROUTERS` (Арх. 2.6); при старте публикует в каталог доступные пары
«специализация — грейд» (Арх. 5.2).
"""

from __future__ import annotations

from fastapi import APIRouter


def _routers() -> list[APIRouter]:
    from app.modules.assessment.admin_router import router as admin_router
    from app.modules.assessment.router import router

    return [router, admin_router]


def __getattr__(name: str) -> object:
    # Роутеры создаются при первом обращении `app.wiring`: импорт пакета (например, из генератора семейства
    # или из `engine/`) не тянет за собой FastAPI-слой и модели.
    if name == "ROUTERS":
        routers = _routers()
        globals()["ROUTERS"] = routers
        return routers
    raise AttributeError(name)


def on_startup() -> None:
    """Хук старта процесса `api`: проверить инварианты плана на активных семействах и опубликовать доступность."""
    from app.core.db import session_scope
    from app.modules.assessment import repo

    with session_scope() as db:
        repo.refresh_availability(db)
