"""Экспертная сверка E1–E3 — единственная часть проверки тестирования, не зависящая от симулятора (Арх. 12.2).

    python -m app.eval.testing.expert export-sheets  [--out КАТАЛОГ] [--bank ...] [--seed N]
    python -m app.eval.testing.expert import-ratings [--dir КАТАЛОГ] [--report report.json]

`export-sheets` готовит материалы: `difficulty_ratings.csv` (E1: два оценщика ставят сложность каждому уровню),
`level_samples.jsonl` (примеры заданий уровней), `sheets.jsonl` и `sheet_labels.csv` (E2: 40 слепых листов ответов),
а отдельно — `levels_author.csv` и `sheets_key.json`, которые оценщикам не показывают. `import-ratings` считает
согласие и вписывает его в `expert_results.json` и в `report.json`. Людей инструмент не заменяет: без оценок отчёт
пишет «E1 — оценка автора банка; E2 и E3 не проводились».
"""

# ruff: noqa: E501 — подписи отчёта и длинные проверки читаются лучше в одну строку

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.eval.testing.bank import SimBank, load
from app.eval.testing.pathsim import simulate_path
from app.modules.assessment.config import GRADES
from app.modules.assessment.families._lib.contract import Reject, variant_payload
from app.simulation.population import generate, item_world

SHEETS_PER_GRADE = 10
SAMPLES_PER_LEVEL = 2
EXPERTS = ("E1", "E2")
SCALE = ("none", *GRADES)
ANCHORS = "якоря: b = −1.5 — минимально годный Junior решает в половине случаев; 0 — Middle; +1.5 — Senior; шаг 0.5, от −2.0 до 2.0"


