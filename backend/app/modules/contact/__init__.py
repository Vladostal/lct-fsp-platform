"""Модуль `contact` (слой 6): механика «Приглашение с возвратом» (Арх. 4).

Приглашение: машина состояний, сверка вилки, `settle`, проекции двух сторон, воронка, сводка причин,
жалобы. Модуль подключается к приложению списком `ROUTERS` (Арх. 2.6); фасад для верхних модулей — `service.py`.
"""

from fastapi import APIRouter

from app.modules.contact.router_candidate import router as candidate_router
from app.modules.contact.router_common import router as common_router
from app.modules.contact.router_employer import router as employer_router

ROUTERS: list[APIRouter] = [candidate_router, employer_router, common_router]
