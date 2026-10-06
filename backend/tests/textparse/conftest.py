"""Фикстуры тестов `textparse`: доступные пары публикует `assessment`, здесь — вручную."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest

from app.modules.catalog import service as catalog


@pytest.fixture(autouse=True)
def only_backend_available(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Гарантированный состав стенда (Арх. 5.2): три категории `backend`; остальное — «тест готовится»."""
    monkeypatch.setattr(catalog, "_available", {("backend", g) for g in ("junior", "middle", "senior")})
    yield


@pytest.fixture
def publish(monkeypatch: pytest.MonkeyPatch) -> Callable[[set[tuple[str, str]]], None]:
    def apply(pairs: set[tuple[str, str]]) -> None:
        monkeypatch.setattr(catalog, "_available", set(pairs))

    return apply
