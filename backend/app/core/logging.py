"""Журналирование процесса.

Один формат для приложения, uvicorn и скриптов. В журнал не пишутся пароли, токены, `code`, `state`, тела выгрузок
ФСП и контакты; `fsp_id` — только последние 4 символа (Арх. 10.8). Адреса почты маскирует `core.mail`.
"""

from __future__ import annotations

import logging
import sys

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

_HANDLER_MARK = "_fsp_podbor_handler"


def setup_logging(level: str = "info") -> None:
    """Настроить корневой журнал и журналы uvicorn. Повторный вызов безопасен.

    Чужие обработчики корневого журнала не трогаются (их ставят pytest и среды запуска): добавляется один свой.
    """
    numeric = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(numeric)
    handler = next((item for item in root.handlers if getattr(item, _HANDLER_MARK, False)), None)
    if handler is None:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        setattr(handler, _HANDLER_MARK, True)
        root.addHandler(handler)

    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(numeric)

    # Журнал доступа uvicorn выключен: он печатает строку запроса целиком, а в ней бывают `code` и `state`
    # возврата из ФСП ID. Запросы журналирует app.main — метод, путь без параметров, статус, время.
    access = logging.getLogger("uvicorn.access")
    access.handlers = [handler]
    access.propagate = False
    access.setLevel(logging.WARNING)

    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def mask_tail(value: str | None, keep: int = 4) -> str:
    """Оставить от идентификатора последние `keep` символов: «…1234»."""
    if not value:
        return "—"
    return "…" + value[-keep:]
