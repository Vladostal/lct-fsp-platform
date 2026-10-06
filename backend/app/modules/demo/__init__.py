"""Модуль `demo` (слой 8): демо-аккаунты, вход «как…», перезапуск сценария, чистка клонов.

Подключается к приложению списком `ROUTERS` (Арх. 2.6); фасад — `service.py`. Сид вызывается только через
`DEMO_HOOKS` (`app.wiring`).
"""

from fastapi import APIRouter

from app.modules.demo.router import router

ROUTERS: list[APIRouter] = [router]
