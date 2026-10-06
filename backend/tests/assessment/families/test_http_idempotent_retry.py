"""Приёмка семейства `http.idempotent_retry` (B21c)."""

from __future__ import annotations

from app.modules.assessment.families._lib.netmodel import HttpRequest, conditional_puts, orders_after
from tests.assessment.families._b21c_checks import assert_accepted, assert_deterministic


def test_accepted() -> None:
    assert_accepted("http.idempotent_retry")


def test_deterministic_and_selfcheck() -> None:
    assert_deterministic("http.idempotent_retry")


def test_semantics_of_methods() -> None:
    # POST дважды (повтор после таймаута) создаёт два заказа, PUT по тому же номеру — один.
    assert orders_after([1], [HttpRequest("POST", attempts=2)]) == 3
    assert orders_after([1], [HttpRequest("PUT", 20, attempts=3)]) == 2
    # Ключ идемпотентности: повторы с одним ключом создают один заказ; DELETE повторять безопасно.
    assert orders_after([1, 2], [HttpRequest("POST", key="k1", attempts=3), HttpRequest("DELETE", 1, attempts=2)]) == 2
    assert orders_after([1], [HttpRequest("POST", attempts=2)], post_is_idempotent=True) == 2


def test_if_match_retry_is_stale_after_success() -> None:
    # Первая отправка применилась (версия 3 -> 4), повтор с If-Match: 3 устарел и получает 412.
    assert conditional_puts(3, [(3, 2)]) == 4
    assert conditional_puts(3, [(3, 2)], if_match_ignored=True) == 5
    assert conditional_puts(3, [(2, 1), (3, 1)]) == 4
