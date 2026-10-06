"""Модели сетевых семейств `http.*` и `svc.rate_limiter` (приложение A, §3.1, §3.3).

Чистые функции без случайности и времени. Каждая модель принимает данные задания и возвращает то, о чём спрашивает
вопрос; флаги в аргументах включают модель типичной ошибки кандидата. Правила — подмножество RFC 9110/9111,
записанное в условии задания: семейства дословно повторяют эти правила в тексте вопроса.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction

__all__ = [
    "CachePolicy",
    "CacheRequest",
    "HttpRequest",
    "browser_cache",
    "conditional_puts",
    "fixed_window_rejects",
    "orders_after",
    "shared_cache_origin_hits",
    "sliding_window_rejects",
    "token_bucket_rejects",
]


# --------------------------------------------------------------------------------------------------------------------
# Повторы и идемпотентность
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class HttpRequest:
    """Запрос клиента: `attempts` — число отправок; все, кроме последней, закончились таймаутом клиента.

    Сервер обрабатывает каждую дошедшую отправку, независимо от того, получил ли клиент ответ.
    """

    method: str  # POST, PUT, DELETE
    target: int | None = None  # номер заказа для PUT и DELETE
    key: str | None = None  # Idempotency-Key для POST
    attempts: int = 1


def orders_after(initial: Sequence[int], requests: Sequence[HttpRequest], *, post_is_idempotent: bool = False) -> int:
    """Сколько заказов будет в системе после всех отправок.

    POST без ключа создаёт новый заказ при каждой отправке; POST с уже виденным ключом ничего не меняет;
    PUT по номеру создаёт заказ, если его нет, и не меняет число заказов, если он есть; DELETE убирает заказ,
    повторный DELETE ничего не меняет. `post_is_idempotent` — модель ошибки: повторы POST не считаются.
    """
    orders = set(initial)
    seen_keys: set[str] = set()
    next_id = max(orders, default=0) + 1000  # номера, создаваемые POST, не пересекаются с номерами из запросов
    for request in requests:
        sends = 1 if post_is_idempotent and request.method == "POST" else request.attempts
        for _ in range(sends):
            if request.method == "POST":
                if request.key is not None and request.key in seen_keys:
                    continue
                if request.key is not None:
                    seen_keys.add(request.key)
                orders.add(next_id)
                next_id += 1
            elif request.method == "PUT":
                assert request.target is not None
                orders.add(request.target)
            elif request.method == "DELETE":
                orders.discard(request.target)
            else:
                raise ValueError(request.method)
    return len(orders)


def conditional_puts(start: int, puts: Sequence[tuple[int, int]], *, if_match_ignored: bool = False) -> int:
    """Версия документа в конце: `puts` — (значение `If-Match`, число отправок).

    PUT применяется, только если `If-Match` равен текущей версии; применённый PUT увеличивает версию на 1, иначе
    сервер отвечает 412 и ничего не меняет. Повтор после таймаута идёт с тем же `If-Match`, поэтому после успешной
    первой отправки он уже устарел. `if_match_ignored` — модель ошибки: заголовок игнорируется.
    """
    version = start
    for if_match, attempts in puts:
        for _ in range(attempts):
            if if_match_ignored or if_match == version:
                version += 1
    return version


# --------------------------------------------------------------------------------------------------------------------
# Кэш
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CachePolicy:
    """Заголовки ответа: `Cache-Control` и наличие `ETag`."""

    max_age: int | None = None
    s_maxage: int | None = None
    no_cache: bool = False
    no_store: bool = False
    private: bool = False
    etag: bool = False
    vary_language: bool = False


@dataclass(frozen=True)
class CacheRequest:
    """GET в момент `time` (секунды) от пользователя `user` с языком `language`."""

    time: int
    user: int = 1
    language: str = "ru"


def _version(changes: Sequence[int], t: int) -> int:
    """Версия ресурса на сервере в момент t: сколько изменений произошло не позже t."""
    return sum(1 for c in changes if c <= t)


def browser_cache(
    times: Sequence[int],
    policy: CachePolicy,
    changes: Sequence[int] = (),
    *,
    age_from_first: bool = False,
) -> list[str]:
    """Исходы GET в кэш одного браузера: `cache` (из кэша), `304` (дошёл до сервера, без тела), `200` (с телом).

    Ответ свеж, пока его возраст `t - stored_at` строго меньше `max-age`; `no-cache` требует проверки при каждом
    запросе, `no-store` запрещает сохранение. Проверка по `ETag` даёт 304, если версия ресурса не менялась.
    Успешная проверка (304) обновляет момент сохранения. `age_from_first` — модель ошибки: возраст считается от
    первой загрузки и не обновляется.
    """
    entry: tuple[int, int] | None = None  # (момент сохранения, версия)
    first: int | None = None
    outcomes: list[str] = []
    for t in times:
        fresh = (
            entry is not None
            and not policy.no_cache
            and policy.max_age is not None
            and t - (first if age_from_first and first is not None else entry[0]) < policy.max_age
        )
        if fresh:
            outcomes.append("cache")
            continue
        current = _version(changes, t)
        if entry is not None and policy.etag and entry[1] == current:
            outcomes.append("304")
            entry = (t, current)
            continue
        outcomes.append("200")
        if not policy.no_store:
            entry = (t, current)
            first = t if first is None else first
    return outcomes


def shared_cache_origin_hits(
    requests: Sequence[CacheRequest], policy: CachePolicy, *, rules_ignored: bool = False
) -> int:
    """Сколько запросов дойдёт до сервера при кэшах браузеров (у каждого пользователя свой) и общем кэше.

    Браузер хранит ответ, если нет `no-store`, и считает его свежим `max-age` секунд. Общий кэш не хранит ответы
    с `private` и `no-store`; свежесть в нём — `s-maxage`, а при его отсутствии `max-age`; при `Vary:
    Accept-Language` запись общего кэша своя для каждого языка, без `Vary` — одна на всех. Валидаторов нет:
    устаревший ответ загружается заново. Заголовок `Age` не учитывается. `rules_ignored` — модель ошибки:
    общий кэш ведёт себя как браузерный (`max-age`, без `private` и `Vary`).
    """
    browser: dict[int, int] = {}
    shared: dict[str, int] = {}
    hits = 0
    for request in sorted(requests, key=lambda r: r.time):
        t = request.time
        stored = browser.get(request.user)
        if stored is not None and policy.max_age is not None and t - stored < policy.max_age:
            continue
        shared_ok = not policy.no_store and (rules_ignored or not policy.private)
        lifetime = policy.max_age if rules_ignored or policy.s_maxage is None else policy.s_maxage
        key = request.language if policy.vary_language and not rules_ignored else "*"
        served = False
        if shared_ok and lifetime is not None and key in shared and t - shared[key] < lifetime:
            served = True
        if not served:
            hits += 1
            if shared_ok:
                shared[key] = t
        if not policy.no_store:
            browser[request.user] = t
    return hits


# --------------------------------------------------------------------------------------------------------------------
# Ограничитель частоты
# --------------------------------------------------------------------------------------------------------------------


def fixed_window_rejects(
    requests: Sequence[tuple[int, str]], limit: int, window: int, *, no_reset: bool = False
) -> int:
    """Сколько запросов получат 429 при фиксированном окне: окна выровнены по `window` секунд (`t // window`).

    В каждом окне у каждого ключа разрешено `limit` запросов. `no_reset` — модель ошибки: счётчик не сбрасывается.
    """
    counts: dict[tuple[str, int], int] = {}
    rejected = 0
    for t, key in requests:
        slot = (key, 0 if no_reset else t // window)
        counts[slot] = counts.get(slot, 0) + 1
        if counts[slot] > limit:
            rejected += 1
    return rejected


def token_bucket_rejects(times: Sequence[int], capacity: int, rate: Fraction, *, no_refill: bool = False) -> int:
    """Сколько запросов получат 429 при корзине токенов: корзина полна в момент 0, пополняется `rate` токенов в секунду.

    Запрос забирает один токен; если токена нет, запрос отклоняется и токен не тратится. `no_refill` — модель
    ошибки: корзина не пополняется.
    """
    tokens = Fraction(capacity)
    last = 0
    rejected = 0
    for t in times:
        if not no_refill:
            tokens = min(Fraction(capacity), tokens + (t - last) * rate)
        last = t
        if tokens >= 1:
            tokens -= 1
        else:
            rejected += 1
    return rejected


def sliding_window_rejects(
    requests: Sequence[tuple[int, str]], limit: int, window: int, *, as_fixed: bool = False
) -> int:
    """Сколько запросов получат 429 при скользящем окне: у ключа не больше `limit` принятых запросов за `window` секунд.

    Окно — полуинтервал `(t - window, t]`; отклонённые запросы в журнал не попадают. `as_fixed` — модель ошибки:
    вместо скользящего окна кандидат применяет фиксированное.
    """
    if as_fixed:
        return fixed_window_rejects(requests, limit, window)
    logs: dict[str, deque[int]] = {}
    rejected = 0
    for t, key in requests:
        log = logs.setdefault(key, deque())
        while log and log[0] <= t - window:
            log.popleft()
        if len(log) < limit:
            log.append(t)
        else:
            rejected += 1
    return rejected
