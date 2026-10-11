"""Общие части сида: ключи аккаунтов, детерминированный датчик, генерация синтетических людей (Арх. 13.5).

Всё случайное берётся из `random.Random(SEED + смещение)`: повторный запуск строит те же люди и те же пути
тестов, поэтому недописанный сид можно продолжить, а проверки — повторить. Адреса синтетических людей
живут на `demo.test`, телефоны, имена пользователей и ссылки выдуманы.
"""

# ruff: noqa: E501 — таблицы текстов и имён читаются лучше в строку

from __future__ import annotations

import logging
import random
from datetime import timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

log = logging.getLogger("app.seed")

SEED = 20261006
DEMO_DOMAIN = "demo.test"

#: Сколько синтетических кандидатов специализации `backend` создаёт сид (переменная `SEED_PER_SPECIALIZATION`).
DEFAULT_POPULATION = 150
#: Сколько кандидатов с заявленным грейдом создаёт сид в каждой специализации без теста
#: (переменная `SEED_DECLARED_PER_SPECIALIZATION`; 0 — не создавать).
DEFAULT_DECLARED = 12
#: Доли грейдов в популяции: junior, middle, senior.
GRADE_SHARES: tuple[tuple[str, float], ...] = (("junior", 0.34), ("middle", 0.40), ("senior", 0.26))
#: Доля кандидатов с привязкой ФСП и с привязкой без участий (приложение D, §8.4).
FSP_HISTORY_SHARE = 0.40
FSP_EMPTY_SHARE = 0.05
BATCH = 25

COMPANY_KEYS = ("company_1", "company_2", "company_3")
EMPLOYER_KEY = "orbita"
#: Именованные кандидаты сценария (Арх. 13.5). `nina` — клон на вход — в этой сборке не создаётся.
CANDIDATE_KEYS = ("anna", "dmitry", "ivan", "gleb", "boris", "olga", "maria", "petr")
SCENARIO_KEYS = (EMPLOYER_KEY, *CANDIDATE_KEYS)


def population_key(index: int) -> str:
    return f"cand_{index:03d}"


def email_for(key: str) -> str:
    return f"{key.replace('_', '-')}@{DEMO_DOMAIN}" if key.startswith(("cand_", "company_")) else f"{key}@{DEMO_DOMAIN}"


def rng_for(offset: int) -> random.Random:
    return random.Random(SEED + offset)


def invitation_key(*parts: object) -> str:
    """Ключ идемпотентности приглашения сида: повторный запуск не плодит дубликаты."""
    return str(uuid5(NAMESPACE_URL, "seed:" + ":".join(str(part) for part in parts)))


def days(value: float) -> timedelta:
    return timedelta(days=value)


# --- люди --------------------------------------------------------------------------------------------------------------

MALE = (
    "Александр", "Алексей", "Андрей", "Антон", "Артём", "Борис", "Вадим", "Василий", "Виктор", "Глеб", "Григорий",
    "Даниил", "Денис", "Дмитрий", "Евгений", "Егор", "Иван", "Игорь", "Илья", "Кирилл", "Константин", "Леонид",
    "Максим", "Михаил", "Никита", "Николай", "Олег", "Павел", "Пётр", "Роман", "Руслан", "Сергей", "Тимур", "Фёдор",
    "Юрий", "Ярослав",
)  # fmt: skip
FEMALE = (
    "Алёна", "Алиса", "Анастасия", "Анна", "Валерия", "Вера", "Виктория", "Дарья", "Евгения", "Екатерина", "Елена",
    "Ирина", "Карина", "Кристина", "Ксения", "Людмила", "Маргарита", "Мария", "Милана", "Наталья", "Ольга", "Полина",
    "Светлана", "София", "Татьяна", "Ульяна", "Юлия", "Яна",
)  # fmt: skip
SURNAMES = (
    "Абрамов", "Андреев", "Баранов", "Белов", "Богданов", "Воробьёв", "Герасимов", "Григорьев", "Громов", "Дмитриев",
    "Егоров", "Ершов", "Зайцев", "Исаев", "Карпов", "Киселёв", "Ковалёв", "Комаров", "Крылов", "Куликов", "Лазарев",
    "Макаров", "Медведев", "Миронов", "Назаров", "Орлов", "Осипов", "Пономарёв", "Русаков", "Савельев", "Селезнёв",
    "Тарасов", "Устинов", "Фролов", "Хохлов", "Шубин", "Щербаков", "Юдин", "Яковлев",
)  # fmt: skip

