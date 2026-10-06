"""Симуляция и отчёт валидации тестирования на учебном банке; экспертная сверка (Арх. 12.1, 12.2)."""

# ruff: noqa: E501 — подписи отчёта и длинные проверки читаются лучше в одну строку

from __future__ import annotations

import csv
import json
import random
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.eval.testing import bank as simbank
from app.eval.testing import expert, pathsim, run
from app.modules.reports.schemas import TestingSummary
from app.simulation import generate, item_world, true_grade
from tests.assessment.fake_families._bank import fake_bank

FAKE = "tests.assessment.fake_families._bank:fake_bank"
AT = datetime(2026, 10, 6, tzinfo=UTC)


@pytest.fixture(scope="module")
def bank() -> simbank.SimBank:
    return simbank.load(FAKE)


@pytest.fixture(scope="module")
def report(bank: simbank.SimBank) -> dict:
    return run.build_report(bank, seed=7, n=120, generated_at=AT, v7_sessions=(20, 40, 80))


def test_population_follows_assumptions() -> None:
    people = generate(4000, ["backend", "frontend"], random.Random(1))
    again = generate(4000, ["backend", "frontend"], random.Random(1))
    assert people == again
    thetas = [p.theta_true for p in people]
    mean = sum(thetas) / len(thetas)
    sd = (sum((t - mean) ** 2 for t in thetas) / len(thetas)) ** 0.5
    assert abs(mean - 0.2) < 0.08 and abs(sd - 1.3) < 0.08
    assert sum(1 for p in people if p.specialization == "backend") == 2000
    assert all(p.true_grade == true_grade(p.theta_true) for p in people)
    assert true_grade(-1.6) is None and true_grade(-1.5) == "junior" and true_grade(1.5) == "senior"
    same = sum(1 for p in people if p.true_grade == p.claimed_grade) / len(people)
    assert 0.55 < same < 0.8  # 0.60 плюс обрезка по границам справочника
    assert 0.25 < sum(1 for p in people if p.min_salary is None) / len(people) < 0.35
    assert all(p.work_formats for p in people) and {p.persona for p in people} == {"responsive", "selective", "expensive", "silent"}
    assert all(p.lang_module == "js" for p in people if p.specialization == "frontend")


def test_simulate_path_uses_engine_rules(bank: simbank.SimBank) -> None:
    people = generate(300, ["backend"], random.Random(3))
    world = item_world(bank.families, random.Random(4))
    exact = 0
    for person in people:
        path = pathsim.simulate_path(person, bank, random.Random(f"p:{person.id}"), world=world)
        again = pathsim.simulate_path(person, bank, random.Random(f"p:{person.id}"), world=world)
        assert path == again and 1 <= len(path.sessions) <= 3
        assert path.sessions[0].grade == person.claimed_grade
        for session in path.sessions:
            assert session.length in (14, 20, 26)
            assert len({item.family_id for item in session.items}) == session.length
        if path.grade is not None:
            # Грейд категории — всегда грейд одной из сессий с подтверждающим исходом.
            assert any(s.grade == path.grade and s.outcome.value.startswith("confirmed") for s in path.sessions)
        exact += path.grade == person.true_grade
        seeded = pathsim.to_seed_sessions(path, AT)
        assert len(seeded) == len(path.sessions) and seeded[-1].finished_at == AT
        assert [len(s.items) for s in seeded] == [s.length for s in path.sessions]
    assert exact / len(people) > 0.6
    # Без world путь строится от одного датчика — так его вызывает сид.
    assert pathsim.simulate_path(people[0], bank, random.Random(5)).sessions


