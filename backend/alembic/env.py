"""Окружение Alembic (Арх. 13.4).

* Метаданные — `core.db.Base.metadata` с тем же `naming_convention`; модели всех модулей и демо-реестра
  импортируются функцией `core.db.import_all_models` (строго: сломанный `models.py` останавливает миграцию).
* `include_schemas=True`: сравниваются схемы `public` (платформа) и `fspmock` (демо-реестр); чужие схемы
  сервера автогенерация не видит.
* Адрес базы — из настроек приложения (`DATABASE_URL`), драйвер синхронный.

Начальную миграцию `0001_initial` собирает сборочный пакет автогенерацией и дополняет вручную
(`CREATE SCHEMA fspmock`, триггер неизменяемости `invitation_terms`). До её появления схему создаёт
`core.db.create_schema` — и на стенде, и в тестах.
"""

from __future__ import annotations

from logging.config import fileConfig
from typing import Any

from sqlalchemy import pool, text

from alembic import context
from app.core.config import get_settings
from app.core.db import FSPMOCK_SCHEMA, Base, import_all_models, make_engine

config = context.config

# Журнал настраивается из alembic.ini только при запуске командой alembic; при вызове из app.scripts.init
# (и из тестов) действует журнал приложения.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

import_all_models(strict=True)
target_metadata = Base.metadata

MANAGED_SCHEMAS = {None, "public", FSPMOCK_SCHEMA}


def include_name(name: str | None, type_: str, parent_names: Any) -> bool:
    """Автогенерация смотрит только на свои схемы."""
    if type_ == "schema":
        return name in MANAGED_SCHEMAS
    return True


def _configure(**kwargs: Any) -> None:
    context.configure(
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        compare_type=True,
        compare_server_default=True,
        **kwargs,
    )


def run_migrations_offline() -> None:
    """Режим без соединения: печатает SQL (`alembic upgrade head --sql`)."""
    _configure(url=get_settings().database_url, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Обычный режим: одно соединение без пула, одна транзакция на все ревизии."""
    engine = make_engine(poolclass=pool.NullPool)
    with engine.connect() as connection:
        # Схема демо-реестра нужна до сравнения и до создания таблиц; повторный вызов безвреден.
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {FSPMOCK_SCHEMA}"))
        connection.commit()
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
