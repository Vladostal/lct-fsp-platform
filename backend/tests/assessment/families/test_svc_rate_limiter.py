"""Приёмка семейства `svc.rate_limiter` (B21c)."""

from __future__ import annotations

from fractions import Fraction

from app.modules.assessment.families._lib.netmodel import (
    fixed_window_rejects,
    sliding_window_rejects,
    token_bucket_rejects,
)
from tests.assessment.families._b21c_checks import assert_accepted, assert_deterministic


def test_accepted() -> None:
    assert_accepted("svc.rate_limiter")


def test_deterministic_and_selfcheck() -> None:
    assert_deterministic("svc.rate_limiter")


def test_fixed_window_boundary() -> None:
    requests = [(t, "-") for t in (4, 4, 4, 5, 5, 5)]  # окна по 5 с: [0,5) и [5,10)
    assert fixed_window_rejects(requests, 2, 5) == 2
    assert fixed_window_rejects(requests, 2, 5, no_reset=True) == 4
    assert sliding_window_rejects(requests, 2, 5) == 4  # на границе окно скользящее: 4 запроса за 5 с


def test_token_bucket_refills_exactly() -> None:
    assert token_bucket_rejects([0, 0, 0, 2, 3, 4], 2, Fraction(1, 2)) == 2
    assert token_bucket_rejects([0, 0, 0, 2, 3, 4], 2, Fraction(1, 2), no_refill=True) == 4


def test_sliding_window_is_per_client() -> None:
    requests = [(0, "A"), (0, "A"), (1, "A"), (1, "B"), (5, "A")]
    assert sliding_window_rejects(requests, 2, 5) == 1  # A: третий запрос в t=1 отклонён, в t=5 нулевой уже вне окна
