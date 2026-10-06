"""Фикстуры тестов модуля `assessment`."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.modules.assessment.families import Discovery, discover
from app.modules.assessment.families._lib.contract import Family
from tests.assessment.fake_families import PACKAGE


@pytest.fixture(scope="session")
def fake_discovery() -> Discovery:
    """Три учебных семейства из `tests/assessment/fake_families`."""
    return discover(PACKAGE)


@pytest.fixture(scope="session")
def fake_families(fake_discovery: Discovery) -> dict[str, Family]:
    """Учебные семейства по идентификатору."""
    return {family.meta.id: family for family in fake_discovery.families}


@pytest.fixture
def min_pool_3(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Целевое значение MIN_POOL = 3 (по умолчанию 2): ядро P0 и нулевые запасы пулов считаются при нём."""
    from app.modules.assessment.config import get_config

    monkeypatch.setenv("ASSESSMENT_MIN_POOL", "3")
    get_config.cache_clear()
    yield
    monkeypatch.undo()
    get_config.cache_clear()


T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
def catalog_guard(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Доступность пар публикуется в память каталога: после теста возвращается прежнее состояние."""
    from app.modules.catalog import service as catalog

    monkeypatch.setattr(catalog, "_available", set(catalog._available))
    yield


@pytest.fixture
def bank(db: Session, catalog_guard: None) -> list[Family]:
    """Учебный банк (70 семейств реестра на учебных генераторах) в базе теста; все пары доступны."""
    from tests.assessment.bankdb import install_bank

    return install_bank(db)


@pytest.fixture
def candidate_ready(db: Session, bank: list[Family], make_user: Callable[..., Any]) -> Callable[..., Any]:
    """Кандидат с пройденным опросом и заявленным грейдом: `candidate_ready("middle", specialization="backend")`."""
    from app.modules.assessment import candidate
    from app.modules.assessment.config import get_config

    directions = {"backend": "development", "frontend": "development", "fullstack": "development", "data_ml": "data"}
    languages = {"backend": "python", "frontend": "javascript", "fullstack": "javascript", "data_ml": "python"}

    def factory(grade: str | None = "middle", specialization: str = "backend", language: str | None = None) -> Any:
        user = make_user("candidate")
        answers = {
            "direction": directions[specialization],
            "specialization": specialization,
            "main_language": language or languages[specialization],
            "experience_band": "2_4",
            "industry_domains": ["fintech"],
        }
        candidate.put_survey(db, user.id, get_config().survey_version, answers, False, T0)
        if grade is not None:
            candidate.put_claim(db, user.id, grade, T0)
        return user

    return factory
