"""Семейства заданий: автообнаружение файлов генераторов (Арх. 5.3; план работ, B20).

Семейство подключается тем, что его файл лежит в этом каталоге: списков для ручного дополнения нет, поэтому
пакеты семейств не правят общих файлов. Правила файла:

* имя — идентификатор семейства с подчёркиванием вместо точки: `sql.join_rows` -> `sql_join_rows.py`;
* в модуле есть `META` (строится `registry.family_meta`), `generate(level, seed)`, `selfcheck(v)` и,
  если у семейства есть независимый оракул, `oracle_check(v)`;
* файлы и каталоги с подчёркиванием в начале (`_lib`) и `registry.py` семействами не считаются.

Сломанный файл не роняет остальные: ошибка импорта или несоответствие контракту попадает в `Discovery.errors`,
семейство считается отсутствующим, а доступность пар (специализация, грейд) пересчитывается без него (Арх. 5.2).
Этот модуль при импорте ничего не загружает: генераторы импортируются только вызовом `discover`.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field

from app.modules.assessment.families._lib.contract import Family, FamilyMeta
from app.modules.assessment.families.registry import REGISTRY, FamilySpec, module_name

__all__ = ["DEFAULT_PACKAGE", "Discovery", "discover", "load_family", "meta_mismatch"]

#: Пакет с боевыми семействами.
DEFAULT_PACKAGE = "app.modules.assessment.families"
_SKIP = frozenset({"registry"})


@dataclass(frozen=True)
class Discovery:
    """Результат обхода пакета: загруженные семейства и причины, по которым остальные не загружены."""

    families: tuple[Family, ...]
    #: Имя модуля -> причина.
    errors: dict[str, str] = field(default_factory=dict)

    def get(self, family_id: str) -> Family | None:
        """Семейство по идентификатору."""
        return next((family for family in self.families if family.meta.id == family_id), None)

    def metas(self) -> list[FamilyMeta]:
        """Паспорта загруженных семейств — вход функций `blueprints`."""
        return [family.meta for family in self.families]


def meta_mismatch(meta: FamilyMeta, spec: FamilySpec) -> list[str]:
    """Чем паспорт расходится со строкой реестра; пустой список — совпадает.

    Паспорт, собранный `family_meta`, совпадает всегда; проверка ловит `FamilyMeta`, написанный руками.
    """
    problems = []
    if (meta.group, meta.kind, meta.extra_kinds) != (spec.group, spec.kind, spec.extra_kinds):
        problems.append("группа или вид задания не совпадают с реестром")
    if tuple(meta.skill_tags) != spec.skill_tags:
        problems.append("теги навыков не совпадают с реестром")
    if tuple(meta.specializations) != spec.specializations:
        problems.append("специализации не совпадают с реестром")
    if tuple((level.level, level.b) for level in meta.levels) != tuple((level.level, level.b) for level in spec.levels):
        problems.append("уровни и b не совпадают с реестром")
    if meta.priority != spec.priority:
        problems.append("приоритет не совпадает с реестром")
    return problems


def load_family(module: str, *, require_registry: bool = True) -> Family:
    """Импортировать модуль семейства и проверить контракт; `ValueError` с причиной, если он нарушен."""
    mod = importlib.import_module(module)
    meta = getattr(mod, "META", None)
    if not isinstance(meta, FamilyMeta):
        raise ValueError("нет META типа FamilyMeta")
    for name in ("generate", "selfcheck"):
        if not callable(getattr(mod, name, None)):
            raise ValueError(f"нет функции {name}")
    oracle = getattr(mod, "oracle_check", None)
    if oracle is not None and not callable(oracle):
        raise ValueError("oracle_check должен быть функцией")
    short = module.rsplit(".", 1)[-1]
    if short != module_name(meta.id):
        raise ValueError(f"имя файла {short}.py не соответствует идентификатору {meta.id}")
    if meta.id.split(".", 1)[0] != meta.group:
        raise ValueError(f"идентификатор {meta.id} не начинается с группы {meta.group}")
    spec = REGISTRY.get(meta.id)
    if spec is None and require_registry:
        raise ValueError(f"семейства {meta.id} нет в families/registry.py")
    if spec is not None:
        problems = meta_mismatch(meta, spec)
        if problems:
            raise ValueError("; ".join(problems))
    if not meta.levels or [level.level for level in meta.levels] != list(range(1, len(meta.levels) + 1)):
        raise ValueError("уровни должны идти подряд с единицы")
    return Family(meta=meta, generate=mod.generate, selfcheck=mod.selfcheck, oracle_check=oracle, module=module)


def discover(package: str = DEFAULT_PACKAGE) -> Discovery:
    """Найти и загрузить все семейства пакета через `pkgutil` (порядок — по имени модуля).

    Для боевого пакета семейство обязано быть в реестре; для любого другого (учебные семейства тестов) — нет.
    """
    root = importlib.import_module(package)
    families: list[Family] = []
    errors: dict[str, str] = {}
    seen: dict[str, str] = {}
    for info in sorted(pkgutil.iter_modules(root.__path__), key=lambda item: item.name):
        if info.ispkg or info.name.startswith("_") or info.name in _SKIP:
            continue
        module = f"{package}.{info.name}"
        try:
            family = load_family(module, require_registry=package == DEFAULT_PACKAGE)
        except Exception as exc:  # сломанный файл семейства не должен ронять остальные (Арх. 5.2)
            errors[module] = f"{type(exc).__name__}: {exc}"
            continue
        if family.meta.id in seen:
            errors[module] = f"идентификатор {family.meta.id} уже занят модулем {seen[family.meta.id]}"
            continue
        seen[family.meta.id] = module
        families.append(family)
    return Discovery(families=tuple(families), errors=errors)
