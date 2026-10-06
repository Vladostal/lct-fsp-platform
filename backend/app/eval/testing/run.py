"""Сборка отчёта валидации тестирования: `report.json`, `report.md`, рисунки (Арх. 12.2).

Тот же seed и тот же банк дают побайтно тот же `report.json`: времени выполнения и текущего момента в нём нет,
дата отчёта — аргумент `--date` (по умолчанию — сегодняшняя дата, без времени).
"""

# ruff: noqa: E501 — подписи отчёта и длинные проверки читаются лучше в одну строку

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from app.eval.testing import experiments as ex
from app.eval.testing import figures
from app.eval.testing.bank import SimBank, load
from app.modules.assessment import blueprints
from app.modules.assessment.config import GRADES, get_config
from app.modules.assessment.groups import SPECIALIZATIONS
from app.simulation.population import PopulationParams, WorldParams, item_world

EXPERT_FILE = "expert/expert_results.json"
DEFAULT_EXPERT: dict[str, Any] = {
    "e1": "author_only",
    "e2_kappa": None,
    "e3": "not_done",
    "note": "E1 — оценка автора банка; E2 и E3 не проводились. Сложность заданий нельзя называть экспертной.",
}

ASSUMPTIONS = """VirtualCandidate: specialization — поровну по специализациям с доступным тестом;
    theta_true ~ N(0.2, 1.3²) на шкале теста; delta[group] ~ N(0, 0.4²);
    true_grade по THETA_CUT (ниже −1.5 — без грейда);
    claimed_grade: истинный 0.60, на грейд выше 0.25, ниже 0.15
«Истинные» параметры заданий (движок их не знает):
    a_true ~ LogNormal(ln 1.1, 0.25), обрезано до [0.5, 2.2]; b_true = b + N(0, 0.4²); дрейф варианта N(0, 0.25²)
    P(верно) = c + (1 − c) / (1 + exp(−a_true · (theta_true + delta[group] − b_true − дрейф)))
Движок считает с a = 1.0 и назначенными b."""

NOT_CLAIMED = [
    "Числа симуляции — самосогласованность механики со своими допущениями, а не валидность теста: ответы порождает "
    "та же логистическая модель, на которой построен движок, а истинный грейд задан теми же порогами.",
    "Сложность заданий b — оценка автора банка, пока не проведена сверка E1; шкала не откалибрована на людях.",
    "Тест не защищает от языковой модели, подмены человека и подсказок: это фильтр для категории, а не решение о найме.",
    "Новый аккаунт на другом адресе начинает без накопления и без лимитов: вероятность ложного подтверждения растёт "
    "с числом независимых серий (строки v5_series_*). Личность кандидата в MVP не проверяется.",
    "При сдвиге знакомства 1.0 логита защита пулами семейств заметно слабее (строка leak_false_confirm_m5_pessimistic): "
    "при целенаправленной подготовке по всем типам заданий она сходит на нет.",
    "После исчерпания пула уровня варианты выдаются повторно (строки v7_first_repeat_*): чужой ответ подходит тому, "
    "кому выпал тот же вариант.",
    "V6 условна по модели: наклон заданий — входной параметр симуляции.",
    "Подтверждение отдельного навыка опирается на один-два ответа и зависит от выпавшего семейства (V10, «близнецы»).",
]


def _value(table: dict[str, Any], metric: str) -> float | None:
    return next((item["value"] for item in table["rows"] if item["metric"] == metric), None)


