"""Приёмка семейства `http.cache_timeline` (B21c)."""

from __future__ import annotations

from app.modules.assessment.families._lib.netmodel import (
    CachePolicy,
    CacheRequest,
    browser_cache,
    shared_cache_origin_hits,
)
from tests.assessment.families._b21c_checks import assert_accepted, assert_deterministic


def test_accepted() -> None:
    assert_accepted("http.cache_timeline")


def test_deterministic_and_selfcheck() -> None:
    assert_deterministic("http.cache_timeline")


def test_max_age_is_strict_and_refreshes_on_reload() -> None:
    policy = CachePolicy(max_age=10)
    assert browser_cache([0, 9, 10, 15], policy) == ["200", "cache", "200", "cache"]
    # Модель ошибки: возраст от первой загрузки — на t=15 ответ уже считался бы устаревшим.
    assert browser_cache([0, 9, 10, 15], policy, age_from_first=True) == ["200", "cache", "200", "200"]


def test_no_cache_revalidates_and_no_store_does_not_keep() -> None:
    etag = CachePolicy(etag=True, no_cache=True)
    assert browser_cache([0, 5, 9], etag, changes=[7]) == ["200", "304", "200"]
    store = CachePolicy(etag=True, no_store=True)
    assert browser_cache([0, 5, 9], store, changes=[7]) == ["200", "200", "200"]


def test_shared_cache_rules() -> None:
    requests = [CacheRequest(0, 1), CacheRequest(5, 2), CacheRequest(50, 1)]
    public = CachePolicy(max_age=10, s_maxage=60)
    assert shared_cache_origin_hits(requests, public) == 1  # общий кэш держит ответ 60 с
    assert shared_cache_origin_hits(requests, CachePolicy(max_age=10, private=True)) == 3
    ru_en = [CacheRequest(0, 1, "ru"), CacheRequest(1, 2, "en")]
    assert shared_cache_origin_hits(ru_en, CachePolicy(max_age=20, s_maxage=60, vary_language=True)) == 2
    assert shared_cache_origin_hits(ru_en, CachePolicy(max_age=20, s_maxage=60)) == 1
