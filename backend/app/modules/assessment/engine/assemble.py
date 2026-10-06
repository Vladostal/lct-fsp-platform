"""Детерминированная сборка формы теста (Арх. 5.4; приложение A, §4.3).

Библиотечный `random` не используется: выбор зависит только от seed сессии, поэтому одна и та же сессия собирается
одинаково на любой версии интерпретатора, а симуляция повторяет рабочий сервис.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field

from app.modules.assessment.blueprints import (
    MAIN_RANGE,
    STRETCH_RANGE,
    PoolFamily,
    Range,
    eligible,
    plan_slots,
)
from app.modules.assessment.config import AssessmentConfig, get_config
from app.modules.assessment.groups import GROUP_ORDER, LANG_SLOT
from app.shared.enums import SlotRole

__all__ = ["BankUnavailable", "FormSlot", "assemble_base", "assemble_ext", "session_seed", "u"]


class BankUnavailable(Exception):
    """В банке не хватает семейств или вариантов, чтобы собрать форму (API отвечает 503 `bank_unavailable`)."""


@dataclass(frozen=True)
class FormSlot:
    """Одно задание формы: слот плана, выбранное семейство и уровень."""

    slot: int
    stage: int
    role: SlotRole
    #: Группа, к которой привязан слот плана; `None` — свободный слот.
    slot_group: str | None
    family_id: str
    #: Группа выбранного семейства.
    group: str
    level: int
    b: float


def session_seed(secret: str, candidate_id: object, specialization: str, grade: str, attempt_no: int) -> str:
    """`HMAC_SHA256(ASSESSMENT_SECRET, "session:{candidate_id}:{specialization}:{grade}:{attempt_no}").hexdigest()`."""
    label = f"session:{candidate_id}:{specialization}:{grade}:{attempt_no}"
    return hmac.new(secret.encode("utf-8"), label.encode("utf-8"), hashlib.sha256).hexdigest()


def u(seed: str, label: str) -> float:
    """`u(seed, label) = int(HMAC_SHA256(seed, label)[:8]) / 2**64` — число из [0, 1), зависящее только от seed."""
    digest = hmac.new(bytes.fromhex(seed), label.encode("utf-8"), hashlib.sha256).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


@dataclass
class _Context:
    pools: tuple[PoolFamily, ...]
    seed: str
    specialization: str
    grade: str
    lang: str | None
    seen: frozenset[str]
    blocked: frozenset[tuple[str, int]]
    used: set[str] = field(default_factory=set)
    _weights: dict[str, float] = field(default_factory=dict)

    def levels(self, family: PoolFamily, rng: Range) -> list[tuple[int, float]]:
        """Уровни семейства со сложностью в диапазоне, у которых ещё есть вариант для этого кандидата."""
        return [
            (index + 1, b)
            for index, b in enumerate(family.bs)
            if rng[0] <= b <= rng[1] and (family.id, index + 1) not in self.blocked
        ]

    def pool(self, group: str | None, rng: Range) -> list[PoolFamily]:
        """`eligible(group, rng)` без уже взятых в сессию семейств."""
        return [
            f
            for f in eligible(self.pools, self.specialization, self.lang, group, rng)
            if f.id not in self.used and self.levels(f, rng)
        ]

    def weight(self, family: PoolFamily) -> float:
        """Вес семейства в свободном слоте: `max(0.05, 1 − k_g / n_g)²` (Арх. 5.4).

        `k_g` — привязанных слотов группы семейства в этом плане, `n_g` — её пул в основном диапазоне. Группы,
        плотно занятые привязанными слотами, выбираются реже: это снижает наибольшую экспозицию семейства.
        """
        if family.group not in self._weights:
            k = plan_slots(self.specialization, self.grade, self.lang).get(family.group, 0)
            n = len(eligible(self.pools, self.specialization, self.lang, family.group, MAIN_RANGE[self.grade]))
            self._weights[family.group] = max(0.05, 1.0 - (k / n if n else 1.0)) ** 2
        return self._weights[family.group]


def _pick(ctx: _Context, slot: int, stage: int, group: str | None, rng: Range, role: SlotRole) -> FormSlot:
    """Выбор семейства и уровня для слота (Арх. 5.4, функция `pick`).

    Пулы по убыванию предпочтения: `eligible(group) − used − seen`; `eligible(group) − used`;
    `eligible(None) − used − seen`; `eligible(None) − used`; иначе `BankUnavailable`. Семейство — взвешенный выбор
    из пула, отсортированного по идентификатору, по `u(seed, "fam:{stage}:{slot}")`; в привязанных слотах веса
    равны. Уровень — равновероятно среди уровней с `b` в диапазоне по `u(seed, "lvl:{stage}:{slot}")`.
    """
    candidates: list[PoolFamily] = []
    for target in dict.fromkeys((group, None)):
        full = ctx.pool(target, rng)
        fresh = [f for f in full if f.id not in ctx.seen]
        candidates = fresh or full
        if candidates:
            weighted = target is None
            break
    if not candidates:
        raise BankUnavailable(f"нет семейства для слота {stage}:{slot} (группа {group or 'любая'})")
    weights = [ctx.weight(f) if weighted else 1.0 for f in candidates]
    point = u(ctx.seed, f"fam:{stage}:{slot}") * sum(weights)
    family = candidates[-1]
    acc = 0.0
    for item, weight in zip(candidates, weights, strict=True):
        acc += weight
        if point < acc:
            family = item
            break
    levels = ctx.levels(family, rng)
    level, b = levels[min(int(u(ctx.seed, f"lvl:{stage}:{slot}") * len(levels)), len(levels) - 1)]
    ctx.used.add(family.id)
    return FormSlot(slot, stage, role, group, family.id, family.group, level, b)


def _context(
    families: Iterable[PoolFamily],
    seed: str,
    specialization: str,
    grade: str,
    lang: str | None,
    used: Collection[str],
    seen: Collection[str],
    blocked: Collection[tuple[str, int]],
) -> _Context:
    return _Context(
        pools=tuple(families),
        seed=seed,
        specialization=specialization,
        grade=grade,
        lang=lang,
        seen=frozenset(seen),
        blocked=frozenset(blocked),
        used=set(used),
    )


def assemble_base(
    families: Iterable[PoolFamily],
    *,
    seed: str,
    specialization: str,
    grade: str,
    lang: str | None,
    seen: Collection[str] = (),
    blocked: Collection[tuple[str, int]] = (),
    cfg: AssessmentConfig | None = None,
) -> list[FormSlot]:
    """Базовая часть формы в порядке показа (Арх. 5.4, `assemble_base`).

    12 привязанных слотов плана в порядке `GROUP_ORDER` (основной диапазон грейда) и 2 свободных слота растяжки
    (у senior растяжки нет — слоты основные). Столбец `lang` — группа языкового модуля, а без модуля — `code`.
    Семейство в сессии не повторяется. Порядок показа: два задания с наименьшим `b` идут первыми (разминка),
    остальные тасуются по Фишеру—Йетсу числами `u(seed, "ord:{i}")`.

    `seen` — семейства кандидата за окно (выбираются в последнюю очередь); `blocked` — пары (семейство, уровень),
    у которых не осталось варианта, не показанного этому кандидату.
    """
    cfg = cfg or get_config()
    ctx = _context(families, seed, specialization, grade, lang, (), seen, blocked)
    main, stretch = MAIN_RANGE[grade], STRETCH_RANGE[grade]
    plan = plan_slots(specialization, grade, lang)
    slots: list[FormSlot] = []
    done: set[str] = set()
    for column in GROUP_ORDER:
        group = (lang or "code") if column == LANG_SLOT else column
        if group in done or group not in plan:
            continue
        done.add(group)
        for _ in range(plan[group]):
            slots.append(_pick(ctx, len(slots), 0, group, main, SlotRole.MAIN))
    for _ in range(cfg.base_stretch):
        if stretch is None:
            slots.append(_pick(ctx, len(slots), 0, None, main, SlotRole.MAIN))
        else:
            slots.append(_pick(ctx, len(slots), 0, None, stretch, SlotRole.STRETCH))

    warmup = sorted(slots, key=lambda item: (item.b, item.slot))[:2]
    rest = [item for item in slots if item not in warmup]
    for i in range(len(rest) - 1, 0, -1):
        j = min(int(u(seed, f"ord:{i}") * (i + 1)), i)
        rest[i], rest[j] = rest[j], rest[i]
    return warmup + rest


def assemble_ext(
    families: Iterable[PoolFamily],
    *,
    seed: str,
    specialization: str,
    grade: str,
    lang: str | None,
    stage: int,
    used: Collection[str],
    seen: Collection[str] = (),
    blocked: Collection[tuple[str, int]] = (),
    cfg: AssessmentConfig | None = None,
) -> list[FormSlot]:
    """Добавочный блок (Арх. 5.4, `assemble_ext`): `EXT_BLOCK` свободных слотов основного диапазона грейда.

    `used` — семейства, уже выданные в этой сессии; `stage` — номер блока (1 или 2). Если семейств не хватает,
    поднимается `BankUnavailable`: тест завершается с текущим исходом.
    """
    cfg = cfg or get_config()
    ctx = _context(families, seed, specialization, grade, lang, used, seen, blocked)
    return [_pick(ctx, i, stage, None, MAIN_RANGE[grade], SlotRole.EXT) for i in range(cfg.ext_block)]
