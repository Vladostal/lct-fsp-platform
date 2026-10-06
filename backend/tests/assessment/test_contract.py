"""Контракт семейства: типы, реестр, автообнаружение (Арх. 5.3; приложение A, §2.2–2.4)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from app.modules.assessment.families import DEFAULT_PACKAGE, Discovery, discover, load_family
from app.modules.assessment.families._lib.contract import (
    AnswerSpec,
    Family,
    ItemKind,
    Option,
    canonical_json,
    content_hash,
    default_time_budget,
    guess_probability,
    raw_answer_for,
    variant_payload,
    variant_to_json,
)
from app.modules.assessment.families.registry import REGISTRY, family_meta
from tests.assessment.fake_families import FAKE_SPECS

LEVELS = [(family_id, level.level) for family_id, spec in FAKE_SPECS.items() for level in spec.levels]


def first_variant(family: Family, level: int, start: int = 0):
    """Первый невырожденный вариант уровня, начиная с seed `start`."""
    from app.modules.assessment.families._lib.contract import Reject

    for seed in range(start, start + 500):
        try:
            return family.generate(level, seed)
        except Reject:
            continue
    raise AssertionError("генератор отбрасывает все seed")


def test_fake_families_discovered(fake_discovery: Discovery) -> None:
    assert fake_discovery.errors == {}
    assert sorted(f.meta.id for f in fake_discovery.families) == sorted(FAKE_SPECS)
    assert fake_discovery.get("code.fake_sum").oracle_check is not None
    assert fake_discovery.get("http.fake_status").oracle_check is None


def test_real_package_discovery_does_not_fail() -> None:
    result = discover(DEFAULT_PACKAGE)
    assert all(family.meta.id in REGISTRY for family in result.families)
    assert all(DEFAULT_PACKAGE in module for module in result.errors)


def test_discovery_isolates_broken_modules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "fakepkg_b20"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "_helper.py").write_text("raise RuntimeError('не семейство')\n")
    (package / "code_broken.py").write_text("raise RuntimeError('упал при импорте')\n")
    (package / "code_no_meta.py").write_text("def generate(level, seed): ...\ndef selfcheck(v): return []\n")
    good = (
        "from tests.assessment.fake_families.code_fake_sum import META, generate, selfcheck\n"
        "__all__ = ['META', 'generate', 'selfcheck']\n"
    )
    (package / "code_fake_sum.py").write_text(good)
    (package / "code_wrong_name.py").write_text(good)
    monkeypatch.syspath_prepend(str(tmp_path))

    result = discover("fakepkg_b20")

    assert [family.meta.id for family in result.families] == ["code.fake_sum"]
    assert set(result.errors) == {"fakepkg_b20.code_broken", "fakepkg_b20.code_no_meta", "fakepkg_b20.code_wrong_name"}
    assert "упал при импорте" in result.errors["fakepkg_b20.code_broken"]
    assert "META" in result.errors["fakepkg_b20.code_no_meta"]
    assert "имя файла" in result.errors["fakepkg_b20.code_wrong_name"]


def test_real_package_requires_registry_row() -> None:
    with pytest.raises(ValueError, match="нет в families/registry"):
        load_family("tests.assessment.fake_families.code_fake_sum", require_registry=True)


def test_family_meta_takes_levels_from_registry() -> None:
    meta = family_meta(
        "sql.join_rows", version=3, feature_bounds={1: {"joins": (1, 1)}, 2: {"joins": (1, 2)}, 3: {"joins": (1, 2)}}
    )
    spec = REGISTRY["sql.join_rows"]
    assert (meta.group, meta.kind, meta.skill_tags) == ("sql", ItemKind.NUMERIC_INPUT, ("sql", "sql_joins"))
    assert [level.b for level in meta.levels] == [-1.5, 0.0, 1.0]
    assert [level.time_budget_s for level in meta.levels] == [75, 105, 150]
    assert meta.misconceptions == spec.misconceptions == ("inner_instead_of_left", "no_fanout")
    assert meta.priority == "P0" and meta.specializations == ("backend", "frontend", "fullstack", "data_ml")
    assert meta.level(2).feature_bounds == {"joins": (1, 2)}
    assert family_meta("py.classes_mro", version=1, feature_bounds={1: {}, 2: {}, 3: {}}).specializations == ("*",)


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"version": 1, "feature_bounds": {1: {}}}, ValueError),
        ({"version": 0, "feature_bounds": {1: {}, 2: {}, 3: {}}}, ValueError),
        ({"version": 1, "feature_bounds": {1: {"joins": (2, 1)}, 2: {}, 3: {}}}, ValueError),
        ({"version": 1, "feature_bounds": {1: {}, 2: {}, 3: {}}, "time_budget_s": {4: 60}}, ValueError),
        ({"version": 1, "feature_bounds": {1: {}, 2: {}, 3: {}}, "misconceptions": ("a", "a")}, ValueError),
    ],
)
def test_family_meta_rejects_bad_input(kwargs: dict, error: type[Exception]) -> None:
    with pytest.raises(error):
        family_meta("sql.join_rows", **kwargs)


def test_family_meta_unknown_family() -> None:
    with pytest.raises(KeyError):
        family_meta("sql.no_such_family", version=1, feature_bounds={})


def test_answer_spec_json_by_kind() -> None:
    assert AnswerSpec.numeric(42).to_json() == {
        "value": 42,
        "integer": True,
        "tolerance_abs": 0.0,
        "tolerance_rel": 0.0,
    }
    rounded = AnswerSpec.numeric(0.12345, decimals=2)
    assert (rounded.value, rounded.integer, rounded.tolerance_abs) == (0.12, False, 0.01)
    assert AnswerSpec.numeric(99.5, tolerance_rel=0.02).integer is False
    assert AnswerSpec.text("A C B", mode="tokens").to_json() == {
        "value": "A C B",
        "mode": "tokens",
        "case_sensitive": False,
    }
    assert AnswerSpec.choice("o3").to_json() == {"option_id": "o3"}
    assert AnswerSpec.multi(["o10", "o2", "o2"]).to_json() == {"option_ids": ["o2", "o10"]}
    assert AnswerSpec.line(7).to_json() == {"lines": [7]}
    assert AnswerSpec.blocks(["b2", "b1"], mode="dag", precedence=[("b2", "b1")]).to_json() == {
        "order": ["b2", "b1"],
        "mode": "dag",
        "precedence": [["b2", "b1"]],
    }
    with pytest.raises(TypeError):
        AnswerSpec.numeric(True)
    with pytest.raises(ValueError):
        AnswerSpec.text("x", mode="fuzzy")  # type: ignore[arg-type]


def test_raw_answer_for_matches_api_body() -> None:
    assert raw_answer_for(ItemKind.NUMERIC_INPUT, 42) == {"value": "42"}
    assert raw_answer_for(ItemKind.NUMERIC_INPUT, 0.5) == {"value": "0.5"}
    assert raw_answer_for(ItemKind.NUMERIC_INPUT, 3.0) == {"value": "3"}
    assert raw_answer_for(ItemKind.SINGLE_CHOICE, "o2") == {"option_id": "o2"}
    assert raw_answer_for(ItemKind.MULTI_CHOICE, ("o1", "o4")) == {"option_ids": ["o1", "o4"]}
    assert raw_answer_for(ItemKind.PICK_LINE, 7) == {"line": 7}


def test_helpers() -> None:
    assert [default_time_budget(b) for b in (-2.0, -1.0, -0.5, 0.5, 1.0, 2.0)] == [75, 75, 105, 105, 150, 150]
    assert guess_probability(ItemKind.NUMERIC_INPUT) == 0.0
    assert guess_probability(ItemKind.SINGLE_CHOICE, options=8) == 0.125
    assert guess_probability(ItemKind.MULTI_CHOICE, options=5) == 0.03
    assert guess_probability(ItemKind.PICK_LINE, lines=10) == 0.1


@pytest.mark.parametrize(("family_id", "level"), LEVELS)
def test_generate_is_deterministic_and_hides_answer(
    fake_families: dict[str, Family], family_id: str, level: int
) -> None:
    family = fake_families[family_id]
    variant = first_variant(family, level)
    again = family.generate(level, variant.seed)

    assert canonical_json(variant_to_json(variant)) == canonical_json(variant_to_json(again))
    assert family.selfcheck(variant) == []
    assert (variant.family_id, variant.level, variant.kind) == (family_id, level, family.meta.kind)

    payload = variant_payload(variant)
    assert set(payload) == {"kind", "prompt", "code", "tables", "options", "blocks", "input"}
    text = canonical_json(payload)
    assert "misconception" not in text and "explanation" not in text and variant.explanation not in text
    assert set(variant.misconception_answers) <= set(family.meta.misconceptions)


def test_content_hash_ignores_seed_and_option_order(fake_families: dict[str, Family]) -> None:
    variant = first_variant(fake_families["http.fake_status"], 1)
    assert variant.options is not None
    shuffled = replace(variant, seed=variant.seed + 1, options=tuple(reversed(variant.options)))
    other = replace(variant, options=(*variant.options[:-1], Option(id=variant.options[-1].id, text="418")))
    assert content_hash(variant) == content_hash(shuffled)
    assert content_hash(variant) != content_hash(other)
    assert content_hash(variant) != content_hash(replace(variant, prompt=variant.prompt + " Ещё условие."))
