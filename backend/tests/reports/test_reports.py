"""`GET /validation/summary`: секции по моделям Арх. 9.11, `null` для отсутствующих файлов."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.reports import service
from app.modules.reports.schemas import ContactSummary, MatchingSummary, TestingSummary

URL = "/api/v1/validation/summary"
META = {"generated_at": "2026-10-06T10:00:00Z", "seed": 7, "n": 400, "versions": {"bank": "1"}}

TESTING = {
    **META,
    "v1_accuracy": 0.91,
    "v2_agreement": 0.8,
    "v3_exact": 0.7,
    "v3_overgrade": 0.02,
    "v4_agreement": None,
    "v5_three_attempts": 0.1,
    "v6_correlation": 0.6,
    "leak_false_confirm_m5": 0.01,
    "leak_false_confirm_m5_pessimistic": 0.03,
    "sessions_to_first_repeat": 12,
    "expert": {"e1": "author_only", "e2_kappa": None, "e3": "not_done"},
}
MATCHING = {
    **META,
    "p10_ours": 0.8,
    "p10_declared": 0.6,
    "p10_random": 0.2,
    "p10_diff_declared": 0.2,
    "p10_diff_ci_low": 0.1,
    "p10_diff_ci_high": 0.3,
    "p10_strength_only": 0.75,
    "manual_pairs": 0,
    "manual_kappa": None,
}
CONTACT = {
    **META,
    "delivered_share": 0.99,
    "reply_in_time_share": 0.7,
    "accept_share": 0.4,
    "needs_filled_share": 0.9,
    "needs_filled_share_no_limits": 0.5,
}


@pytest.fixture
def reports_dir(tmp_path: Path, override_settings) -> Path:
    override_settings(validation_dir=tmp_path)
    service._cache.clear()
    return tmp_path


def write(root: Path, name: str, summary: object, *, raw: str | None = None) -> None:
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "report.json").write_text(raw if raw is not None else json.dumps({"summary": summary, "other": 1}))


def test_all_sections_missing_are_null(client, reports_dir):
    response = client.get(URL)
    assert response.status_code == 200
    assert response.json() == {"testing": None, "matching": None, "contact": None}


def test_sections_from_files(client, reports_dir):
    write(reports_dir, "testing", TESTING)
    write(reports_dir, "matching", MATCHING)
    write(reports_dir, "contact", CONTACT)
    body = client.get(URL).json()
    assert body["testing"]["v1_accuracy"] == 0.91 and body["testing"]["v4_agreement"] is None
    assert body["testing"]["expert"] == {"e1": "author_only", "e2_kappa": None, "e3": "not_done"}
    assert body["matching"]["p10_strength_only"] == 0.75 and body["matching"]["manual_pairs"] == 0
    assert body["contact"]["accept_share"] == 0.4 and body["contact"]["seed"] == 7


def test_only_present_sections_are_filled(client, reports_dir):
    write(reports_dir, "matching", MATCHING)
    body = client.get(URL).json()
    assert body["testing"] is None and body["contact"] is None and body["matching"]["n"] == 400


def test_broken_or_mismatching_file_gives_null(client, reports_dir, caplog):
    write(reports_dir, "testing", None, raw="{не json")
    write(reports_dir, "matching", {**MATCHING, "extra_key": 1})  # лишний ключ: файл расходится с моделью
    write(reports_dir, "contact", None, raw=json.dumps({"no_summary": True}))
    assert client.get(URL).json() == {"testing": None, "matching": None, "contact": None}
    assert "не прочитан" in caplog.text or "нет секции" in caplog.text


def test_file_change_is_picked_up(client, reports_dir):
    write(reports_dir, "contact", CONTACT)
    assert client.get(URL).json()["contact"]["accept_share"] == 0.4
    write(reports_dir, "contact", {**CONTACT, "accept_share": 0.5, "n": 4000})  # размер файла изменился
    assert client.get(URL).json()["contact"]["accept_share"] == 0.5


def test_models_reject_unknown_keys():
    for model, payload in ((TestingSummary, TESTING), (MatchingSummary, MATCHING), (ContactSummary, CONTACT)):
        model.model_validate(payload)
        with pytest.raises(ValueError):
            model.model_validate({**payload, "surprise": 1})


def test_public_endpoint_needs_no_session(client, reports_dir):
    assert client.get(URL).status_code == 200
