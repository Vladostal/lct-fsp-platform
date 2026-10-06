"""Таблица семейств банка как данные (Арх. 5.3; приложение A, §3.1–3.3).

Зачем отдельный файл. Уровни и сложность `b` — оценка, а не свойство генератора: после экспертной сверки E1 они
меняются, и планы теста проверяются заново. Поэтому генератор не задаёт `b` сам, а строит паспорт функцией
`family_meta(...)`, которая берёт группу, теги, вид задания, уровни и очередь отсюда. Тест выполнимости планов
(`test_blueprints_feasible`) работает на этой таблице до написания первого генератора.

Что здесь есть:

* `REGISTRY` — все 70 семейств: идентификатор, группа, теги навыков, вид задания, `b` уровней, модели ошибок
  из приложения A, независимый оракул (Арх. 5.3), очередь и признак «ядро P0»;
* `CORE_P0` — ядро P0 в порядке написания. Список вычислен функцией `bank.core.compute_core` и записан данными;
  тест `test_core_p0_matches_registry` падает, если после смены `b` он перестал быть наименьшим выполнимым;
* `family_meta(...)` — паспорт семейства для файла генератора.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.modules.assessment.families._lib.contract import (
    B_MAX,
    B_MIN,
    B_STEP,
    FamilyMeta,
    ItemKind,
    LevelMeta,
    Priority,
    default_time_budget,
)
from app.modules.assessment.groups import GROUPS

__all__ = [
    "CORE_P0",
    "EXTERNAL_ORACLES",
    "QUEUE_TITLES",
    "REGISTRY",
    "FamilySpec",
    "LevelSpec",
    "core_families",
    "family_meta",
    "module_name",
    "specs",
]

#: Оракулы, для которых семейство обязано экспортировать `oracle_check` (Арх. 5.3): ответ считает собственная
#: модель, а сверяет его независимая реализация. `builtin` — ответ и есть результат независимой реализации
#: (CPython, `sqlite3`, `urllib.parse`); `manual` — оракула нет, правила модели стоят в условии, 10 вариантов
#: на уровень проверяет человек (задача H2).
EXTERNAL_ORACLES: frozenset[str] = frozenset({"cpython", "sqlite3_explain", "asyncio", "git", "node", "pandas"})

#: Очереди наполнения банка (Арх. 5.3): порядок работ пакетов семейств.
QUEUE_TITLES: dict[int, str] = {
    1: "ядро P0: backend на трёх грейдах",
    2: "P1: frontend и fullstack (js, css, web)",
    3: "P1: расширение пулов backend",
    4: "P2: data_ml (stats, ml, dw)",
}


@dataclass(frozen=True)
class LevelSpec:
    """Уровень семейства в реестре: номер и сложность."""

    level: int
    b: float


@dataclass(frozen=True)
class FamilySpec:
    """Строка таблицы приложения A, §3."""

    id: str
    title: str
    group: str
    skill_tags: tuple[str, ...]
    kind: ItemKind
    levels: tuple[LevelSpec, ...]
    #: Модели типичных ошибок из приложения A — значение по умолчанию для `FamilyMeta.misconceptions`.
    misconceptions: tuple[str, ...] = ()
    extra_kinds: tuple[ItemKind, ...] = ()
    #: Независимый оракул ключа: `cpython`, `sqlite3_explain`, `asyncio`, `git`, `node`, `pandas`, `builtin`, `manual`.
    oracle: str = "manual"
    #: Специализации; заполняются по группе, у учебных семейств задаются явно.
    specializations: tuple[str, ...] = ()
    #: Очередь наполнения, ключ `QUEUE_TITLES`.
    queue: int = 0
    #: Входит ли семейство в ядро P0.
    core_p0: bool = False
    #: Входит ли семейство в демо-ядро: наименьший набор при `MIN_POOL = 2` (подмножество ядра P0).
    demo_core: bool = False
    #: Место семейства в порядке написания ядра (с единицы); 0 — не в ядре.
    core_order: int = 0

    @property
    def priority(self) -> Priority:
        """Приоритет по очереди: ядро — P0, расширение пулов `backend` и очередь frontend — P1, `data_ml` — P2."""
        if self.queue == 1:
            return "P0"
        return "P2" if self.queue == 4 else "P1"

    @property
    def package(self) -> str:
        """Пакет плана работ, который пишет семейство."""
        return GROUPS[self.group].package

    @property
    def bs(self) -> tuple[float, ...]:
        """Сложности уровней по порядку."""
        return tuple(level.b for level in self.levels)

    @property
    def needs_oracle_check(self) -> bool:
        """Обязан ли модуль семейства экспортировать `oracle_check` (Арх. 5.3)."""
        return self.oracle in EXTERNAL_ORACLES


NUM, TEXT, ONE, MULTI, LINE = (
    ItemKind.NUMERIC_INPUT,
    ItemKind.TEXT_INPUT,
    ItemKind.SINGLE_CHOICE,
    ItemKind.MULTI_CHOICE,
    ItemKind.PICK_LINE,
)

# id, название, теги, вид, b по уровням, модели ошибок, оракул[, дополнительные виды]
_Row = (
    tuple[str, str, tuple[str, ...], ItemKind, tuple[float, ...], tuple[str, ...], str]
    | tuple[str, str, tuple[str, ...], ItemKind, tuple[float, ...], tuple[str, ...], str, tuple[ItemKind, ...]]
)

_ROWS: tuple[_Row, ...] = (
    # --- code: чтение кода и поиск ошибок (B21a) ---------------------------------------------------------------------
    ("code.trace_loops", "Трассировка циклов", ("code_reading",), NUM, (-2.0, -0.5, 1.0),
     ("off_by_one", "ignore_break"), "cpython"),
    ("code.trace_strings", "Трассировка строк и срезов", ("code_reading",), TEXT, (-1.5, 0.0),
     ("inclusive_slice_end",), "cpython"),
    ("code.trace_collections", "Трассировка словарей и списков", ("code_reading", "data_structures"), NUM,
     (-1.5, 0.0, 1.0), ("copy_instead_of_alias",), "cpython"),
    ("code.trace_recursion", "Трассировка рекурсии", ("code_reading", "algorithms"), NUM, (-1.0, 0.5, 1.5),
     ("count_without_memo", "miss_base_case"), "cpython"),
    ("code.bug_boundary", "Поиск ошибки в границах", ("debugging",), LINE, (-1.0, 0.5, 1.5), (), "cpython"),
    ("code.bug_logic", "Поиск логической ошибки", ("debugging",), LINE, (-1.5, 0.0, 1.0), (), "cpython"),
    # --- algo: алгоритмы и сложность (B21a) --------------------------------------------------------------------------
    ("algo.bigo_loops", "Класс сложности по коду", ("algorithms", "complexity"), ONE, (-1.5, 0.0, 1.5), (),
     "cpython"),
    ("algo.ops_count", "Число выполнений строки", ("algorithms", "complexity"), NUM, (-2.0, -0.5, 1.0),
     ("rectangular_instead_of_triangular",), "cpython"),
    ("algo.binary_search", "Шаги бинарного поиска", ("algorithms",), NUM, (-1.5, 0.0), ("off_by_one_mid",),
     "cpython"),
    ("algo.sort_state", "Состояние массива при сортировке", ("algorithms",), TEXT, (-1.5, -0.5, 1.0),
     ("neighbor_algorithm",), "cpython"),
    ("algo.graph_traversal", "Обходы и пути в графе", ("algorithms", "graphs"), TEXT, (-1.0, 0.5, 1.5),
     ("dfs_instead_of_bfs", "greedy_path"), "cpython", (NUM,)),
    ("algo.dp_table", "Таблица динамического программирования", ("algorithms", "dynamic_programming"), NUM,
     (0.5, 1.5, 2.0), ("greedy_choice",), "cpython"),
    # --- ds: структуры данных (B21a) ---------------------------------------------------------------------------------
    ("ds.stack_queue", "Стек, очередь, дек", ("data_structures",), TEXT, (-2.0, -0.5), ("fifo_lifo_swap",),
     "cpython"),
    ("ds.heap_array", "Двоичная куча в массиве", ("data_structures",), TEXT, (-1.0, 0.0, 1.0), ("sorted_array",),
     "cpython"),
    ("ds.hash_probing", "Хеш-таблица и коллизии", ("data_structures", "hashing"), NUM, (-1.0, 0.5, 1.5),
     ("no_collision", "ignore_tombstone"), "cpython"),
    ("ds.bst_ops", "Дерево поиска: вставки и удаления", ("data_structures", "trees"), TEXT, (-1.5, 0.0, 1.0),
     ("predecessor_instead_of_successor",), "cpython", (NUM,)),
    # --- sql (B21b) --------------------------------------------------------------------------------------------------
    ("sql.order_limit", "Сортировка и LIMIT", ("sql",), TEXT, (-2.0, -0.5), ("asc_desc_swap",), "builtin"),
    ("sql.group_having", "GROUP BY и HAVING", ("sql", "sql_aggregation"), NUM, (-1.5, 0.0, 1.0),
     ("where_instead_of_having", "count_star_vs_column"), "builtin"),
    ("sql.join_rows", "Число строк соединения", ("sql", "sql_joins"), NUM, (-1.5, 0.0, 1.0),
     ("inner_instead_of_left", "no_fanout"), "builtin"),
    ("sql.null_logic", "Логика NULL", ("sql",), NUM, (-1.0, 0.5, 1.5), ("null_equals_null", "not_in_ignores_null"),
     "builtin"),
    ("sql.window", "Оконные функции", ("sql", "sql_window_functions"), NUM, (0.5, 1.5, 2.0),
     ("rank_vs_dense_rank", "default_frame"), "builtin"),
    ("sql.subquery_cte", "Подзапросы и WITH", ("sql",), NUM, (0.0, 1.0, 2.0), ("uncorrelated_reading",), "builtin"),
    ("sql.dml_effect", "Результат изменения данных", ("sql",), NUM, (-1.5, 0.0, 1.0), ("rollback_ignored",),
     "builtin"),
    # --- http (B21c) -------------------------------------------------------------------------------------------------
    ("http.url_parts", "Части адреса", ("http",), TEXT, (-2.0, -0.5), (), "builtin"),
    ("http.status_choice", "Код ответа по ситуации", ("http", "rest_api"), ONE, (-1.5, 0.0, 1.0), (), "manual"),
    ("http.idempotent_retry", "Повторы и идемпотентность", ("http", "rest_api"), NUM, (-1.0, 0.5, 1.5),
     ("post_is_idempotent",), "manual"),
    ("http.cache_timeline", "Кэш: лента запросов", ("http", "web_caching"), NUM, (-1.0, 0.5, 1.5),
     ("no_cache_means_no_store",), "manual"),
    ("http.cookies_cors", "Cookie и CORS", ("http", "web_security_basics"), NUM, (-1.0, 0.5, 1.5),
     ("samesite_ignored",), "manual"),
    # --- git (B21c) --------------------------------------------------------------------------------------------------
    ("git.log_reach", "Достижимые коммиты", ("git",), NUM, (-1.5, 0.0, 1.0), (), "git"),
    ("git.reset_restore", "reset, restore, stash", ("git",), MULTI, (-1.0, 0.5, 1.5), (), "git"),
    ("git.merge_rebase", "Слияние и перебазирование", ("git",), NUM, (-1.0, 0.5, 1.5), ("rebase_keeps_hashes",),
     "git"),
    ("git.conflict_predict", "Предсказание конфликтов", ("git",), MULTI, (-1.5, 0.0, 1.0), (), "git"),
    # --- py: языковой модуль Python (B21c) ---------------------------------------------------------------------------
    ("py.scope_defaults", "Области видимости и значения по умолчанию", ("python",), TEXT, (-1.0, 0.5, 1.5),
     ("fresh_default_each_call",), "builtin"),
    ("py.iter_generators", "Итераторы и генераторы", ("python",), TEXT, (-1.5, 0.0, 1.0), ("iterator_reusable",),
     "builtin"),
    ("py.exceptions_flow", "Порядок обработки исключений", ("python",), TEXT, (-1.5, 0.0, 1.0), (), "builtin"),
    ("py.classes_mro", "Классы и порядок разрешения методов", ("python",), TEXT, (-1.0, 0.5, 1.5),
     ("instance_shadows_class",), "builtin"),
    # --- js: языковой модуль JavaScript (B22) ------------------------------------------------------------------------
    ("js.array_methods", "Методы массивов", ("javascript",), TEXT, (-1.5, 0.0, 1.0), ("numeric_default_sort",),
     "node"),
    ("js.coercion_equality", "Приведение типов и равенство", ("javascript",), NUM, (-1.0, 0.5), (), "node"),
    ("js.closure_scope", "Замыкания и области видимости", ("javascript",), TEXT, (-1.0, 0.5, 1.5),
     ("var_block_scoped",), "node"),
    ("js.event_loop", "Событийный цикл", ("javascript", "async_js"), TEXT, (-1.0, 0.5, 1.5),
     ("timeout_zero_is_sync",), "node"),
    ("js.this_binding", "Привязка this", ("javascript",), TEXT, (0.5, 1.5), (), "node"),
    # --- db: индексы и транзакции (B21b) -----------------------------------------------------------------------------
    ("db.constraints_effect", "Ограничения целостности", ("databases", "sql"), NUM, (-1.5, 0.0), (), "builtin"),
    ("db.index_prefix", "Составной индекс и запросы", ("databases", "db_indexes"), MULTI, (-1.0, 0.5, 1.5), (),
     "sqlite3_explain"),
    ("db.fd_keys", "Функциональные зависимости и ключи", ("databases", "db_design"), ONE, (-1.0, 0.5, 1.5), (),
     "manual"),
    ("db.isolation_timeline", "Уровни изоляции по шагам", ("databases", "db_transactions"), NUM, (0.5, 1.5, 2.0),
     ("sees_uncommitted",), "manual"),
    ("db.deadlock_graph", "Взаимные блокировки", ("databases", "db_transactions"), ONE, (0.0, 1.0, 2.0), (),
     "manual"),
    # --- svc: конкурентность и надёжность (B21c) ---------------------------------------------------------------------
    ("svc.race_interleaving", "Гонки: чередование шагов", ("concurrency",), NUM, (0.0, 1.5, 2.0),
     ("atomic_increment",), "manual"),
    ("svc.async_order", "Порядок в асинхронном коде", ("async", "concurrency"), TEXT, (-1.0, 0.5, 1.5), (),
     "asyncio"),
    ("svc.rate_limiter", "Ограничитель частоты запросов", ("system_design", "rest_api"), NUM, (-1.0, 0.5, 1.5),
     ("window_reset_ignored",), "manual"),
    ("svc.capacity_availability", "Ёмкость и доступность", ("system_design",), NUM, (0.0, 1.0, 2.0), (), "manual"),
    # --- css (B22) ---------------------------------------------------------------------------------------------------
    ("css.specificity", "Специфичность и каскад", ("css",), ONE, (-1.5, 0.0, 1.0), (), "manual"),
    ("css.box_model", "Блочная модель", ("css", "css_layout"), NUM, (-1.5, 0.0), ("border_box_ignored",), "manual"),
    ("css.flex_sizes", "Размеры во flex-контейнере", ("css", "css_layout"), NUM, (-1.0, 0.5, 1.5), (), "manual"),
    ("css.selector_match", "Сопоставление селекторов", ("css", "dom"), NUM, (-1.0, 0.5, 1.5), (), "manual"),
    # --- web (B22) ---------------------------------------------------------------------------------------------------
    ("web.event_propagation", "Фазы события", ("dom",), TEXT, (-1.0, 0.5, 1.5), (), "manual"),
    ("web.render_count", "Число отрисовок компонента", ("react", "frontend_performance"), NUM, (-1.0, 0.5, 1.5), (),
     "manual"),
    ("web.debounce_throttle", "debounce и throttle", ("javascript", "frontend_performance"), NUM, (-1.0, 0.0, 1.0),
     (), "manual"),
    ("web.script_loading", "Порядок загрузки скриптов", ("frontend_performance", "dom"), TEXT, (-1.5, 0.0, 1.0), (),
     "manual"),
    # --- stats (B23) -------------------------------------------------------------------------------------------------
    ("stats.descriptive", "Описательная статистика", ("statistics",), NUM, (-2.0, -0.5, 1.0),
     ("mean_instead_of_median",), "manual"),
    ("stats.bayes_rates", "Условная вероятность и Байес", ("probability", "statistics"), NUM, (-1.0, 0.5, 1.5),
     ("base_rate_neglect",), "manual"),
    ("stats.ab_decision", "Решение по A/B-тесту", ("ab_testing", "statistics"), NUM, (-1.0, 0.5, 1.5), (), "manual"),
    ("stats.expectation", "Математическое ожидание", ("probability",), NUM, (-1.5, 0.0, 1.0), (), "manual"),
    # --- ml (B23) ----------------------------------------------------------------------------------------------------
    ("ml.confusion_metrics", "Метрики по матрице ошибок", ("ml_metrics",), NUM, (-1.5, 0.0, 1.0),
     ("precision_recall_swap",), "manual"),
    ("ml.ranking_auc", "Метрики ранжирования и AUC", ("ml_metrics",), NUM, (-1.0, 0.5, 1.5), ("ties_ignored",),
     "manual"),
    ("ml.leakage_line", "Утечка данных в конвейере", ("ml_validation",), LINE, (-1.0, 0.5, 1.5), (), "manual"),
    ("ml.overfit_curve", "Переобучение по кривым", ("ml_validation",), NUM, (-1.5, 0.0, 1.0), (), "manual"),
    # --- dw (B23) ----------------------------------------------------------------------------------------------------
    ("dw.groupby_pivot", "Группировка и сводная таблица", ("pandas", "data_wrangling"), NUM, (-1.5, 0.0, 1.0), (),
     "pandas"),
    ("dw.merge_shapes", "Размер результата merge", ("pandas", "data_wrangling"), NUM, (-1.0, 0.5, 1.5),
     ("no_fanout",), "pandas"),
    ("dw.missing_values", "Пропуски в данных", ("pandas", "data_wrangling"), NUM, (-1.5, 0.0), (), "pandas"),
    ("dw.rolling_shift", "Сдвиги и скользящие окна", ("pandas", "data_wrangling"), NUM, (-1.0, 0.5, 1.5), (),
     "pandas"),
)  # fmt: skip

#: Ядро P0 в порядке написания (Арх. 5.3): наименьший набор семейств, при котором инварианты планов выполняются
#: для трёх грейдов `backend` — и без языкового модуля, и с модулем `py`. Первыми идут группы с наименьшим
#: запасом пула. Список пересчитывается командой `python -m app.modules.assessment.bank core` и вносится сюда
#: руками: это решение о порядке работ, а не производное значение.
CORE_P0: tuple[str, ...] = (
    # B21a: ds — резерв 0
    "ds.heap_array", "ds.hash_probing", "ds.bst_ops",
    # B21b: db — резерв 0
    "db.constraints_effect", "db.index_prefix", "db.fd_keys", "db.isolation_timeline",
    # B21a: code — пять из шести: без языкового модуля на junior четыре слота уходят в code
    "code.trace_loops", "code.trace_collections", "code.trace_recursion", "code.bug_boundary", "code.bug_logic",
    # B21c
    "http.status_choice", "http.idempotent_retry", "http.cache_timeline",
    "git.log_reach", "git.reset_restore", "git.merge_rebase",
    "py.scope_defaults", "py.iter_generators", "py.exceptions_flow",
    "svc.race_interleaving", "svc.async_order", "svc.rate_limiter",
    # B21b
    "sql.group_having", "sql.join_rows", "sql.null_logic",
    # B21a
    "algo.bigo_loops", "algo.ops_count", "algo.sort_state", "algo.graph_traversal",
)  # fmt: skip

#: Демо-ядро: ядро P0, пересчитанное при `ASSESSMENT_MIN_POOL=2` (значение по умолчанию; целевое — 3). Кандидаты —
#: только семейства `CORE_P0`, чтобы не требовать ещё не написанных. Выпадает одно семейство: группа `svc` при двух
#: слотах держится на пуле 3, остальные группы упираются в `slots + 1` и от `MIN_POOL` не зависят. Меньше 30 не
#: получается: сумма `slots + 1` по группам даёт 25 даже без добавочных блоков (`ASSESSMENT_MAX_EXT_BLOCKS=0`),
#: а длина теста до 26 требует 26 свободных семейств. Тест `test_demo_core_matches_registry` сверяет список с расчётом.
DEMO_CORE: tuple[str, ...] = tuple(i for i in CORE_P0 if i != "svc.race_interleaving")

_BACKEND_QUEUE_GROUPS = frozenset({"code", "algo", "ds", "sql", "http", "git", "py", "db", "svc"})
_FRONTEND_QUEUE_GROUPS = frozenset({"js", "css", "web"})


def _queue(family_id: str, group: str) -> int:
    if family_id in CORE_P0:
        return 1
    if group in _FRONTEND_QUEUE_GROUPS:
        return 2
    return 3 if group in _BACKEND_QUEUE_GROUPS else 4


def _build(rows: Sequence[_Row]) -> dict[str, FamilySpec]:
    """Собрать реестр и проверить его целостность: ошибка в таблице должна падать при импорте, а не в сборке банка."""
    result: dict[str, FamilySpec] = {}
    for row in rows:
        family_id, title, tags, kind, bs, misconceptions, oracle = row[:7]
        extra_kinds: tuple[ItemKind, ...] = row[7] if len(row) > 7 else ()
        group = family_id.split(".", 1)[0]
        if family_id in result:
            raise ValueError(f"реестр семейств: повтор идентификатора {family_id}")
        if group not in GROUPS:
            raise ValueError(f"реестр семейств: у {family_id} неизвестная группа {group}")
        if not 1 <= len(bs) <= 3 or list(bs) != sorted(bs):
            raise ValueError(f"реестр семейств: у {family_id} уровней должно быть от 1 до 3, b — по возрастанию")
        for b in bs:
            if not B_MIN <= b <= B_MAX or (b / B_STEP) != int(b / B_STEP):
                raise ValueError(f"реестр семейств: у {family_id} сложность {b} вне шкалы")
        result[family_id] = FamilySpec(
            id=family_id,
            title=title,
            group=group,
            skill_tags=tags,
            kind=kind,
            levels=tuple(LevelSpec(level=i, b=b) for i, b in enumerate(bs, start=1)),
            misconceptions=misconceptions,
            extra_kinds=extra_kinds,
            oracle=oracle,
            specializations=GROUPS[group].specializations,
            queue=_queue(family_id, group),
            core_p0=family_id in CORE_P0,
            demo_core=family_id in DEMO_CORE,
            core_order=CORE_P0.index(family_id) + 1 if family_id in CORE_P0 else 0,
        )
    unknown = [family_id for family_id in CORE_P0 if family_id not in result]
    if unknown or len(set(CORE_P0)) != len(CORE_P0):
        raise ValueError(f"реестр семейств: в CORE_P0 неизвестные или повторяющиеся идентификаторы {unknown}")
    return result


#: Все семейства банка MVP: идентификатор -> строка таблицы.
REGISTRY: dict[str, FamilySpec] = _build(_ROWS)


def specs(*, package: str | None = None, queue: int | None = None) -> list[FamilySpec]:
    """Строки реестра в порядке работ: очередь, место в ядре, порядок таблицы. Фильтры — пакет и очередь."""
    items = [
        spec
        for spec in REGISTRY.values()
        if (package is None or spec.package == package) and (queue is None or spec.queue == queue)
    ]
    order = {family_id: index for index, family_id in enumerate(REGISTRY)}
    return sorted(items, key=lambda spec: (spec.queue, spec.core_order, order[spec.id]))


def core_families() -> list[FamilySpec]:
    """Ядро P0 в порядке написания."""
    return [REGISTRY[family_id] for family_id in CORE_P0]


def module_name(family_id: str) -> str:
    """Имя файла семейства без расширения: «sql.join_rows» -> «sql_join_rows»."""
    return family_id.replace(".", "_")


def family_meta(
    family_id: str,
    *,
    version: int,
    feature_bounds: Mapping[int, Mapping[str, tuple[float, float]]],
    misconceptions: Sequence[str] | None = None,
    time_budget_s: Mapping[int, int] | None = None,
    title: str | None = None,
    spec: FamilySpec | None = None,
) -> FamilyMeta:
    """Паспорт семейства для файла генератора: `META = family_meta("sql.join_rows", version=1, feature_bounds=...)`.

    Группа, теги, вид задания, специализации, уровни, `b` и приоритет берутся из реестра — генератор их не задаёт.
    Автор семейства задаёт только то, что знает он один:

    * `version` — увеличивается на единицу при любом изменении `generate`;
    * `feature_bounds` — для КАЖДОГО уровня реестра границы признаков сложности, которые генератор кладёт
      в `Variant.features`: `{1: {"code_lines": (4, 8)}, 2: {...}}`; обе границы включены;
    * `misconceptions` — коды моделей ошибок, если список приложения A нужно заменить или дополнить
      (у семейств, для которых приложение ошибок не называет, список обязателен: правило L07);
    * `time_budget_s` — расчётное время по уровням, если значение по умолчанию (75, 105, 150 с по `b`) не подходит.

    `spec` передают только учебные семейства из тестов: строку реестра, которой нет в `REGISTRY`.
    """
    row = spec if spec is not None else REGISTRY.get(family_id)
    if row is None or row.id != family_id:
        raise KeyError(f"семейства {family_id} нет в реестре families/registry.py")
    if version < 1:
        raise ValueError(f"{family_id}: version начинается с 1")
    known = {level.level for level in row.levels}
    if set(feature_bounds) != known:
        raise ValueError(
            f"{family_id}: feature_bounds задаются для уровней {sorted(known)}, получены {sorted(feature_bounds)}"
        )
    for level, bounds in feature_bounds.items():
        for key, (low, high) in bounds.items():
            if low > high:
                raise ValueError(f"{family_id}: уровень {level}, признак {key}: нижняя граница больше верхней")
    budgets = dict(time_budget_s or {})
    if not set(budgets) <= known:
        raise ValueError(f"{family_id}: time_budget_s задан для уровней, которых нет в реестре")
    codes = tuple(misconceptions) if misconceptions is not None else row.misconceptions
    if len(set(codes)) != len(codes):
        raise ValueError(f"{family_id}: коды моделей ошибок повторяются")
    return FamilyMeta(
        id=row.id,
        version=version,
        title=title or row.title,
        group=row.group,
        skill_tags=row.skill_tags,
        kind=row.kind,
        specializations=row.specializations,
        levels=tuple(
            LevelMeta(
                level=level.level,
                b=level.b,
                time_budget_s=budgets.get(level.level, default_time_budget(level.b)),
                feature_bounds=dict(feature_bounds[level.level]),
            )
            for level in row.levels
        ),
        misconceptions=codes,
        priority=row.priority,
        extra_kinds=row.extra_kinds,
    )
