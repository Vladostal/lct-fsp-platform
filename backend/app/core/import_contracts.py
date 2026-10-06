"""Свои типы контрактов import-linter для правила границ модулей (Арх. 2.4, п. 1 и п. 7).

Этот файл исполняется только линтером (`lint-imports`, `make lint`) и архитектурным тестом; приложение его не
импортирует. Причина появления: пакеты пишутся параллельно в одном каталоге, и встроенный контракт `forbidden`
падает с ошибкой конфигурации, пока модуля-источника ещё нет на диске (`app.fsp_mock`, `matching.scoring`, …),
а перечислить «внутренние файлы» чужого модуля заранее невозможно — их имена его внутреннее дело.

* `forbidden_when_present` — тот же `forbidden` (с косвенными импортами), но источник, которого ещё нет, просто
  пропускается, а проверка включается сама, как только файл появится. Поле `allowed_importers` называет модули,
  которым прямой импорт запрещённого разрешён (единственный случай — `fsp.gateway.mock` → `app.fsp_mock`).
* `facade_only` — у каждого пакета внутри `container` снаружи видны только сам пакет и его публичные файлы
  (`service`, `dto`); прямой импорт любого другого файла из чужого пакета — нарушение.
"""

from __future__ import annotations

from typing import Any

from grimp import ImportGraph
from importlinter.application import contract_utils, output
from importlinter.application.contract_utils import AlertLevel
from importlinter.contracts.forbidden import ForbiddenContract
from importlinter.domain import fields
from importlinter.domain.contract import Contract, ContractCheck


def _with_descendants(graph: ImportGraph, module: str) -> set[str]:
    """Модуль и всё, что лежит внутри него как пакета; пусто, если модуля нет в графе."""
    if module not in graph.modules:
        return set()
    if graph.is_module_squashed(module):  # внешний пакет (sqlalchemy): в графе он одна вершина
        return {module}
    return {module, *graph.find_descendants(module)}


class ForbiddenWhenPresentContract(ForbiddenContract):
    """`forbidden`, который не требует существования источников и знает разрешённых импортёров."""

    type_name = "forbidden_when_present"

    # Поля объявлены заново: import-linter собирает их только из словаря самого класса, без наследования.
    source_modules = fields.SetField(subfield=fields.ModuleExpressionField())
    forbidden_modules = fields.SetField(subfield=fields.ModuleExpressionField())
    ignore_imports = fields.SetField(subfield=fields.ImportExpressionField(), required=False)
    allow_indirect_imports = fields.BooleanField(required=False, default=False)
    unmatched_ignore_imports_alerting = fields.EnumField(AlertLevel, default=AlertLevel.NONE)
    as_packages = fields.BooleanField(required=False, default=True)
    broken_contract_guidance = fields.TextField(required=False)
    allowed_importers = fields.SetField(subfield=fields.StringField(), required=False)

    def check(self, graph: ImportGraph, verbose: bool) -> ContractCheck:
        declared: Any = self.source_modules
        present = {expr for expr in declared if expr.has_wildcard_expression() or expr.expression in graph.modules}
        skipped = sorted(str(expr) for expr in set(declared) - present)
        if skipped:
            output.verbose_print(verbose, f"Источников ещё нет, пропущены: {', '.join(skipped)}")
        self.source_modules = present  # type: ignore[assignment]

        forbidden: set[str] = set()
        expressions: Any = self.forbidden_modules
        for expr in expressions:
            forbidden |= _with_descendants(graph, str(expr))
        importers: Any = self.allowed_importers or ()
        for allowed in importers:
            for importer in _with_descendants(graph, allowed):
                for imported in graph.find_modules_directly_imported_by(importer) & forbidden:
                    graph.remove_import(importer=importer, imported=imported)
        return super().check(graph, verbose)


class FacadeOnlyContract(Contract):
    """Чужой пакет виден только через публичные файлы (`service.py`, `dto.py`).

    Параметры:
        container       пакет, дочерние пакеты которого — модули с фасадами (`app.modules`);
        public          имена публичных файлов модуля (`service`, `dto`);
        sources         чьи импорты проверяются (пакеты целиком); остальной код правило не затрагивает;
        ignore_imports  явные исключения в виде «импортёр -> импортируемое» (необязательно).

    Проверяются только прямые импорты: косвенный путь через фасад — именно то, чего правило добивается.
    Импорт внутри своего пакета разрешён всегда.
    """

    type_name = "facade_only"

    container = fields.StringField()
    public = fields.SetField(subfield=fields.StringField())
    sources = fields.SetField(subfield=fields.StringField())
    ignore_imports = fields.SetField(subfield=fields.ImportExpressionField(), required=False)

    def check(self, graph: ImportGraph, verbose: bool) -> ContractCheck:
        container: Any = self.container
        public_names: Any = self.public
        source_names: Any = self.sources
        ignored: Any = self.ignore_imports

        removal = contract_utils.remove_ignored_imports_and_report(
            graph=graph, ignore_imports=ignored, unmatched_alerting=AlertLevel.NONE
        )
        if container not in graph.modules:
            raise ValueError(f"Module '{container}' does not exist.")

        sources: set[str] = set()
        for name in source_names:
            sources |= _with_descendants(graph, name)

        violations: list[dict[str, Any]] = []
        for package in sorted(graph.find_children(container)):
            own = _with_descendants(graph, package)
            public: set[str] = {package}
            for name in public_names:
                public |= _with_descendants(graph, f"{package}.{name}")
            for internal in sorted(own - public):
                importers = graph.find_modules_that_directly_import(internal)
                for importer in sorted(importers & sources - own):
                    details = graph.get_import_details(importer=importer, imported=internal)
                    violations.append(
                        {
                            "importer": importer,
                            "imported": internal,
                            "line_numbers": sorted({item["line_number"] for item in details}),
                        }
                    )
            output.verbose_print(verbose, f"{package}: закрытых файлов — {len(own - public)}")

        return ContractCheck(
            kept=not violations,
            warnings=list(removal.warnings),
            ignored_import_count=removal.ignored_import_count,
            metadata={"violations": violations, "public": sorted(public_names)},
        )

    def render_broken_contract(self, check: ContractCheck) -> None:
        public = ", ".join(f"{name}.py" for name in check.metadata["public"])
        for item in check.metadata["violations"]:
            lines = ", ".join(f"l.{number}" for number in item["line_numbers"])
            output.print_error(f"{item['importer']} -> {item['imported']} ({lines})", bold=False)
        output.new_line()
        advice = "перенесите нужное в фасад или в dto.py владельца (Арх. 2.4, п. 1)"
        output.print_error(f"Снаружи модуля доступны только {public}: {advice}.", bold=False)
        output.new_line()