def test_report_is_deterministic_and_complete(bank: simbank.SimBank, report: dict) -> None:
    again = run.build_report(bank, seed=7, n=120, generated_at=AT, v7_sessions=(20, 40, 80))
    dump = lambda data: json.dumps(data, ensure_ascii=False, sort_keys=True)  # noqa: E731
    assert dump(report) == dump(again)
    assert dump(run.build_report(bank, seed=8, n=120, generated_at=AT, v7_sessions=(20, 40, 80))) != dump(report)

    for key in ("v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8", "v10"):
        assert report[key]["rows"], key
    metrics = {item["metric"]: item for key in report if key.startswith("v") and "rows" in report[key] for item in report[key]["rows"]}
    # Планки — по границе бутстреп-интервала, а не по точечной оценке.
    accuracy = metrics["v1_accuracy"]
    assert accuracy["bar"] == 0.88 and accuracy["op"] == ">=" and accuracy["met"] == (accuracy["ci"][0] >= 0.88)
    over = metrics["v3_overgrade"]
    assert over["bar"] == 0.09 and over["met"] == (over["ci"][1] <= 0.09)
    assert metrics["v3_below_junior_no_category"]["value"] is not None
    # V5: кривая по числу независимых серий без накопления, без планки; обе ветки накопления.
    assert [p["series"] for p in report["v5"]["series_curve"]] == [1, 2, 4, 8]
    curve = [p["value"] for p in report["v5"]["series_curve"]]
    assert curve == sorted(curve) and all(metrics[f"v5_series_{k}"]["bar"] is None for k in (1, 2, 4, 8))
    assert metrics["v5_three_attempts_05"]["bar"] == 0.10 and metrics["v5_three_attempts_familiar"]["bar"] is None
    assert "v5_three_attempts_05_no_pool" in metrics
    # V6: три намеренно испорченных семейства.
    assert len(report["v6"]["broken"]) == 3 and metrics["v6_broken_in_bottom5"]["bar"] == 3.0
    # V7: кривая исчерпания при 60 и 200 вариантах на уровень, экспозиция по категориям.
    assert {"v7_first_repeat_60", "v7_first_repeat_200", "v7_sessions_with_repeat_60", "v7_max_exposure", "v7_unused_families"} <= set(metrics)
    assert len(report["v7"]["pairs"]) == 12 and report["v3"]["max_same_level_per_candidate"] <= 3
    # V8: оба сдвига, оба устройства банка, справочная линия статичного банка.
    assert {(c["design"], c["shift"]) for c in report["v8"]["curves"]} == {("pools", 0.5), ("pools", 1.0), ("single_family", 0.5), ("single_family", 1.0)}
    assert [p["m"] for p in report["v8"]["curves"][0]["points"]] == [0, 1, 2, 3, 5, 10, 30]
    assert metrics["leak_false_confirm_m5"]["bar"] == 0.15 and metrics["leak_false_confirm_m5_pessimistic"]["bar"] is None
    assert report["v8"]["static_bank"]["value"] == 1.0
    # V9: новые строки чувствительности.
    keys = [item["key"] for item in report["v9"]["table"]]
    assert keys == ["baseline", "slope_low", "slope_high", "b_error", "skill_spread", "omniscient", "narrow", "near_cuts", "drift"]
    assert all(isinstance(item["failed"], list) for item in report["v9"]["table"])
    # V10: оба веса, группы с одним слотом, «близнецы».
    for name in ("v10_all_strong_full", "v10_all_strong_partial", "v10_one_slot_strong_partial", "v10_multi_slot_weak_full", "v10_twins_skills_differ", "v10_twins_band_differ"):
        assert name in metrics, name
    assert metrics["v10_all_strong_any"]["value"] > metrics["v10_all_weak_any"]["value"]

    summary = TestingSummary.model_validate(report["summary"])  # ровно ключи Арх. 9.11: лишний ключ — ошибка
    assert summary.seed == 7 and summary.n == 120 and summary.expert.e1 == "author_only" and summary.expert.e3 == "not_done"
    assert summary.v1_accuracy == metrics["v1_accuracy"]["value"] and summary.leak_false_confirm_m5_pessimistic is not None
    assert report["acceptance"]["total"] == len(report["acceptance"]["bars"]) >= 14
    assert report["meta"]["bank"]["skipped_pairs"] == [] and any("самосогласованность" in text for text in report["not_claimed"])


def test_report_files_and_cli(tmp_path: Path, report: dict, capsys: pytest.CaptureFixture[str]) -> None:
    run.write_report(report, tmp_path)
    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    for heading in ("## V1.", "## V5.", "## V9.", "## V10.", "## Чего мы не заявляем", "## Экспертная сверка E1–E3", "Несбывшиеся планки"):
        assert heading in text
    assert "E1 — оценка автора банка; E2 и E3 не проводились" in text
    for name in ("leak_curve.svg", "stability_by_distance.svg", "exposure.svg", "confusion_flow.svg"):
        svg = (tmp_path / "figures" / name).read_text(encoding="utf-8")
        assert svg.startswith("<svg") and "<title>" in svg
    assert json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))["summary"] == report["summary"]

    args = ["--seed", "3", "--n", "40", "--bank", FAKE, "--quick", "--date", "2026-10-06"]
    assert run.main([*args, "--out", str(tmp_path / "a")]) == 0
    assert run.main([*args, "--out", str(tmp_path / "b")]) == 0
    assert (tmp_path / "a" / "report.json").read_bytes() == (tmp_path / "b" / "report.json").read_bytes()
    assert "планок выполнено" in capsys.readouterr().out


