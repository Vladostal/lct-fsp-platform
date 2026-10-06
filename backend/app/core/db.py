"""База данных: декларативная основа, сессии, граница транзакции (Арх. 2.4, п. 4; 8.1; 13.4).

Что здесь лежит и как этим пользоваться:

* `Base` — основа моделей всех модулей; имена ограничений задаёт `NAMING_CONVENTION`
  (`pk_`, `fk_`, `uq_`, `ix_`, `ck_`).
* `create_schema(engine)` — единственная функция, создающая схему из метаданных: ею пользуются и стенд до появления
  начальной миграции (Арх. 13.2), и тесты.
* `TxRoute` — класс маршрута: фиксирует транзакцию сразу после возврата обработчика, до отправки ответа. Роутеры
  модулей создаются как `APIRouter(route_class=TxRoute)`; сервисы `commit` не вызывают.
* `run_in_tx(db, fn)` — для операций, которые фиксируют себя сами и один раз повторяются при `40001` и `40P01`
  (операции `contact`).
* `session_scope()` — короткая собственная сессия вне запроса: скрипты, фоновый цикл, захват попытки синхронизации.

Время в базу пишет только Python (`core.clock`): значения по умолчанию `now()` в DDL запрещены (Арх. 2.4, п. 5).
"""

from __future__ import annotations

import importlib
import logging
import threading
from collections.abc import Callable, Coroutine, Iterator
from contextlib import contextmanager
from enum import Enum
from typing import Any

from fastapi import Request, Response
from fastapi.routing import APIRoute
from sqlalchemy import CheckConstraint, Engine, MetaData, create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from starlette.background import BackgroundTask, BackgroundTasks
from starlette.concurrency import run_in_threadpool

from app.core import mail
from app.core.config import get_settings
from app.core.errors import ApiException

log = logging.getLogger("app.db")

#: Имена ограничений (Арх. 8.1). Одинаковы в метаданных и в миграциях, иначе `alembic check` видит расхождения.
NAMING_CONVENTION: dict[str, str] = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
}

#: Схема таблиц демо-реестра ФСП (Арх. 8.12); платформа её не читает.
FSPMOCK_SCHEMA = "fspmock"

#: Модули с таблицами. Порядок — снизу вверх по слоям (Арх. 2.3); на создание схемы он не влияет.
MODEL_MODULES: tuple[str, ...] = (
    "app.modules.identity.models",
    "app.modules.catalog.models",
    "app.modules.company.models",
    "app.modules.assessment.models",
    "app.modules.fsp.models",
    "app.modules.profile.models",
    "app.modules.matching.models",
    "app.modules.contact.models",
    "app.modules.vacancies.models",
    "app.modules.pulse.models",
    "app.modules.integrations.models",
    "app.fsp_mock.models",
)

#: Коды SQLSTATE, при которых транзакцию имеет смысл повторить: сбой сериализации и взаимная блокировка.
RETRYABLE_SQLSTATES = frozenset({"40001", "40P01"})

#: Модели, которые есть на диске, но не импортировались (нестрогий режим): имя модуля → причина. Тесты показывают
#: это предупреждением, иначе владелец сломанного файла увидел бы только «relation does not exist».
MODEL_IMPORT_ERRORS: dict[str, str] = {}

# Ключ блокировки на время создания схемы: два процесса (migrate и локальный запуск) не делают DDL одновременно.
_SCHEMA_LOCK_KEY = 7_316_001


