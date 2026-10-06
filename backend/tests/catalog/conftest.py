"""Фикстуры тестов `catalog`: чистое состояние публикаций модуля."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.modules.catalog import service


@pytest.fixture(autouse=True)
def clean_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Пустые публикации (лимиты и доступные пары) на время теста; прежние возвращаются после."""
    monkeypatch.setattr(service, "_limits", {})
    monkeypatch.setattr(service, "_available", set())
    yield
