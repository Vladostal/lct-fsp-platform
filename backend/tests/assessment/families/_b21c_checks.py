"""Общие проверки тестов семейств пакета B21c: приёмка уровней, детерминизм, оракул ловит подмену ключа."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.modules.assessment.bank.build import BuildOptions, build_family
from app.modules.assessment.families import load_family
from app.modules.assessment.families._lib.contract import (
    AnswerSpec,
    Family,
    ItemKind,
    OracleUnavailable,
    Variant,
    variant_to_json,
)


def family(family_id: str) -> Family:
    """Загрузить боевое семейство по идентификатору реестра."""
    return load_family(f"app.modules.assessment.families.{family_id.replace('.', '_')}")


def assert_accepted(family_id: str, per_level: int = 60) -> None:
    """Приёмка как в `bank build --check-only`: уровень набирает `per_level` вариантов при браке не выше 50 %.

    Для семейств с настоящим git и asyncio в тестах берётся 20 вариантов (минимум для правила L09): полные 60
    проверяет `make bank-check`, иначе тесты идут минутами.
    """
    fam = family(family_id)
    result = build_family(fam, BuildOptions(secret="b21c-test-secret", per_level=per_level, time_check=False))
    failed = [lv.level for lv in result.levels if not lv.ok]
    assert result.ok, f"{family_id}: не приняты уровни {failed}; ошибки {result.errors}"
    assert [len(lv.variants) for lv in result.levels] == [per_level] * len(fam.meta.levels)


def assert_deterministic(family_id: str, seeds: range = range(1, 8)) -> None:
    """Повторный `generate` даёт тот же JSON; selfcheck и ответы моделей ошибок в порядке."""
    fam = family(family_id)
    checked = 0
    for level in (lv.level for lv in fam.meta.levels):
        for seed in seeds:
            try:
                first = fam.generate(level, seed)
            except Exception as exc:  # Reject: вырожденный seed
                assert type(exc).__name__ == "Reject"
                continue
            assert variant_to_json(first) == variant_to_json(fam.generate(level, seed))
            assert fam.selfcheck(first) == []
            assert first.misconception_answers
            assert set(first.misconception_answers) <= set(fam.meta.misconceptions)
            checked += 1
    assert checked >= 10


def tampered(v: Variant) -> Variant:
    """Вариант с неверным ключом: по виду задания меняется значение ответа."""
    spec = v.answer
    if spec.kind is ItemKind.NUMERIC_INPUT:
        bad = AnswerSpec.numeric(int(spec.value) + 1)  # type: ignore[arg-type]
    elif spec.kind is ItemKind.TEXT_INPUT:
        bad = AnswerSpec.text(f"{spec.value} zzz", mode="tokens")
    elif spec.kind is ItemKind.MULTI_CHOICE:
        ids = [o.id for o in v.options or ()]
        wrong = [i for i in ids if i not in spec.option_ids]
        bad = AnswerSpec.multi([*spec.option_ids, wrong[0]] if wrong else spec.option_ids[1:])
    else:
        other = next(o.id for o in v.options or () if o.id != spec.option_id)
        bad = AnswerSpec.choice(other)
    return replace(v, answer=bad)


def assert_oracle_detects_tamper(family_id: str, levels: tuple[int, ...] = (1, 2, 3)) -> None:
    """Оракул принимает верный ключ и отвергает подменённый на каждом уровне."""
    fam = family(family_id)
    assert fam.oracle_check is not None
    for level in levels:
        seed = 11
        while True:
            try:
                v = fam.generate(level, seed)
                break
            except Exception:
                seed += 1
        try:
            assert fam.oracle_check(v) == []
            assert fam.oracle_check(tampered(v)) != []
        except OracleUnavailable:
            pytest.skip("оракул недоступен")