class Base(DeclarativeBase):
    """Основа моделей. Таблицы платформы — схема `public`, демо-реестра — `fspmock`."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def enum_check(column: str, enum_cls: type[Enum]) -> CheckConstraint:
    """`CHECK (column IN (...))` по перечислению Арх. 8.2: перечисления хранятся как `text` (Арх. 8.1).

    Пример: `__table_args__ = (enum_check("role", Role),)` даёт ограничение `ck_app_user_role`.
    """
    values = ", ".join("'" + str(member.value).replace("'", "''") + "'" for member in enum_cls)
    return CheckConstraint(f"{column} IN ({values})", name=column)


# --------------------------------------------------------------------------------------------------------------------
# Движок и сессии
# --------------------------------------------------------------------------------------------------------------------

_lock = threading.Lock()
_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def make_engine(url: str | None = None, **kwargs: Any) -> Engine:
    """Новый движок по `DATABASE_URL`. Пул — 10 соединений (Арх. 13.6); соединение проверяется перед выдачей.

    Часовой пояс соединения — UTC независимо от настроек сервера: моменты времени читаются из базы в UTC
    и в том же виде уходят в ответы API (Арх. 9.1).
    """
    settings = get_settings()
    options: dict[str, Any] = {
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_pre_ping": True,
        "connect_args": {"options": "-c timezone=UTC"},
    }
    options.update(kwargs)
    if "poolclass" in options:
        options.pop("pool_size", None)
        options.pop("max_overflow", None)
    return create_engine(url or settings.database_url, **options)


def get_engine() -> Engine:
    """Движок процесса; создаётся при первом обращении, чтобы импорт приложения не требовал базы."""
    global _engine, _session_factory
    if _engine is None:
        with _lock:
            if _engine is None:
                _engine = make_engine()
                _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=True)
    return _engine


def dispose_engine() -> None:
    """Закрыть пул и забыть движок (остановка процесса, смена `DATABASE_URL` в тестах)."""
    global _engine, _session_factory
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _session_factory = None


def new_session() -> Session:
    """Новая сессия на общем движке. Закрывает её тот, кто открыл.

    `expire_on_commit=False`: объекты остаются читаемыми после фиксации — `run_in_tx` фиксирует транзакцию
    внутри обработчика, а ответ строится из уже загруженных объектов без новых запросов.
    """
    get_engine()
    assert _session_factory is not None
    return _session_factory()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Собственная короткая сессия: фиксация при выходе, откат при исключении.

    Письма, поставленные в очередь внутри блока, уходят после успешной фиксации и сбрасываются при откате.
    """
    db = new_session()
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        mail.discard(db)
        raise
    else:
        mail.flush(db)
    finally:
        db.close()


# --------------------------------------------------------------------------------------------------------------------
# Схема
# --------------------------------------------------------------------------------------------------------------------


def import_all_models(*, strict: bool | None = None) -> list[str]:
    """Импортировать `models.py` всех модулей, чтобы их таблицы попали в `Base.metadata`.

    Импорт ленивый и по именам: `core` не зависит от модулей статически (Арх. 2.4). Модуля без `models.py`
    (ещё не написан либо таблиц нет) это не касается. Сломанный `models.py` при `WIRING_STRICT=false` даёт
    предупреждение и пропускается, чтобы недописанный чужой файл не останавливал остальные пакеты;
    при `true` — ошибка. Возвращает список загруженных модулей.
    """
    if strict is None:
        strict = get_settings().wiring_strict
    importlib.import_module("app.core.clock")  # таблица service_clock
    loaded: list[str] = []
    for name in MODEL_MODULES:
        try:
            importlib.import_module(name)
        except Exception as exc:
            # Нет самого models.py или его пакета — нормальное состояние; нет чего-то внутри него — ошибка.
            missing = exc.name if isinstance(exc, ModuleNotFoundError) else None
            if missing and (name == missing or name.startswith(missing + ".")):
                continue
            if strict:
                raise
            MODEL_IMPORT_ERRORS[name] = f"{type(exc).__name__}: {exc}"
            log.warning("модели %s не загружены: %s", name, MODEL_IMPORT_ERRORS[name])
        else:
            MODEL_IMPORT_ERRORS.pop(name, None)
            loaded.append(name)
    return loaded


def create_schema(engine: Engine | None = None) -> None:
    """Создать схему из метаданных: `public`, `fspmock`, все таблицы и DDL-события моделей (Арх. 13.2, 13.4).

    Идемпотентна: существующие таблицы не трогает (изменение модели требует пересоздать базу — до начальной
    миграции это `docker compose down -v`). Одна и та же функция работает на стенде без миграции и в тестах.
    """
    engine = engine or get_engine()
    import_all_models()
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _SCHEMA_LOCK_KEY})
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {FSPMOCK_SCHEMA}"))
        Base.metadata.create_all(conn)


