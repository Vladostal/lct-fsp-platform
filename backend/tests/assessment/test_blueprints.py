"""Выполнимость планов теста на реестре семейств и ядро P0 (Арх. 5.2–5.4; приложение A, §3.4, §4.2)."""

from __future__ import annotations

from collections import Counter

import pytest

from app.modules.assessment.bank.core import compute_core
from app.modules.assessment.blueprints import (
    BLUEPRINTS,
    MAIN_RANGE,
    available_pairs,
    check_plan,
    eligible,
    feasibility_report,
    lang_module,
    lang_module_available,
    pool_families,
)
from app.modules.assessment.config import GRADES, get_config
from app.modules.assessment.families.registry import CORE_P0, DEMO_CORE, REGISTRY, core_families, specs
from app.modules.assessment.groups import GROUPS, SKILL_GROUP_MAP, SPECIALIZATIONS
from tests.assessment.fake_families._bank import fake_bank

ALL_PAIRS = {(spec, grade) for spec in SPECIALIZATIONS for grade in GRADES}
BACKEND = {("backend", grade) for grade in GRADES}

#: Приложение A, §3.4: группа -> (всего, junior, middle, senior).
POOL_SIZES = {
    "code": (6, 6, 6, 5), "algo": (6, 5, 6, 5), "ds": (4, 4, 4, 3), "sql": (7, 5, 7, 6), "http": (5, 5, 5, 4),
    "git": (4, 4, 4, 4), "py": (4, 4, 4, 4), "js": (5, 4, 5, 4), "db": (5, 3, 5, 4), "svc": (4, 2, 4, 4),
    "css": (4, 4, 4, 3), "web": (4, 4, 4, 4), "stats": (4, 4, 4, 4), "ml": (4, 4, 4, 4), "dw": (4, 4, 4, 3),
}  # fmt: skip


def test_registry_matches_appendix_tables() -> None:
    assert len(REGISTRY) == 70
    assert sum(len(spec.levels) for spec in REGISTRY.values()) == 200
    assert Counter(spec.package for spec in REGISTRY.values()) == {
        "B21a": 16, "B21b": 12, "B21c": 17, "B22": 13, "B23": 12,
    }  # fmt: skip
    pools = pool_families(REGISTRY.values())
    for group, (total, *by_grade) in POOL_SIZES.items():
        members = [f for f in pools if f.group == group]
        assert len(members) == total, group
        assert [sum(f.has_level(MAIN_RANGE[grade]) for f in members) for grade in GRADES] == by_grade, group
    direct = {skill for item in SKILL_GROUP_MAP.values() for skill in item.direct}
    for spec in REGISTRY.values():
        assert spec.id.split(".")[0] == spec.group and spec.group in GROUPS
        assert set(spec.skill_tags) <= direct, spec.id
        assert set(spec.skill_tags) & set(SKILL_GROUP_MAP[spec.group].direct), spec.id


def test_blueprint_rows_sum_to_base_main() -> None:
    assert set(BLUEPRINTS) == ALL_PAIRS
    assert all(sum(slots.values()) == get_config().base_main for slots in BLUEPRINTS.values())


def test_blueprints_feasible() -> None:
    """Инварианты планов на полной таблице реестра: все 12 пар и все языковые сценарии (Арх. 5.4)."""
    report = feasibility_report(REGISTRY.values())
    failed = [(c.specialization, c.grade, c.lang, [str(v) for v in c.violations]) for c in report if not c.ok]
    assert failed == []
    assert len(report) == 21
    assert available_pairs(REGISTRY.values()) == ALL_PAIRS


def test_blueprints_feasible_on_fake_bank() -> None:
    """То же на учебных семействах: паспорта учебного банка повторяют группы и уровни реестра."""
    metas = [family.meta for family in fake_bank()]
    assert available_pairs(metas) == ALL_PAIRS
    assert all(check.ok for check in feasibility_report(metas))


def test_blueprints_feasible_on_core_p0(min_pool_3: None) -> None:
    """Ядро P0 открывает ровно три пары backend — без языкового модуля и с модулем py (Арх. 5.3)."""
    core = core_families()
    assert available_pairs(core) == BACKEND
    for grade in GRADES:
        assert check_plan(core, "backend", grade, None) == []
        assert check_plan(core, "backend", grade, "py") == []
        assert lang_module_available(core, "backend", grade, "py")
        assert not lang_module_available(core, "backend", grade, "js")


def test_core_p0_matches_registry(min_pool_3: None) -> None:
    """`CORE_P0` в реестре — то, что выдаёт расчёт: после смены `b` (E1) список нужно пересчитать."""
    plan = compute_core(REGISTRY.values())
    assert plan.families == CORE_P0
    assert len(CORE_P0) == 31
    assert {package: len(ids) for package, ids in plan.by_package().items()} == {"B21a": 12, "B21b": 7, "B21c": 12}
    assert all(REGISTRY[i].core_p0 and REGISTRY[i].queue == 1 and REGISTRY[i].priority == "P0" for i in CORE_P0)
    assert [spec.core_order for spec in core_families()] == list(range(1, 32))
    # Первыми идут группы, которым во всей таблице нечем заменить выбывшее семейство.
    assert [group for group, reserve in plan.group_reserve.items() if reserve == 0] == ["ds", "db"]
    assert {CORE_P0[i].split(".")[0] for i in range(7)} == {"ds", "db"}
    assert min(plan.free_slack.values()) >= 0


