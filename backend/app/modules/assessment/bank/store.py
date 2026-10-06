"""Запись собранного банка в базу и сборка при первом запуске стенда (Арх. 5.3, 13.2).

`bank/build.py` превращает генераторы в принятые варианты; этот файл кладёт их в таблицы `assessment_family`,
`assessment_family_level`, `assessment_variant`. Запись идемпотентна: вариант определяется четвёркой
(семейство, версия, уровень, seed), повторная сборка добавляет только недостающие. В рантайме генераторы
не исполняются: сессии читают готовые варианты.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core import clock
from app.core.db import session_scope
from app.modules.assessment.bank.build import BankBuild, BuildOptions, FamilyBuild, build_bank
from app.modules.assessment.config import get_config
from app.modules.assessment.families import discover
from app.modules.assessment.families._lib.contract import (
    Family,
    ItemKind,
    Variant,
    content_hash,
    guess_probability,
    variant_answer_json,
    variant_payload,
    variant_to_json,
)
from app.modules.assessment.models import FamilyLevelRow, FamilyRow, VariantRow
from app.shared.enums import FamilyStatus, VariantStatus

log = logging.getLogger("app.init")

__all__ = ["build_if_empty", "variant_guess", "write_bank", "write_builds", "write_family"]

_CHUNK = 500


def variant_guess(v: Variant) -> float:
    """Вероятность угадать `c` для варианта (приложение A, §2.3): по виду задания и числу вариантов или строк кода."""
    options = len(v.options or ())
    lines = len(v.code.text.strip("\n").split("\n")) if v.code is not None else 0
    return guess_probability(v.kind, options=options, lines=lines)


def _variant_row(v: Variant, status: VariantStatus) -> dict[str, Any]:
    data = variant_to_json(v)
    return {
        "family_id": v.family_id,
        "family_version": v.family_version,
        "level": v.level,
        "seed": Decimal(v.seed),
        "payload": variant_payload(v),
        "answer": variant_answer_json(v),
        "misconception_answers": data["misconception_answers"],
        "features": data["features"],
        "guess": Decimal(str(variant_guess(v))),
        "content_hash": content_hash(v),
        "status": status.value,
        "served_count": 0,
    }


def write_family(
    db: Session,
    family: Family,
    variants: Mapping[int, Sequence[Variant]],
    demo: Mapping[int, Sequence[Variant]] | None = None,
    *,
    now: datetime,
) -> int:
    """Записать семейство, его уровни и варианты; вернуть число добавленных вариантов.

    Новое семейство получает статус `active`; у существующего статус не меняется (карантин переживает пересборку).
    Варианты прежних версий семейства получают статус `retired`: идущие сессии доигрываются на своих вариантах.
    """
    meta = family.meta
    values = {
        "version": meta.version,
        "title": meta.title,
        "group_code": meta.group,
        "kind": ItemKind(meta.kind).value,
        "specializations": list(meta.specializations),
        "skill_tags": list(meta.skill_tags),
        "priority": meta.priority,
    }
    db.execute(
        insert(FamilyRow)
        .values(id=meta.id, status=FamilyStatus.ACTIVE.value, status_changed_at=now, **values)
        .on_conflict_do_update(index_elements=[FamilyRow.id], set_=values)
    )
    for level in meta.levels:
        level_values = {"b": Decimal(str(level.b)), "time_budget_s": level.time_budget_s}
        db.execute(
            insert(FamilyLevelRow)
            .values(family_id=meta.id, level=level.level, **level_values)
            .on_conflict_do_update(index_elements=[FamilyLevelRow.family_id, FamilyLevelRow.level], set_=level_values)
        )
    db.execute(
        update(VariantRow)
        .where(VariantRow.family_id == meta.id, VariantRow.family_version != meta.version)
        .values(status=VariantStatus.RETIRED.value)
    )
    rows = [_variant_row(v, VariantStatus.ACTIVE) for items in variants.values() for v in items]
    rows += [_variant_row(v, VariantStatus.DEMO) for items in (demo or {}).values() for v in items]
    added = 0
    for start in range(0, len(rows), _CHUNK):
        inserted = db.execute(
            insert(VariantRow)
            .values(rows[start : start + _CHUNK])
            .on_conflict_do_nothing(index_elements=["family_id", "family_version", "level", "seed"])
            .returning(VariantRow.id)
        )
        added += len(inserted.all())
    return added


def write_builds(db: Session, builds: Iterable[FamilyBuild], *, now: datetime) -> dict[str, int]:
    """Записать принятые семейства сборки; непринятые пропускаются (доступность пар считается без них, Арх. 5.2)."""
    families = variants = skipped = 0
    for item in builds:
        if not item.ok:
            skipped += 1
            continue
        families += 1
        variants += write_family(
            db,
            item.family,
            {level.level: level.variants for level in item.levels},
            {level.level: level.demo for level in item.levels},
            now=now,
        )
    return {"families": families, "variants_added": variants, "skipped": skipped}


def write_bank(result: BankBuild, report: dict[str, Any]) -> None:
    """Точка входа команды `bank build` без `--check-only`: записать результат сборки в базу стенда."""
    with session_scope() as db:
        stats = write_builds(db, result.families, now=clock.now(db))
    print(
        f"Записано в базу: семейств {stats['families']}, новых вариантов {stats['variants_added']}; "
        f"не принято и пропущено семейств: {stats['skipped']}"
    )
    if "available_pairs" in report:
        print(f"Доступные пары после сборки: {', '.join(report['available_pairs']) or 'нет'}")


def build_if_empty() -> None:
    """Шаг инициализации стенда (Арх. 13.2): собрать семейства, которых ещё нет в базе (или сменилась версия).

    Сверка с внешними оракулами и пределы времени сюда не входят: это делает `make bank-check` в CI (Арх. 5.3).
    Семейство, не прошедшее линтер, не записывается и выключает только свои пары.
    """
    from app.core.config import get_settings

    with session_scope() as db:
        existing = {row.id: row.version for row in db.execute(select(FamilyRow.id, FamilyRow.version))}
    cfg = get_config()
    discovery = discover()
    for module, error in discovery.errors.items():
        log.warning("банк заданий: семейство %s не загружено: %s", module, error)
    options = BuildOptions(
        secret=get_settings().assessment_secret,
        per_level=cfg.variants_per_level,
        demo_per_level=cfg.demo_variants_per_level,
        skip_oracle=True,
        time_check=False,
    )
    total = {"families": 0, "variants_added": 0, "skipped": 0}
    # Каждое семейство собирается и фиксируется отдельно: прерванная инициализация продолжится с места остановки.
    todo = [f for f in discovery.families if existing.get(f.meta.id) != f.meta.version]
    if not todo:
        log.info("банк заданий: все семейства (%s) уже в базе, сборка пропущена", len(existing))
        return
    for family in todo:
        result = build_bank([family], options)
        with session_scope() as db:
            stats = write_builds(db, result.families, now=clock.now(db))
        for key, value in stats.items():
            total[key] += value
        if stats["skipped"]:
            log.warning("банк заданий: семейство %s не принято линтером и пропущено", family.meta.id)
    log.info(
        "банк заданий собран: семейств %s, вариантов %s, не принято %s",
        total["families"],
        total["variants_added"],
        total["skipped"],
    )
