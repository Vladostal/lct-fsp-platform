"""Учебный банк в тестовой базе: варианты генерируются напрямую, без линтера сборки (он проверяется отдельно)."""

# ruff: noqa: E501 — подписи отчёта и длинные проверки читаются лучше в одну строку

from __future__ import annotations

from datetime import UTC, datetime
from functools import cache

from sqlalchemy.orm import Session

from app.modules.assessment import repo
from app.modules.assessment.bank.build import variant_seed
from app.modules.assessment.bank.store import write_family
from app.modules.assessment.families._lib.contract import Family, Reject, Variant
from tests.assessment.fake_families._bank import fake_bank

BANK_AT = datetime(2026, 9, 1, tzinfo=UTC)


def _variants(family: Family, level: int, count: int, *, demo: bool) -> list[Variant]:
    result: list[Variant] = []
    n = 0
    while len(result) < count and n < count * 20:
        seed = variant_seed("test-bank", family.meta.id, family.meta.version, level, n, demo=demo)
        n += 1
        try:
            result.append(family.generate(level, seed))
        except Reject:
            continue
    assert len(result) == count, f"{family.meta.id} L{level}: не набрано {count} вариантов"
    return result


@cache
def generated(per_level: int = 5, demo: int = 1) -> tuple[tuple[Family, dict[int, list[Variant]], dict[int, list[Variant]]], ...]:
    """70 учебных семейств реестра с вариантами; считается один раз на запуск."""
    rows = []
    for family in fake_bank():
        levels = [level.level for level in family.meta.levels]
        rows.append(
            (
                family,
                {level: _variants(family, level, per_level, demo=False) for level in levels},
                {level: _variants(family, level, demo, demo=True) for level in levels},
            )
        )
    return tuple(rows)


def install_bank(db: Session, *, per_level: int = 5, only_groups: set[str] | None = None) -> list[Family]:
    """Записать учебный банк в базу теста и опубликовать доступные пары в каталог."""
    families = []
    for family, variants, demo in generated(per_level):
        if only_groups is not None and family.meta.group not in only_groups:
            continue
        write_family(db, family, variants, demo, now=BANK_AT)
        families.append(family)
    db.flush()
    repo.refresh_availability(db)
    return families
