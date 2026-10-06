"""Пагинация курсором (Арх. 9.3)."""

from __future__ import annotations

import pytest

from app.core.errors import ApiException
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, PageParams, decode_cursor, encode_cursor, make_page
from app.shared.schemas import Page


def test_cursor_roundtrip_is_opaque_base64url():
    position = {"at": "2026-10-05T10:00:00+00:00", "id": "7b1f", "label": "кандидат"}
    cursor = encode_cursor(position)
    assert "=" not in cursor and "+" not in cursor and "/" not in cursor
    assert decode_cursor(cursor) == position


def test_empty_cursor_is_start_of_list():
    assert decode_cursor(None) is None and decode_cursor("") is None


@pytest.mark.parametrize("cursor", ["!!!", "abc", "bm90IGpzb24", "WzEsMl0", "x" * 3000])
def test_broken_cursor_is_422_cursor_invalid(cursor):
    # «bm90IGpzb24» — base64 от «not json»; «WzEsMl0» — от «[1,2]» (не объект).
    with pytest.raises(ApiException) as error:
        decode_cursor(cursor)
    assert (error.value.status, error.value.code) == (422, "cursor_invalid")


def test_page_params_limits():
    assert PageParams.parse(None).limit == DEFAULT_LIMIT == 20
    assert PageParams.parse(None, 500).limit == MAX_LIMIT == 50
    assert PageParams.parse(encode_cursor({"id": 1}), 10).position == {"id": 1}


def test_make_page_uses_extra_row_as_continuation_marker():
    rows = list(range(1, 7))  # сервис читает limit + 1 строку
    page = make_page(rows, 5, lambda row: {"id": row})
    assert isinstance(page, Page)
    assert page.items == [1, 2, 3, 4, 5]
    assert decode_cursor(page.next_cursor) == {"id": 5}

    last = make_page(rows[:3], 5, lambda row: {"id": row})
    assert last.items == [1, 2, 3] and last.next_cursor is None
    assert make_page([], 5, lambda row: {"id": row}).model_dump() == {"items": [], "next_cursor": None}
