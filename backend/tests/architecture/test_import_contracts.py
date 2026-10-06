"""Контракты импорта (Арх. 2.4, п. 7): правило границ модулей проверяется на настоящем коде и на учебных пакетах.

`test_project_contracts_are_kept` запускает те же контракты, что `make lint` (`lint-imports`), по всему
каталогу `app`. Остальные тесты доказывают, что свои типы контрактов действительно ловят нарушения, а не просто
всегда зелёные: для этого во временном каталоге собирается маленький пакет с заведомо плохими импортами.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import grimp
import pytest
from importlinter.configuration import configure

from app.core.config import BACKEND_DIR
from app.core.import_contracts import FacadeOnlyContract, ForbiddenWhenPresentContract


def test_project_contracts_are_kept():
    lint_imports = Path(sys.executable).with_name("lint-imports")
    result = subprocess.run(
        [str(lint_imports), "--no-cache"], cwd=BACKEND_DIR, capture_output=True, text=True, timeout=300
    )
    assert result.returncode == 0, f"нарушены контракты импорта:\n{result.stdout}\n{result.stderr}"
    assert "0 broken" in result.stdout


def test_pyproject_declares_all_rules_of_the_architecture():
    import tomllib

    config = tomllib.loads((BACKEND_DIR / "pyproject.toml").read_text("utf-8"))["tool"]["importlinter"]
    assert config["root_package"] == "app"
    contracts = {contract["type"]: contract for contract in config["contracts"]}
    assert set(contracts) == {"layers", "facade_only", "forbidden_when_present"}

    layers = contracts["layers"]["layers"]
    declared = [name.strip().removeprefix("app.modules.") for line in layers[:-1] for name in line.split("|")]
    assert sorted(declared) == sorted(
        ["identity", "catalog", "reports", "company", "textparse", "assessment", "profile", "fsp", "matching",
         "contact", "vacancies", "pulse", "integrations", "demo"]
    )  # fmt: skip
    assert layers[0] == "app.modules.demo" and "app.core" in layers[-1] and "app.shared" in layers[-1]

    forbidden = [contract for contract in config["contracts"] if contract["type"] == "forbidden_when_present"]
    targets = {name for contract in forbidden for name in contract["forbidden_modules"]}
    assert {"app.eval", "app.seed", "app.simulation", "app.fsp_mock", "app.modules", "sqlalchemy"} <= targets
    pure = next(contract for contract in forbidden if contract["forbidden_modules"] == ["sqlalchemy"])
    assert set(pure["source_modules"]) == {
        "app.modules.assessment.engine",
        "app.modules.matching.scoring",
        "app.modules.matching.ranking",
        "app.modules.fsp.signal",
        "app.modules.contact.rules",
    }


# --------------------------------------------------------------------------------------------------------------------
# Учебный пакет с нарушениями
# --------------------------------------------------------------------------------------------------------------------

FILES = {
    "__init__.py": "",
    "core.py": "",
    "seed.py": "from zoo.modules.alpha import models\nfrom zoo.modules.alpha import service\n",
    "evalx.py": "from zoo.modules.alpha import engine\n",  # валидация вызывает чистые ядра — ей можно
    "mock/__init__.py": "",
    "mock/registry.py": "",
    "modules/__init__.py": "",
    "modules/alpha/__init__.py": "ROUTERS = []\n",
    "modules/alpha/service.py": "from zoo.modules.alpha import models, engine\n",  # свои файлы — можно
    "modules/alpha/dto.py": "",
    "modules/alpha/models.py": "import sqlalchemy\n",
    "modules/alpha/engine.py": "from zoo.modules.alpha import helpers\n",
    "modules/alpha/helpers.py": "from zoo.modules.alpha import models\n",  # косвенно тянет sqlalchemy в ядро
    "modules/beta/__init__.py": "",
    "modules/beta/service.py": textwrap.dedent(
        """
        import zoo.modules.alpha
        from zoo.modules.alpha import service, dto
        from zoo.modules.alpha import models
        from zoo.modules.alpha.helpers import *
        """
    ),
    "modules/beta/dto.py": "",
    "modules/beta/gateway/__init__.py": "",
    "modules/beta/gateway/mock.py": "from zoo.mock import registry\n",
    "modules/beta/router.py": "from zoo.mock import registry\n",
}


@pytest.fixture
def zoo_graph(tmp_path, monkeypatch) -> grimp.ImportGraph:
    package = tmp_path / "zoo"
    for name, source in FILES.items():
        path = package / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, "utf-8")
    monkeypatch.syspath_prepend(tmp_path)
    configure()  # то же, что делает команда lint-imports перед проверкой контрактов
    return grimp.build_graph("zoo", include_external_packages=True, cache_dir=None)


def make(contract_class, **options):
    session = {"root_packages": ["zoo"], "include_external_packages": True}
    return contract_class(name="учебный", session_options=session, contract_options=options)


def test_facade_only_catches_direct_imports_of_foreign_internals(zoo_graph):
    contract = make(
        FacadeOnlyContract,
        container="zoo.modules",
        public=["service", "dto"],
        sources=["zoo.modules", "zoo.seed", "zoo.core"],
    )
    check = contract.check(zoo_graph, verbose=False)
    assert check.kept is False
    found = {(item["importer"], item["imported"]) for item in check.metadata["violations"]}
    assert found == {
        ("zoo.modules.beta.service", "zoo.modules.alpha.models"),
        ("zoo.modules.beta.service", "zoo.modules.alpha.helpers"),
        ("zoo.seed", "zoo.modules.alpha.models"),
    }
    # Не нарушения: импорт пакета и фасада, свои внутренние файлы, код вне списка источников (evalx).
    contract.render_broken_contract(check)  # отчёт строится без ошибок


def test_facade_only_respects_ignore_imports_and_passes_on_clean_code(zoo_graph):
    contract = make(
        FacadeOnlyContract,
        container="zoo.modules",
        public=["service", "dto"],
        sources=["zoo.modules", "zoo.seed"],
        ignore_imports=[
            "zoo.modules.beta.service -> zoo.modules.alpha.models",
            "zoo.modules.beta.service -> zoo.modules.alpha.helpers",
            "zoo.seed -> zoo.modules.alpha.models",
            "zoo.nobody -> zoo.modules.alpha.models",  # несуществующее исключение — не ошибка
        ],
    )
    assert contract.check(zoo_graph, verbose=False).kept is True


def test_forbidden_when_present_skips_sources_that_do_not_exist_yet(zoo_graph):
    contract = make(
        ForbiddenWhenPresentContract,
        source_modules=["zoo.modules.gamma.scoring", "zoo.not_written"],
        forbidden_modules=["sqlalchemy"],
    )
    assert contract.check(zoo_graph, verbose=False).kept is True


def test_forbidden_when_present_catches_indirect_import_into_pure_core(zoo_graph):
    """engine → helpers → models → sqlalchemy: косвенный импорт в чистое ядро тоже нарушение."""
    contract = make(
        ForbiddenWhenPresentContract,
        source_modules=["zoo.modules.alpha.engine", "zoo.modules.gamma.scoring"],
        forbidden_modules=["sqlalchemy"],
    )
    check = contract.check(zoo_graph, verbose=False)
    assert check.kept is False
    chains = check.metadata["invalid_chains"]
    assert [(item["downstream_module"], item["upstream_module"]) for item in chains] == [
        ("zoo.modules.alpha.engine", "sqlalchemy")
    ]


def test_forbidden_when_present_allows_only_named_importer(zoo_graph):
    """На демо-реестр из модулей ссылается только адаптер шлюза: router того же модуля — уже нарушение."""
    options = {"source_modules": ["zoo.modules"], "forbidden_modules": ["zoo.mock"]}
    strict = make(ForbiddenWhenPresentContract, **options).check(zoo_graph, verbose=False)
    assert strict.kept is False

    with_gateway = make(
        ForbiddenWhenPresentContract, **options, allowed_importers=["zoo.modules.beta.gateway.mock"]
    ).check(zoo_graph, verbose=False)
    assert with_gateway.kept is False
    chains = [chain for item in with_gateway.metadata["invalid_chains"] for chain in item["chains"]]
    importers = {link["importer"] for chain in chains for link in chain}
    assert importers == {"zoo.modules.beta.router"}

    both = make(
        ForbiddenWhenPresentContract,
        **options,
        allowed_importers=["zoo.modules.beta.gateway.mock", "zoo.modules.beta.router"],
    ).check(zoo_graph, verbose=False)
    assert both.kept is True