def build_report(
    bank: SimBank,
    *,
    seed: int,
    n: int,
    generated_at: datetime,
    v7_sessions: Sequence[int] = ex.V7_SESSIONS,
    expert: dict[str, Any] | None = None,
    progress: Any = None,
) -> dict[str, Any]:
    """Прогнать V1–V10 на банке и собрать отчёт. Недоступные пары пропускаются и названы в `meta.skipped_pairs`."""
    cfg = get_config()

    def note(text: str) -> None:
        if progress is not None:
            progress(text)

    pairs = bank.pairs()
    if not pairs:
        raise ValueError("в банке нет ни одной доступной пары (специализация, грейд): отчёт строить не на чем")
    skipped = [f"{s}:{g}" for s in SPECIALIZATIONS for g in GRADES if (s, g) not in pairs]
    base = ex.Scenario("base", "Базовые допущения")
    note("V1–V4: общий прогон")
    core = ex.run_core(bank, seed, n, base)
    world = item_world(bank.families, ex._rng(seed, "world:extra"), WorldParams())
    tables: dict[str, Any] = {"v1": ex.v1(core, seed), "v2": ex.v2(core, seed), "v3": ex.v3(core, seed), "v4": ex.v4(core, seed)}
    note("V5: повторные попытки")
    tables["v5"] = ex.v5(bank, seed, n, world)
    note("V6: дискриминативность")
    tables["v6"] = ex.v6(bank, seed, n, core)
    note("V7: экспозиция")
    tables["v7"] = ex.v7(bank, seed, world, v7_sessions)
    note("V8: утечка")
    tables["v8"] = ex.v8(bank, seed, n, world)
    note("V9: чувствительность")
    tables["v9"] = ex.v9(bank, seed, n, ex.core_numbers(core, seed))
    note("V10: навыки")
    tables["v10"] = ex.v10(bank, seed, core)

    expert_data = {**DEFAULT_EXPERT, **(expert or {})}
    versions = {"bank": cfg.bank_version, "engine": cfg.engine_version}
    summary = {
        "generated_at": generated_at.isoformat(),
        "seed": seed,
        "n": n,
        "versions": versions,
        "v1_accuracy": _value(tables["v1"], "v1_accuracy"),
        "v2_agreement": _value(tables["v2"], "v2_agreement"),
        "v3_exact": _value(tables["v3"], "v3_exact"),
        "v3_overgrade": _value(tables["v3"], "v3_overgrade"),
        "v4_agreement": _value(tables["v4"], "v4_agreement"),
        "v5_three_attempts": _value(tables["v5"], "v5_three_attempts_05"),
        "v6_correlation": _value(tables["v6"], "v6_correlation"),
        "leak_false_confirm_m5": _value(tables["v8"], "leak_false_confirm_m5"),
        "leak_false_confirm_m5_pessimistic": _value(tables["v8"], "leak_false_confirm_m5_pessimistic"),
        "sessions_to_first_repeat": _value(tables["v7"], f"v7_first_repeat_{ex.V7_VARIANTS[0]}"),
        "expert": {key: expert_data[key] for key in ("e1", "e2_kappa", "e3")},
    }
    bars = [
        {"experiment": key, **{k: item[k] for k in ("metric", "label", "value", "ci", "bar", "op", "met", "n", "unit")}}
        for key, table in tables.items()
        for item in table.get("rows", [])
        if item["bar"] is not None
    ]
    return {
        "meta": {
            "title": "Валидация тестирования: симуляция на боевом движке",
            "generated_at": generated_at.isoformat(),
            "seed": seed,
            "n": n,
            "versions": versions,
            "bank": {
                "source": bank.source,
                "families": len(bank.families),
                "levels": sum(len(f.levels) for f in bank.families),
                "available_pairs": [f"{s}:{g}" for s, g in pairs],
                "skipped_pairs": skipped,
                "pools": {
                    f"{s}:{g}": len(blueprints.eligible(bank.pools, s, bank.lang(s, g, None), None, blueprints.MAIN_RANGE[g]))
                    for s, g in pairs
                },
            },
            "bootstrap": ex.BOOTSTRAP,
            "population": PopulationParams().__dict__,
            "world": {k: v for k, v in WorldParams().__dict__.items() if k != "broken"},
        },
        "assumptions": ASSUMPTIONS,
        "acceptance": {"met": sum(1 for b in bars if b["met"]), "total": len(bars), "bars": bars},
        **tables,
        "expert": expert_data,
        "not_claimed": NOT_CLAIMED,
        "summary": summary,
    }


# --------------------------------------------------------------------------------------------------------------------
# Текст отчёта
# --------------------------------------------------------------------------------------------------------------------


def _fmt(item: dict[str, Any]) -> str:
    value = item["value"]
    if value is None:
        return "—"
    if item.get("unit", "share") == "share":
        return f"{value * 100:.1f} %"
    return f"{value:g}"


def _ci(item: dict[str, Any]) -> str:
    low, high = item["ci"]
    if low is None or high is None:
        return "—"
    if item.get("unit", "share") == "share":
        return f"{low * 100:.1f}–{high * 100:.1f} %"
    return f"{low:g}–{high:g}"


def _bar(item: dict[str, Any]) -> str:
    if item["bar"] is None:
        return "без планки"
    bar = f"{item['bar'] * 100:g} %" if item.get("unit", "share") == "share" else f"{item['bar']:g}"
    sign = "≥" if item["op"] == ">=" else "≤"
    return f"{sign} {bar}: {'выполнено' if item['met'] else '**не выполнено**'}"


