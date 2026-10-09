"""Словари имён для генераторов: переменные, функции, таблицы, столбцы, значения (приложение A, §2.2).

Зачем общий файл. Имена — то, что seed меняет от варианта к варианту без изменения сложности. Если каждый пакет
заведёт свои списки, задания разных групп будут узнаваться по лексике, а одинаковые сущности называться по-разному.

Правила:

* только кортежи строк и чистые функции от переданного `random.Random`; никакого глобального состояния;
* все значения выдуманы и обезличены: адреса — в домене `example.com`, имена — распространённые, без фамилий;
* внутри кортежа значения различны; порядок менять нельзя — от него зависит результат генераторов. Новые значения
  добавляются только в конец, и это требует `version + 1` у семейств, которые берут имена из этого кортежа.
"""

from __future__ import annotations

from collections.abc import Sequence
from random import Random

# --- код -----------------------------------------------------------------------------------------------------------

#: Счётчики циклов.
LOOP_VARS: tuple[str, ...] = ("i", "j", "k", "n", "m", "t")
#: Числовые переменные.
NUM_VARS: tuple[str, ...] = ("total", "count", "acc", "res", "cur", "best", "left", "right", "step", "limit", "x", "y")
#: Переменные-коллекции.
LIST_VARS: tuple[str, ...] = ("items", "data", "nums", "values", "queue", "stack", "seen", "buf", "rows", "parts")
#: Переменные-словари.
DICT_VARS: tuple[str, ...] = ("counts", "index", "cache", "groups", "by_key", "table", "memo", "stats")
#: Имена функций — без смысловой нагрузки: имя не должно подсказывать или искажать, что делает код
#: (`merge` и `split` заменены на `handle` и `compute` на тех же местах, версии семейств увеличены).
FUNC_NAMES: tuple[str, ...] = (
    "calc", "solve", "process", "walk", "fold", "scan", "handle", "compute", "build", "check",
)  # fmt: skip
#: Имена классов.
CLASS_NAMES: tuple[str, ...] = ("Base", "Node", "Item", "Task", "Shape", "Event", "Account", "Buffer", "Worker")
#: Короткие слова латиницей: значения строк, ключи словарей, метки.
WORDS: tuple[str, ...] = (
    "alpha", "beta", "gamma", "delta", "omega", "kappa", "sigma", "theta",
    "red", "green", "blue", "amber", "olive", "coral", "ivory", "slate",
    "north", "south", "east", "west", "river", "stone", "cloud", "maple",
)  # fmt: skip
#: Метки для заданий на порядок вывода.
LABELS: tuple[str, ...] = ("A", "B", "C", "D", "E", "F", "G", "H")

# --- таблицы и данные ----------------------------------------------------------------------------------------------

#: Имена таблиц (единственное число, латиница) с типичными столбцами: первый столбец — ключ.
TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "orders": ("id", "customer_id", "amount", "status", "city"),
    "customers": ("id", "name", "city", "segment"),
    "products": ("id", "title", "category", "price", "stock"),
    "employees": ("id", "name", "dept", "salary", "manager_id"),
    "payments": ("id", "order_id", "amount", "method"),
    "tickets": ("id", "author_id", "priority", "state", "hours"),
    "visits": ("id", "user_id", "page", "duration"),
    "shipments": ("id", "order_id", "warehouse", "weight"),
}
TABLE_NAMES: tuple[str, ...] = tuple(TABLE_COLUMNS)

#: Имена людей (без фамилий).
FIRST_NAMES: tuple[str, ...] = (
    "Анна", "Борис", "Вера", "Глеб", "Дарья", "Егор", "Жанна", "Захар",
    "Инна", "Кирилл", "Лидия", "Марк", "Нина", "Олег", "Полина", "Роман",
)  # fmt: skip
#: Те же имена латиницей — для строковых значений в коде.
FIRST_NAMES_LATIN: tuple[str, ...] = (
    "anna", "boris", "vera", "gleb", "daria", "egor", "zhanna", "zakhar",
    "inna", "kirill", "lidia", "mark", "nina", "oleg", "polina", "roman",
)  # fmt: skip
CITIES: tuple[str, ...] = ("Казань", "Самара", "Тверь", "Пермь", "Омск", "Тула", "Уфа", "Томск")
DEPARTMENTS: tuple[str, ...] = ("dev", "qa", "ops", "sales", "support", "design")
STATUSES: tuple[str, ...] = ("new", "paid", "shipped", "done", "cancelled")
CATEGORIES: tuple[str, ...] = ("books", "tools", "toys", "games", "music", "garden")
SEGMENTS: tuple[str, ...] = ("retail", "partner", "vip")
PAYMENT_METHODS: tuple[str, ...] = ("card", "cash", "transfer")
PRIORITIES: tuple[str, ...] = ("low", "normal", "high")

# --- сеть, файлы, git ----------------------------------------------------------------------------------------------

#: Узлы только в зарезервированном домене example.com (RFC 2606).
HOSTS: tuple[str, ...] = ("example.com", "api.example.com", "shop.example.com", "cdn.example.com", "app.example.com")
URL_PATHS: tuple[str, ...] = ("/items", "/orders", "/users", "/cart", "/search", "/reports", "/files", "/profile")
QUERY_KEYS: tuple[str, ...] = ("page", "limit", "sort", "q", "lang", "tag", "from", "to")
RESOURCES: tuple[str, ...] = ("order", "user", "invoice", "comment", "booking", "report")
FILE_NAMES: tuple[str, ...] = (
    "app.py", "config.yaml", "README.md", "utils.py", "models.py", "routes.py", "tests.py", "notes.txt",
)  # fmt: skip
BRANCH_NAMES: tuple[str, ...] = ("main", "dev", "feature", "hotfix", "release", "topic")
COOKIE_NAMES: tuple[str, ...] = ("sid", "theme", "lang", "cart", "promo", "track")

# --- вёрстка -------------------------------------------------------------------------------------------------------

COLORS: tuple[str, ...] = ("red", "green", "blue", "orange", "purple", "teal", "gray", "black")
HTML_TAGS: tuple[str, ...] = ("div", "section", "article", "ul", "li", "p", "span", "a", "button")
CSS_CLASSES: tuple[str, ...] = ("card", "title", "menu", "item", "active", "note", "badge", "row")
ELEMENT_IDS: tuple[str, ...] = ("main", "nav", "hero", "list", "footer", "side")


# --- выбор ---------------------------------------------------------------------------------------------------------


def pick[T](rng: Random, pool: Sequence[T]) -> T:
    """Один элемент словаря. Единственный источник случайности — переданный `rng`."""
    return pool[rng.randrange(len(pool))]


def pick_many[T](rng: Random, pool: Sequence[T], count: int) -> list[T]:
    """`count` различных элементов словаря в случайном порядке; `ValueError`, если словарь короче."""
    if count > len(pool):
        raise ValueError(f"в словаре {len(pool)} значений, запрошено {count}")
    return rng.sample(list(pool), count)


def option_ids(count: int) -> list[str]:
    """Идентификаторы вариантов выбора по порядку показа: «o1», «o2», …"""
    return [f"o{i}" for i in range(1, count + 1)]


def block_ids(count: int) -> list[str]:
    """Идентификаторы блоков для задания на порядок: «b1», «b2», …"""
    return [f"b{i}" for i in range(1, count + 1)]
