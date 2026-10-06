"""Пагинация курсором (Арх. 9.3).

Курсор непрозрачен для клиента: `base64url` от JSON с позицией последней отданной строки (например,
`{"at": "2026-10-05T10:00:00+00:00", "id": "…"}`). Битый курсор — 422 `cursor_invalid`.

Пример сервиса::

    position = paging.position                      # dict | None
    rows = query_after(position).limit(paging.limit + 1).all()
    return make_page(rows, paging.limit, lambda row: {"at": row.created_at.isoformat(), "id": str(row.id)})
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from app.core.errors import ApiException
from app.shared.schemas import Page

DEFAULT_LIMIT = 20
MAX_LIMIT = 50
_MAX_CURSOR_LENGTH = 2048


def encode_cursor(position: dict[str, Any]) -> str:
    """Позиция → непрозрачная строка (`base64url` без дополнения)."""
    raw = json.dumps(position, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_cursor(cursor: str | None) -> dict[str, Any] | None:
    """Строка курсора → позиция; `None` и пустая строка — начало списка; мусор — 422 `cursor_invalid`."""
    if not cursor:
        return None
    if len(cursor) > _MAX_CURSOR_LENGTH:
        raise ApiException(422, "cursor_invalid")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        position = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True).decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise ApiException(422, "cursor_invalid") from None
    if not isinstance(position, dict):
        raise ApiException(422, "cursor_invalid")
    return position


@dataclass(frozen=True, slots=True)
class PageParams:
    """Разобранные параметры `cursor` и `limit` запроса."""

    position: dict[str, Any] | None
    limit: int

    @classmethod
    def parse(cls, cursor: str | None, limit: int = DEFAULT_LIMIT) -> PageParams:
        return cls(position=decode_cursor(cursor), limit=max(1, min(limit, MAX_LIMIT)))


def make_page[T](rows: Sequence[T], limit: int, position_of: Callable[[T], dict[str, Any]]) -> Page[T]:
    """Собрать страницу из `limit + 1` прочитанных строк: лишняя строка означает, что продолжение есть."""
    items = list(rows[:limit])
    more = len(rows) > limit
    return Page[T](items=items, next_cursor=encode_cursor(position_of(items[-1])) if more and items else None)
