"""Банк в памяти для симуляции: паспорта семейств без содержания заданий.

Симуляции нужны группа, специализации, теги, вид задания и сложности уровней; варианты она не генерирует:
моделируется только факт верного ответа (приложение A, §10.1). Источник — семейства на диске, таблица реестра,
банк в базе стенда или любой набор, названный как `модуль:функция`.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from app.modules.assessment import blueprints
from app.modules.assessment.blueprints import PoolFamily
from app.modules.assessment.config import GRADES
from app.modules.assessment.families._lib.contract import Family, ItemKind, guess_probability
from app.modules.assessment.groups import SPECIALIZATIONS


@dataclass(frozen=True)
class SimLevel:
    level: int
    b: float


@dataclass(frozen=True)
class SimFamily:
    id: str
    group: str
    specializations: tuple[str, ...]
    skill_tags: tuple[str, ...]
    kind: str
    levels: tuple[SimLevel, ...]
    #: Вероятность угадать, которую записал бы движок в `c_used`.
    c: float
    title: str = ""

    def b(self, level: int) -> float:
        return self.levels[level - 1].b


@dataclass(frozen=True)
class SimBank:
    """Набор семейств и то, что из него следует: пулы для сборки формы и доступные пары."""

    families: tuple[SimFamily, ...]
    source: str = ""
    #: Генераторы, если банк собран из загруженных семейств: нужны только листам экспертной сверки.
    generators: dict[str, Family] = field(default_factory=dict, compare=False)

    @property
    def pools(self) -> tuple[PoolFamily, ...]:
        return _pools(self)

    @property
    def by_id(self) -> dict[str, SimFamily]:
        return _by_id(self)

    def pairs(self) -> list[tuple[str, str]]:
        """Доступные пары (специализация, грейд) в порядке справочника."""
        available = blueprints.available_pairs(self.families)
        return [(spec, grade) for spec in SPECIALIZATIONS for grade in GRADES if (spec, grade) in available]

    def lang(self, specialization: str, grade: str, wanted: str | None) -> str | None:
        """Языковой модуль сессии: желаемый, если банк позволяет; иначе обязательный либо запасной путь."""
        key = (specialization, grade, wanted)
        cache = _LANG.setdefault(id(self), {})
        if key not in cache:
            ok = wanted is not None and blueprints.lang_module_available(self.families, specialization, grade, wanted)
            cache[key] = wanted if ok else blueprints.base_scenario(specialization)
        return cache[key]


_POOLS: dict[int, tuple[PoolFamily, ...]] = {}
_BY_ID: dict[int, dict[str, SimFamily]] = {}
_LANG: dict[int, dict[tuple[str, str, str | None], str | None]] = {}


def _pools(bank: SimBank) -> tuple[PoolFamily, ...]:
    if id(bank) not in _POOLS:
        _POOLS[id(bank)] = blueprints.pool_families(bank.families)
    return _POOLS[id(bank)]


def _by_id(bank: SimBank) -> dict[str, SimFamily]:
    if id(bank) not in _BY_ID:
        _BY_ID[id(bank)] = {family.id: family for family in bank.families}
    return _BY_ID[id(bank)]


def sim_family(obj: Any) -> SimFamily:
    """Привести строку реестра, паспорт, загруженное семейство или семейство банка стенда к `SimFamily`."""
    if isinstance(obj, SimFamily):
        return obj
    meta = obj.meta if isinstance(obj, Family) else obj
    kind = ItemKind(meta.kind)
    return SimFamily(
        id=meta.id,
        group=meta.group,
        specializations=tuple(meta.specializations),
        skill_tags=tuple(meta.skill_tags),
        kind=kind.value,
        levels=tuple(SimLevel(level.level, float(level.b)) for level in meta.levels),
        c=guess_probability(kind),
        title=getattr(meta, "title", ""),
    )


def from_items(items: Iterable[Any], source: str = "") -> SimBank:
    rows = list(items)
    families = tuple(sorted((sim_family(item) for item in rows), key=lambda f: f.id))
    generators = {item.meta.id: item for item in rows if isinstance(item, Family)}
    return SimBank(families=families, source=source, generators=generators)


def from_db(db: Any) -> SimBank:
    """Банк стенда: активные семейства из базы (для сида и прогона на собранном банке)."""
    from app.modules.assessment import repo

    return from_items(repo.load_families(db), source="db")


def load(spec: str) -> SimBank:
    """`discovered` — семейства на диске; `registry` — таблица реестра; иначе `модуль:функция`, возвращающая набор."""
    if spec == "registry":
        from app.modules.assessment.families.registry import REGISTRY

        return from_items(REGISTRY.values(), source="registry")
    if spec == "discovered":
        from app.modules.assessment.families import discover

        return from_items(discover().families, source="discovered")
    module, _, name = spec.partition(":")
    if not name:
        raise ValueError(f"банк «{spec}»: ожидается discovered, registry или модуль:функция")
    return from_items(getattr(importlib.import_module(module), name)(), source=spec)
