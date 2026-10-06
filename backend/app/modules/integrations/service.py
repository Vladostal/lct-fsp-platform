"""Фасад модуля `integrations` (P2; Арх. 2.5, 14.3).

Заглушка пакета-фундамента: сигнатуры нормативны, тела заменяет владелец модуля. Фоновая задача безопасна уже
в заглушке.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session


def deliver_pending(db: Session, now: datetime) -> None:
    """Фоновая задача (раз в 15 с, при `FEATURE_INTEGRATIONS`): доставить ожидающие события вебхуков."""
    return None
