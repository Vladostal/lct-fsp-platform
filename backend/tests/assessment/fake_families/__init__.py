"""Учебные семейства: образец для авторов генераторов и материал для тестов контракта, линтера и сборки.

Три файла показывают три вида заданий:

* `code_fake_sum.py` — трассировка (`numeric_input`), код в условии, `Reject`, сверка с CPython в `oracle_check`;
* `http_fake_status.py` — выбор по таблице правил (`single_choice`), перемешивание вариантов;
* `sql_fake_total.py` — запрос к случайной таблице (`numeric_input`), ответ считает `sqlite3`.

Настоящее семейство строит паспорт вызовом `family_meta("sql.join_rows", version=1, feature_bounds=...)`: строка
берётся из `families/registry.py`. Учебных семейств в реестре нет, поэтому их строки лежат здесь, в `FAKE_SPECS`,
и передаются в `family_meta(..., spec=FAKE_SPECS[...])`. Больше отличий от боевого семейства нет.

Проверка: `python -m app.modules.assessment.bank build --check-only --package tests.assessment.fake_families`.
"""

from app.modules.assessment.families._lib.contract import ItemKind
from app.modules.assessment.families.registry import FamilySpec, LevelSpec

PACKAGE = "tests.assessment.fake_families"

_ALL = ("backend", "frontend", "fullstack", "data_ml")

FAKE_SPECS: dict[str, FamilySpec] = {
    spec.id: spec
    for spec in (
        FamilySpec(
            id="code.fake_sum",
            title="Учебное: сумма в цикле",
            group="code",
            skill_tags=("code_reading",),
            kind=ItemKind.NUMERIC_INPUT,
            levels=(LevelSpec(1, -2.0), LevelSpec(2, -0.5)),
            misconceptions=("off_by_one", "ignore_break"),
            oracle="cpython",
            specializations=_ALL,
            queue=1,
        ),
        FamilySpec(
            id="http.fake_status",
            title="Учебное: код ответа",
            group="http",
            skill_tags=("http", "rest_api"),
            kind=ItemKind.SINGLE_CHOICE,
            levels=(LevelSpec(1, -1.5), LevelSpec(2, 0.0)),
            misconceptions=("neighbor_code",),
            oracle="manual",
            specializations=("backend", "frontend", "fullstack"),
            queue=1,
        ),
        FamilySpec(
            id="sql.fake_total",
            title="Учебное: сумма по условию",
            group="sql",
            skill_tags=("sql", "sql_aggregation"),
            kind=ItemKind.NUMERIC_INPUT,
            levels=(LevelSpec(1, -1.5), LevelSpec(2, 0.0)),
            misconceptions=("or_instead_of_and", "having_ignored"),
            oracle="builtin",
            specializations=_ALL,
            queue=1,
        ),
    )
}
