"""Счётчики лимитов на таблице `login_attempt` (Арх. 2.5 `throttle`, 10.1, 10.10).

Внешнего хранилища нет: лимит — это подсчёт строк журнала за окно. Время — реальное (`clock.real_now()`):
демо-сдвиг часов на лимиты не действует.

Здесь три вида счётчиков:

* `throttle` — общий счётчик событий, фасад для всех модулей;
* `failures_guard` и `record_attempt` — счёт неудачных попыток (вход, проверка текущего пароля);
* `mail_allowed` — лимит писем на адрес.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import ApiException
from app.modules.identity.models import LoginAttempt

_KIND_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
#: Ключ в `Session.info`: строки `throttle`, записанные в текущей транзакции (см. `throttle`).
_INFO_KEY = "identity.throttle"


def rate_limited(retry_after: float) -> ApiException:
    """429 `rate_limited` с `params.retry_after` — целые секунды, не меньше одной (Арх. 9.2)."""
    return ApiException(429, "rate_limited", params={"retry_after": max(1, math.ceil(retry_after))})


def _retry_after(times_desc: list[datetime], limit: int, window: timedelta, now: datetime) -> float:
    """Через сколько секунд событий в окне станет меньше `limit`.

    `times_desc` — моменты событий окна от новых к старым. Место освободится, когда из окна выйдет `limit`-е
    с конца событие: `retry_after = at[limit − 1] + window − now`.
    """
    if limit <= 0 or len(times_desc) < limit:
        return window.total_seconds()
    return (times_desc[limit - 1] + window - now).total_seconds()


def _recent(db: Session, *conditions: ColumnElement[bool], since: datetime, limit: int) -> list[datetime]:
    statement = (
        select(LoginAttempt.at)
        .where(LoginAttempt.at > since, *conditions)
        .order_by(LoginAttempt.at.desc())
        .limit(max(limit, 1))
    )
    return list(db.scalars(statement))


def _own_rows(db: Session) -> dict[str, int]:
    """Строки `throttle` текущей транзакции: вид → идентификатор строки.

    Привязка — к объекту корневой транзакции сессии: после фиксации, отката и при повторе `run_in_tx` транзакция
    другая, и память о строках сбрасывается сама.
    """
    # Транзакция начинается явно, если её ещё нет: иначе первая же запись начала бы новую, и память обнулилась бы.
    transaction = db.get_transaction() or db.begin()
    stored: tuple[Any, dict[str, int]] | None = db.info.get(_INFO_KEY)
    if stored is None or stored[0] is not transaction:
        stored = (transaction, {})
        db.info[_INFO_KEY] = stored
    return stored[1]


def throttle(
    db: Session,
    kind: str,
    *,
    ip: str | None = None,
    email_hash: str | None = None,
    limit: int,
    window_s: int,
) -> None:
    """Учесть событие вида `kind` и поднять 429 `rate_limited`, если лимит за окно исчерпан.

    Правило: считаются строки `kind` за последние `window_s` секунд, совпадающие со всеми переданными ключами
    (`ip`, `email_hash`); без ключей — все строки вида. Если их уже `limit` или больше — 429 с
    `params.retry_after`, событие не записывается (отклонённые попытки окно не продлевают). Иначе пишется строка.

    **Одно событие — одна строка.** Несколько вызовов с одним `kind` в одной транзакции (например, «не чаще раза
    в 10 минут с одного IP и раза в 2 минуты на стенд») учитывают одно и то же событие: вторая строка не пишется,
    к первой дописываются недостающие ключи, а сама она в подсчёт не входит. Поэтому порядок вызовов не важен.
    """
    if not _KIND_RE.fullmatch(kind):
        raise ValueError(f"throttle: вид счётчика должен быть коротким идентификатором в нижнем регистре: {kind!r}")
    now = clock.real_now()
    window = timedelta(seconds=window_s)
    own = _own_rows(db)
    own_id = own.get(kind)

    conditions: list[ColumnElement[bool]] = [LoginAttempt.kind == kind]
    if ip is not None:
        conditions.append(LoginAttempt.ip == ip)
    if email_hash is not None:
        conditions.append(LoginAttempt.email_sha256 == email_hash)
    if own_id is not None:
        conditions.append(LoginAttempt.id != own_id)
    times = _recent(db, *conditions, since=now - window, limit=limit)
    if limit <= 0 or len(times) >= limit:
        raise rate_limited(_retry_after(times, limit, window, now))

    if own_id is None:
        row = LoginAttempt(kind=kind, email_sha256=email_hash, ip=ip, ok=True, at=now)
        db.add(row)
        db.flush()
        own[kind] = row.id
        return
    existing = db.get(LoginAttempt, own_id)
    if existing is not None:
        existing.ip = existing.ip or ip
        existing.email_sha256 = existing.email_sha256 or email_hash
        db.flush()


def record_attempt(db: Session, kind: str, *, email_hash: str | None, ip: str | None, ok: bool) -> None:
    """Записать попытку (вход, проверка пароля). Неудача должна пережить откат — её фиксирует
    `ApiException(..., commit=True)` у вызывающего.
    """
    db.add(LoginAttempt(kind=kind, email_sha256=email_hash, ip=ip, ok=ok, at=clock.real_now()))
    db.flush()


def failures_guard(
    db: Session,
    kind: str,
    *,
    email_hash: str | None = None,
    ip: str | None = None,
    max_failures: int,
    window: timedelta,
) -> None:
    """Поднять 429, если неудачных попыток `kind` по ключу за окно уже `max_failures` (Арх. 10.1).

    Ключ один: адрес (с любых IP) либо IP (на любые адреса) — счётчики раздельные, вызывающий проверяет оба.
    Сама отклонённая попытка не записывается, иначе блокировка продлевалась бы каждым новым запросом.
    """
    conditions: list[ColumnElement[bool]] = [LoginAttempt.kind == kind, LoginAttempt.ok.is_(False)]
    if email_hash is not None:
        conditions.append(LoginAttempt.email_sha256 == email_hash)
    if ip is not None:
        conditions.append(LoginAttempt.ip == ip)
    now = clock.real_now()
    times = _recent(db, *conditions, since=now - window, limit=max_failures)
    if len(times) >= max_failures:
        raise rate_limited(_retry_after(times, max_failures, window, now))


def mail_allowed(
    db: Session,
    kind: str,
    email_hash: str,
    *,
    per_window: int,
    window: timedelta,
    min_interval: timedelta | None = None,
) -> bool:
    """Можно ли отправить ещё одно письмо вида `kind` на адрес; при «да» отправка сразу учитывается.

    Правило: не больше `per_window` писем за `window` и, если задан `min_interval`, не чаще одного за этот
    интервал. При «нет» вызывающий отвечает клиенту так же, как при «да», и письмо не шлёт (Арх. 10.1):
    по ответу нельзя узнать ни о существовании адреса, ни о лимите.
    """
    now = clock.real_now()
    times = _recent(
        db, LoginAttempt.kind == kind, LoginAttempt.email_sha256 == email_hash, since=now - window, limit=per_window
    )
    if len(times) >= per_window:
        return False
    if min_interval is not None and times and now - times[0] < min_interval:
        return False
    db.add(LoginAttempt(kind=kind, email_sha256=email_hash, ip=None, ok=True, at=now))
    db.flush()
    return True
