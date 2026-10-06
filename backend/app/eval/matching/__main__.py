"""Команды валидации подбора (Арх. 12.3, 12.6).

python -m app.eval.matching run --out docs/validation/matching [--quick] [--seeds 201-220]
python -m app.eval.matching export-pairs --out docs/validation/matching [--seed 201]
python -m app.eval.matching import-labels --out docs/validation/matching --a labels_a.csv [--b labels_b.csv]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.eval.matching import manual
from app.eval.matching.run import QUICK_SEEDS, REPORT_SEEDS, console, run


def _seeds(value: str) -> list[int]:
    first, _, last = value.partition("-")
    return list(range(int(first), int(last or first) + 1))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.eval.matching", description="Валидация подбора")
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="прогон и отчёт")
    run_parser.add_argument("--out", type=Path, required=True)
    run_parser.add_argument("--quick", action="store_true", help="3 сида, основные режимы — для CI")
    run_parser.add_argument("--seeds", type=_seeds, default=None, help="диапазон сидов, например 201-220")
    export = commands.add_parser("export-pairs", help="материалы для ручной разметки")
    export.add_argument("--out", type=Path, required=True)
    export.add_argument("--seed", type=int, default=REPORT_SEEDS[0])
    labels = commands.add_parser("import-labels", help="принять метки разметчиков")
    labels.add_argument("--out", type=Path, required=True)
    labels.add_argument("--a", type=Path, required=True, help="метки первого разметчика")
    labels.add_argument("--b", type=Path, default=None, help="метки второго разметчика")
    args = parser.parse_args(argv)

    if args.command == "run":
        seeds = args.seeds or (QUICK_SEEDS if args.quick else REPORT_SEEDS)
        report = run(args.out, seeds=seeds, quick=args.quick)
        print(console(report))
        print(f"Отчёт: {args.out / 'report.md'}, {args.out / 'report.json'} ({report['passport']['duration_s']} с)")
        return 0
    if args.command == "export-pairs":
        count = manual.export_pairs(args.out / "manual", seed=args.seed)
        print(f"Пар для разметки: {count}. Файлы: {args.out / 'manual'}")
        return 0
    result = manual.import_labels(args.out / "manual", args.a, args.b)
    print(f"Принято пар: {result['pairs']}; разметчиков: {result['raters']}; взвешенная κ: {result['kappa']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
