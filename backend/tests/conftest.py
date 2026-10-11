"""Общий каркас тестов бэкенда (план работ, раздел 0, п. 6; Арх. 13.4).

Главное:

* **Своя база на каждый запуск pytest.** Имя `test_<случайный суффикс>`; база создаётся при первом обращении
  к фикстурам `db` или `client` и удаляется по завершении запуска. Чужие базы и схемы тесты не трогают, поэтому
  пакеты запускают тесты одновременно на одном PostgreSQL. Схема создаётся той же функцией, что и на стенде без
  миграции: `core.db.create_schema`. Тест без базы (чистые ядра) PostgreSQL не требует вовсе.
* **Сервер БД** берётся из переменной `TEST_DATABASE_URL` (по умолчанию `postgresql+psycopg://app:app@127.0.0.1:5432/app`). Имя базы в адресе заменяется на тестовое.
* **Окружение тестов задано здесь** и не зависит от `.env` разработчика: учебные секреты, `WIRING_STRICT=false`,
  фоновый цикл выключен, все флаги усилений включены, письма не уходят в SMTP, а складываются в `mailbox`.

Фикстуры для всех пакетов (свои — в `tests/<модуль>/conftest.py`):

* `db` — сессия внутри внешней транзакции; после теста всё откатывается. `commit()` внутри теста и приложения
  безопасен: это точка сохранения.
* `client` — `TestClient` приложения, работающий в той же сессии `db`: тест видит записанное запросом и наоборот.
* `make_client()` — ещё один независимый клиент (свои cookie) на той же сессии: сценарии с двумя пользователями.
* `make_user(role="candidate", ...)` — пользователь, созданный напрямую в `app_user` (без модуля `identity`).
* `login_as(user, client=None)` — сессия входа напрямую в `auth_session` и cookie `sid` в клиенте; возвращает клиент.
* `freeze_now(момент)` — заморозить реальное время (`clock.real_now()`, а значит и `clock.now()`);
  `freeze_now.tick(...)` сдвигает его.
* `mailbox` — список писем, «отправленных» после фиксации транзакции.
* `override_settings(**значения)` — временно поменять настройки (`feature_vacancies=False` и т. п.).
* `db_factory` — настоящие независимые сессии с настоящей фиксацией: тесты гонок и блокировок (метка `real_db`);
  после теста таблицы очищаются.
* `app`, `engine`, `settings` — приложение, движок и настройки запуска.
"""

from __future__ import annotations

import atexit
import os
import secrets
import signal
import threading
import warnings
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

# --------------------------------------------------------------------------------------------------------------------
# Окружение запуска. Задаётся до первого импорта приложения: настройки читаются один раз и кэшируются.
# --------------------------------------------------------------------------------------------------------------------

DEFAULT_SERVER_URL = "postgresql+psycopg://app:app@127.0.0.1:5432/app"
SERVER_URL = os.environ.get("TEST_DATABASE_URL") or DEFAULT_SERVER_URL
TEST_DB_NAME = f"test_{secrets.token_hex(6)}"
TEST_PASSWORD = "Test-pass-2026"


def _with_database(url: str, database: str) -> str:
    from sqlalchemy.engine import make_url

    return make_url(url).set(database=database).render_as_string(hide_password=False)


os.environ.pop("APP_ENV_FILE", None)
os.environ.update(
    {
        "APP_ENV": "development",
        "DATABASE_URL": _with_database(SERVER_URL, TEST_DB_NAME),
        "DB_POOL_SIZE": "3",
        "DB_MAX_OVERFLOW": "7",
        "ASSESSMENT_SECRET": "test-only-assessment-secret",
        "ADMIN_TOKEN": "test-only-admin-token",
        "PUBLIC_BASE_URL": "http://localhost:8080",
        "ALLOWED_ORIGINS": "",
        "COOKIE_SECURE": "false",
        "WIRING_STRICT": "false",
        "BACKGROUND_ENABLED": "false",
        "LOG_LEVEL": "warning",
        "DEMO_MODE": "true",
        "FSP_MODE": "mock",
        "FSP_MOCK_ENABLED": "true",
        "FEATURE_VACANCIES": "true",
        "FEATURE_PULSE": "true",
        "FEATURE_INTEGRATIONS": "true",
        "SMTP_HOST": "smtp.invalid",
        "TRUSTED_PROXY_CIDRS": "172.28.5.0/24",
        "REREGISTER_COOLDOWN_DAYS": "30",
        "SIGNUP_IP_LIMIT_PER_HOUR": "5",
    }
)

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pwdlib import PasswordHash  # noqa: E402
from pwdlib.hashers.argon2 import Argon2Hasher  # noqa: E402
from sqlalchemy import (  # noqa: E402
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Table,
    Text,
    Uuid,
    create_engine,
    insert,
    text,
)
from sqlalchemy.engine import Engine  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.core import clock, mail, security  # noqa: E402
from app.core import db as core_db  # noqa: E402
from app.core.config import Settings, get_settings  # noqa: E402
from app.core.deps import get_db  # noqa: E402
from app.shared.enums import Role  # noqa: E402

