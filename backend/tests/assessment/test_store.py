"""Запись собранного банка в базу, шаг инициализации и хук старта (Арх. 5.2, 5.3, 13.2)."""

# ruff: noqa: E501 — длинные проверки читаются лучше в одну строку

from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import app.modules.assessment as assessment_module
from app.modules.assessment import repo
from app.modules.assessment.bank import build_if_empty, cli, store
from app.modules.assessment.bank.build import BuildOptions, build_bank
from app.modules.assessment.families import Discovery
from app.modules.assessment.models import FamilyLevelRow, FamilyRow, VariantRow
from app.modules.catalog import service as catalog
from tests.assessment.bankdb import BANK_AT, install_bank

OPTIONS = BuildOptions(secret="test-bank", per_level=20, demo_per_level=3, skip_oracle=True, time_check=False)


def test_write_bank_is_idempotent_and_hides_nothing_needed(db: Session, fake_discovery: Discovery, capsys) -> None:
    result = build_bank(fake_discovery.families, OPTIONS)
    assert result.ok
    store.write_bank(result, {"available_pairs": []})
    assert "Записано в базу: семейств 3" in capsys.readouterr().out
    levels = db.scalar(select(func.count()).select_from(FamilyLevelRow))
    counts = dict(db.execute(select(VariantRow.status, func.count()).group_by(VariantRow.status)).all())
    assert db.scalar(select(func.count()).select_from(FamilyRow)) == 3
    assert counts == {"active": 20 * levels, "demo": 3 * levels}
    row = db.scalars(select(VariantRow).where(VariantRow.family_id == "http.fake_status", VariantRow.status == "active")).first()
    assert row.payload["kind"] == "single_choice" and "answer" not in row.payload and row.answer["option_id"]
    assert float(row.guess) == round(1 / len(row.payload["options"]), 3) and len(row.content_hash) == 64
    assert 0 <= int(row.seed) < 2**64 and row.misconception_answers
    family = db.get(FamilyRow, "code.fake_sum")
    assert (family.status, family.group_code, family.kind, family.priority) == ("active", "code", "numeric_input", "P0")

    # Повторная запись ничего не добавляет; карантин семейства переживает пересборку.
    family.status = "quarantined"
    db.flush()
    assert store.write_builds(db, result.families, now=BANK_AT) == {"families": 3, "variants_added": 0, "skipped": 0}
    assert db.get(FamilyRow, "code.fake_sum").status == "quarantined"

    # Новая версия семейства: прежние варианты получают статус retired, сессии доигрываются на своих.
    old = fake_discovery.get("code.fake_sum")
    bumped = replace(old, meta=replace(old.meta, version=2), generate=lambda level, seed: replace(old.generate(level, seed), family_version=2))
    added = store.write_builds(db, build_bank([bumped], OPTIONS).families, now=BANK_AT)["variants_added"]
    versions = dict(
        db.execute(
            select(VariantRow.family_version, func.count())
            .where(VariantRow.family_id == "code.fake_sum", VariantRow.status == "retired")
            .group_by(VariantRow.family_version)
        ).all()
    )
    assert added > 0 and set(versions) == {1}


def test_rejected_family_is_not_written(db: Session, fake_discovery: Discovery) -> None:
    good = fake_discovery.get("sql.fake_total")
    broken = replace(fake_discovery.get("code.fake_sum"), selfcheck=lambda v: ["ключ неверен"])
    result = build_bank([good, broken], OPTIONS)
    stats = store.write_builds(db, result.families, now=BANK_AT)
    assert (stats["families"], stats["skipped"]) == (1, 1) and stats["variants_added"] > 0
    assert db.get(FamilyRow, "code.fake_sum") is None and db.get(FamilyRow, "sql.fake_total") is not None


def test_build_if_empty_step(db: Session, fake_discovery: Discovery, monkeypatch: pytest.MonkeyPatch, override_settings) -> None:
    monkeypatch.setattr(store, "discover", lambda: fake_discovery)
    monkeypatch.setattr(store, "get_config", lambda: replace_config(per_level=20))
    build_if_empty()
    assert db.scalar(select(func.count()).select_from(FamilyRow)) == 3
    before = db.scalar(select(func.count()).select_from(VariantRow))
    build_if_empty()  # все семейства уже в базе: шаг ничего не делает
    assert db.scalar(select(func.count()).select_from(VariantRow)) == before


def replace_config(per_level: int):
    from app.modules.assessment.config import get_config

    return get_config().model_copy(update={"variants_per_level": per_level})


def test_cli_build_writes_through_store(db: Session, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    code = cli.main(["build", "--package", "tests.assessment.fake_families", "--per-level", "20", "--skip-oracle", "--no-time-check"])
    out = capsys.readouterr().out
    assert code == 0 and "Записано в базу: семейств 3" in out
    assert db.scalar(select(func.count()).select_from(FamilyRow)) == 3


def test_on_startup_publishes_available_pairs(db: Session, catalog_guard: None, override_settings) -> None:
    catalog.publish_availability(set())
    assessment_module.on_startup()
    assert catalog.get_catalog().available_categories == []  # банк пуст — тест «готовится» у всех
    install_bank(db, only_groups={"code", "algo", "ds", "sql", "http", "git", "py", "db", "svc"})
    assessment_module.on_startup()
    assert catalog.get_catalog().available_categories == ["backend:junior", "backend:middle", "backend:senior"]
    assert catalog.specialization("backend").available and not catalog.specialization("frontend").available
    install_bank(db)
    override_settings(disabled_specializations=["data_ml", "fullstack"])
    assert {spec for spec, _ in repo.refresh_availability(db)} == {"backend", "frontend"}
    assert len(assessment_module.ROUTERS) == 2
