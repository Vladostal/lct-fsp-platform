"""Общие правила текста для подписей, которые формирует сервер (Арх. 6.10, 9.1).

В готовых текстах нет чисел балла, процентов и сравнений с другими кандидатами — за этим следит вызывающий код;
здесь только склонения, перечисления и форматы.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

from app.core.config import get_settings

NBSP = "\u00a0"  # неразрывный пробел


def plural(n: int, one: str, few: str, many: str) -> str:
    """Форма слова по числу: `plural(3, "день", "дня", "дней")` → «дня».

    Правило русского языка: 1, 21, 31… — `one`; 2–4, 22–24… — `few`; остальное, включая 11–14, — `many`.
    Возвращается только слово; число вызывающий подставляет сам.
    """
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def count_phrase(n: int, one: str, few: str, many: str) -> str:
    """Число со словом через неразрывный пробел: «3 дня», «21 кандидат»."""
    return f"{n}{NBSP}{plural(n, one, few, many)}"


def join_titles(titles: Sequence[str], limit: int = 3) -> str:
    """Перечисление названий: «A», «A и B», «A, B и C», «A, B, C и ещё {k}» (приложение B, §6.4).

    В тексте остаётся не больше `limit` названий; остальные сворачиваются в «и ещё k».
    """
    items = [title for title in titles if title]
    if not items:
        return ""
    if len(items) > limit:
        return f"{', '.join(items[:limit])} и ещё {len(items) - limit}"
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} и {items[-1]}"


def fmt_date(value: date | datetime) -> str:
    """Дата `ДД.ММ.ГГГГ`. Момент времени сначала переводится в часовой пояс `APP_TZ`."""
    if isinstance(value, datetime):
        # Часовой пояс берётся из настроек напрямую, а не через core.clock: этот файл импортируют чистые ядра,
        # которым нельзя тянуть за собой SQLAlchemy (Арх. 2.4, п. 6).
        value = value.astimezone(get_settings().tz).date()
    return value.strftime("%d.%m.%Y")


def fmt_money(amount: int) -> str:
    """Сумма с разрядами и знаком рубля: «180 000 ₽» (пробелы неразрывные)."""
    return f"{amount:,}".replace(",", NBSP) + f"{NBSP}₽"


def fmt_salary_range(salary_from: int, salary_to: int) -> str:
    """Вилка: «180 000 – 240 000 ₽»."""
    return f"{salary_from:,}".replace(",", NBSP) + f"{NBSP}–{NBSP}" + fmt_money(salary_to)
