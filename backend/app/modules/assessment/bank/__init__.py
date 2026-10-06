"""Банк заданий: сборка вариантов, линтер, отчёт о браке, ядро P0 (Арх. 5.3).

Команда: `python -m app.modules.assessment.bank build [--per-level 60] [--family ID] [--check-only]`.
При импорте пакет ничего не загружает: генераторы семейств импортируются только командой сборки.
"""


def build_if_empty() -> None:
    """Шаг инициализации стенда (строка `INIT_STEPS` в `app.wiring`): собрать банк, если база пуста."""
    from app.modules.assessment.bank import store

    store.build_if_empty()