def _table(rows: Sequence[dict[str, Any]]) -> list[str]:
    out = ["| Показатель | Значение | Интервал 95 % | Планка (по границе интервала) | n |", "|---|---|---|---|---|"]
    out += [f"| {r['label']} | {_fmt(r)} | {_ci(r)} | {_bar(r)} | {r['n'] if r['n'] is not None else '—'} |" for r in rows]
    return out


def render_markdown(report: dict[str, Any]) -> str:
    """`report.md`: допущения, таблицы V1–V10 с планками и несбывшимися, E1–E3, «Чего мы не заявляем»."""
    meta = report["meta"]
    titles = {
        "v1": "V1. Одна сессия на заявленный грейд",
        "v2": "V2. Две независимые сессии",
        "v3": "V3. Полный путь по правилам грейда",
        "v4": "V4. Полный путь дважды",
        "v5": "V5. Повторные попытки и независимые серии",
        "v6": "V6. Дискриминативность (условна по модели)",
        "v7": "V7. Экспозиция и исчерпание пула",
        "v8": "V8. Кривая утечки",
        "v10": "V10. Доказательства по навыкам и «близнецы»",
    }
    lines = [
        f"# {meta['title']}",
        "",
        f"Версия банка {meta['versions']['bank']}, версия движка {meta['versions']['engine']}, seed {meta['seed']}, "
        f"кандидатов {meta['n']}, дата {meta['generated_at'][:10]}.",
        f"Банк: {meta['bank']['families']} семейств, {meta['bank']['levels']} уровней (источник: {meta['bank']['source']}). "
        f"Доступные пары: {', '.join(meta['bank']['available_pairs'])}.",
    ]
    if meta["bank"]["skipped_pairs"]:
        lines.append(f"Пропущены недоступные пары: {', '.join(meta['bank']['skipped_pairs'])}.")
    acceptance = report["acceptance"]
    lines += [
        "",
        f"**Планок выполнено: {acceptance['met']} из {acceptance['total']}.** Планка считается выполненной, если ей "
        "удовлетворяет граница 95-процентного бутстреп-интервала, а не точечная оценка.",
        "",
        "Симуляция вызывает боевой код движка (`assessment/engine`), а не его копию. Её числа — самосогласованность "
        "механики со своими допущениями, а не валидность теста.",
        "",
        "## Допущения",
        "",
        "```",
        report["assumptions"],
        "```",
        "",
        "## Главная таблица: планки",
        "",
        *_table(acceptance["bars"]),
    ]
    failed = [b for b in acceptance["bars"] if not b["met"]]
    lines += ["", "Несбывшиеся планки: " + ("; ".join(b["label"] for b in failed) if failed else "нет") + "."]
    for key, title in titles.items():
        lines += ["", f"## {title}", "", *_table(report[key]["rows"])]
        if key == "v1":
            outcomes = ", ".join(f"{name} — {value * 100:.1f} %" for name, value in report["v1"]["outcomes"].items())
            lines += ["", f"Исходы: {outcomes}."]
        if key == "v2":
            lines += ["", "![Стабильность по расстоянию до порога](figures/stability_by_distance.svg)"]
        if key == "v3":
            lines += ["", "![Истинный грейд и итоговая категория](figures/confusion_flow.svg)"]
        if key == "v6":
            bottom = ", ".join(f"{i['family_id']} ({i['correlation']})" for i in report["v6"]["bottom"][:5])
            lines += ["", f"Испорчены намеренно: {', '.join(report['v6']['broken'])}. Нижняя пятёрка: {bottom}."]
        if key == "v7":
            lines += ["", "![Экспозиция](figures/exposure.svg)"]
        if key == "v8":
            lines += [
                "",
                "![Кривая утечки](figures/leak_curve.svg)",
                "",
                "| Устройство банка | Сдвиг | " + " | ".join(f"m = {m}" for m in ex.LEAK_M) + " |",
                "|---|---|" + "---|" * len(ex.LEAK_M),
            ]
            for curve in report["v8"]["curves"]:
                name = "пулы семейств" if curve["design"] == "pools" else "одно семейство на слот"
                cells = " | ".join(f"{(p['value'] or 0) * 100:.1f} %" for p in curve["points"])
                lines.append(f"| {name} | {curve['shift']} | {cells} |")
            lines += ["", f"Статичный банк: {report['v8']['static_bank']['note']}."]
    v9 = report["v9"]
    lines += [
        "",
        "## V9. Чувствительность",
        "",
        "Таблица без планок; **выделены** значения, при которых планки V2–V4 не выполняются.",
        "",
        "| Допущение | n | " + " | ".join(v9["columns"]) + " |",
        "|---|---|" + "---|" * len(v9["columns"]),
    ]
    for item in v9["table"]:
        marks: list[str] = []
        for column in v9["columns"]:
            value = item[column]
            text = "—" if value is None else f"{value:.3f}"
            marks.append(f"**{text}**" if column in item["failed"] else text)
        lines.append(f"| {item['label']} | {item['n']} | " + " | ".join(marks) + " |")
    expert = report["expert"]
    lines += [
        "",
        "## Экспертная сверка E1–E3",
        "",
        f"- E1 (сложность уровней): {'проведена двумя оценщиками' if expert['e1'] == 'done' else 'оценка автора банка' if expert['e1'] == 'author_only' else 'не проводилась'}.",
        f"- E2 (слепые листы): {'κ = ' + str(expert['e2_kappa']) if expert['e2_kappa'] is not None else 'не проводилась'}. "
        "Лист строит симулятор, поэтому E2 проверяет здравый смысл шкалы, а не валидность теста.",
        f"- E3 (пилот на людях): {'проведён' if expert['e3'] == 'done' else 'не проводился'}.",
    ]
    if expert.get("note"):
        lines.append(f"- {expert['note']}")
    lines += ["", "## Чего мы не заявляем", "", *[f"- {text}" for text in report["not_claimed"]], ""]
    return "\n".join(lines)


