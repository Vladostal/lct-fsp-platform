"""Сборка банка в памяти и команда `bank build --check-only` (Арх. 5.3; приложение A, §2.7)."""

from __future__ import annotations

import hashlib
import hmac
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from app.modules.assessment.bank import build as build_module
from app.modules.assessment.bank.build import BuildOptions, build_bank, build_family, variant_seed
from app.modules.assessment.bank.cli import main, parser
from app.modules.assessment.families import Discovery
from app.modules.assessment.families._lib.contract import (
    Family,
    OracleUnavailable,
    Reject,
    Variant,
    canonical_json,
    variant_to_json,
)
from tests.assessment.fake_families import FAKE_SPECS, PACKAGE
from tests.assessment.fake_families._bank import fake_bank

BACKEND_DIR = Path(__file__).resolve().parents[2]
OPTIONS = BuildOptions(secret="test-secret", per_level=20, time_check=False)


def dump(result: object) -> str:
    return canonical_json(
        [
            [variant_to_json(v) for level in item.levels for v in (*level.variants, *level.demo)]
            for item in result.families
        ]  # type: ignore[attr-defined]
    )


def test_variant_seed_formula() -> None:
    digest = hmac.new(b"secret", b"variant:sql.join_rows:2:3:7", hashlib.sha256).digest()
    assert variant_seed("secret", "sql.join_rows", 2, 3, 7) == int.from_bytes(digest[:8], "big")
    demo = hmac.new(b"secret", b"demo:variant:sql.join_rows:2:3:7", hashlib.sha256).digest()
    assert variant_seed("secret", "sql.join_rows", 2, 3, 7, demo=True) == int.from_bytes(demo[:8], "big")
    assert variant_seed("other", "sql.join_rows", 2, 3, 7) != variant_seed("secret", "sql.join_rows", 2, 3, 7)


def test_fake_families_build_with_default_quota(fake_discovery: Discovery) -> None:
    result = build_bank(fake_discovery.families, replace(OPTIONS, per_level=60))
    assert result.ok and len(result.families) == 3
    for item in result.families:
        for level in item.levels:
            assert (level.accepted, len(level.demo), level.errors) == (60, 3, [])
            assert level.reject_share <= 0.5
            seeds = [v.seed for v in (*level.variants, *level.demo)]
            assert len(set(seeds)) == len(seeds)
            report = level.to_json()
            assert report["accepted"] == 60 and report["attempts"] == 60 + sum(report["rejects"].values())


def test_build_is_deterministic_and_depends_on_secret(fake_discovery: Discovery) -> None:
    first = build_bank(fake_discovery.families, OPTIONS)
    second = build_bank(fake_discovery.families, OPTIONS)
    other = build_bank(fake_discovery.families, replace(OPTIONS, secret="another"))
    assert dump(first) == dump(second)
    assert dump(first) != dump(other)


def test_only_filter(fake_discovery: Discovery) -> None:
    result = build_bank(fake_discovery.families, OPTIONS, only=["sql.fake_total"])
    assert [item.family.meta.id for item in result.families] == ["sql.fake_total"]


def test_reject_share_fails_level(fake_families: dict[str, Family]) -> None:
    source = fake_families["http.fake_status"]

    def picky(level: int, seed: int) -> Variant:
        if seed % 3:
            raise Reject("two_of_three")
        return source.generate(level, seed)

    result = build_family(replace(source, generate=picky), OPTIONS)
    assert not result.ok
    level = result.levels[0]
    assert level.accepted == 20 and level.rejects["reject:two_of_three"] > 20
    assert any("брак" in error for error in level.errors)
    assert level.examples["reject:two_of_three"][0].startswith("seed=")


def test_generator_errors_are_counted_not_raised(fake_families: dict[str, Family]) -> None:
    source = fake_families["http.fake_status"]

    def crash(level: int, seed: int) -> Variant:
        raise ZeroDivisionError("деление на ноль")

    result = build_family(replace(source, generate=crash), OPTIONS)
    level = result.levels[0]
    assert not result.ok and level.accepted == 0 and level.attempts == 100
    assert level.rejects == {"error:ZeroDivisionError": 100}
    assert any("принято 0 из 20" in error for error in level.errors)
    assert any("предпросмотра" in error for error in level.errors)


def test_lint_rejects_are_reported_by_rule(fake_families: dict[str, Family]) -> None:
    source = fake_families["code.fake_sum"]
    result = build_family(replace(source, selfcheck=lambda v: ["ключ неверен"]), OPTIONS)
    assert not result.ok and set(result.levels[0].rejects) == {"L02"}
    assert "ключ неверен" in result.levels[0].examples["L02"][0]

    def constant(level: int, seed: int) -> Variant:
        return replace(source.generate(level, 3), seed=seed)

    duplicates = build_family(replace(source, generate=constant, selfcheck=lambda v: []), OPTIONS)
    assert duplicates.levels[0].accepted == 1 and set(duplicates.levels[0].rejects) == {"L05"}