def _write_csv(path: Path, header: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [{k: (v or "").strip() for k, v in row.items() if k} for row in csv.DictReader(handle)]


def _sample(bank: SimBank, family_id: str, level: int, rng: random.Random) -> dict[str, Any] | None:
    """Пример задания уровня; `None`, если у банка нет генераторов (таблица реестра)."""
    family = bank.generators.get(family_id)
    if family is None:
        return None
    for _ in range(40):
        try:
            return variant_payload(family.generate(level, rng.getrandbits(64)))
        except Reject:
            continue
    return None


def export_sheets(bank: SimBank, out: Path, seed: int) -> dict[str, int]:
    """Подготовить материалы E1 и E2. Возвращает числа: уровней, листов, примеров."""
    out.mkdir(parents=True, exist_ok=True)
    levels = [(family, level) for family in bank.families for level in family.levels]
    _write_csv(
        out / "difficulty_ratings.csv",
        ["family_id", "level", "expert_id", "b"],
        [[family.id, level.level, expert, ""] for family, level in levels for expert in EXPERTS],
    )
    _write_csv(
        out / "levels_author.csv",
        ["family_id", "level", "group", "kind", "title", "b_author"],
        [[f.id, lv.level, f.group, f.kind, f.title, lv.b] for f, lv in levels],
    )
    rng = random.Random(f"{seed}:expert:samples")
    samples = 0
    with (out / "level_samples.jsonl").open("w", encoding="utf-8") as handle:
        for family, level in levels:
            for _ in range(SAMPLES_PER_LEVEL):
                payload = _sample(bank, family.id, level.level, rng)
                if payload is None:
                    continue
                samples += 1
                record = {"family_id": family.id, "level": level.level, "title": family.title, **payload}
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    pairs = bank.pairs()
    sheets: list[dict[str, Any]] = []
    key: dict[str, Any] = {}
    if pairs:
        specs = list(dict.fromkeys(spec for spec, _ in pairs))
        people = generate(4000, specs, random.Random(f"{seed}:expert:pop"), first_id=40_000_000)
        world = item_world(bank.families, random.Random(f"{seed}:expert:world"))
        taken: Counter[str] = Counter()
        text_rng = random.Random(f"{seed}:expert:text")
        for person in people:
            name = person.true_grade or "none"
            if taken[name] >= SHEETS_PER_GRADE:
                continue
            taken[name] += 1
            path = simulate_path(person, bank, random.Random(f"{seed}:expert:path:{person.id}"), world=world)
            sheet_id = f"S{len(sheets) + 1:02d}"
            items = []
            for session in path.sessions:
                for item in session.items:
                    family = bank.by_id[item.family_id]
                    items.append(
                        {
                            "title": family.title or family.id,
                            "group": family.group,
                            "task": _sample(bank, item.family_id, item.level, text_rng),
                            "correct": bool(item.score),
                        }
                    )
            sheets.append({"sheet_id": sheet_id, "specialization": person.specialization, "items": items})
            key[sheet_id] = {
                "true_grade": name,
                "engine_category": path.grade or "none",
                "theta_hat": round(path.post.theta, 3),
                "tests": [session.grade for session in path.sessions],
            }
            if all(taken[g] >= SHEETS_PER_GRADE for g in SCALE):
                break
    # Листы перемешаны: по номеру нельзя угадать истинный грейд.
    order = list(range(len(sheets)))
    random.Random(f"{seed}:expert:order").shuffle(order)
    renamed = {}
    with (out / "sheets.jsonl").open("w", encoding="utf-8") as handle:
        for new, index in enumerate(order, start=1):
            sheet = sheets[index]
            new_id = f"L{new:02d}"
            renamed[new_id] = key[sheet["sheet_id"]]
            handle.write(json.dumps({**sheet, "sheet_id": new_id}, ensure_ascii=False, sort_keys=True) + "\n")
    (out / "sheets_key.json").write_text(json.dumps(renamed, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_csv(
        out / "sheet_labels.csv",
        ["sheet_id", "expert_id", "grade"],
        [[sheet_id, expert, ""] for sheet_id in sorted(renamed) for expert in EXPERTS],
    )
    (out / "README.md").write_text(
        "# Материалы экспертной сверки\n\n"
        f"- **E1.** `difficulty_ratings.csv`: каждый оценщик, не писавший семейства, заполняет столбец `b` своих строк ({ANCHORS}). "
        "Примеры заданий уровней — `level_samples.jsonl`. Файл `levels_author.csv` оценщикам не показывать.\n"
        "- **E2.** `sheets.jsonl` — слепые листы ответов; в `sheet_labels.csv` оценщик ставит грейд: none, junior, middle, senior. "
        "Файл `sheets_key.json` оценщикам не показывать. Лист строит симулятор: E2 проверяет здравый смысл шкалы, а не валидность теста.\n"
        "- **E3.** Пилот: `pilot.csv` со столбцами `person_id, known_grade, outcome, theta_hat`.\n\n"
        "Итоги: `python -m app.eval.testing.expert import-ratings --dir <этот каталог>`.\n",
        encoding="utf-8",
    )
    return {"levels": len(levels), "sheets": len(renamed), "samples": samples}


# --------------------------------------------------------------------------------------------------------------------
# Согласие
# --------------------------------------------------------------------------------------------------------------------


def spearman(x: Sequence[float], y: Sequence[float]) -> float | None:
    """Ранговая корреляция Спирмена (со средними рангами при совпадениях)."""

    def ranks(values: Sequence[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        result = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j < len(order) and values[order[j]] == values[order[i]]:
                j += 1
            for k in range(i, j):
                result[order[k]] = (i + j + 1) / 2
            i = j
        return result

    if len(x) < 3:
        return None
    rx, ry = ranks(x), ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sxx = sum((v - mx) ** 2 for v in rx)
    syy = sum((v - my) ** 2 for v in ry)
    if sxx <= 0 or syy <= 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True)) / (sxx * syy) ** 0.5


def weighted_kappa(a: Sequence[int], b: Sequence[int], categories: int = len(SCALE)) -> float | None:
    """Взвешенная κ с линейными весами: расхождение на два грейда стоит вдвое дороже, чем на один."""
    n = len(a)
    if n == 0:
        return None
    ca, cb = Counter(a), Counter(b)
    observed = sum(abs(x - y) for x, y in zip(a, b, strict=True)) / (n * (categories - 1))
    expected = sum(ca[i] * cb[j] * abs(i - j) for i in ca for j in cb) / (n * n * (categories - 1))
    return 1.0 if expected == 0 else 1.0 - observed / expected


def _round_half(value: float) -> float:
    return max(-2.0, min(2.0, round(value * 2) / 2))


def import_ratings(directory: Path) -> dict[str, Any]:
    """Посчитать согласие по заполненным файлам; результат — секция `expert` отчёта."""
    result: dict[str, Any] = {"e1": "author_only", "e2_kappa": None, "e3": "not_done", "note": None}
    notes = []

    ratings: dict[tuple[str, str], dict[str, float]] = {}
    for item in _read_csv(directory / "difficulty_ratings.csv"):
        try:
            value = float(item.get("b", "").replace(",", "."))
        except ValueError:
            continue
        ratings.setdefault((item["family_id"], item["level"]), {})[item["expert_id"]] = value
    experts = sorted({expert for row in ratings.values() for expert in row})
    both = {k: row for k, row in ratings.items() if len(row) >= 2}
    if len(experts) >= 2 and both:
        first, second = experts[0], experts[1]
        common = sorted(k for k, row in both.items() if first in row and second in row)
        x, y = [ratings[k][first] for k in common], [ratings[k][second] for k in common]
        author = {(r["family_id"], r["level"]): float(r["b_author"]) for r in _read_csv(directory / "levels_author.csv")}
        final_rows, changed = [], 0
        for k in sorted(both):
            final = _round_half(sum(both[k].values()) / len(both[k]))
            changed += int(k in author and author[k] != final)
            final_rows.append([k[0], k[1], author.get(k, ""), final])
        _write_csv(directory / "b_final.csv", ["family_id", "level", "b_author", "b_final"], final_rows)
        rho = spearman(x, y)
        result["e1"] = "done"
        result["e1_details"] = {
            "experts": experts,
            "levels": len(common),
            "spearman": None if rho is None else round(rho, 3),
            "mean_abs_diff": round(sum(abs(p - q) for p, q in zip(x, y, strict=True)) / len(common), 3),
            "share_diff_over_1": round(sum(1 for p, q in zip(x, y, strict=True) if abs(p - q) > 1.0) / len(common), 3),
            "levels_changed": changed,
        }
        notes.append(
            f"E1 проведена: итоговая b — среднее двух оценок, округлённое до 0.5 (b_final.csv); изменилось уровней: {changed}. "
            "После переноса b в families/registry.py нужно повторить test_blueprints_feasible."
        )
    else:
        notes.append("E1 — оценка автора банка: независимых оценок сложности нет.")

    labels: dict[str, dict[str, int]] = {}
    for item in _read_csv(directory / "sheet_labels.csv"):
        grade = item.get("grade", "").lower()
        if grade in SCALE:
            labels.setdefault(item["sheet_id"], {})[item["expert_id"]] = SCALE.index(grade)
    key_path = directory / "sheets_key.json"
    key = json.loads(key_path.read_text(encoding="utf-8")) if key_path.exists() else {}
    rated = sorted(sheet for sheet in labels if sheet in key)
    if rated:
        consensus = [round(sum(labels[s].values()) / len(labels[s]) + 1e-9) for s in rated]
        engine = [SCALE.index(key[s]["engine_category"]) for s in rated]
        kappa = weighted_kappa(consensus, engine)
        result["e2_kappa"] = None if kappa is None else round(kappa, 3)
        details: dict[str, Any] = {
            "sheets": len(rated),
            "exact_agreement": round(sum(1 for c, e in zip(consensus, engine, strict=True) if c == e) / len(rated), 3),
        }
        raters = sorted({expert for s in rated for expert in labels[s]})
        if len(raters) >= 2:
            shared = [s for s in rated if raters[0] in labels[s] and raters[1] in labels[s]]
            between = weighted_kappa([labels[s][raters[0]] for s in shared], [labels[s][raters[1]] for s in shared])
            details["between_experts_kappa"] = None if between is None else round(between, 3)
        result["e2_details"] = details
        notes.append("E2 проведена: лист строит симулятор, поэтому она проверяет здравый смысл шкалы, а не валидность теста.")
    else:
        notes.append("E2 не проводилась.")

    pilot = [r for r in _read_csv(directory / "pilot.csv") if r.get("known_grade") and r.get("outcome")]
    if pilot:
        matrix = Counter((r["known_grade"], r["outcome"]) for r in pilot)
        result["e3"] = "done"
        result["e3_details"] = {
            "people": len(pilot),
            "matrix": [{"known_grade": g, "outcome": o, "count": c} for (g, o), c in sorted(matrix.items())],
            "note": "без вывода о значимости",
        }
        notes.append(f"E3 проведён: {len(pilot)} человек, без вывода о значимости.")
    else:
        notes.append("E3 не проводился.")
    if result["e1"] != "done":
        notes.append("Сложность заданий нельзя называть экспертной.")
    result["note"] = " ".join(notes)
    return result


def apply_to_report(expert: dict[str, Any], report_path: Path) -> bool:
    """Вписать итоги сверки в `report.json` (секции `expert` и `summary.expert`) и обновить `report.md`."""
    if not report_path.exists():
        return False
    from app.eval.testing.run import render_markdown

    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["expert"] = expert
    report["summary"]["expert"] = {key: expert[key] for key in ("e1", "e2_kappa", "e3")}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (report_path.parent / "report.md").write_text(render_markdown(report), encoding="utf-8")
    return True


def main(argv: Sequence[str] | None = None) -> int:
    """Команды `export-sheets` и `import-ratings`."""
    parser = argparse.ArgumentParser(prog="python -m app.eval.testing.expert", description="Экспертная сверка E1–E3")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export-sheets", help="подготовить difficulty_ratings.csv и sheets.jsonl")
    export.add_argument("--out", default="docs/validation/testing/expert")
    export.add_argument("--bank", default="discovered")
    export.add_argument("--seed", type=int, default=20261005)
    load_cmd = commands.add_parser("import-ratings", help="посчитать согласие и вписать его в report.json")
    load_cmd.add_argument("--dir", default="docs/validation/testing/expert")
    load_cmd.add_argument("--report", default=None, help="по умолчанию — report.json каталогом выше")
    args = parser.parse_args(argv)
    if args.command == "export-sheets":
        stats = export_sheets(load(args.bank), Path(args.out), args.seed)
        print(f"Материалы сверки: {args.out}; уровней {stats['levels']}, листов {stats['sheets']}, примеров заданий {stats['samples']}")
        if not stats["samples"]:
            print("у банка нет генераторов: примеры заданий и тексты в листах не выгружены (только названия семейств)")
        return 0
    directory = Path(args.dir)
    if not directory.is_dir():
        print(f"каталог {directory} не найден: сначала выполните export-sheets")
        return 1
    expert = import_ratings(directory)
    (directory / "expert_results.json").write_text(json.dumps(expert, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path = Path(args.report) if args.report else directory.parent / "report.json"
    patched = apply_to_report(expert, report_path)
    print(expert["note"])
    print(f"Итоги: {directory / 'expert_results.json'}" + (f"; вписаны в {report_path}" if patched else "; report.json не найден — итоги войдут в следующий прогон"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
