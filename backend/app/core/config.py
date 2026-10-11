"""Конфигурация приложения из переменных окружения (Арх. 13.3).

Правила:

* единственный способ получить настройки — `get_settings()`; значение кэшируется на процесс
  (тесты сбрасывают кэш через `get_settings.cache_clear()`);
* файл `.env` приложение само не читает, если не задана переменная `APP_ENV_FILE`: в контейнере переменные
  приходят из compose (`env_file`), в тестах — из `tests/conftest.py`, для локальных команд `Makefile`
  передаёт `APP_ENV_FILE=../.env`. Так тесты не зависят от личного `.env` разработчика;
* константы механик (`CONTACT_*`, `ASSESSMENT_*`, `MATCHING_*`) здесь не объявляются: каждый модуль читает их
  в своём `constants.py` через `module_env(prefix)`.
"""

from __future__ import annotations

import ipaddress
import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal, Self
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

#: Каталог backend (в нём лежат app/, alembic/, tests/).
BACKEND_DIR = Path(__file__).resolve().parents[2]
#: Корень репозитория. В образе раскладка та же: /srv/backend и рядом /srv/docs, /srv/data (compose.yml).
REPO_ROOT = BACKEND_DIR.parent

#: Префикс учебных секретов из `.env.example`; при `APP_ENV=production` запуск с ними запрещён (Арх. 10.6).
DEV_SECRET_PREFIX = "dev-only-"

#: Потолок карантина адреса: журнал `login_attempt`, где лежит отметка, чистится через 30 суток (Арх. 2.6, 10.5).
MAX_REREGISTER_COOLDOWN_DAYS = 30.0

CsvList = Annotated[list[str], NoDecode]


def _split_csv(value: Any) -> Any:
    """Строка «a, b,c» из окружения → список; пустая строка → пустой список."""
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return value


def _origin(url: str) -> str:
    """Схема и хост (с портом) адреса без пути — в том виде, в каком браузер шлёт заголовок Origin."""
    parts = urlsplit(url.strip())
    return f"{parts.scheme}://{parts.netloc}".lower()


