"""Модуль `catalog` (слой 1).

Справочники в памяти: направления, специализации, грейды, навыки, роли, города; публичные лимиты и флаги.
Загрузка и проверка файлов — `loader.py`, фасад — `service.py`, `GET /catalog` — `router.py`, таблица
`skill_miss_log` — `models.py`. Модуль подключается к приложению списком `ROUTERS` (Арх. 2.6).
"""

from fastapi import APIRouter

from app.modules.catalog.router import router

ROUTERS: list[APIRouter] = [router]