def ping(engine: Engine | None = None) -> None:
    """Проверить соединение с базой (`SELECT 1`); при сбое поднимает исключение драйвера."""
    with (engine or get_engine()).connect() as conn:
        conn.execute(text("SELECT 1"))


# --------------------------------------------------------------------------------------------------------------------
# Граница транзакции запроса
# --------------------------------------------------------------------------------------------------------------------


def _finish_request_tx(db: Session, *, commit: bool) -> list[mail.OutgoingMail]:
    """Зафиксировать либо откатить транзакцию запроса; вернуть письма, которые теперь можно отправлять."""
    if not commit:
        db.rollback()
        mail.discard(db)
        return []
    try:
        db.commit()
    except BaseException:
        db.rollback()
        mail.discard(db)
        raise
    return mail.take(db)


def _with_task(background: BackgroundTask | None, messages: list[mail.OutgoingMail]) -> BackgroundTask:
    """Добавить отправку писем к фоновым задачам ответа, сохранив уже назначенные."""
    tasks = background if isinstance(background, BackgroundTasks) else BackgroundTasks()
    if background is not None and background is not tasks:
        tasks.tasks.append(background)
    tasks.add_task(mail.deliver, messages)
    return tasks


class TxRoute(APIRoute):
    """Маршрут с транзакцией «одна на запрос, фиксация до отправки ответа» (Арх. 2.4, п. 4).

    Сессию открывает зависимость `core.deps.get_db` и кладёт в `request.state.db`. Сразу после возврата
    обработчика (ответ уже построен, но ещё не отправлен) маршрут фиксирует транзакцию, поэтому клиент не может
    получить 2xx раньше фиксации, а сбой фиксации превращается в ошибку, а не в ложный успех. Исключение
    обработчика и ответ со статусом 4xx/5xx откатывают транзакцию. Письма из `mail.enqueue` уходят фоновой
    задачей ответа только после успешной фиксации; при откате очередь сбрасывается.

    Исключение из правила отката — `ApiException(..., commit=True)`: записанное до ошибки фиксируется.
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                response = await original(request)
            except BaseException as exc:
                db: Session | None = getattr(request.state, "db", None)
                if db is not None:
                    keep = isinstance(exc, ApiException) and exc.commit
                    messages = await run_in_threadpool(_finish_request_tx, db, commit=keep)
                    if messages:
                        # Ответ построит обработчик ошибок; он и заберёт задачу отправки (core.errors).
                        request.state.after_commit = BackgroundTask(mail.deliver, messages)
                raise
            db = getattr(request.state, "db", None)
            if db is not None:
                messages = await run_in_threadpool(_finish_request_tx, db, commit=response.status_code < 400)
                if messages:
                    response.background = _with_task(response.background, messages)
            return response

        return handler


def run_in_tx[T](db: Session, fn: Callable[[Session], T], *, retries: int = 1) -> T:
    """Выполнить `fn(db)` и зафиксировать; при `40001` и `40P01` — откатить и повторить один раз (Арх. 2.4, п. 4).

    `fn` должна быть повторяемой: всё состояние она читает из базы заново. Очередь писем сбрасывается при каждом
    откате, поэтому при повторе письмо не уходит дважды, а при окончательной неудаче не уходит вовсе. После
    успешной фиксации письма остаются в очереди сессии: их отправит `TxRoute` (в запросе) либо `session_scope`
    и фоновый цикл (вне запроса).
    """
    attempt = 0
    while True:
        try:
            result = fn(db)
            db.commit()
            return result
        except ApiException as exc:
            # Тот же договор, что у TxRoute: commit=True сохраняет записанное до ошибки (и очередь писем).
            if exc.commit:
                db.commit()
            else:
                db.rollback()
                mail.discard(db)
            raise
        except DBAPIError as exc:
            db.rollback()
            mail.discard(db)
            sqlstate = getattr(exc.orig, "sqlstate", None)
            if sqlstate in RETRYABLE_SQLSTATES and attempt < retries:
                attempt += 1
                log.info("повтор транзакции после %s (попытка %s)", sqlstate, attempt + 1)
                continue
            raise
        except BaseException:
            db.rollback()
            mail.discard(db)
            raise
