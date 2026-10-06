"""Фасад модуля `vacancies` (P1; Арх. 2.5, 4.15).

Заглушка пакета-фундамента: сигнатуры нормативны, тела заменяет владелец модуля. Фоновая задача безопасна уже
в заглушке.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session


def settle_applications(db: Session, now: datetime) -> None:
    """Фоновая задача (раз в 60 с, при `FEATURE_VACANCIES`): материализовать истёкшие отклики."""
    return None
