"""Валидация подбора: метрики с ручным расчётом, быстрый прогон, ручной слой (Арх. 12.3)."""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path

import pytest

from app.eval.matching import metrics as M
from app.eval.matching import systems as S
from app.eval.matching.__main__ import main
from app.eval.matching.relevance import relevance
from app.eval.matching.world import MAIN_REGIME, REGIMES, build_world
from app.modules.matching.features import FEATURE_FIELDS
from app.modules.reports.schemas import MatchingSummary


def test_metrics_by_hand() -> None:
    rels = [3, 0, 2, 1, 0, 2]
    assert M.precision_at(rels, 5) == pytest.approx(2 / 5) and M.precision_at(rels, 10) == pytest.approx(3 / 10)
    assert M.mrr(rels) == 1.0 and M.mrr([0, 1, 2]) == pytest.approx(1 / 3) and M.mrr([0, 1]) == 0.0
    # DCG = 7/log2(2) + 3/log2(4) + 1/log2(5) + 3/log2(7); идеал для [3, 2, 2, 1] = 7 + 3/log2(3) + 3/2 + 1/log2(5)
    dcg = 7 + 3 / 2 + 1 / 2.321928 + 3 / 2.807355
    ideal = 7 + 3 / 1.584963 + 3 / 2 + 1 / 2.321928
    assert M.ndcg_at(rels, rels, 10) == pytest.approx(dcg / ideal, abs=1e-5)
    assert M.ndcg_at([0, 0], [0, 0]) == 0.0
    assert M.rbo(list("abcde"), list("abcde")) == pytest.approx(1.0)
    assert M.rbo(list("abcde"), list("vwxyz")) == 0.0
    assert 0 < M.rbo(list("abcde"), list("bacde")) < 1
    assert M.gini([1, 1, 1, 1]) == pytest.approx(0.0) and M.gini([0, 0, 0, 4]) == pytest.approx(0.75)
    assert M.weighted_kappa([0, 1, 2, 2], [0, 1, 2, 2]) == pytest.approx(1.0)
    assert M.weighted_kappa([0, 0, 2, 2], [2, 2, 0, 0]) == pytest.approx(-1.0)
    low, high = M.bootstrap_ci([0.5] * 20)
    assert low == high == pytest.approx(0.5)
    assert M.median([3, 1, 2]) == 2 and M.median([1, 2, 3, 4]) == 2.5


def test_relevance_scale() -> None:
    base = {"same_specialization": True, "cut": 0.0, "width": 1.5, "must_skills": ["a", "b"], "nice_skills": ["c"]}
    assert relevance(theta_true=0.5, skills={"a": 2, "b": 3, "c": 1}, **base) == 3
    assert relevance(theta_true=0.5, skills={"a": 2, "b": 3}, **base) == 2  # желательных нет
    assert relevance(theta_true=0.5, skills={"a": 2, "b": 1}, **base) == 1  # половина обязательных
    assert relevance(theta_true=0.5, skills={"a": 1}, **base) == 0
    assert relevance(theta_true=-2.0, skills={"a": 3, "b": 3, "c": 3}, **base) == 0
    assert relevance(theta_true=0.5, skills={"a": 3, "b": 3, "c": 3}, **{**base, "same_specialization": False}) == 0


def test_world_is_deterministic_and_scorer_sees_only_features() -> None:
    first, second = build_world(11, REGIMES[MAIN_REGIME]), build_world(11, REGIMES[MAIN_REGIME])
    assert [item.features for item in first.observed] == [item.features for item in second.observed]
    # Специализация без теста: в пуле все 400 человек, у каждого грейд заявлен и оценки теста нет.
    assert len(first.declared_pool) == 400
    assert all(item.features.basis == "declared" and item.features.theta is None for item in first.declared_pool)
    assert all(item.features.basis == "test" and item.features.experience_years is not None for item in first.observed)
    assert [need.query for need in first.needs] == [need.query for need in second.needs]
    assert len(first.latents) == 400 and len(first.needs) == 30 and 200 < len(first.observed) <= 400
    latent_only = {"theta_true", "skills", "min_salary", "name", "gender", "birth_year"}
    assert not latent_only & set(FEATURE_FIELDS)
    case = S.make_cases(first)[0]
    assert S.ids(S.ranked(case)) == S.ids(S.ranked(case))
    oracle = [case.rels[cid] for cid in S.oracle_order(case, S.ranked(case))]
    exact = [item for item in S.ranked(case) if item.key[0] == 0]
    assert oracle[: len(exact)] == sorted(oracle[: len(exact)], reverse=True)