def test_oracle_mismatch_unavailable_and_skip(fake_families: dict[str, Family]) -> None:
    source = fake_families["code.fake_sum"]
    mismatch = build_family(replace(source, oracle_check=lambda v: ["оракул дал другое"]), OPTIONS)
    assert not mismatch.ok and set(mismatch.levels[0].rejects) == {"oracle"}

    def missing(v: Variant) -> list[str]:
        raise OracleUnavailable("нет git")

    unavailable = build_family(replace(source, oracle_check=missing), OPTIONS)
    assert not unavailable.ok and unavailable.levels[0].accepted == 20
    assert any("оракул недоступен" in error for error in unavailable.levels[0].errors)
    assert build_family(replace(source, oracle_check=missing), replace(OPTIONS, skip_oracle=True)).ok


def test_registry_family_without_required_oracle_check() -> None:
    family = next(f for f in fake_bank() if f.meta.id == "git.log_reach")
    assert family.oracle_check is None
    result = build_family(family, OPTIONS)
    assert not result.ok and "oracle_check" in result.errors[0]
    assert all(level.ok for level in result.levels)
    assert build_family(family, replace(OPTIONS, skip_oracle=True)).ok
    assert result.to_json()["core_p0"] is True and result.to_json()["oracle"] == "git"


def test_time_limits(fake_families: dict[str, Family], monkeypatch: pytest.MonkeyPatch) -> None:
    source = fake_families["http.fake_status"]
    monkeypatch.setattr(build_module, "MAX_CALL_MS", -1.0)
    slow = build_family(source, replace(OPTIONS, time_check=True))
    assert not slow.ok and set(slow.levels[0].rejects) == {"time"}
    assert build_family(source, OPTIONS).ok
    monkeypatch.setattr(build_module, "MAX_CALL_MS", 200.0)
    monkeypatch.setattr(build_module, "MAX_MEAN_MS", -1.0)
    mean = build_family(source, replace(OPTIONS, time_check=True))
    assert any("в среднем" in error for error in mean.levels[0].errors)


def test_cli_check_only_report_and_samples(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    report_path, samples = tmp_path / "bank_report.json", tmp_path / "samples"
    args = ["build", "--check-only", "--package", PACKAGE, "--per-level", "12", "--no-time-check"]
    code = main([*args, "--report", str(report_path), "--samples", str(samples)])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "Семейств принято: 3 из 3" in out and "ГОДНО code.fake_sum v1" in out

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is True and report["check_only"] is True and report["per_level"] == 12
    assert [family["id"] for family in report["families"]] == sorted(FAKE_SPECS)
    level = report["families"][0]["levels"][0]
    assert {"level", "b", "attempts", "accepted", "demo", "reject_share", "rejects", "max_ms", "ok"} <= set(level)
    assert report["available_pairs"] == [] and report["discovery_errors"] == {}

    files = sorted(path.name for path in samples.iterdir())
    assert files == [
        f"{name}_L{n}.json" for name in ("code_fake_sum", "http_fake_status", "sql_fake_total") for n in (1, 2)
    ]
    sample = json.loads((samples / "sql_fake_total_L1.json").read_text(encoding="utf-8"))
    assert len(sample) == 10 and {"payload", "answer", "explanation", "misconception_answers"} <= set(sample[0])


def test_cli_single_family_and_unknown(capsys: pytest.CaptureFixture[str]) -> None:
    base = ["build", "--check-only", "--package", PACKAGE, "--per-level", "8", "--no-time-check"]
    assert main([*base, "--family", "http.fake_status"]) == 0
    out = capsys.readouterr().out
    assert "http.fake_status" in out and "code.fake_sum" not in out and "Доступные пары" not in out
    assert main([*base, "--family", "http.no_such"]) == 1
    assert "не найдены" in capsys.readouterr().out
    assert main(["build", "--check-only", "--per-level", "0"]) == 2


def test_cli_interface_is_stable() -> None:
    args = parser().parse_args(["build", "--per-level", "60", "--family", "sql.join_rows", "--check-only"])
    assert (args.command, args.per_level, args.family, args.check_only) == ("build", 60, ["sql.join_rows"], True)
    defaults = parser().parse_args(["build"])
    assert (defaults.per_level, defaults.family, defaults.check_only) == (None, None, False)
    assert defaults.package == "app.modules.assessment.families"


def test_cli_core_command(capsys: pytest.CaptureFixture[str], min_pool_3: None) -> None:
    assert main(["core"]) == 0
    out = capsys.readouterr().out
    assert "Ядро P0 для backend: 31 семейств" in out and "Совпадает с CORE_P0" in out
    assert main(["core", "--specialization", "frontend"]) == 0
    assert "Сверх ядра P0 для frontend нужно 9" in capsys.readouterr().out


def test_command_runs_as_module() -> None:
    """Команда запускается так, как её запускают авторы семейств: `python -m ...` из каталога backend."""
    done = subprocess.run(
        [sys.executable, "-m", "app.modules.assessment.bank", "build", "--check-only", "--package", PACKAGE,
         "--family", "code.fake_sum", "--per-level", "10"],
        cwd=BACKEND_DIR, capture_output=True, text=True, timeout=120, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stdout + done.stderr
    assert "ГОДНО code.fake_sum v1" in done.stdout
