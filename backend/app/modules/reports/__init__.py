"""Модуль `reports`: отдача сводок отчётов валидации (слой 1).

Модуль без таблиц и без функций фасада: читает файлы отчётов и отдаёт их своим роутером. Подключается списком
`ROUTERS` (Арх. 2.6).
"""

from fastapi import APIRouter

from app.modules.reports.router import router

ROUTERS: list[APIRouter] = [router]
