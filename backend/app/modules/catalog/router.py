"""Эндпоинт `GET /catalog` (Арх. 9.4): справочники, публичные лимиты и флаги стенда.

Публичный, без сессии и без обращения к базе: всё берётся из памяти процесса. Интерфейс кэширует ответ навсегда
(`staleTime: Infinity`), поэтому доступность категорий он узнаёт при следующей загрузке страницы.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.db import TxRoute
from app.modules.catalog import service
from app.modules.catalog.dto import Catalog

router = APIRouter(route_class=TxRoute)


@router.get("/catalog", response_model=Catalog, summary="Справочники, лимиты и флаги")
def read_catalog() -> Catalog:
    """Направления, специализации, грейды, навыки, роли, доступные категории, публичные лимиты и флаги."""
    return service.get_catalog()
