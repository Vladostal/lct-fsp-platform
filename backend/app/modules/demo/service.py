"""Фасад модуля `demo` (Арх. 2.5, 13.5): вход «как…», перезапуск сценария, фоновая чистка.

Сид вызывается только через `app.wiring.demo_hook` (`restart_scenario`): модуль не импортирует `app.seed`.
В этой сборке нет клонов `nina`, быстрого демо-теста, демо-приглашения, сдвига часов и сквозного сброса.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app import wiring
from app.core.errors import ApiException, not_found
from app.modules.demo.dto import DemoAccount
from app.modules.identity import service as identity
from app.shared.enums import Role

#: Именованные аккаунты сценария: (ключ, название, состояние для таблицы `/demo`). Порядок — порядок таблицы.
ACCOUNTS: tuple[tuple[str, str, str], ...] = (
    ("orbita", "Орбита", "Потребность «Backend-разработчик в платёжный сервис», версия подборки, история приглашений"),
    ("anna", "Анна", "Backend · Middle, сильная история ФСП; ждёт приглашение: принять с выбором канала"),
    ("dmitry", "Дмитрий", "Минимум 260 000 ₽: «Не доставлено: условия не совпали»"),
    ("ivan", "Иван", "Ждёт ответа: отклонить с условием «удалённо»"),
    ("gleb", "Глеб", "Молчит: истечение срока, возврат слота, автопауза"),
    ("boris", "Борис", "Backend · Junior без приглашений: воронка спроса"),
    ("olga", "Ольга", "ФСП ID привязан, истории нет"),
    ("maria", "Мария", "Middle подтверждён с запасом: тест на Senior доступен сразу"),
    ("petr", "Пётр", "Тест на Middle не подтверждён, категории нет; тест на Junior доступен сразу"),
)
SCENARIO_KEYS: tuple[str, ...] = tuple(key for key, _, _ in ACCOUNTS)


def accounts(db: Session) -> list[DemoAccount]:
    """Именованные аккаунты, которые сейчас есть в базе."""
    present: dict[str, UUID] = {}
    for key in SCENARIO_KEYS:
        ids = identity.demo_user_ids(db, [key])
        if ids:
            present[key] = ids[0]
    users = identity.users(db, list(present.values()))
    return [
        DemoAccount(key=key, title=title, role=users[present[key]].role, state_label=state)
        for key, title, state in ACCOUNTS
        if key in present and present[key] in users
    ]


def login_user_id(db: Session, key: str) -> UUID:
    """Идентификатор именованного демо-аккаунта; чужой ключ и отсутствующий аккаунт — 404."""
    if key not in SCENARIO_KEYS:
        raise not_found()
    ids = identity.demo_user_ids(db, [key])
    if not ids:
        raise not_found()
    return ids[0]


def is_scenario_user(db: Session, user_id: UUID) -> bool:
    return user_id in set(identity.demo_user_ids(db, SCENARIO_KEYS))


def restart_scenario() -> None:
    """Пересоздать именованных кандидатов и их историю с `orbita` (сид, Арх. 13.5)."""
    try:
        hook = wiring.demo_hook("restart_scenario")
    except wiring.WiringError as exc:
        raise ApiException(503, "service_unavailable") from exc
    hook()


def purge_clones(db: Session, now: datetime) -> int:
    """Фоновая задача (раз в 10 минут, при `DEMO_MODE`): удалить клоны `nina` старше `DEMO_CLONE_TTL_HOURS`.

    Клонов в этой сборке нет, поэтому удалять нечего.
    """
    return 0


__all__ = ["Role", "accounts", "is_scenario_user", "login_user_id", "purge_clones", "restart_scenario"]
