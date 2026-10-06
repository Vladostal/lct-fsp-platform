"""Модуль `fsp`: привязка ФСП ID, синхронизация, факты, сигнал, проекции для показа, календарь (слой 4).

Публичная поверхность — `service.py` и `dto.py` (Арх. 2.4, 2.5). Модуль подключается к приложению списком
`ROUTERS` (Арх. 2.6); каждый роутер создаётся как `APIRouter(route_class=TxRoute)`.
"""

from fastapi import APIRouter

from app.modules.fsp.router import router

ROUTERS: list[APIRouter] = [router]
