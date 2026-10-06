"""Планы теста и проверка их выполнимости на наборе семейств (Арх. 5.2, 5.4; приложение A, §4.1–4.3).

В этом файле: диапазоны сложности грейдов, таблица стандартных планов, правило языкового модуля и инварианты плана.
Инварианты считаются отдельно для каждой пары (специализация, грейд): невыполненный выключает только эту пару,
а не весь банк (Арх. 5.2). Одна и та же функция `check_plan` работает на таблице реестра (до написания генераторов),
на загруженных семействах и на активных семействах банка при старте.

Всё здесь — чистые функции без базы.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from app.modules.assessment.config import GRADES, get_config
from app.modules.assessment.groups import (
    GROUP_ORDER,
    LANG_GROUPS,
    LANG_SLOT,
    SKILL_GROUP_MAP,
    SPECIALIZATIONS,
)

Range = tuple[float, float]

#: Основные слоты дают информацию у порога грейда (Арх. 5.4).
MAIN_RANGE: dict[str, Range] = {"junior": (-2.0, -1.0), "middle": (-0.5, 0.5), "senior": (1.0, 2.0)}
#: Слоты растяжки — у порога «с запасом». У senior грейда выше нет: его два свободных слота — основные.
STRETCH_RANGE: dict[str, Range | None] = {"junior": (-0.5, 0.0), "middle": (1.0, 1.5), "senior": None}

_ROWS: tuple[tuple[str, str, tuple[int, ...]], ...] = (
    # специализация, грейд,  code lang algo ds sql http git db svc css web stats ml dw
    ("backend", "junior", (2, 2, 1, 1, 2, 2, 1, 1, 0, 0, 0, 0, 0, 0)),
    ("backend", "middle", (1, 2, 1, 1, 2, 1, 1, 2, 1, 0, 0, 0, 0, 0)),
    ("backend", "senior", (1, 1, 1, 1, 2, 2, 1, 2, 1, 0, 0, 0, 0, 0)),
    ("frontend", "junior", (2, 2, 1, 1, 1, 1, 1, 0, 0, 2, 1, 0, 0, 0)),
    ("frontend", "middle", (1, 2, 1, 1, 1, 2, 1, 0, 0, 1, 2, 0, 0, 0)),
    ("frontend", "senior", (1, 2, 1, 1, 1, 2, 1, 0, 0, 1, 2, 0, 0, 0)),
    ("fullstack", "junior", (2, 2, 1, 0, 2, 2, 1, 0, 0, 1, 1, 0, 0, 0)),
    ("fullstack", "middle", (1, 2, 1, 0, 1, 2, 1, 1, 1, 1, 1, 0, 0, 0)),
    ("fullstack", "senior", (1, 2, 1, 0, 1, 2, 1, 1, 1, 1, 1, 0, 0, 0)),
    ("data_ml", "junior", (2, 2, 1, 0, 2, 0, 1, 0, 0, 0, 0, 1, 1, 2)),
    ("data_ml", "middle", (1, 1, 1, 0, 3, 0, 1, 0, 0, 0, 0, 2, 2, 1)),
    ("data_ml", "senior", (1, 1, 2, 0, 2, 0, 1, 0, 0, 0, 0, 2, 2, 1)),
)

#: Стандартный план категории (Арх. 5.4): 12 слотов, привязанных к группам; ключ «lang» — языковой модуль сессии.
#: Версионируется вместе с `BANK_VERSION`. Группы с нулём слотов в словарь не входят.
BLUEPRINTS: dict[tuple[str, str], dict[str, int]] = {
    (spec, grade): {group: n for group, n in zip(GROUP_ORDER, slots, strict=True) if n} for spec, grade, slots in _ROWS
}


@dataclass(frozen=True)
class LangRule:
    """Языковой модуль специализации (Арх. 5.2)."""

    #: Модуль, без которого теста нет (`js` у frontend и fullstack); `None` — есть запасной путь через `code`.
    required: str | None
    #: Ответ на вопрос опроса `main_language` → модуль; прочие языки — без модуля.
    by_language: dict[str, str]


LANG_RULES: dict[str, LangRule] = {
    "backend": LangRule(None, {"python": "py", "nodejs": "js"}),
    "frontend": LangRule("js", {}),
    "fullstack": LangRule("js", {}),
    "data_ml": LangRule(None, {"python": "py"}),
}


def lang_module(specialization: str, main_language: str | None) -> str | None:
    """Языковой модуль сессии по ответам опроса (Арх. 5.2).

    frontend и fullstack → `js`; backend: python → `py`, nodejs → `js`, иначе нет; data_ml: python → `py`, иначе нет.
    Без модуля слоты `lang` уходят в группу `code`.
    """
    rule = LANG_RULES[specialization]
    if rule.required is not None:
        return rule.required
    return rule.by_language.get(main_language or "")


def base_scenario(specialization: str) -> str | None:
    """Языковой модуль, по которому считается доступность пары: обязательный модуль либо запасной путь без модуля."""
    return LANG_RULES[specialization].required


def lang_scenarios(specialization: str) -> tuple[str | None, ...]:
    """Все языковые модули, с которыми может идти сессия специализации; первым — тот, что определяет доступность."""
    rule = LANG_RULES[specialization]
    if rule.required is not None:
        return (rule.required,)
    return (None, *dict.fromkeys(rule.by_language.values()))


# --------------------------------------------------------------------------------------------------------------------
# Пулы семейств
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PoolFamily:
    """Семейство глазами плана: группа, специализации и сложности уровней. Больше планам ничего не нужно."""

    id: str
    group: str
    specializations: tuple[str, ...]
    bs: tuple[float, ...]

    def has_level(self, rng: Range | None) -> bool:
        """Есть ли у семейства уровень со сложностью в диапазоне (границы включены)."""
        return rng is not None and any(rng[0] <= b <= rng[1] for b in self.bs)


def pool_family(obj: Any) -> PoolFamily:
    """Привести строку реестра (`FamilySpec`), паспорт (`FamilyMeta`) или готовый `PoolFamily` к одному виду."""
    if isinstance(obj, PoolFamily):
        return obj
    return PoolFamily(
        id=obj.id,
        group=obj.group,
        specializations=tuple(obj.specializations),
        bs=tuple(float(level.b) for level in obj.levels),
    )


def pool_families(families: Iterable[Any]) -> tuple[PoolFamily, ...]:
    """То же для набора семейств."""
    return tuple(pool_family(item) for item in families)


def any_groups(families: Iterable[PoolFamily], specialization: str, lang: str | None) -> frozenset[str]:
    """Группы, из которых берутся свободные слоты: неязыковые группы семейств специализации плюс языковой модуль."""
    groups = {f.group for f in families if specialization in f.specializations and f.group not in LANG_GROUPS}
    if lang is not None:
        groups.add(lang)
    return frozenset(groups)


def eligible(
    families: Iterable[PoolFamily], specialization: str, lang: str | None, group: str | None, rng: Range | None
) -> list[PoolFamily]:
    """Пул слота (приложение A, §4.3, функция `eligible` без учёта показанных вариантов).

    Семейство подходит, если оно принадлежит специализации либо его группа — языковой модуль сессии; его группа
    равна `group` (для свободного слота — входит в `any_groups`); у него есть уровень со сложностью в `rng`.
    """
    items = list(families)
    free_groups = any_groups(items, specialization, lang) if group is None else frozenset()
    result = []
    for f in items:
        in_spec = specialization in f.specializations or (lang is not None and f.group == lang)
        in_group = f.group == group if group is not None else f.group in free_groups
        if in_spec and in_group and f.has_level(rng):
            result.append(f)
    return sorted(result, key=lambda f: f.id)


def plan_slots(specialization: str, grade: str, lang: str | None) -> dict[str, int]:
    """Привязанные слоты плана; слоты столбца `lang` уходят в группу языкового модуля, а без модуля — в `code`."""
    slots: dict[str, int] = {}
    for group, n in BLUEPRINTS[(specialization, grade)].items():
        target = (lang or "code") if group == LANG_SLOT else group
        slots[target] = slots.get(target, 0) + n
    return slots


# --------------------------------------------------------------------------------------------------------------------
# Инварианты
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanViolation:
    """Нарушенный инвариант плана для одной пары и одного языкового модуля."""

    #: `pool_min` — пул группы меньше `MIN_POOL`; `pool_slots` — слотов больше, чем `pool − 1`;
    #: `free_pool` — свободных семейств не хватает на растяжки и добавочные блоки;
    #: `stretch_pool` — после привязанных слотов может не остаться семейств для растяжки.
    code: str
    group: str | None
    need: int
    have: int

    def __str__(self) -> str:
        where = f"группа {self.group}: " if self.group else ""
        text = {
            "pool_min": "пул меньше MIN_POOL",
            "pool_slots": "слотов больше, чем пул − 1",
            "free_pool": "мало семейств для свободных слотов и добавочных блоков",
            "stretch_pool": "мало семейств для слотов растяжки",
        }[self.code]
        return f"{where}{text} (нужно {self.need}, есть {self.have})"


def check_plan(families: Iterable[Any], specialization: str, grade: str, lang: str | None) -> list[PlanViolation]:
    """Инварианты плана для пары (специализация, грейд) при языковом модуле `lang` (Арх. 5.4; приложение A, §4.2).

    1. Для каждой группы с привязанными слотами: `pool ≥ MIN_POOL` и `slots ≤ pool − 1`, где `pool` — число семейств
       группы с уровнем в основном диапазоне грейда. Первое защищает от узнавания задания по группе, второе держит
       долю показов семейства ниже единицы (Арх. 5.8).
    2. Запасной путь без языкового модуля — тот же инвариант при `lang=None`: слоты `lang` складываются со слотами
       `code`, то есть `code + lang ≤ pool(code) − 1`.
    3. Свободных семейств хватает на всю длину теста без повторов семейства в сессии:
       `|eligible(None, main)| ≥ BASE_MAIN + BASE_STRETCH + EXT_BLOCK · MAX_EXT_BLOCKS` (12 + 2 + 12 = 26).
    4. Для грейда с растяжкой: даже если привязанные слоты заберут наибольшее возможное число семейств, у которых
       есть уровень растяжки, таких семейств останется не меньше `BASE_STRETCH`.

    Пустой список — план выполним.
    """
    cfg = get_config()
    pools = pool_families(families)
    main, stretch = MAIN_RANGE[grade], STRETCH_RANGE[grade]
    slots = plan_slots(specialization, grade, lang)
    violations: list[PlanViolation] = []

    group_pools = {group: eligible(pools, specialization, lang, group, main) for group in slots}
    for group, n in slots.items():
        pool = len(group_pools[group])
        if pool < cfg.min_pool:
            violations.append(PlanViolation("pool_min", group, cfg.min_pool, pool))
        if n > pool - 1:
            violations.append(PlanViolation("pool_slots", group, n + 1, pool))

    free = eligible(pools, specialization, lang, None, main)
    need_free = cfg.base_main + cfg.base_stretch + cfg.ext_block * cfg.max_ext_blocks
    if len(free) < need_free:
        violations.append(PlanViolation("free_pool", None, need_free, len(free)))

    if stretch is not None:
        stretch_ids = {f.id for f in eligible(pools, specialization, lang, None, stretch)}
        taken = sum(min(n, sum(1 for f in group_pools[group] if f.id in stretch_ids)) for group, n in slots.items())
        left = len(stretch_ids) - taken
        if left < cfg.base_stretch:
            violations.append(PlanViolation("stretch_pool", None, cfg.base_stretch, left))
    return violations


def pair_available(families: Iterable[Any], specialization: str, grade: str) -> bool:
    """Доступна ли пара (Арх. 5.2): инварианты выполнены для обязательного модуля либо для пути без модуля."""
    return not check_plan(families, specialization, grade, base_scenario(specialization))


def lang_module_available(families: Iterable[Any], specialization: str, grade: str, lang: str) -> bool:
    """Можно ли выдать сессии языковой модуль; если нет — сессия идёт запасным путём через `code` с примечанием."""
    return lang in lang_scenarios(specialization) and not check_plan(families, specialization, grade, lang)


def available_pairs(families: Iterable[Any], disabled: Collection[str] = ()) -> set[tuple[str, str]]:
    """Все доступные пары (специализация, грейд); `disabled` — специализации, выключенные принудительно."""
    pools = pool_families(families)
    return {
        (spec, grade)
        for spec in SPECIALIZATIONS
        if spec not in disabled
        for grade in GRADES
        if pair_available(pools, spec, grade)
    }


@dataclass(frozen=True)
class PlanCheck:
    """Результат проверки одной пары при одном языковом модуле — строка отчёта о выполнимости."""

    specialization: str
    grade: str
    lang: str | None
    #: Группа -> (привязанных слотов, семейств в пуле).
    pools: dict[str, tuple[int, int]]
    free_pool: int
    violations: tuple[PlanViolation, ...]

    @property
    def ok(self) -> bool:
        """Выполнены ли все инварианты."""
        return not self.violations


def feasibility_report(families: Iterable[Any], specializations: Sequence[str] = SPECIALIZATIONS) -> list[PlanCheck]:
    """Проверка всех пар и всех языковых модулей: для теста `test_blueprints_feasible` и команды `bank build`."""
    pools = pool_families(families)
    report = []
    for spec in specializations:
        for grade in GRADES:
            for lang in lang_scenarios(spec):
                slots = plan_slots(spec, grade, lang)
                report.append(
                    PlanCheck(
                        specialization=spec,
                        grade=grade,
                        lang=lang,
                        pools={
                            g: (n, len(eligible(pools, spec, lang, g, MAIN_RANGE[grade]))) for g, n in slots.items()
                        },
                        free_pool=len(eligible(pools, spec, lang, None, MAIN_RANGE[grade])),
                        violations=tuple(check_plan(pools, spec, grade, lang)),
                    )
                )
    return report


# --------------------------------------------------------------------------------------------------------------------
# План под описание вакансии
# --------------------------------------------------------------------------------------------------------------------

#: Веса спроса (Арх. 5.4): приоритет требования и связь навыка с группой.
PRIORITY_WEIGHT: dict[str, float] = {"must": 2.0, "nice": 1.0}
RELATION_WEIGHT: dict[str, float] = {"direct": 1.0, "related": 0.5}
#: Больше трёх слотов одной группе план под вакансию не даёт.
NEED_GROUP_CAP = 3


@dataclass(frozen=True)
class CoverageRow:
    """Строка отчёта о покрытии: чем тест категории проверяет требование вакансии."""

    skill: str
    priority: str
    group: str | None
    #: `direct`, `related`, `untested`, `above_grade`.
    relation: str
    #: Слотов этой группы в стандартном плане категории (его получит кандидат).
    slots: int


@dataclass(frozen=True)
class NeedPlan:
    """План категории и индикативный план под описание (Арх. 5.4): группа -> число привязанных слотов."""

    standard: dict[str, int]
    need: dict[str, int]
    demand: dict[str, float]
    coverage: tuple[CoverageRow, ...]


def need_plan(
    families: Iterable[Any],
    specialization: str,
    grade: str,
    lang: str | None,
    must_skills: Sequence[str],
    nice_skills: Sequence[str],
) -> NeedPlan:
    """Как описание вакансии перераспределяет 12 привязанных слотов плана (Арх. 5.4; приложение A, §4.4).

    1. Спрос группы: `demand[g] = Σ w_priority · w_relation`; `must = 2`, `nice = 1`; `direct = 1`, `related = 0.5`
       по `SKILL_GROUP_MAP`. Учитываются группы специализации (с языковым модулем) с пулом не меньше `MIN_POOL`.
    2. До `FLEX_SLOTS` раз слот переходит от группы с нулевым спросом (группа `code` отдаёт только сверх одного;
       раньше отдаёт та, у которой слотов больше, при равенстве — по алфавиту) к группе со спросом:
       получатель — `argmax demand[g] / (slots[g] + 1)` (ничья — больший спрос, затем алфавит),
       предел группы — `min(3, pool_g − 1)`.
    3. Покрытие по каждому навыку: `direct`, `related`, `untested` (навыка нет в карте либо группа недоступна),
       `above_grade` (у семейств с этим тегом нет уровня в диапазонах грейда).

    Кандидату этот план не выдаётся: категорию все получают на стандартном плане, иначе кандидаты одной категории
    были бы измерены на разном содержании.
    """
    cfg = get_config()
    items = list(families)
    pools = pool_families(items)
    tags = {pool.id: tuple(getattr(item, "skill_tags", ())) for pool, item in zip(pools, items, strict=True)}
    main, stretch = MAIN_RANGE[grade], STRETCH_RANGE[grade]
    standard = plan_slots(specialization, grade, lang)
    group_pool = {
        group: eligible(pools, specialization, lang, group, main)
        for group in sorted(any_groups(pools, specialization, lang) | set(standard))
    }
    open_groups = {group for group, pool in group_pool.items() if len(pool) >= cfg.min_pool}

    def in_grade(skill: str, group: str) -> bool:
        tagged = [f for f in pools if f.group == group and skill in tags[f.id]]
        return not tagged or any(f.has_level(main) or f.has_level(stretch) for f in tagged)

    demand: dict[str, float] = {}
    coverage: list[CoverageRow] = []
    seen: set[str] = set()
    for priority, skills in (("must", must_skills), ("nice", nice_skills)):
        for skill in skills:
            if skill in seen:
                continue
            seen.add(skill)
            links: list[tuple[str, str]] = []
            for group in GROUP_ORDER[:1] + tuple(g for g in SKILL_GROUP_MAP if g != "code"):
                if group not in open_groups:
                    continue
                skill_map = SKILL_GROUP_MAP[group]
                relation = "direct" if skill in skill_map.direct else "related" if skill in skill_map.related else None
                if relation is not None:
                    links.append((group, relation))
                    demand[group] = demand.get(group, 0.0) + PRIORITY_WEIGHT[priority] * RELATION_WEIGHT[relation]
            if not links:
                coverage.append(CoverageRow(skill, priority, None, "untested", 0))
                continue
            # Показывается самая сильная связь; при равных — группа, у которой больше слотов в плане категории.
            group, relation = min(links, key=lambda link: (link[1] != "direct", -standard.get(link[0], 0), link[0]))
            if relation == "direct" and not in_grade(skill, group):
                relation = "above_grade"
            coverage.append(CoverageRow(skill, priority, group, relation, standard.get(group, 0)))

    need = dict(standard)
    cap = {group: min(NEED_GROUP_CAP, len(group_pool[group]) - 1) for group in open_groups}
    for _ in range(cfg.flex_slots):
        donors = [g for g, n in need.items() if demand.get(g, 0.0) == 0 and n > (1 if g == "code" else 0)]
        takers = [g for g in open_groups if demand.get(g, 0.0) > 0 and need.get(g, 0) < cap[g]]
        if not donors or not takers:
            break
        donor = min(donors, key=lambda g: (-need[g], g))
        taker = min(takers, key=lambda g: (-demand[g] / (need.get(g, 0) + 1), -demand[g], g))
        need[donor] -= 1
        need[taker] = need.get(taker, 0) + 1
    return NeedPlan(standard=standard, need=need, demand=demand, coverage=tuple(coverage))
