"""Фоновый цикл процесса `api` (Арх. 2.6).

Планировщика и брокера нет: цикл запускается в `lifespan` и раз в секунду проверяет, какой задаче пора.
Задача — функция фасада `(db, now)`: получает собственную сессию и время сервиса; после возврата транзакция
фиксируется, письма из очереди уходят. На корректность цикл не влияет — все сроки проверяются и при обращении, —
он лишь материализует истечения без запросов пользователей.

Перед каждой задачей берётся `pg_try_advisory_lock`: `api` работает одним воркером, блокировка оставлена на случай
запуска нескольких — задачу в каждый момент выполняет один процесс. Блокировка держится на отдельном соединении:
задача может фиксировать транзакцию несколько раз, и блокировка уровня транзакции отпускалась бы на первой фиксации.

Тот же цикл раз в сутки удаляет технические журналы старше 30 суток (Арх. 10.5).
"""

from __future__ import annotations

import asyncio
import logging
import time
import zlib
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core import clock, mail
from app.core.db import get_engine, new_session

log = logging.getLogger("app.background")

TICK_SECONDS = 1.0
#: Задержка первого запуска: дать процессу подняться и ответить на healthcheck.
FIRST_RUN_DELAY_SECONDS = 5.0
PURGE_PERIOD_SECONDS = 24 * 3600
#: Срок хранения технических журналов (Арх. 10.5): хэш адреса, IP, user-agent истёкших сессий.
TECH_LOG_RETENTION = timedelta(days=30)

TaskFn = Callable[[Session, datetime], Any]


def lock_key(name: str) -> int:
    """Устойчивый ключ advisory-блокировки по имени задачи (в пределах int4)."""
    return zlib.crc32(f"fsp-podbor:periodic:{name}".encode()) & 0x7FFFFFFF


@dataclass
class Job:
    """Задача цикла: период, имя и способ получить функцию (лениво — модуль может появиться позже)."""

    name: str
    seconds: float
    loader: Callable[[], TaskFn | None]
    #: `True` — задаче передаётся реальное время, а не время сервиса (чистка технических журналов).
    real_time: bool = False
    next_run: float = field(default=0.0)
    disabled: bool = field(default=False)
    _fn: TaskFn | None = field(default=None, repr=False)

    def resolve(self) -> TaskFn | None:
        if self._fn is None:
            self._fn = self.loader()
        return self._fn


def run_job(job: Job) -> bool:
    """Выполнить задачу один раз в текущем потоке. `False` — пропущена (занята другим процессом, нет функции)."""
    fn = job.resolve()
    if fn is None:
        return False
    key = lock_key(job.name)
    with get_engine().connect() as lock_conn:
        if not lock_conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}).scalar():
            return False
        try:
            db = new_session()
            try:
                now = clock.real_now() if job.real_time else clock.now(db)
                fn(db, now)
                db.commit()
            except BaseException:
                db.rollback()
                mail.discard(db)
                raise
            else:
                mail.flush(db)
            finally:
                db.close()
        finally:
            lock_conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
            lock_conn.commit()
    return True


def _run_guarded(job: Job) -> None:
    started = time.monotonic()
    try:
        ran = run_job(job)
    except NotImplementedError:
        # Заглушка фасада: модуль ещё не реализован. Повторять каждые 30 секунд незачем.
        job.disabled = True
        log.warning("фоновая задача %s выключена до перезапуска: функция ещё не реализована", job.name)
        return
    except Exception:
        log.exception("фоновая задача %s завершилась ошибкой", job.name)
        return
    if ran:
        log.debug("фоновая задача %s выполнена за %.0f мс", job.name, (time.monotonic() - started) * 1000)


async def run_loop(jobs: Sequence[Job], stop: asyncio.Event) -> None:
    """Главный цикл: задачи выполняются по одной в пуле потоков; ошибка задачи цикл не останавливает."""
    start = time.monotonic()
    for job in jobs:
        job.next_run = start + FIRST_RUN_DELAY_SECONDS
    log.info("фоновый цикл запущен: %s", ", ".join(f"{job.name} / {job.seconds:g} с" for job in jobs) or "задач нет")
    while not stop.is_set():
        current = time.monotonic()
        for job in jobs:
            if stop.is_set():
                break
            if job.disabled or current < job.next_run:
                continue
            await run_in_threadpool(_run_guarded, job)
            job.next_run = time.monotonic() + job.seconds
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=TICK_SECONDS)
    log.info("фоновый цикл остановлен")


# --------------------------------------------------------------------------------------------------------------------
# Чистка технических журналов
# --------------------------------------------------------------------------------------------------------------------

# Таблицами владеет модуль identity; core обращается к ним по именам Арх. 8.3 и только если они уже созданы.
_PURGE_STATEMENTS: tuple[tuple[str, str], ...] = (
    ("login_attempt", "DELETE FROM login_attempt WHERE at < :before"),
    ("auth_session", "DELETE FROM auth_session WHERE expires_at < :before"),
    ("email_token", "DELETE FROM email_token WHERE expires_at < :before"),
)


def purge_technical_logs(db: Session, now_real: datetime) -> int:
    """Удалить строки `login_attempt` и истёкшие `auth_session`, `email_token` старше 30 суток (Арх. 10.5).

    Считается по реальному времени: это журналы входа, демо-сдвиг часов на них не действует. Отметка карантина
    адреса (`kind = account_deleted`) живёт в `login_attempt` и уходит той же чисткой, поэтому
    `REREGISTER_COOLDOWN_DAYS` ограничен тридцатью сутками (`core.config`).
    """
    before = now_real - TECH_LOG_RETENTION
    deleted = 0
    for table_name, statement in _PURGE_STATEMENTS:
        if db.execute(text("SELECT to_regclass(:name)"), {"name": f"public.{table_name}"}).scalar() is None:
            continue
        deleted += int(db.execute(text(statement), {"before": before}).rowcount or 0)  # type: ignore[attr-defined]
    if deleted:
        log.info("чистка технических журналов: удалено строк — %s", deleted)
    return deleted


def purge_job() -> Job:
    return Job(
        name="core.purge_technical_logs",
        seconds=PURGE_PERIOD_SECONDS,
        loader=lambda: purge_technical_logs,
        real_time=True,
    )
