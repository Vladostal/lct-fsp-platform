"""Учебный банк: каждая строка реестра, за которой стоит один из трёх учебных генераторов.

Нужен тестам движка, сборки формы и валидации, которым требуется полный состав банка (70 семейств с настоящими
группами, уровнями и `b`), а не содержание заданий. Вид задания у такого семейства — вид учебного генератора,
а не тот, что записан в реестре; всё остальное (группа, теги, уровни, специализации, очередь) — из реестра.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from app.modules.assessment.families import discover
from app.modules.assessment.families._lib.contract import Family, Variant
from app.modules.assessment.families.registry import REGISTRY, FamilySpec, family_meta
from tests.assessment.fake_families import PACKAGE


def _clone(spec: FamilySpec, template: Family) -> Family:
    top = len(template.meta.levels)
    source = template.meta

    def template_level(level: int) -> int:
        return min(level, top)

    meta = family_meta(
        spec.id,
        version=1,
        feature_bounds={
            level.level: dict(source.level(template_level(level.level)).feature_bounds) for level in spec.levels
        },
        misconceptions=source.misconceptions,
        spec=replace(spec, kind=source.kind, extra_kinds=()),
    )

    def generate(level: int, seed: int) -> Variant:
        variant = template.generate(template_level(level), seed)
        return replace(variant, family_id=meta.id, family_version=meta.version, level=level)

    def selfcheck(v: Variant) -> list[str]:
        original = replace(v, family_id=source.id, family_version=source.version, level=template_level(v.level))
        return template.selfcheck(original)

    return Family(meta=meta, generate=generate, selfcheck=selfcheck, module=f"{PACKAGE}._bank:{spec.id}")


def fake_bank(specs: Iterable[FamilySpec] | None = None) -> list[Family]:
    """Учебные семейства для строк реестра (по умолчанию — для всех 70), генераторы чередуются по кругу."""
    templates = discover(PACKAGE).families
    rows = list(REGISTRY.values() if specs is None else specs)
    return [_clone(spec, templates[index % len(templates)]) for index, spec in enumerate(rows)]