_database_created = False


def pytest_report_header() -> str:
    from sqlalchemy.engine import make_url

    server = make_url(SERVER_URL)
    return f"тестовая база: {TEST_DB_NAME} на {server.host}:{server.port or 5432} (создаётся при первом обращении)"


# --------------------------------------------------------------------------------------------------------------------
# База запуска
# --------------------------------------------------------------------------------------------------------------------


def _admin_engine() -> Engine:
    """Служебное соединение с сервером: только для CREATE DATABASE и DROP DATABASE своей базы."""
    return create_engine(SERVER_URL, isolation_level="AUTOCOMMIT", poolclass=NullPool)


def _create_database() -> None:
    global _database_created
    admin = _admin_engine()
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    except OperationalError as exc:
        pytest.exit(
            "PostgreSQL для тестов недоступен ("
            + _with_database(SERVER_URL, "…").split("@")[-1]
            + "). Задайте адрес PostgreSQL в переменной TEST_DATABASE_URL.\n"
            + f"Причина: {exc.orig}",
            returncode=3,
        )
    finally:
        admin.dispose()
    _database_created = True


def _drop_database() -> None:
    """Удалить базу этого запуска. Вызывается из фикстуры и ещё раз при выходе процесса — на случай аварии."""
    global _database_created
    if not _database_created:
        return
    core_db.dispose_engine()
    admin = _admin_engine()
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
        _database_created = False
    finally:
        admin.dispose()


atexit.register(_drop_database)


def _terminate(signum: int, frame: object) -> None:
    """SIGTERM (тайм-аут запускающей среды) → обычное прерывание pytest: фикстуры завершатся, база будет удалена."""
    raise KeyboardInterrupt("SIGTERM")


if threading.current_thread() is threading.main_thread():
    signal.signal(signal.SIGTERM, _terminate)


def _ensure_identity_tables() -> None:
    """Таблицы `app_user` и `auth_session` для тестов, пока модуль `identity` не написал свои модели.

    На `app_user(id)` ссылаются внешние ключи всех модулей, а `make_user` и `login_as` пишут в эти таблицы
    напрямую. Колонки — ровно по Арх. 8.3. Как только появится `identity/models.py`, таблицы приходят из него,
    и эта подстановка перестаёт срабатывать.
    """
    metadata = core_db.Base.metadata
    if "app_user" not in metadata.tables:
        Table(
            "app_user",
            metadata,
            Column("id", Uuid, primary_key=True),
            Column("email", Text, nullable=False, unique=True),
            Column("password_hash", Text, nullable=True),
            Column("role", Text, nullable=False),
            Column("email_verified_at", DateTime(timezone=True), nullable=True),
            Column("is_adult_confirmed", Boolean, nullable=False),
            Column("is_demo", Boolean, nullable=False),
            Column("demo_key", Text, nullable=True, unique=True),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("last_login_at", DateTime(timezone=True), nullable=True),
        )
    if "auth_session" not in metadata.tables:
        Table(
            "auth_session",
            metadata,
            Column("id", Uuid, primary_key=True),
            Column("user_id", Uuid, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True),
            Column("token_hash", Text, nullable=False, unique=True),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("expires_at", DateTime(timezone=True), nullable=False),
            Column("last_seen_at", DateTime(timezone=True), nullable=False),
            Column("user_agent", Text, nullable=True),
        )


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """Движок на базе этого запуска: база создана, схема развёрнута из метаданных."""
    _create_database()
    try:
        core_db.import_all_models()
        for name, reason in core_db.MODEL_IMPORT_ERRORS.items():
            warnings.warn(
                pytest.PytestWarning(f"модели {name} не загрузились, их таблиц в тестовой базе нет: {reason}"),
                stacklevel=1,
            )
        _ensure_identity_tables()
        test_engine = core_db.get_engine()
        core_db.create_schema(test_engine)
        yield test_engine
    finally:
        _drop_database()


