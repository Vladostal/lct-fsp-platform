"""Фасад модуля `demo` (Арх. 2.5, 13.5): вход «как…», быстрый демо-тест, часы сервиса, перезапуск, сброс и
самовосстановление устаревшего сценария.

Сид вызывается только через `app.wiring.demo_hook` (`restart_scenario`, `reset_all`): модуль не импортирует
`app.seed`. Клонов `nina` и демо-приглашения живому кандидату в этой сборке нет: демо-компания по правилу стенда
не видит настоящих кандидатов (`matching.evidence.blocked_for_demo`), и объяснение «почему пригласили» для такой
пары не строится.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app import wiring
from app.core import clock
from app.core.config import get_settings
from app.core.errors import ApiException, not_found
from app.modules.assessment import service as assessment
from app.modules.contact import service as contact
from app.modules.demo.dto import DemoAccount, DemoClock
from app.modules.identity import service as identity

log = logging.getLogger("app.demo")

#: Быстрый демо-тест: столько ответов базовой формы подставлено верными, остальные даёт кандидат («2 из 14»).
QUICK_ANSWERED = 12

#: Самовосстановление сценария. Без действующего приглашения этим аккаунтам кандидатскую сторону показать нечем:
#: `anna` — «принять с выбором канала», `ivan` — «отклонить с условием». Приглашения сида живут 5–6 дней, а повторно
#: пригласить ту же пару `orbita` не может ещё 30 дней, поэтому руками сценарий не чинится.
REFRESH_KEYS: tuple[str, ...] = ("anna", "ivan")
EMPLOYER_KEY = "orbita"
#: Сценарий не трогается, пока демо-аккаунтами пользуются: отметка активности сессии не старше этого срока.
#: Отметка обновляется раз в час, так что два часа означают «не меньше часа без единого запроса».
REFRESH_IDLE = timedelta(hours=2)
#: И не чаще этого интервала: сид, который не может создать приглашение, не должен пересоздаваться по кругу.
REFRESH_MIN_INTERVAL_S = 6 * 3600

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


def quick_session(db: Session, candidate_id: UUID, grade_code: str, now: datetime) -> UUID:
    """Быстрый демо-тест: обычный старт теста, в котором первые ответы подставлены верными.

    Право на старт проверяет модуль `assessment` теми же правилами, что и для обычного теста; результат и категория
    по нему помечаются как демо (`is_demo_result`) и в отчётах платформы не учитываются.
    """
    return assessment.start_quick_session(db, candidate_id, grade_code, QUICK_ANSWERED, now)


def clock_state(db: Session) -> DemoClock:
    return DemoClock(now=clock.now(db), offset_seconds=clock.offset_seconds(db))


def advance_clock(db: Session, hours: int, *, force: bool) -> DemoClock:
    """Сдвинуть время сервиса вперёд. Идущие тесты после сдвига закроются по времени — без `force` это 409."""
    active = assessment.active_session_count(db, clock.now(db))
    if active and not force:
        raise ApiException(
            409,
            "sessions_in_progress",
            "Есть идущие тесты: после сдвига их время выйдет. Повторите с подтверждением",
            params={"count": active},
        )
    clock.advance(db, hours * 3600)
    return clock_state(db)


def reset_all() -> None:
    """Удалить все демо-аккаунты и создать сид заново (сдвиг часов сохраняется)."""
    try:
        hook = wiring.demo_hook("reset_all")
    except wiring.WiringError as exc:
        raise ApiException(503, "service_unavailable") from exc
    hook()


def scenario_stale(db: Session) -> bool:
    """Устарел ли сценарий: у `anna` или `ivan` нет действующего приглашения `orbita` (истекло либо на него ответили).

    Сценария нет вовсе (нет `orbita`) — это забота инициализации, а не перезапуска: ложь.
    """
    employer = identity.demo_user_ids(db, [EMPLOYER_KEY])
    if not employer:
        return False
    for key in REFRESH_KEYS:
        candidate = identity.demo_user_ids(db, [key])
        if not candidate or not contact.has_active_invitation(db, employer[0], candidate[0]):
            return True
    return False


def refresh_scenario(db: Session, now: datetime) -> bool:
    """Фоновая задача (раз в 10 минут, при `DEMO_MODE`): пересоздать устаревший сценарий, которым никто не занят.

    Нужна стенду, который стоит без присмотра: жюри может открыть его через неделю после развёртывания, когда
    приглашения сида уже истекли. Три условия сразу — сценарий устарел (`scenario_stale`), ни одна сессия
    именованных аккаунтов не отмечалась `REFRESH_IDLE`, прошлый автоперезапуск был не раньше
    `REFRESH_MIN_INTERVAL_S` назад. Выключается настройкой `DEMO_AUTO_RESTART=false`. Возвращает «перезапущен».
    """
    if not get_settings().demo_auto_restart or not scenario_stale(db):
        return False
    seen = identity.last_activity(db, identity.demo_user_ids(db, SCENARIO_KEYS))
    if seen is not None and clock.real_now() - seen < REFRESH_IDLE:
        return False
    try:
        identity.throttle(db, "demo_auto_restart", limit=1, window_s=REFRESH_MIN_INTERVAL_S)
    except ApiException:
        return False
    # Сид пишет в своих транзакциях и удаляет именованных кандидатов: свою сначала фиксируем.
    db.commit()
    restart_scenario()
    log.info("сценарий устарел и не использовался: пересоздан автоматически")
    return True


def purge_clones(db: Session, now: datetime) -> int:
    """Фоновая задача (раз в 10 минут, при `DEMO_MODE`): удалить клоны `nina` старше `DEMO_CLONE_TTL_HOURS`.

    Клонов в этой сборке нет, поэтому удалять нечего.
    """
    return 0


__all__ = [
    "accounts",
    "advance_clock",
    "clock_state",
    "is_scenario_user",
    "login_user_id",
    "purge_clones",
    "quick_session",
    "refresh_scenario",
    "reset_all",
    "restart_scenario",
    "scenario_stale",
]
