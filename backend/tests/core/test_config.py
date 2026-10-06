"""Настройки (Арх. 13.3, 10.6): разбор окружения и отказ старта публичного стенда с учебными значениями."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings, module_env

GOOD_SECRETS = {"assessment_secret": "a" * 64, "admin_token": "b" * 64}
DEV_SECRETS = {
    "assessment_secret": "dev-only-assessment-secret-change-me",
    "admin_token": "dev-only-admin-token-change-me",
}


def make(**values) -> Settings:
    """Настройки только из аргументов: без окружения процесса и без файла .env."""

    class Isolated(Settings):
        @classmethod
        def settings_customise_sources(cls, settings_cls, init_settings, **other_sources):
            return (init_settings,)

    return Isolated(**values)


def production(**values) -> Settings:
    base = {
        "app_env": "production",
        "cookie_secure": True,
        "public_base_url": "https://podbor.example.com",
        "mail_ui_user": "jury",
        "mail_ui_password": "mail-password",
        **GOOD_SECRETS,
    }
    return make(**{**base, **values})


def test_development_starts_with_example_values():
    settings = make(**DEV_SECRETS)
    assert settings.demo is True and settings.fsp_mock is True
    assert settings.features == {"demo": True, "vacancies": False, "pulse": False, "integrations": False}
    assert settings.wiring_strict is True
    assert settings.reregister_cooldown_days == 30
    assert settings.signup_ip_limit_per_hour == 5


def test_secrets_are_required():
    with pytest.raises(ValidationError) as error:
        make()
    assert {item["loc"][0] for item in error.value.errors()} == {"assessment_secret", "admin_token"}


def test_production_starts_with_proper_values_and_demo_off_by_default():
    settings = production()
    assert settings.is_production
    assert settings.demo is False and settings.fsp_mock is False  # Арх. 10.3: включаются только явно
    assert production(demo_mode=True, fsp_mock_enabled=True).features["demo"] is True


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"assessment_secret": DEV_SECRETS["assessment_secret"]}, "ASSESSMENT_SECRET"),
        ({"admin_token": DEV_SECRETS["admin_token"]}, "ADMIN_TOKEN"),
        ({"admin_token": "   "}, "ADMIN_TOKEN"),
        ({"cookie_secure": False}, "COOKIE_SECURE"),
        ({"mail_ui_password": ""}, "MAIL_UI"),
    ],
)
def test_production_refuses_to_start(override, fragment):
    with pytest.raises(ValidationError) as error:
        production(**override)
    assert fragment in str(error.value)


def test_production_with_real_smtp_does_not_need_mail_ui_password():
    assert (
        production(smtp_host="smtp.example.com", mail_ui_user="", mail_ui_password="").smtp_host == "smtp.example.com"
    )


def test_lists_are_parsed_from_comma_separated_strings():
    settings = make(
        **DEV_SECRETS,
        trusted_proxy_cidrs="172.28.5.0/24, 10.0.0.0/8",
        disabled_specializations="frontend,data_ml",
        allowed_origins="http://web, https://Stand.Example.com/",
    )
    assert [str(net) for net in settings.trusted_networks] == ["172.28.5.0/24", "10.0.0.0/8"]
    assert settings.disabled_specializations == ["frontend", "data_ml"]
    assert {
        "http://localhost:8080",
        "http://web",
        "https://stand.example.com",
        "http://localhost:5173",
    } <= settings.origins
    assert make(**DEV_SECRETS, disabled_specializations="").disabled_specializations == []


def test_dev_server_origin_is_not_allowed_in_production():
    assert production().origins == {"https://podbor.example.com"}


def test_empty_flag_means_default():
    assert make(**DEV_SECRETS, demo_mode="", fsp_mock_enabled="").demo is True


@pytest.mark.parametrize(
    "values",
    [
        {"trusted_proxy_cidrs": "172.28.5.0/33"},
        {"public_base_url": "localhost:8080"},
        {"app_tz": "Europe/Nowhere"},
        {"reregister_cooldown_days": 31},
        {"reregister_cooldown_days": -1},
        {"app_env": "staging"},
    ],
)
def test_invalid_values_are_rejected(values):
    with pytest.raises(ValidationError):
        make(**DEV_SECRETS, **values)


def test_cooldown_accepts_fraction_of_a_day():
    """Стенд ставит карантин адреса в минуты: дробное число суток допустимо."""
    assert make(**DEV_SECRETS, reregister_cooldown_days="0.007").reregister_cooldown_days == pytest.approx(0.007)


def test_paths_resolve_from_repository_root():
    settings = make(**DEV_SECRETS)
    assert settings.validation_path.parts[-2:] == ("docs", "validation")
    assert settings.validation_path.is_absolute() and settings.data_path.name == "data"


def test_env_example_matches_settings_and_is_accepted(monkeypatch):
    """Каждая переменная .env.example известна настройкам, а файл целиком проходит проверку запуска."""
    from app.core.config import REPO_ROOT

    example = REPO_ROOT / ".env.example"
    names = {
        line.split("=", 1)[0].strip().lower()
        for line in example.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    unknown = names - set(Settings.model_fields)
    assert not unknown, f"в .env.example есть переменные, которых нет в Settings: {sorted(unknown)}"

    for name in list(Settings.model_fields):
        monkeypatch.delenv(name.upper(), raising=False)
    settings = Settings(_env_file=example)
    assert settings.assessment_secret.startswith("dev-only-") and settings.admin_token.startswith("dev-only-")
    assert settings.signup_ip_limit_per_hour == 50
    assert settings.database_url == "postgresql+psycopg://app:app@db:5432/app"

    # Тот же файл с APP_ENV=production не проходит: учебные секреты и COOKIE_SECURE=false.
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(ValidationError):
        Settings(_env_file=example)


def test_module_env_reads_prefixed_variables(monkeypatch):
    from pydantic_settings import BaseSettings

    class ContactConstants(BaseSettings):
        model_config = module_env("CONTACT_")
        slots: int = 5

    assert ContactConstants().slots == 5
    monkeypatch.setenv("CONTACT_SLOTS", "8")
    assert ContactConstants().slots == 8


def test_get_settings_reports_problems_without_values(monkeypatch):
    """Сообщение об ошибке запуска называет переменные, но не печатает их значения (среди них секреты)."""
    from app.core.config import SettingsError, get_settings

    load = get_settings.__wrapped__  # без кэша: настройки запуска тестов остаются нетронутыми

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ADMIN_TOKEN", "dev-only-super-secret-value")
    monkeypatch.setenv("SESSION_TTL_DAYS", "много")
    with pytest.raises(SettingsError) as error:
        load()
    message = str(error.value)
    assert "SESSION_TTL_DAYS" in message
    assert "dev-only-super-secret-value" not in message and "test-only" not in message

    monkeypatch.setenv("SESSION_TTL_DAYS", "14")
    with pytest.raises(SettingsError) as error:
        load()
    message = str(error.value)
    assert "ADMIN_TOKEN" in message and "COOKIE_SECURE" in message
    assert "dev-only-super-secret-value" not in message and "test-only" not in message