def _truncate_all(target: Engine) -> None:
    tables = [
        f'"{table.schema}"."{table.name}"' if table.schema else f'"{table.name}"'
        for table in core_db.Base.metadata.sorted_tables
    ]
    if tables:
        with target.begin() as conn:
            conn.execute(text(f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE"))


@pytest.fixture
def db(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    """Сессия теста. Всё записанное — и тестом, и приложением — откатывается после теста.

    Сессия привязана к соединению с открытой внешней транзакцией; её `commit()` лишь освобождает точку сохранения.
    Собственные короткие сессии кода (`core.db.new_session`, `session_scope`) в тесте открываются на том же
    соединении, поэтому видят данные теста и откатываются вместе с ним.
    """
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    monkeypatch.setattr(core_db, "_session_factory", factory)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture
def db_factory(engine: Engine) -> Iterator[Callable[[], Session]]:
    """Настоящие независимые сессии с настоящей фиксацией — для гонок, блокировок и повторов `run_in_tx`.

    Не сочетается с `db` и `client` в одном тесте. После теста все таблицы очищаются (`TRUNCATE`), поэтому такие
    тесты помечаются `@pytest.mark.real_db` и держатся отдельно от быстрых.
    """
    opened: list[Session] = []

    def factory() -> Session:
        session = core_db.new_session()
        opened.append(session)
        return session

    try:
        yield factory
    finally:
        for session in opened:
            session.close()
        _truncate_all(engine)


# --------------------------------------------------------------------------------------------------------------------
# Приложение и клиент
# --------------------------------------------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def app(engine: Engine) -> Iterator[FastAPI]:
    """Приложение запуска. Старт (`lifespan`: лимиты модулей, хуки старта) выполняется один раз."""
    from app import wiring
    from app.main import create_app

    application = create_app()
    # WIRING_STRICT=false: сломанный модуль пропускается, и его маршруты в тестах отвечали бы 404 без объяснений.
    for spec in wiring.ROUTERS:
        try:
            wiring.load(spec)
        except wiring.WiringError as exc:
            warnings.warn(pytest.PytestWarning(f"роутеры не подключены: {exc}"), stacklevel=1)
    with TestClient(application):
        yield application


@pytest.fixture
def make_client(app: FastAPI, db: Session) -> Iterator[Callable[..., TestClient]]:
    """Фабрика клиентов на сессии теста: у каждого клиента свои cookie.

    Перед каждым запросом подготовленные тестом данные «фиксируются» (освобождается точка сохранения): так откат
    транзакции запроса при ошибке не уносит то, что тест создал до запроса, — как и в жизни, где запрос видит
    только зафиксированное.
    """

    def override(request: Request) -> Iterator[Session]:
        db.commit()
        request.state.db = db
        yield db

    app.dependency_overrides[get_db] = override

    def factory(**kwargs: Any) -> TestClient:
        return TestClient(app, **kwargs)

    try:
        yield factory
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    """Клиент API без сессии входа; необработанная ошибка приложения поднимается в тесте исключением."""
    return make_client()


# --------------------------------------------------------------------------------------------------------------------
# Пользователи и вход — напрямую, без модуля identity
# --------------------------------------------------------------------------------------------------------------------

# Быстрый Argon2 для тестовых паролей: хеш того же формата, обычный `security.verify_password` его проверяет.
_fast_hasher = PasswordHash((Argon2Hasher(time_cost=1, memory_cost=8, parallelism=1),))
_hash_cache: dict[str, str] = {}


def fast_password_hash(password: str) -> str:
    if password not in _hash_cache:
        _hash_cache[password] = _fast_hasher.hash(password)
    return _hash_cache[password]


@dataclass(frozen=True)
class TestUser:
    """Пользователь, созданный `make_user`. `id` — он же `candidate_id` или `employer_id`."""

    __test__ = False

    id: UUID
    email: str
    role: Role
    is_demo: bool
    password: str


@pytest.fixture
def make_user(db: Session) -> Callable[..., TestUser]:
    """Создать пользователя напрямую в `app_user`: `make_user()`, `make_user("employer", email="hr@example.com")`.

    По умолчанию адрес подтверждён, пароль — `TEST_PASSWORD`. Дополнительные колонки таблицы можно передать
    именованными аргументами (`demo_key="anna"`).
    """
    table = core_db.Base.metadata.tables["app_user"]

    def factory(
        role: Role | str = Role.CANDIDATE,
        *,
        email: str | None = None,
        password: str | None = TEST_PASSWORD,
        verified: bool = True,
        is_demo: bool = False,
        **columns: Any,
    ) -> TestUser:
        role = Role(role)
        user_id = uuid4()
        created = clock.real_now()
        values: dict[str, Any] = {
            "id": user_id,
            "email": (email or f"{role.value}-{user_id.hex[:10]}@example.com").lower(),
            "password_hash": fast_password_hash(password) if password and verified else None,
            "role": role.value,
            "email_verified_at": created if verified else None,
            "is_adult_confirmed": True,
            "is_demo": is_demo,
            "demo_key": None,
            "created_at": created,
            "last_login_at": None,
        }
        values.update(columns)
        db.execute(insert(table).values({key: value for key, value in values.items() if key in table.c}))
        db.commit()
        return TestUser(id=user_id, email=values["email"], role=role, is_demo=is_demo, password=password or "")

    return factory


@pytest.fixture
def login_as(db: Session, client: TestClient) -> Callable[..., TestClient]:
    """Открыть сессию входа напрямую в `auth_session` и положить cookie `sid` в клиент.

    `login_as(user)` — в клиент фикстуры `client`; `login_as(user, client=make_client())` — в отдельный клиент.
    """
    table = core_db.Base.metadata.tables["auth_session"]
    default_client = client

    def factory(user: TestUser, client: TestClient | None = None) -> TestClient:
        target = client or default_client
        token = security.new_token()
        opened = clock.real_now()
        values: dict[str, Any] = {
            "id": uuid4(),
            "user_id": user.id,
            "token_hash": security.hash_token(token),
            "created_at": opened,
            "expires_at": opened + security.session_ttl(),
            "last_seen_at": opened,
            "user_agent": "pytest",
        }
        db.execute(insert(table).values({key: value for key, value in values.items() if key in table.c}))
        db.commit()
        target.cookies.set(security.SESSION_COOKIE, token)
        return target

    return factory


# --------------------------------------------------------------------------------------------------------------------
# Время, почта, настройки
# --------------------------------------------------------------------------------------------------------------------


class FrozenClock:
    """Управление замороженным реальным временем: `freeze_now(момент)`, затем `freeze_now.tick(hours=2)`."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._monkeypatch = monkeypatch
        self._current: datetime | None = None

    def __call__(self, moment: datetime | str | None = None) -> datetime:
        """Заморозить время на `moment` (datetime либо ISO-строка; без часового пояса — UTC; `None` — текущее)."""
        if moment is None:
            moment = datetime.now(UTC)
        elif isinstance(moment, str):
            moment = datetime.fromisoformat(moment)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        self._current = moment.astimezone(UTC)
        self._monkeypatch.setattr(clock, "_time_source", self._read)
        return self._current

    def _read(self) -> datetime:
        assert self._current is not None
        return self._current

    @property
    def current(self) -> datetime:
        return self._current if self._current is not None else clock.real_now()

    def tick(self, seconds: float = 0, **delta: float) -> datetime:
        """Сдвинуть замороженное время вперёд: `tick(30)`, `tick(days=7)`."""
        if self._current is None:
            self()
        assert self._current is not None
        self._current = self._current + timedelta(seconds=seconds, **delta)
        return self._current


@pytest.fixture
def freeze_now(monkeypatch: pytest.MonkeyPatch) -> FrozenClock:
    """Заморозить реальное время. Время сервиса `clock.now(db)` = замороженное + демо-сдвиг `service_clock`."""
    return FrozenClock(monkeypatch)


@pytest.fixture(autouse=True)
def mailbox() -> Iterator[list[mail.OutgoingMail]]:
    """Письма, отправленные за тест. Настоящего SMTP в тестах нет: транспорт заменён списком."""
    sent: list[mail.OutgoingMail] = []
    previous = mail.set_transport(sent.extend)
    try:
        yield sent
    finally:
        mail.set_transport(previous)


@pytest.fixture
def override_settings(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Settings]:
    """Временно поменять настройки процесса: `override_settings(feature_pulse=False, demo_mode=False)`.

    Действует на всё, что читает `get_settings()` в момент вызова. Список роутеров приложения уже собран и
    от флагов после старта не зависит.
    """

    def apply(**values: Any) -> Settings:
        current = get_settings()
        for name, value in values.items():
            if name not in Settings.model_fields:
                raise AttributeError(f"нет такой настройки: {name}")
            monkeypatch.setattr(current, name, value)
        return current

    return apply