class Settings(BaseSettings):
    """Переменные окружения процесса `api` и служебных скриптов."""

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False, env_file_encoding="utf-8")

    # --- процесс ----------------------------------------------------------------------------------------------------
    app_env: Literal["development", "production"] = "development"
    app_name: str = "ФСП.Подбор"
    public_base_url: str = "http://localhost:8080"
    #: Дополнительные разрешённые значения заголовка Origin (через запятую): адрес фронтенда при сквозных тестах
    #: в контейнере и т. п. В development адреса dev-сервера Vite разрешены и без этой переменной.
    allowed_origins: CsvList = Field(default_factory=list)
    web_concurrency: int = 1
    log_level: str = "info"
    wiring_strict: bool = True
    #: Фоновый цикл (Арх. 2.6). Выключается только в тестах и в скриптах без сервера.
    background_enabled: bool = True

    # --- база -------------------------------------------------------------------------------------------------------
    database_url: str = "postgresql+psycopg://app:app@db:5432/app"
    db_pool_size: int = 10
    db_max_overflow: int = 5

    # --- секреты ----------------------------------------------------------------------------------------------------
    assessment_secret: str
    admin_token: str

    # --- сессия и регистрация ---------------------------------------------------------------------------------------
    cookie_secure: bool = False
    session_ttl_days: int = 14
    signup_ip_limit_per_hour: int = 5
    trusted_proxy_cidrs: CsvList = Field(default_factory=lambda: ["172.28.5.0/24"])
    nginx_real_ip_from: str = ""  # читает nginx контейнера web; здесь — только чтобы переменная была описана
    reregister_cooldown_days: float = 30.0

    # --- время ------------------------------------------------------------------------------------------------------
    app_tz: str = "Europe/Moscow"

    # --- почта ------------------------------------------------------------------------------------------------------
    smtp_host: str = "mailpit"
    smtp_port: int = 1025
    mail_from: str = "noreply@localhost"
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_tls: bool = False
    mailpit_public_url: str = "/mail/"
    mail_ui_user: str = ""
    mail_ui_password: str = ""

    # --- демо-режим -------------------------------------------------------------------------------------------------
    #: `None` — «по умолчанию»: включено везде, кроме `APP_ENV=production` (Арх. 10.3); итог — свойство `demo`.
    demo_mode: bool | None = None
    demo_public_restart: bool = True
    #: Самовосстановление сценария: устаревший (истекли приглашения `anna` или `ivan`) и никем не используемый
    #: сценарий пересоздаётся фоновой задачей — стенд, оставленный на несколько дней, остаётся пригодным к показу.
    demo_auto_restart: bool = True
    demo_clone_per_ip_per_hour: int = 6
    demo_clone_max: int = 40
    demo_clone_ttl_hours: int = 24
    demo_password: str = "Demo-2026"

    # --- флаги усилений ---------------------------------------------------------------------------------------------
    feature_vacancies: bool = False
    feature_pulse: bool = False
    feature_integrations: bool = False
    disabled_specializations: CsvList = Field(default_factory=list)
    need_parser: Literal["rules", "llm"] = "rules"

    # --- каталоги (относительный путь считается от корня репозитория) -----------------------------------------------
    validation_dir: Path = Path("docs/validation")
    data_dir: Path = Path("data")

    # --- ФСП (Арх. 7.11) --------------------------------------------------------------------------------------------
    fsp_mode: Literal["mock", "keycloak"] = "mock"
    fsp_oidc_discovery_url: str = ""
    fsp_oidc_issuer: str = ""
    fsp_oidc_client_id: str = ""
    fsp_oidc_client_secret: str = ""
    fsp_oidc_scope: str = "openid fsp.achievements.read"
    fsp_registry_url: str = ""
    #: `None` — «по умолчанию»: включено везде, кроме `APP_ENV=production`; итог — свойство `fsp_mock`.
    fsp_mock_enabled: bool | None = None
    fsp_mock_admin: bool = True
    fspmock_auth: Literal["none", "keycloak"] = "none"
    fsp_refresh_after_hours: int = 24
    fsp_manual_sync_min_interval_s: int = 60
    fsp_retry_min_interval_min: int = 10
    fsp_k_anon: int = 20
    fsp_consent_version: str = "fsp-data-1"
    fsp_seed: int = 20261005
    fsp_skill_corr: float = 0.5

    # --- разбор значений --------------------------------------------------------------------------------------------
    @field_validator("allowed_origins", "trusted_proxy_cidrs", "disabled_specializations", mode="before")
    @classmethod
    def _csv(cls, value: Any) -> Any:
        return _split_csv(value)

    @field_validator("demo_mode", "fsp_mock_enabled", mode="before")
    @classmethod
    def _empty_is_default(cls, value: Any) -> Any:
        # Пустая строка в .env («DEMO_MODE=») означает «по умолчанию», а не ошибку разбора.
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("log_level")
    @classmethod
    def _log_level(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("public_base_url")
    @classmethod
    def _base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("PUBLIC_BASE_URL должен быть адресом вида http(s)://хост[:порт]")
        return value

    @field_validator("trusted_proxy_cidrs")
    @classmethod
    def _cidrs(cls, value: list[str]) -> list[str]:
        for cidr in value:
            ipaddress.ip_network(cidr, strict=False)  # ValueError с понятным текстом при опечатке
        return value

    @field_validator("app_tz")
    @classmethod
    def _tz(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (KeyError, ValueError) as exc:  # ZoneInfoNotFoundError — подкласс KeyError
            raise ValueError(f"APP_TZ: неизвестный часовой пояс {value!r}") from exc
        return value

    @field_validator("reregister_cooldown_days")
    @classmethod
    def _cooldown(cls, value: float) -> float:
        # Отметка карантина живёт в журнале login_attempt, который чистится через 30 суток: значение больше
        # молча оборвало бы карантин раньше срока, поэтому оно отвергается при запуске.
        if not 0 <= value <= MAX_REREGISTER_COOLDOWN_DAYS:
            limit = f"{MAX_REREGISTER_COOLDOWN_DAYS:g}"
            raise ValueError(f"REREGISTER_COOLDOWN_DAYS должен быть в пределах 0–{limit} (дробное значение допустимо)")
        return value

    @model_validator(mode="after")
    def _production_guard(self) -> Self:
        """Арх. 10.6: публичный стенд не стартует с учебными секретами и без защищённой cookie."""
        if self.app_env != "production":
            return self
        problems: list[str] = []
        for name, secret in (("ASSESSMENT_SECRET", self.assessment_secret), ("ADMIN_TOKEN", self.admin_token)):
            if not secret.strip() or secret.startswith(DEV_SECRET_PREFIX):
                problems.append(f"{name} пуст или учебный ({DEV_SECRET_PREFIX}…): выполните make init-env")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE должен быть true")
        if self.smtp_host == "mailpit" and not (self.mail_ui_user and self.mail_ui_password):
            problems.append("при почте через Mailpit обязательны MAIL_UI_USER и MAIL_UI_PASSWORD (ящик /mail/)")
        if problems:
            raise ValueError("APP_ENV=production: " + "; ".join(problems))
        return self

    # --- производные значения ---------------------------------------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def demo(self) -> bool:
        """Итоговое значение `DEMO_MODE`: явное либо «включено везде, кроме production»."""
        return (not self.is_production) if self.demo_mode is None else self.demo_mode

    @property
    def fsp_mock(self) -> bool:
        """Итоговое значение `FSP_MOCK_ENABLED`: явное либо «включено везде, кроме production»."""
        return (not self.is_production) if self.fsp_mock_enabled is None else self.fsp_mock_enabled

    @property
    def features(self) -> dict[str, bool]:
        """Флаги для `Catalog.features` и зависимости `require_feature` (Арх. 9.11)."""
        return {
            "demo": self.demo,
            "vacancies": self.feature_vacancies,
            "pulse": self.feature_pulse,
            "integrations": self.feature_integrations,
        }

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.app_tz)

    @property
    def trusted_networks(self) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
        return tuple(ipaddress.ip_network(cidr, strict=False) for cidr in self.trusted_proxy_cidrs)

    @property
    def origins(self) -> frozenset[str]:
        """Значения заголовка Origin, с которыми принимаются изменяющие запросы (Арх. 10.1, CSRF)."""
        allowed = {_origin(self.public_base_url), *(_origin(item) for item in self.allowed_origins)}
        if not self.is_production:
            # dev-сервер Vite (frontend/vite.config.ts): запросы /api проксируются, но Origin остаётся его собственным.
            allowed |= {"http://localhost:5173", "http://127.0.0.1:5173"}
        return frozenset(allowed)

    @property
    def validation_path(self) -> Path:
        return self._resolve(self.validation_dir)

    @property
    def data_path(self) -> Path:
        return self._resolve(self.data_dir)

    @staticmethod
    def _resolve(path: Path) -> Path:
        return path if path.is_absolute() else REPO_ROOT / path


class SettingsError(RuntimeError):
    """Окружение не прошло проверку запуска. Текст называет переменные, но не их значения."""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Настройки процесса. Файл `.env` читается, только если задан `APP_ENV_FILE`.

    Ошибка проверки превращается в `SettingsError` без значений переменных: исходное сообщение Pydantic
    печатает входные данные, а среди них секреты.
    """
    env_file = os.environ.get("APP_ENV_FILE") or None
    try:
        return Settings(_env_file=env_file)
    except ValidationError as exc:
        problems = [
            f"{'.'.join(str(part) for part in error['loc']).upper() or 'окружение'}: "
            + str(error["msg"]).removeprefix("Value error, ")
            for error in exc.errors(include_input=False, include_url=False)
        ]
        raise SettingsError("настройки не прошли проверку — " + " | ".join(problems)) from None


def module_env(prefix: str) -> SettingsConfigDict:
    """Конфигурация `BaseSettings` для констант механик, переопределяемых окружением (Арх. 1.2, п. 8).

    Пример (`contact/constants.py`)::

        class ContactConstants(BaseSettings):
            model_config = module_env("CONTACT_")
            slots: int = 5            # переопределяется переменной CONTACT_SLOTS
    """
    return SettingsConfigDict(
        env_prefix=prefix,
        extra="ignore",
        case_sensitive=False,
        env_file=os.environ.get("APP_ENV_FILE") or None,
        env_file_encoding="utf-8",
    )
