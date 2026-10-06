"""Общие зависимости роутеров (Арх. 2.4, 9.1, 10.1, 10.3).

Типичный обработчик::

    router = APIRouter(route_class=TxRoute)

    @router.get("/candidate/profile", response_model=ProfileView, responses=error_responses(401, 403))
    def get_profile(user: Candidate, db: Db, now: Now) -> ProfileView:
        return service.profile_view(db, user.id, now)

* `Db` — сессия запроса; фиксирует её `core.db.TxRoute`, код после `yield` только закрывает.
* `Now` — время сервиса (с демо-сдвигом), одно на запрос. Реальное время — `clock.real_now()`.
* `AnyUser`, `Candidate`, `Employer` — вошедший пользователь любой роли либо нужной: без сессии 401
  `not_authenticated`, чужая роль 403 `forbidden`.
* `Admin` — служебные действия по заголовку `X-Admin-Token`; пользовательская сессия не нужна.
* `require_feature(name)` — эндпоинт за флагом: 404 `feature_disabled`.
* `ClientIp` — адрес клиента; единственное место, где он определяется.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Annotated

from fastapi import Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.core import clock, security
from app.core.config import Settings, get_settings
from app.core.db import new_session
from app.core.errors import ApiException
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, PageParams
from app.core.security import CurrentUser
from app.shared.enums import Role

ADMIN_HEADER = "X-Admin-Token"
REAL_IP_HEADER = "X-Real-IP"
#: Имена флагов `Catalog.features` (Арх. 9.11); значения — `Settings.features`.
FEATURE_NAMES = ("demo", "vacancies", "pulse", "integrations")


def get_db(request: Request) -> Iterator[Session]:
    """Сессия запроса: одна транзакция на запрос (Арх. 2.4, п. 4).

    Сессия кладётся в `request.state.db`, откуда её берёт `TxRoute` для фиксации до отправки ответа.
    Здесь после `yield` сессия только закрывается: этот код выполняется уже после отправки ответа.
    """
    db = new_session()
    request.state.db = db
    try:
        yield db
    finally:
        db.close()


Db = Annotated[Session, Depends(get_db)]


def get_now(db: Db) -> datetime:
    """Время сервиса, прочитанное один раз на запрос."""
    return clock.now(db)


Now = Annotated[datetime, Depends(get_now)]


def settings_dep() -> Settings:
    return get_settings()


AppSettings = Annotated[Settings, Depends(settings_dep)]


# --------------------------------------------------------------------------------------------------------------------
# Адрес клиента
# --------------------------------------------------------------------------------------------------------------------


def client_ip(request: Request) -> str:
    """Адрес клиента (Арх. 10.1) — механизм один.

    Берётся адрес TCP-соединения: `uvicorn` запущен без `--proxy-headers`, чтобы его никто не подменял. Если
    соединение пришло из доверенной сети (`TRUSTED_PROXY_CIDRS`, по умолчанию подсеть compose, то есть от `nginx`
    контейнера `web`), адресом клиента считается значение `X-Real-IP`. От любого другого источника заголовок
    игнорируется — иначе лимиты по IP обходились бы подстановкой заголовка.
    """
    peer = request.client.host if request.client else ""
    try:
        peer_addr = ipaddress.ip_address(peer)
    except ValueError:
        return peer or "unknown"  # не IP (например, сокет тестового клиента): заголовкам не доверяем
    if any(peer_addr in network for network in get_settings().trusted_networks):
        forwarded = request.headers.get(REAL_IP_HEADER, "").strip()
        if forwarded:
            try:
                return str(ipaddress.ip_address(forwarded))
            except ValueError:
                pass  # мусор в заголовке: остаётся адрес соединения
    return str(peer_addr)


ClientIp = Annotated[str, Depends(client_ip)]


# --------------------------------------------------------------------------------------------------------------------
# Пользователь и роли
# --------------------------------------------------------------------------------------------------------------------


def optional_user(request: Request, response: Response, db: Db) -> CurrentUser | None:
    """Пользователь по cookie `sid` либо `None`. Срок сессии — по реальному времени (Арх. 10.1)."""
    token = request.cookies.get(security.SESSION_COOKIE)
    user = security.load_session(db, token, clock.real_now())
    if user is not None and user.session_renewed and token:
        security.set_session_cookie(response, token)  # срок продлён в базе — продлеваем и cookie
    return user


OptionalUser = Annotated[CurrentUser | None, Depends(optional_user)]


def current_user(user: OptionalUser) -> CurrentUser:
    """Вошедший пользователь любой роли; без действующей сессии — 401 `not_authenticated`."""
    if user is None:
        raise ApiException(401, "not_authenticated")
    return user


AnyUser = Annotated[CurrentUser, Depends(current_user)]


def _require_role(role: Role) -> Callable[[CurrentUser], CurrentUser]:
    def dependency(user: AnyUser) -> CurrentUser:
        if user.role != role:
            raise ApiException(403, "forbidden")
        return user

    dependency.__name__ = f"require_{role.value}"
    return dependency


require_candidate = _require_role(Role.CANDIDATE)
require_employer = _require_role(Role.EMPLOYER)

Candidate = Annotated[CurrentUser, Depends(require_candidate)]
Employer = Annotated[CurrentUser, Depends(require_employer)]


def require_admin(request: Request) -> None:
    """Служебное действие: заголовок `X-Admin-Token` равен `ADMIN_TOKEN` (сравнение за постоянное время)."""
    provided = request.headers.get(ADMIN_HEADER, "")
    expected = get_settings().admin_token
    if not provided or not expected or not security.constant_time_equals(provided, expected):
        raise ApiException(403, "forbidden")


Admin = Annotated[None, Depends(require_admin)]


def is_admin(request: Request) -> bool:
    """Есть ли в запросе верный `X-Admin-Token` (для действий, доступных и ведущему, и посетителю с лимитом)."""
    try:
        require_admin(request)
    except ApiException:
        return False
    return True


def require_feature(name: str) -> Callable[[], None]:
    """Зависимость эндпоинта за флагом (`demo`, `vacancies`, `pulse`, `integrations`): 404 `feature_disabled`.

    Подключается к роутеру целиком: `APIRouter(route_class=TxRoute, dependencies=[Depends(require_feature("pulse"))])`.
    """
    if name not in FEATURE_NAMES:
        raise ValueError(f"неизвестный флаг: {name}")

    def dependency() -> None:
        if not get_settings().features[name]:
            raise ApiException(404, "feature_disabled")

    dependency.__name__ = f"require_feature_{name}"
    return dependency


# --------------------------------------------------------------------------------------------------------------------
# Пагинация
# --------------------------------------------------------------------------------------------------------------------


def page_params(
    cursor: Annotated[str | None, Query(description="Непрозрачный курсор из next_cursor", max_length=2048)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT, description="Размер страницы")] = DEFAULT_LIMIT,
) -> PageParams:
    """Параметры списка с продолжением (Арх. 9.3). Битый курсор — 422 `cursor_invalid`."""
    return PageParams.parse(cursor, limit)


Paging = Annotated[PageParams, Depends(page_params)]
