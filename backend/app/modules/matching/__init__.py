"""Модуль `matching` (слой 5).

Потребность, доказательства, ранжирование, объяснение, версии подборки, банк, карточка кандидата. Модуль
подключается к приложению списком `ROUTERS` (Арх. 2.6).

Роутер импортируется при первом обращении к `ROUTERS`, а не при импорте пакета: чистые ядра `scoring.py` и
`ranking.py` вызывает валидация (`app.eval.matching`), и ей не нужны ни настройки стенда, ни база (Арх. 2.4, п. 6).
"""

from typing import Any


def __getattr__(name: str) -> Any:
    if name == "ROUTERS":
        from app.modules.matching.router import router

        return [router]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
