"""Запуск: `python -m app.eval.contact --out docs/validation/contact [--runs 200] [--seed 20261005] [--quick]`.

Печатает сравнение режимов, чувствительность, блок сверки вилки, строку «адаптивный перебор» и секцию `summary`
(ключи `ContactSummary`, Арх. 9.11); пишет `report.md` и `report.json`.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.eval.contact import sim
from app.modules.contact import constants as c

ALPHAS = (0.0, 0.15, 0.3, 0.6)
SILENT_SHARES = (0.05, 0.10, 0.20)
DEFAULT_ALPHA = 0.3
DEFAULT_SILENT = 0.10


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f} %"


def _num(value: float | None) -> str:
    return "—" if value is None else f"{value:g}"


def _table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def build(seed: int, runs: int, sens_runs: int, n: int) -> tuple[str, dict[str, Any]]:
    """Собрать текст отчёта и данные `report.json`."""
    main = sim.compare(seed, runs, DEFAULT_ALPHA, DEFAULT_SILENT, n)
    a, cc = main["A"], main["B"]

    parts: list[str] = [
        "# Валидация механики контакта («Приглашение с возвратом»)",
        "",
        f"Версия правил: {c.RULES_VERSION} · начальное значение датчика: {seed} · прогонов: {runs} · "
        f"кандидатов в популяции: {n} · работодателей: {sim.EMPLOYERS} · горизонт: {sim.HORIZON_DAYS} суток.",
        "",
        "Это сравнение режимов при заданной модели поведения, а не доказательство. Допущения: `ALPHA = "
        f"{DEFAULT_ALPHA}` — падение внимания кандидата с числом неотвеченных приглашений; доли персон и вероятности "
        "ответа в срок заданы моделью; константы механики (Арх. 4.3) не калиброваны. Популяция строится в самом "
        "пакете валидации по правилам Арх. 12.1 (общий модуль `app.simulation` на момент расчёта отсутствовал). "
        "Сверка вилки, суточный лимит, пересмотр и решения персон считаются боевыми функциями `contact/rules.py`.",
        "",
        "## Сравнение режимов",
        "",
        _table(
            ["Показатель", *(sim.MODE_LABELS[m] for m in sim.MODES)],
            [
                ["Попыток отправки на прогон", *(_num(round(main[m].invitations, 1)) for m in sim.MODES)],
                ["Доля доставленных", *(_pct(main[m].delivered_share) for m in sim.MODES)],
                ["Доля ответов в срок", *(_pct(main[m].reply_in_time_share) for m in sim.MODES)],
                ["Доля согласий", *(_pct(main[m].accept_share) for m in sim.MODES)],
                ["Медиана времени до ответа, ч", *(_num(main[m].median_response_hours) for m in sim.MODES)],
                ["Охват кандидатов", *(_pct(main[m].coverage) for m in sim.MODES)],
                ["Концентрация (Джини)", *(_num(main[m].gini) for m in sim.MODES)],
                ["Потребностей с тремя согласиями", *(_pct(main[m].needs_filled_share) for m in sim.MODES)],
                [
                    "Медиана суток до первого согласия",
                    *(_num(main[m].median_days_to_first_accept) for m in sim.MODES),
                ],
                ["Автопауз на прогон", *(_num(main[m].auto_pauses) for m in sim.MODES)],
            ],
        ),
        "",
        f"`Feasible@10` (доля топ-10 подборки, которым приглашение с вилкой потребности было бы доставлено; считается "
        f"офлайн по латентным минимумам, агрегатом): {_pct(cc.feasible_at_10)}. При вилке на уровне медианы категории: "
        f"{_pct(cc.feasible_at_10_median)} — ожидаемый коридор проверки сида 75–90 %: "
        f"{'в коридоре' if 0.75 <= cc.feasible_at_10_median <= 0.90 else 'вне коридора'}.",
        "",
    ]

    # --- чувствительность ---------------------------------------------------------------------------------------
    sens_rows: list[list[str]] = []
    sens_data: list[dict[str, Any]] = []
    order_kept = 0
    zero_alpha_note: list[str] = []
    for alpha in ALPHAS:
        for silent in SILENT_SHARES:
            result = sim.compare(seed, sens_runs, alpha, silent, n)
            reply = {m: result[m].reply_in_time_share or 0.0 for m in sim.MODES}
            filled = {m: result[m].needs_filled_share for m in sim.MODES}
            kept = reply["B"] >= reply["A"]
            order_kept += kept
            sens_rows.append(
                [
                    f"{alpha:g}",
                    _pct(silent),
                    *(_pct(reply[m]) for m in sim.MODES),
                    *(_pct(filled[m]) for m in sim.MODES),
                    *(_num(result[m].median_days_to_first_accept) for m in sim.MODES),
                    "да" if kept else "нет",
                ]
            )
            sens_data.append(
                {
                    "alpha": alpha,
                    "silent_share": silent,
                    "order_kept": kept,
                    **{m: asdict(result[m]) for m in sim.MODES},
                }
            )
            if alpha == 0.0:
                zero_alpha_note.append(
                    f"молчащих {_pct(silent)}: потребностей с тремя согласиями A {_pct(filled['A'])} → B "
                    f"{_pct(filled['B'])}, суток до первого согласия A "
                    f"{_num(result['A'].median_days_to_first_accept)} → B "
                    f"{_num(result['B'].median_days_to_first_accept)}"
                )
    parts += [
        "## Чувствительность",
        "",
        f"По {sens_runs} прогонов на ячейку. Порядок режимов по доле ответов в срок (B ≥ A) сохраняется в "
        f"{order_kept} из {len(sens_rows)} ячеек.",
        "",
        _table(
            [
                "ALPHA",
                "молчащих",
                "ответ в срок A",
                "B",
                "три согласия A",
                "B",
                "суток до согласия A",
                "B",
                "порядок B ≥ A",
            ],
            sens_rows,
        ),
        "",
        "При `ALPHA = 0` внимание кандидата от числа приглашений не зависит, и лимиты могут только снизить "
        "пропускную способность: " + "; ".join(zero_alpha_note) + ".",
        "",
    ]

    # --- сверка вилки -----------------------------------------------------------------------------------------
    quartiles = ["слабейшая четверть", "вторая", "третья", "сильнейшая четверть"]
    parts += [
        "## Сверка вилки",
        "",
        "У кандидатов популяции есть скрытый минимум, работодатели называют «от» своей потребности, отправка "
        "проходит боевую `rules.salary_ok`. Режим B.",
        "",
        _table(
            ["Показатель", "Значение"],
            [
                ["Доля недоставленных в целом", _pct(None if cc.delivered_share is None else 1 - cc.delivered_share)],
                *(
                    [f"Доля недоставленных: {quartiles[q]} по силе профиля", _pct(cc.bounced_share_by_quartile[q])]
                    for q in range(4)
                ),
                ["Доля пересмотров после недоставки, приведших к доставке", _pct(cc.revision_success_share)],
            ],
        ),
        "",
        "Прочерк в четверти означает, что кандидатам этой четверти приглашения не отправлялись: подборки строятся "
        "по силе профиля.",
        "",
    ]

    # --- адаптивный перебор -------------------------------------------------------------------------------------
    costs = sim.attack_costs()
    pass_blocked = sim.revision_pass_blocked()
    parts += [
        "## Адаптивный перебор",
        "",
        "Атакующий с `k` аккаунтами ищет минимум одного кандидата двоичным поиском по лестнице (29 ступеней и "
        "«не задан») с боевыми правилами: у пары две сверки за 30 дней (исходная отправка и один пересмотр только "
        "после недоставки и только с большей нижней границей), каждая проба входит в суточный лимит. "
        "Планки нет: это измеренная стоимость атаки по всем 30 гипотезам.",
        "",
        _table(
            [
                "Аккаунтов",
                "Проб: среднее / максимум",
                "Аккаунтов использовано",
                "Суток: среднее / максимум",
                "За один день",
            ],
            [
                [
                    str(cost.accounts),
                    f"{cost.mean_probes:g} / {cost.max_probes}",
                    f"{cost.mean_accounts_used:g}",
                    f"{cost.mean_days:g} / {cost.max_days}",
                    _pct(cost.same_day_share),
                ]
                for cost in costs
            ],
        ),
        "",
        "Адаптивный перебор: "
        + "; ".join(
            f"k = {cost.accounts} — проб {cost.mean_probes:g}, аккаунтов {cost.mean_accounts_used:g}, "
            f"суток {cost.mean_days:g} (максимум {cost.max_days})"
            for cost in costs
        )
        + ".",
        "",
        "«Пропуск» от приглашения одному кандидату к другому (пересмотр с чужим `revises_id`): "
        + ("отклоняется боевой `rules.same_pair`." if pass_blocked else "НЕ отклоняется — ошибка правил."),
        "",
    ]

    summary = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "seed": seed,
        "n": n,
        "versions": {"contact_rules": c.RULES_VERSION},
        "delivered_share": cc.delivered_share,
        "reply_in_time_share": cc.reply_in_time_share,
        "accept_share": cc.accept_share,
        "needs_filled_share": cc.needs_filled_share,
        "needs_filled_share_no_limits": a.needs_filled_share,
    }
    parts += [
        "## summary",
        "",
        _table(["Ключ", "Значение"], [[key, str(value)] for key, value in summary.items()]),
        "",
    ]
    document = {
        "summary": summary,
        "params": {
            "runs": runs,
            "sens_runs": sens_runs,
            "alpha": DEFAULT_ALPHA,
            "silent_share": DEFAULT_SILENT,
            "employers": sim.EMPLOYERS,
            "horizon_days": sim.HORIZON_DAYS,
        },
        "modes": {mode: asdict(main[mode]) for mode in sim.MODES},
        "sensitivity": sens_data,
        "salary_check": {
            "bounced_share": None if cc.delivered_share is None else round(1 - cc.delivered_share, 4),
            "bounced_share_by_strength_quartile": cc.bounced_share_by_quartile,
            "revision_success_share": cc.revision_success_share,
            "feasible_at_10": cc.feasible_at_10,
            "feasible_at_10_at_median": cc.feasible_at_10_median,
        },
        "adaptive_search": [asdict(cost) for cost in costs],
        "revision_pass_blocked": pass_blocked,
    }
    return "\n".join(parts), document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.eval.contact", description="Отчёт валидации контакта")
    parser.add_argument("--out", type=Path, default=None, help="каталог для report.md и report.json")
    parser.add_argument("--seed", type=int, default=20261005)
    parser.add_argument("--runs", type=int, default=200)
    parser.add_argument("--sens-runs", type=int, default=40)
    parser.add_argument("--n", type=int, default=600, help="кандидатов в популяции")
    parser.add_argument("--quick", action="store_true", help="быстрый прогон: 20 и 5 прогонов")
    args = parser.parse_args(argv)
    runs, sens_runs = (20, 5) if args.quick else (args.runs, args.sens_runs)
    text, document = build(args.seed, runs, sens_runs, args.n)
    print(text)
    if args.out is not None:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "report.md").write_text(text + "\n", encoding="utf-8")
        (args.out / "report.json").write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
