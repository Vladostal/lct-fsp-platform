"""Отчёт `make eval-contact`: состав разделов и ключи секции `summary` (Арх. 12.4, 9.11)."""

from __future__ import annotations

import json

from app.eval.contact import sim
from app.eval.contact.__main__ import main
from app.modules.reports.schemas import ContactSummary


def test_eval_contact_report(tmp_path, capsys):
    assert main(["--out", str(tmp_path), "--runs", "4", "--sens-runs", "1", "--n", "300", "--seed", "7"]) == 0
    printed = capsys.readouterr().out
    for heading in (
        "## Сравнение режимов",
        "## Чувствительность",
        "## Сверка вилки",
        "## Адаптивный перебор",
        "## summary",
    ):
        assert heading in printed
    for line in (
        "Доля недоставленных в целом",
        "сильнейшая четверть по силе профиля",
        "Доля слото-дней, занятых недоставленными",
        "Доля пересмотров после недоставки, приведших к доставке",
        "Адаптивный перебор: k = 1",
        "k = 3",
        "k = 5",
        "При `ALPHA = 0`",
        "Feasible@10",
    ):
        assert line in printed, line
    document = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    summary = ContactSummary.model_validate(document["summary"])  # лишние и недостающие ключи — ошибка
    assert summary.n == 300 and summary.seed == 7 and summary.delivered_share is not None
    assert set(document["modes"]) == {"A", "B", "C"} and len(document["sensitivity"]) == 12
    assert (tmp_path / "report.md").read_text(encoding="utf-8").startswith("# Валидация механики контакта")


def test_adaptive_search_cost_and_revision_pass():
    costs = {cost.accounts: cost for cost in sim.attack_costs()}
    # На лестнице из 30 гипотез двоичному поиску нужно не больше пяти проб.
    assert all(cost.max_probes == 5 for cost in costs.values())
    # Один аккаунт получает не больше двух бит за 30 дней: точное восстановление занимает месяцы.
    assert costs[1].max_days >= 60 and costs[1].same_day_share == 0
    # Пять аккаунтов восстанавливают минимум за день — остаточный риск, названный в Арх. 4.6.
    assert costs[5].max_days == 0 and costs[5].same_day_share == 1
    assert sim.revision_pass_blocked() is True


def test_modes_share_population_and_limits_reduce_volume():
    a = sim.run_once(11, "A", 0.3, 0.1, 300)
    c_mode = sim.run_once(11, "C", 0.3, 0.1, 300)
    assert a.feasible_at_10 == c_mode.feasible_at_10  # одна популяция и одни подборки
    assert a.sent + a.bounced > c_mode.sent + c_mode.bounced
    assert c_mode.accepted + c_mode.declined + c_mode.expired <= c_mode.sent