ABOUT_PLAIN = (
    "Пишу сервисы на бэкенде, люблю понятные интерфейсы между командами и аккуратные миграции баз данных.",
    "Занимаюсь серверной разработкой несколько лет, участвовал в хакатонах и олимпиадах, ищу команду с культурой код-ревью.",
    "Интересны высоконагруженные сервисы и наблюдаемость: метрики, трассировки, алерты, которые не будят зря.",
    "Работал над платёжными и складскими сервисами, умею разбираться в чужом коде и писать тесты на него.",
    "Начинал со спортивного программирования, сейчас делаю внутренние API и интеграции с внешними системами.",
)
#: «О себе» с контактами, записанными словами: до раскрытия они не должны утекать в ответы работодателю.
ABOUT_WITH_CONTACTS = (
    "Мой телефон: восемь девятьсот сорок пять, двенадцать тридцать четыре, пятьдесят шесть. Пишите в любое время.",
    "Связаться со мной проще всего в телеграме: собака, demo, нижнее подчёркивание, writer, один два три.",
    "Почта: demo точка writer собака example точка com, отвечаю по вечерам.",
)

CITIES = ("Москва", "Санкт-Петербург", "Казань", "Новосибирск", "Екатеринбург", "Нижний Новгород", "Самара", "Уфа")

LANGUAGE_SKILL = {"python": "python", "java": "java", "go": "go", "nodejs": "nodejs", "csharp": "csharp", "php": "php"}
EXTRA_SKILLS = (
    "sql", "postgresql", "redis", "docker", "git", "rest_api", "fastapi", "django", "kafka", "rabbitmq", "celery",
    "sqlalchemy", "microservices", "system_design", "grpc", "mongodb", "mysql", "async",
)  # fmt: skip


def full_name(rng: random.Random) -> tuple[str, str]:
    """Фамилия и имя одного рода."""
    surname = rng.choice(SURNAMES)
    if rng.random() < 0.3:
        first = rng.choice(FEMALE)
        surname = surname + ("а" if not surname.endswith("ой") else "")
    else:
        first = rng.choice(MALE)
    return surname, first


def phone_for(index: int) -> str:
    return f"+7 9{index % 90 + 10:02d} {index // 7 % 900 + 100:03d}-{index % 97:02d}-{index % 89 + 10:02d}"


def telegram_for(index: int) -> str:
    return f"@demo_writer_{index:03d}"


def link_for(index: int) -> str:
    return f"https://example.com/in/demo-writer-{index:03d}"


def uuid_str(value: UUID) -> str:
    return str(value)


def ensure_ready() -> bool:
    """Опубликовать доступные пары «специализация — грейд» (хук старта `assessment`) и проверить, что есть `backend`.

    В процессе `api` хук уже выполнен при старте; в `python -m app.seed` и шаге инициализации — нет.
    """
    from app import wiring
    from app.modules.catalog import service as catalog

    wiring.load("app.modules.assessment:on_startup")()
    ok = catalog.is_available("backend")
    if not ok:
        log.warning("сид: специализация backend недоступна (банк не собран), сид пропущен")
    return ok


def available_grades() -> list[str]:
    from app.modules.catalog import service as catalog

    return [grade for grade in ("junior", "middle", "senior") if catalog.is_available("backend", grade)]
