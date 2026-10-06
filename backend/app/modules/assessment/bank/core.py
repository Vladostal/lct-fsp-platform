"""Ядро P0 банка: наименьший набор семейств, при котором работает одна специализация на трёх грейдах (Арх. 5.3).

Задача. Из семейств специализации (для `backend` — 41 семейство общих групп и 4 семейства модуля `py`) выбрать
наименьший набор, на котором инварианты плана (`blueprints.check_plan`) выполнены для всех трёх грейдов и для
каждого языкового сценария из `langs`. Перебор всех подмножеств невозможен (2^45), но инварианты раскладываются
по группам:

* условия `pool ≥ MIN_POOL` и `slots ≤ pool − 1` касаются одной группы;
* число свободных семейств и остаток семейств для слотов растяжки — суммы вкладов групп.

Поэтому для каждой группы перебираются её подмножества (не больше 2^7), а группы сшиваются динамическим
программированием по состоянию «свободных семейств на каждом грейде, остаток растяжки на junior и middle».
Сценарий без языкового модуля строже любого сценария с модулем (слоты `lang` уходят в `code`, а семейства модуля
в свободный пул не входят), поэтому состояние считается по нему, а языковые группы подбираются отдельно.
Найденный набор в конце проверяется настоящей функцией `check_plan` по всем сценариям: расхождение разложения
с инвариантами — ошибка, а не тихо неверный список.

Среди наборов одинакового размера выбирается тот, чьи семейства покрывают больше грейдов (он устойчивее
к выбыванию семейства), затем — первый по порядку таблицы реестра.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from itertools import combinations
from typing import Any

from app.modules.assessment.blueprints import (
    MAIN_RANGE,
    STRETCH_RANGE,
    PoolFamily,
    check_plan,
    eligible,
    plan_slots,
    pool_families,
)
from app.modules.assessment.config import GRADES, get_config
from app.modules.assessment.groups import GROUPS, LANG_GROUPS

__all__ = ["CorePlan", "compute_core", "format_core"]

#: Ключ сравнения наборов: размер, минус покрытие грейдов, номера семейств в порядке реестра.
_Key = tuple[int, int, tuple[int, ...]]


@dataclass(frozen=True)
class CorePlan:
    """Ядро и порядок его написания."""

    specialization: str
    #: Семейства в порядке написания: сначала группы с наименьшим запасом пула.
    families: tuple[str, ...]
    #: Запас группы: наименьшее по грейдам и сценариям `pool − max(MIN_POOL, slots + 1)`; 0 — выбывшее семейство
    #: группы выключает пару (специализация, грейд).
    group_slack: dict[str, int]
    #: Резерв группы во всей таблице реестра: сколько семейств группы можно потерять, прежде чем пара станет
    #: невыполнимой даже с расширением пулов. Группы с нулевым резервом пишутся первыми: заменить их нечем.
    group_reserve: dict[str, int]
    #: Запас свободного пула по грейдам в сценарии, определяющем доступность: `|eligible(None, main)| − 26`.
    free_slack: dict[str, int]

    def by_package(self) -> dict[str, list[str]]:
        """Семейства ядра по пакетам плана работ, внутри пакета — в порядке написания."""
        result: dict[str, list[str]] = {}
        for family_id in self.families:
            result.setdefault(GROUPS[family_id.split(".", 1)[0]].package, []).append(family_id)
        return result


def _group_requirement(specialization: str, group: str, langs: Sequence[str | None]) -> dict[str, int]:
    """Наименьший пул группы по грейдам: `max(MIN_POOL, slots + 1)` там, где у группы есть слоты; иначе 0."""
    min_pool = get_config().min_pool
    need = dict.fromkeys(GRADES, 0)
    for grade in GRADES:
        for lang in langs:
            slots = plan_slots(specialization, grade, lang).get(group, 0)
            if slots:
                need[grade] = max(need[grade], min_pool, slots + 1)
    return need


def _subsets(items: Sequence[tuple[int, PoolFamily]]) -> Iterable[tuple[tuple[int, PoolFamily], ...]]:
    for size in range(len(items) + 1):
        yield from combinations(items, size)


def _pool(subset: Iterable[tuple[int, PoolFamily]], grade: str) -> int:
    return sum(1 for _, family in subset if family.has_level(MAIN_RANGE[grade]))


def _key(subset: Sequence[tuple[int, PoolFamily]]) -> _Key:
    coverage = sum(_pool(subset, grade) for grade in GRADES)
    return (len(subset), -coverage, tuple(index for index, _ in subset))


def _merge(a: _Key, b: _Key) -> _Key:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def compute_core(
    families: Iterable[Any],
    specialization: str = "backend",
    langs: Sequence[str | None] = (None, "py"),
    include: Collection[str] = (),
) -> CorePlan:
    """Наименьший набор семейств, на котором `specialization` доступна на трёх грейдах при каждом модуле из `langs`.

    `families` — строки реестра (`FamilySpec`), паспорта или `PoolFamily`; порядок задаёт выбор при равенстве.
    `langs` обязан содержать сценарий, определяющий доступность пары: `None` у backend и data_ml, `"js"`
    у frontend и fullstack. `include` — идентификаторы семейств, которые входят в набор заранее (уже написанное
    ядро): так считается, что нужно дописать для следующей специализации. `ValueError`, если инварианты
    не выполняются даже на всех семействах.
    """
    cfg = get_config()
    base = langs[0]
    lang_groups = [lang for lang in langs if lang is not None]
    indexed = [
        (index, family)
        for index, family in enumerate(pool_families(families))
        if (specialization in family.specializations and family.group not in LANG_GROUPS) or family.group in lang_groups
    ]
    by_group: dict[str, list[tuple[int, PoolFamily]]] = {}
    for item in indexed:
        by_group.setdefault(item[1].group, []).append(item)
    # Группа со слотами в плане, в которой нет ни одного семейства: пустой список даёт «нет подходящих подмножеств».
    for grade in GRADES:
        for lang in langs:
            for group in plan_slots(specialization, grade, lang):
                by_group.setdefault(group, [])

    need_free = cfg.base_main + cfg.base_stretch + cfg.ext_block * cfg.max_ext_blocks
    stretch_grades = [grade for grade in GRADES if STRETCH_RANGE[grade] is not None]
    cap = tuple([need_free] * len(GRADES) + [cfg.base_stretch] * len(stretch_grades))

    # Состояние: (свободных семейств по грейдам…, остаток растяжки по грейдам с растяжкой…), обрезанное по `cap`.
    states: dict[tuple[int, ...], _Key] = {tuple([0] * len(cap)): (0, 0, ())}
    for group, items in by_group.items():
        need = _group_requirement(specialization, group, langs)
        in_free = group not in LANG_GROUPS or group == base
        options: dict[tuple[int, ...], _Key] = {}
        forced = {index for index, family in items if family.id in include}
        for subset in _subsets(items):
            if not forced <= {index for index, _ in subset}:
                continue
            if any(_pool(subset, grade) < need[grade] for grade in GRADES):
                continue
            vector = [_pool(subset, grade) if in_free else 0 for grade in GRADES]
            for grade in stretch_grades:
                slots = plan_slots(specialization, grade, base).get(group, 0)
                with_stretch = [f for _, f in subset if f.has_level(STRETCH_RANGE[grade])]
                taken = min(slots, sum(1 for f in with_stretch if f.has_level(MAIN_RANGE[grade])))
                vector.append(len(with_stretch) - taken if in_free else 0)
            key = _key(subset)
            if tuple(vector) not in options or key < options[tuple(vector)]:
                options[tuple(vector)] = key
        merged: dict[tuple[int, ...], _Key] = {}
        for state, state_key in states.items():
            for vector_key, key in options.items():
                new_state = tuple(min(c, s + v) for c, s, v in zip(cap, state, vector_key, strict=True))
                new_key = _merge(state_key, key)
                if new_state not in merged or new_key < merged[new_state]:
                    merged[new_state] = new_key
        states = merged

    if cap not in states:
        raise ValueError(f"инварианты планов {specialization} не выполняются даже на всех семействах")
    all_pools = [family for _, family in indexed]
    chosen_index = set(states[cap][2])
    chosen = [family for index, family in indexed if index in chosen_index]
    for grade in GRADES:
        for lang in langs:
            violations = check_plan(chosen, specialization, grade, lang)
            if violations:
                problems = "; ".join(str(v) for v in violations)
                raise RuntimeError(f"разложение ядра разошлось с инвариантами ({grade}, {lang}): {problems}")

    slack: dict[str, int] = {}
    reserve: dict[str, int] = {}
    for group, items in by_group.items():
        need = _group_requirement(specialization, group, langs)
        group_items = [(0, f) for f in chosen if f.group == group]
        slack[group] = min((_pool(group_items, g) - need[g] for g in GRADES if need[g]), default=len(group_items))
        reserve[group] = min((_pool(items, g) - need[g] for g in GRADES if need[g]), default=len(items))
    group_rank = {group: rank for rank, group in enumerate(GROUPS)}
    table_rank = {family.id: rank for rank, family in enumerate(all_pools)}

    def group_key(group: str) -> tuple[int, int, int]:
        return (reserve[group], slack[group], group_rank[group])

    ordered = sorted(chosen, key=lambda f: (*group_key(f.group), table_rank[f.id]))
    free = {grade: len(eligible(chosen, specialization, base, None, MAIN_RANGE[grade])) - need_free for grade in GRADES}
    groups_sorted = sorted(by_group, key=group_key)
    return CorePlan(
        specialization=specialization,
        families=tuple(f.id for f in ordered),
        group_slack={group: slack[group] for group in groups_sorted},
        group_reserve={group: reserve[group] for group in groups_sorted},
        free_slack=free,
    )


def format_core(plan: CorePlan) -> str:
    """Текст для консоли: размер ядра, запасы и порядок написания по пакетам."""
    lines = [
        f"Ядро P0 для {plan.specialization}: {len(plan.families)} семейств",
        "Запас пула групп (0 — выбывшее семейство выключает пару): "
        + ", ".join(f"{group}={value}" for group, value in plan.group_slack.items()),
        "Резерв групп во всей таблице (0 — заменить семейство нечем, писать первыми): "
        + ", ".join(f"{group}={value}" for group, value in plan.group_reserve.items()),
        "Запас свободного пула по грейдам: " + ", ".join(f"{g}={v}" for g, v in plan.free_slack.items()),
        "Порядок написания по пакетам:",
    ]
    for package, ids in sorted(plan.by_package().items()):
        lines.append(f"  {package} ({len(ids)}): {', '.join(ids)}")
    lines.append("CORE_P0 = (")
    lines.extend(f'    "{family_id}",' for family_id in plan.families)
    lines.append(")")
    return "\n".join(lines)
