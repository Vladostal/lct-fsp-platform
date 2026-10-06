"""Фасад модуля `pulse` (P1; Арх. 2.5, 5.9).

Заглушка пакета-фундамента: сигнатуры нормативны, тела заменяет владелец модуля. Фоновая задача и шаг
инициализации безопасны уже в заглушке.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session


def expire_assignments(db: Session, now: datetime) -> None:
    """Фоновая задача (раз в 60 с, при `FEATURE_PULSE`): закрыть назначения, у которых вышел срок."""
    return None


def ensure_platform_tasks() -> None:
    """Шаг инициализации (Арх. 13.2, при `FEATURE_PULSE`): создать задания платформы; идемпотентен.

    Вызывается без аргументов из `app.scripts.init`: сессию открывает сам (`core.db.session_scope`).
    """
    return None