def write_report(report: dict[str, Any], out: Path) -> None:
    """Записать `report.json`, `report.md` и рисунки в каталог."""
    (out / "figures").mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "report.md").write_text(render_markdown(report), encoding="utf-8")
    top = max(report["v7"]["sessions"])
    files = {
        "leak_curve.svg": figures.leak_curve(report["v8"]["curves"]),
        "stability_by_distance.svg": figures.stability_by_distance(report["v2"]["by_distance"]),
        "exposure.svg": figures.exposure(report["v7"]["pairs"], top),
        "confusion_flow.svg": figures.confusion_flow(report["v3"]["confusion"]),
    }
    for name, content in files.items():
        (out / "figures" / name).write_text(content, encoding="utf-8")


def load_expert(out: Path) -> dict[str, Any] | None:
    path = out / EXPERT_FILE
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def main(argv: Sequence[str] | None = None) -> int:
    """`python -m app.eval.testing --seed 20261005 --n 4000 --out docs/validation/testing`."""
    parser = argparse.ArgumentParser(prog="python -m app.eval.testing", description="Валидация тестирования (V1–V10)")
    parser.add_argument("--seed", type=int, default=20261005)
    parser.add_argument("--n", type=int, default=4000, help="виртуальных кандидатов в общем прогоне")
    parser.add_argument("--out", default="docs/validation/testing")
    parser.add_argument(
        "--bank", default="discovered", help="discovered — семейства на диске; registry — таблица реестра; модуль:функция"
    )
    parser.add_argument("--date", default=None, help="дата отчёта ГГГГ-ММ-ДД (по умолчанию сегодня)")
    parser.add_argument("--quick", action="store_true", help="короткий прогон V7 (тест-дым)")
    args = parser.parse_args(argv)
    if args.n < 40:
        print("--n должен быть не меньше 40")
        return 2
    bank = load(args.bank)
    day = date.fromisoformat(args.date) if args.date else datetime.now(UTC).date()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    began = time.monotonic()
    try:
        report = build_report(
            bank,
            seed=args.seed,
            n=args.n,
            generated_at=datetime(day.year, day.month, day.day, tzinfo=UTC),
            v7_sessions=(50, 100, 200) if args.quick else ex.V7_SESSIONS,
            expert=load_expert(out),
            progress=lambda text: print(f"  {text}", file=sys.stderr),
        )
    except ValueError as exc:
        print(f"отчёт не построен: {exc}")
        return 1
    write_report(report, out)
    acceptance = report["acceptance"]
    print(f"Отчёт: {out / 'report.md'}; планок выполнено {acceptance['met']} из {acceptance['total']}; "
          f"время {time.monotonic() - began:.0f} с")
    for item in acceptance["bars"]:
        if not item["met"]:
            print(f"  не выполнено: {item['label']} = {item['value']} (планка {item['op']} {item['bar']})")
    return 0
