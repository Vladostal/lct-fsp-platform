"""Группы заданий и карта «навык → группа» (Арх. 5.3, 5.4).

Группа — единица плана теста и единица вердикта по навыку. Справочник специализаций и грейдов живёт в модуле
`catalog`; здесь остаются только коды, от которых зависит состав теста (Арх. 15.1, № 20).
"""

from __future__ import annotations

from dataclasses import dataclass

#: Специализации, для которых существуют планы теста (Арх. 5.2). Остальные коды каталога — «тест готовится».
SPECIALIZATIONS: tuple[str, ...] = ("backend", "frontend", "fullstack", "data_ml")

#: Специализации, по которым тест написан. Это свойство кода, а не состояния банка: если банк такой специализации
#: не собран или она выключена настройкой, тест «временно недоступен» — заявленную категорию в ней получить нельзя.
TESTED_SPECIALIZATIONS: frozenset[str] = frozenset({"backend"})

#: Отметка «для всех»: специализации семейств языковых групп (Арх. 5.3).
ANY_SPECIALIZATION = "*"

_ALL = SPECIALIZATIONS


@dataclass(frozen=True)
class Group:
    """Группа заданий: строка таблицы Арх. 5.3."""

    code: str
    title: str
    #: Специализации, чьим семействам принадлежит группа; у языковых групп — `("*",)`.
    specializations: tuple[str, ...]
    #: Языковой модуль: группа выдаётся только сессии с `lang_module`, равным её коду.
    is_lang: bool
    #: Пакет плана работ, который пишет семейства группы.
    package: str


GROUPS: dict[str, Group] = {
    g.code: g
    for g in (
        Group("code", "Чтение кода и поиск ошибок", _ALL, False, "B21a"),
        Group("algo", "Алгоритмы и сложность", _ALL, False, "B21a"),
        Group("ds", "Структуры данных", _ALL, False, "B21a"),
        Group("sql", "SQL", _ALL, False, "B21b"),
        Group("http", "HTTP и веб-API", ("backend", "frontend", "fullstack"), False, "B21c"),
        Group("git", "Git", _ALL, False, "B21c"),
        Group("py", "Python", (ANY_SPECIALIZATION,), True, "B21c"),
        Group("db", "Базы данных: индексы и транзакции", ("backend", "fullstack"), False, "B21b"),
        Group("svc", "Сервисы: конкурентность и надёжность", ("backend", "fullstack"), False, "B21c"),
        Group("js", "JavaScript", (ANY_SPECIALIZATION,), True, "B22"),
        Group("css", "CSS и вёрстка", ("frontend", "fullstack"), False, "B22"),
        Group("web", "Браузер и интерфейсы", ("frontend", "fullstack"), False, "B22"),
        Group("stats", "Статистика и вероятность", ("data_ml",), False, "B23"),
        Group("ml", "Машинное обучение: метрики и практика", ("data_ml",), False, "B23"),
        Group("dw", "Обработка данных", ("data_ml",), False, "B23"),
    )
}

#: Языковые группы.
LANG_GROUPS: tuple[str, ...] = tuple(code for code, group in GROUPS.items() if group.is_lang)

#: Столбец плана «языковой модуль»: при сборке формы заменяется группой `py` или `js`, а без модуля — группой `code`.
LANG_SLOT = "lang"

#: Порядок столбцов плана теста (Арх. 5.4): в этом порядке сборка формы обходит привязанные слоты.
GROUP_ORDER: tuple[str, ...] = (
    "code", LANG_SLOT, "algo", "ds", "sql", "http", "git", "db", "svc", "css", "web", "stats", "ml", "dw",
)  # fmt: skip


@dataclass(frozen=True)
class SkillMap:
    """Навыки группы: `direct` — задания группы их действительно проверяют; `related` — косвенная связь."""

    direct: tuple[str, ...]
    related: tuple[str, ...] = ()


#: Таблица Арх. 5.4. Инструменты конкретных поставщиков — только `related`: доказательства «тест» они не дают.
SKILL_GROUP_MAP: dict[str, SkillMap] = {
    "code": SkillMap(("code_reading", "debugging")),
    "algo": SkillMap(("algorithms", "complexity", "graphs", "dynamic_programming")),
    "ds": SkillMap(("data_structures", "hashing", "trees")),
    "sql": SkillMap(
        ("sql", "sql_joins", "sql_aggregation", "sql_window_functions"),
        ("postgresql", "mysql", "clickhouse", "oracle", "mssql", "orm"),
    ),
    "http": SkillMap(
        ("http", "rest_api", "web_caching", "web_security_basics"),
        ("fastapi", "django", "flask", "spring", "express", "graphql", "openapi"),
    ),
    "git": SkillMap(("git",), ("gitlab", "github", "code_review")),
    "py": SkillMap(("python",), ("asyncio",)),
    "js": SkillMap(("javascript", "async_js"), ("typescript", "nodejs")),
    "db": SkillMap(
        ("databases", "db_indexes", "db_transactions", "db_design"), ("postgresql", "mysql", "mongodb", "redis")
    ),
    "svc": SkillMap(
        ("concurrency", "async", "system_design", "multithreading"),
        ("asyncio", "kafka", "rabbitmq", "microservices", "highload"),
    ),
    "css": SkillMap(("css", "css_layout"), ("html", "sass", "tailwind")),
    "web": SkillMap(("dom", "react", "frontend_performance"), ("redux", "vue", "nextjs", "angular")),
    "stats": SkillMap(("statistics", "probability", "ab_testing"), ("product_analytics",)),
    "ml": SkillMap(("ml_metrics", "ml_validation", "machine_learning"), ("sklearn", "catboost", "pytorch")),
    "dw": SkillMap(("pandas", "data_wrangling"), ("numpy", "spark", "etl")),
}