def test_core_is_minimal(min_pool_3: None) -> None:
    """Без любого семейства ядра хотя бы одна пара backend недоступна: меньший набор не годится."""
    core = core_families()
    for removed in core:
        rest = [spec for spec in core if spec.id != removed.id]
        assert available_pairs(rest) != BACKEND or any(check_plan(rest, "backend", grade, "py") for grade in GRADES), (
            removed.id
        )


def test_dropped_family_disables_only_its_pairs(min_pool_3: None) -> None:
    """Выбывшее семейство выключает пару (специализация, грейд), а не весь банк (Арх. 5.2)."""
    without = [spec for spec in REGISTRY.values() if spec.id != "db.constraints_effect"]
    # В группе db на junior ровно три семейства: без одного пул меньше MIN_POOL.
    assert available_pairs(without) == ALL_PAIRS - {("backend", "junior")}
    violations = check_plan(without, "backend", "junior", None)
    assert [(v.code, v.group) for v in violations] == [("pool_min", "db")]
    assert available_pairs(REGISTRY.values(), disabled={"data_ml"}) == {p for p in ALL_PAIRS if p[0] != "data_ml"}


def test_queues_and_priorities() -> None:
    assert Counter(spec.queue for spec in REGISTRY.values()) == {1: 31, 2: 13, 3: 14, 4: 12}
    assert {spec.priority for spec in specs(queue=2)} == {"P1"} and {spec.group for spec in specs(queue=2)} == {
        "js", "css", "web",
    }  # fmt: skip
    assert {spec.priority for spec in specs(queue=3)} == {"P1"}
    assert {spec.priority for spec in specs(queue=4)} == {"P2"}
    ordered = specs(package="B21b")
    assert [spec.id for spec in ordered[:4]] == [i for i in CORE_P0 if i.startswith("db.")]
    assert [spec.queue for spec in ordered] == sorted(spec.queue for spec in ordered)


def test_frontend_minimum_over_core(min_pool_3: None) -> None:
    """Девять семейств B22 сверх ядра открывают frontend и fullstack на трёх грейдах."""
    plan = compute_core(REGISTRY.values(), "frontend", ("js",), include=CORE_P0)
    extra = [family_id for family_id in plan.families if family_id not in CORE_P0]
    assert len(extra) == 9 and {REGISTRY[i].package for i in extra} == {"B22"}
    assert Counter(i.split(".")[0] for i in extra) == {"js": 3, "css": 3, "web": 3}
    opened = available_pairs([*core_families(), *(REGISTRY[i] for i in extra)])
    assert opened == {p for p in ALL_PAIRS if p[0] != "data_ml"}


def test_compute_core_fails_when_infeasible(min_pool_3: None) -> None:
    with pytest.raises(ValueError):
        compute_core([spec for spec in REGISTRY.values() if spec.group != "db"])


def test_lang_module_rules() -> None:
    assert lang_module("frontend", "python") == "js" and lang_module("fullstack", None) == "js"
    assert lang_module("backend", "python") == "py" and lang_module("backend", "nodejs") == "js"
    assert lang_module("backend", "java") is None and lang_module("data_ml", "r") is None
    # Без языкового модуля слоты lang уходят в code: у backend junior это четыре слота из пула шести.
    pools = pool_families(REGISTRY.values())
    assert len(eligible(pools, "backend", None, "code", MAIN_RANGE["junior"])) == 6
    assert not any(f.group in ("py", "js") for f in eligible(pools, "backend", None, None, MAIN_RANGE["junior"]))
    assert any(f.group == "py" for f in eligible(pools, "backend", "py", None, MAIN_RANGE["junior"]))


def test_demo_core_matches_registry() -> None:
    """Демо-ядро (MIN_POOL = 2, по умолчанию) — расчёт на семействах ядра P0; признак `demo_core` в реестре."""
    assert get_config().min_pool == 2
    demo = [REGISTRY[i] for i in CORE_P0 if REGISTRY[i].demo_core]
    plan = compute_core([REGISTRY[i] for i in CORE_P0])
    assert set(plan.families) == set(DEMO_CORE) and len(DEMO_CORE) == 30
    assert {s.id for s in REGISTRY.values() if s.demo_core} == set(DEMO_CORE) <= set(CORE_P0)
    assert available_pairs(demo) == BACKEND
    for grade in GRADES:
        assert check_plan(demo, "backend", grade, None) == [] and check_plan(demo, "backend", grade, "py") == []