def test_quick_run_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    started = time.monotonic()
    assert main(["run", "--out", str(tmp_path), "--quick"]) == 0
    assert time.monotonic() - started < 30
    printed = capsys.readouterr().out
    orders = ("порядок версии 1.0", "порядок версии 1.1", "порядок версии 1.2")
    for marker in ("Критерии успеха", "только сила профиля", *orders, "Близнецы"):
        assert marker in printed
    assert "Накрутка заявленным" in printed and "summary:" in printed

    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    summary = MatchingSummary.model_validate(report["summary"])
    assert set(report["summary"]) == set(MatchingSummary.model_fields)
    assert summary.p10_strength_only is not None and summary.manual_pairs == 0 and summary.n == 90
    assert {"strength_band_diff_share", "confirmed_band_diff_share", "median_position_shift_current"} <= set(
        report["twins"]
    )
    assert "median_position_shift_v11" in report["twins"]
    assert {"order_v10", "order_v11", "order_v12", "strength3"} <= set(report["ablations"])
    # Накрутка заявленным: прежний порядок «сила первой» устойчивее к ней, но по релевантности в топ-10 уступает
    # действующему даже после накрутки; бейзлайн заявленного стека страдает от неё сильнее нашего порядка.
    stuffing = report["stuffing"]
    assert stuffing["order_v12"]["displaced"] == 0
    assert stuffing["order_v12"]["entered"] < stuffing["ours"]["entered"]
    # Ключи у накрутивших: подтверждённое покрытие накрутка не меняет никогда; накрутка одной силы (стаж и число
    # навыков) не меняет ни одного из ключей 1–2; полоса силы от добавленных навыков растёт не больше чем на 3.
    keys = stuffing["keys"]
    assert keys["key_confirmed_changed_share"] == 0 and keys["profile_only_keys_changed_share"] == 0
    assert 0 <= keys["strength_band_gain"] == stuffing["strength_band_gain"] and keys["strength_band_gain_max"] <= 3
    assert {"no_declared", "match2_strength", "no_fsp"} <= set(report["ablations"])
    names = [row["name"] for row in report["criteria"]]
    assert any("match-2" in name for name in names) and any("ключи 1–2" in name for name in names)
    block = report["declared_basis"]
    assert block["status"] == "измерено" and block["n"] == 90 and block["pool"] == 1200
    # Без теста подбор всё ещё заметно лучше случайного порядка в категории.
    assert block["diff_random"]["ci_low"] > 0
    assert {"W_EXPERIENCE ×0.8", "W_SKILLS ×1.2"} <= {row["name"] for row in report["sensitivity"]}
    assert stuffing["ours"]["p10_stuffed"] > stuffing["order_v12"]["p10"]
    assert stuffing["ours"]["p10_stuffed"] >= stuffing["declared"]["p10_stuffed"]
    assert stuffing["declared"]["entered"] > stuffing["ours"]["entered"]
    # Главный критерий: порядок по соответствию потребности превосходит бейзлайн заявленного стека.
    assert report["criteria"][0]["ok"] is True and summary.p10_diff_ci_low > 0
    assert report["fairness"]["feasible_format_at_10"] == 1.0
    assert report["manual"]["status"] == "не проводился"
    assert any("только сила" in row["name"] for row in report["criteria"])
    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "Ручной слой не проводился" in text and "Угрозы валидности" in text and "Критерии успеха" in text
    assert "Специализации без теста" in text and "match-3" in text


def test_export_pairs_and_import_labels(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["export-pairs", "--out", str(tmp_path), "--seed", "11"]) == 0
    manual = tmp_path / "manual"
    with (manual / "pairs.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert 100 <= len(rows) <= 360
    # Разметчик не видит позицию, полосу совпадения, доводы и название системы.
    assert not {"position", "fit_band", "system", "risk", "reasons"} & set(rows[0])
    for name, shift in (("labels_a.csv", 0), ("labels_b.csv", 1)):
        with (tmp_path / name).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["pair_id", "label"])
            for index, row in enumerate(rows):
                writer.writerow([row["pair_id"], (index + (shift if index % 7 == 0 else 0)) % 3])
    args = ["import-labels", "--out", str(tmp_path), "--a", str(tmp_path / "labels_a.csv")]
    assert main([*args, "--b", str(tmp_path / "labels_b.csv")]) == 0
    result = json.loads((manual / "manual.json").read_text(encoding="utf-8"))
    assert result["pairs"] == len(rows) and result["raters"] == 2 and 0.4 < result["kappa"] < 1
    assert set(result["p10"]) == {"ours", "declared", "tfidf"} and (manual / "FROZEN.sha256").exists()

    assert main(["run", "--out", str(tmp_path), "--quick", "--seeds", "11-11"]) == 0
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["summary"]["manual_pairs"] == len(rows) and report["manual"]["status"] == "проведён"
    (manual / "pairs.csv").write_text("pair_id\n", encoding="utf-8")
    assert main(["run", "--out", str(tmp_path), "--quick", "--seeds", "11-11"]) == 0
    changed = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert changed["manual"]["status"] == "набор изменён после заморозки"
    capsys.readouterr()