def test_unavailable_pairs_are_skipped_and_named() -> None:
    backend_only = simbank.from_items([f for f in fake_bank() if f.meta.group in {"code", "algo", "ds", "sql", "http", "git", "py", "db", "svc"}])
    assert {spec for spec, _ in backend_only.pairs()} == {"backend"}
    report = run.build_report(backend_only, seed=1, n=40, generated_at=AT, v7_sessions=(10, 20))
    assert "frontend:middle" in report["meta"]["bank"]["skipped_pairs"] and len(report["v7"]["pairs"]) == 3
    with pytest.raises(ValueError, match="нет ни одной доступной пары"):
        run.build_report(simbank.from_items([]), seed=1, n=40, generated_at=AT)


def test_expert_export_and_import(tmp_path: Path, bank: simbank.SimBank, report: dict) -> None:
    out = tmp_path / "expert"
    stats = expert.export_sheets(bank, out, seed=11)
    assert stats == {"levels": 200, "sheets": 40, "samples": 400}
    ratings = list(csv.DictReader((out / "difficulty_ratings.csv").open(encoding="utf-8")))
    assert len(ratings) == 400 and set(ratings[0]) == {"family_id", "level", "expert_id", "b"} and ratings[0]["b"] == ""
    sheets = [json.loads(line) for line in (out / "sheets.jsonl").read_text(encoding="utf-8").splitlines()]
    key = json.loads((out / "sheets_key.json").read_text(encoding="utf-8"))
    assert len(sheets) == 40 and set(key) == {s["sheet_id"] for s in sheets}
    assert sorted(v["true_grade"] for v in key.values()) == sorted(["none", "junior", "middle", "senior"] * 10)
    # Лист слепой: в нём нет ни сложности, ни оценки движка, ни истинного грейда.
    flat = json.dumps(sheets, ensure_ascii=False)
    assert all(word not in flat for word in ('"b"', "theta", "true_grade", "engine_category", "level"))
    assert all(item["task"]["prompt"] and isinstance(item["correct"], bool) for item in sheets[0]["items"])

    # Без оценок: E1 — оценка автора банка, E2 и E3 не проводились.
    empty = expert.import_ratings(out)
    assert (empty["e1"], empty["e2_kappa"], empty["e3"]) == ("author_only", None, "not_done")
    assert "нельзя называть экспертной" in empty["note"]

    author = {(r["family_id"], r["level"]): float(r["b_author"]) for r in csv.DictReader((out / "levels_author.csv").open(encoding="utf-8"))}
    for item in ratings:
        shift = 0.5 if item["expert_id"] == "E2" and item["level"] == "1" else 0.0
        item["b"] = str(author[(item["family_id"], item["level"])] + shift)
    with (out / "difficulty_ratings.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["family_id", "level", "expert_id", "b"])
        writer.writeheader()
        writer.writerows(ratings)
    with (out / "sheet_labels.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sheet_id", "expert_id", "grade"])
        for sheet_id, info in sorted(key.items()):
            writer.writerow([sheet_id, "E1", info["engine_category"]])
            writer.writerow([sheet_id, "E2", info["engine_category"]])
    (out / "pilot.csv").write_text("person_id,known_grade,outcome,theta_hat\np1,middle,confirmed,0.4\n", encoding="utf-8")

    run.write_report(report, tmp_path)
    assert expert.main(["import-ratings", "--dir", str(out)]) == 0
    result = json.loads((out / "expert_results.json").read_text(encoding="utf-8"))
    assert result["e1"] == "done" and result["e2_kappa"] == 1.0 and result["e3"] == "done"
    assert result["e1_details"]["levels"] == 200 and result["e1_details"]["spearman"] > 0.9
    assert result["e1_details"]["mean_abs_diff"] == 0.175 and result["e2_details"]["between_experts_kappa"] == 1.0
    final = list(csv.DictReader((out / "b_final.csv").open(encoding="utf-8")))
    assert len(final) == 200 and all(float(r["b_final"]) * 2 == int(float(r["b_final"]) * 2) for r in final)
    patched = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert TestingSummary.model_validate(patched["summary"]).expert.e1 == "done"
    assert "E1 (сложность уровней): проведена двумя оценщиками" in (tmp_path / "report.md").read_text(encoding="utf-8")
    assert run.load_expert(tmp_path)["e1"] == "done"  # следующий прогон отчёта сохранит итоги сверки
    assert expert.weighted_kappa([0, 1, 2, 3], [0, 1, 2, 3]) == 1.0 and expert.weighted_kappa([0, 0, 3, 3], [3, 3, 0, 0]) < 0
    assert expert.spearman([1, 2, 3, 4], [2, 4, 6, 9]) == pytest.approx(1.0)
