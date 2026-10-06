"""Командная строка банка заданий (Арх. 5.3).

    python -m app.modules.assessment.bank build [--per-level 60] [--family ID]... [--check-only]
                                                [--package ПАКЕТ] [--report ФАЙЛ] [--samples КАТАЛОГ]
                                                [--skip-oracle] [--no-time-check] [-v]
    python -m app.modules.assessment.bank core [--specialization backend]

`build --check-only` ничего не пишет в базу и не требует её: генерирует варианты, проверяет линтером и оракулом,
печатает отчёт и возвращает 0, если все собранные семейства приняты. Запускается из каталога `backend`.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.modules.assessment.bank.build import BankBuild, BuildOptions, FamilyBuild, build_bank
from app.modules.assessment.bank.core import compute_core, format_core
from app.modules.assessment.blueprints import LANG_RULES, available_pairs, lang_scenarios
from app.modules.assessment.config import get_config
from app.modules.assessment.families import DEFAULT_PACKAGE, Discovery, discover
from app.modules.assessment.families._lib.contract import variant_to_json
from app.modules.assessment.families.registry import CORE_P0, REGISTRY, module_name
from app.modules.assessment.groups import SPECIALIZATIONS

#: Секрет для `--check-only`, когда настройки приложения не заданы (запуск без `.env`). Seed вариантов зависит
#: от секрета, поэтому доля брака на стенде может немного отличаться; `make bank-check` берёт секрет из `.env`.
CHECK_ONLY_SECRET = "dev-check-only"
#: Сколько вариантов на уровень выгружает `--samples` для ручной проверки ключа (задача H2).
SAMPLES_PER_LEVEL = 10

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2


def _secret(check_only: bool) -> str:
    try:
        from app.core.config import get_settings

        return get_settings().assessment_secret
    except Exception as exc:
        if not check_only:
            raise
        print(
            f"настройки приложения не загружены ({type(exc).__name__}): для проверки взят учебный секрет; "
            "seed вариантов на стенде будет другим (make bank-check берёт секрет из .env)",
            file=sys.stderr,
        )
        return CHECK_ONLY_SECRET


def report_json(result: BankBuild, discovery: Discovery, *, check_only: bool, full: bool) -> dict[str, Any]:
    """Содержимое `bank_report.json`: по каждому уровню — принято, отброшено и почему (приложение A, §2.7)."""
    cfg = get_config()
    built = {item.family.meta.id for item in result.families}
    data: dict[str, Any] = {
        "bank_version": cfg.bank_version,
        "per_level": result.options.per_level,
        "check_only": check_only,
        "ok": result.ok and not discovery.errors,
        "families": [item.to_json() for item in result.families],
        "discovery_errors": discovery.errors,
        "manual_review": sorted(i for i in built if i in REGISTRY and REGISTRY[i].oracle == "manual"),
    }
    if full:
        pairs = available_pairs(family.meta for family in result.accepted())
        data["missing"] = [family_id for family_id in REGISTRY if family_id not in built]
        data["core_p0_missing"] = [family_id for family_id in CORE_P0 if family_id not in built]
        data["available_pairs"] = sorted(f"{spec}:{grade}" for spec, grade in pairs)
    return data


def _print_family(item: FamilyBuild, verbose: bool) -> None:
    meta = item.family.meta
    print(f"{'ГОДНО' if item.ok else 'БРАК ':5} {meta.id} v{meta.version}")
    for error in item.errors:
        print(f"      ! {error}")
    for level in item.levels:
        rejects = ", ".join(f"{code}×{count}" for code, count in sorted(level.rejects.items())) or "нет"
        print(
            f"      уровень {level.level} (b={level.b:+.1f}): принято {level.accepted}/{level.quota} "
            f"за {level.attempts} попыток, брак {level.reject_share:.0%} [{rejects}], "
            f"время: в среднем {level.mean_ms:.1f} мс, наибольшее {level.max_ms:.1f} мс"
        )
        for error in level.errors:
            print(f"        ! {error}")
        if verbose or not level.ok:
            for code, examples in sorted(level.examples.items()):
                for text in examples:
                    print(f"        {code}: {text}")


def _write_samples(result: BankBuild, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for item in result.families:
        for level in item.levels:
            path = directory / f"{module_name(item.family.meta.id)}_L{level.level}.json"
            data = [variant_to_json(variant) for variant in level.variants[:SAMPLES_PER_LEVEL]]
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _build(args: argparse.Namespace) -> int:
    discovery = discover(args.package)
    wanted: list[str] = args.family or []
    known = {family.meta.id for family in discovery.families}
    for module, error in discovery.errors.items():
        print(f"НЕ ЗАГРУЖЕНО {module}: {error}")
    unknown = [family_id for family_id in wanted if family_id not in known]
    if unknown:
        print(f"семейства не найдены в пакете {args.package}: {', '.join(unknown)}")
        return EXIT_FAILED

    cfg = get_config()
    try:
        secret = _secret(args.check_only)
    except Exception as exc:
        print(f"настройки приложения не загружены: {exc}\nзапускайте через make bank или задайте APP_ENV_FILE")
        return EXIT_USAGE
    options = BuildOptions(
        secret=secret,
        per_level=args.per_level or cfg.variants_per_level,
        demo_per_level=cfg.demo_variants_per_level,
        skip_oracle=args.skip_oracle,
        time_check=not args.no_time_check,
    )
    result = build_bank(discovery.families, options, only=wanted)
    for item in result.families:
        _print_family(item, args.verbose)

    full = not wanted
    report = report_json(result, discovery, check_only=args.check_only, full=full)
    accepted = sum(1 for item in result.families if item.ok)
    print(f"Семейств принято: {accepted} из {len(result.families)}; вариантов на уровень: {options.per_level}")
    if full:
        print(f"Доступные пары: {', '.join(report['available_pairs']) or 'нет'}")
        if args.package == DEFAULT_PACKAGE and report["core_p0_missing"]:
            print(f"Не написаны семейства ядра P0: {', '.join(report['core_p0_missing'])}")
    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Отчёт: {args.report}")
    if args.samples:
        _write_samples(result, Path(args.samples))
        print(f"Образцы для ручной проверки: {args.samples}")

    ok = bool(report["ok"]) and bool(result.families)
    if not result.families:
        print("в пакете нет ни одного семейства")
    if args.check_only:
        return EXIT_OK if ok else EXIT_FAILED
    try:
        store = importlib.import_module("app.modules.assessment.bank.store")
    except ModuleNotFoundError:
        print("запись банка в базу ещё не подключена (bank/store.py); пока доступна только проверка: --check-only")
        return EXIT_USAGE
    store.write_bank(result, report)
    return EXIT_OK if ok else EXIT_FAILED


def _core(args: argparse.Namespace) -> int:
    spec = args.specialization
    required = LANG_RULES[spec].required
    langs = (required,) if required is not None else tuple(lang for lang in lang_scenarios(spec) if lang != "js")
    include = () if spec == "backend" else CORE_P0
    plan = compute_core(REGISTRY.values(), spec, langs, include=include)
    print(format_core(plan))
    if spec == "backend":
        match = plan.families == CORE_P0
        print("Совпадает с CORE_P0 реестра." if match else "НЕ совпадает с CORE_P0 реестра: обновите registry.py.")
        return EXIT_OK if match else EXIT_FAILED
    extra = [family_id for family_id in plan.families if family_id not in CORE_P0]
    print(f"Сверх ядра P0 для {spec} нужно {len(extra)}: {', '.join(extra)}")
    return EXIT_OK


def parser() -> argparse.ArgumentParser:
    """Разбор аргументов; вынесен отдельно, чтобы тесты проверяли интерфейс команды."""
    root = argparse.ArgumentParser(prog="python -m app.modules.assessment.bank", description="Банк заданий")
    commands = root.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="собрать банк: генерация вариантов, линтер, отчёт о браке")
    build.add_argument("--per-level", type=int, default=None, help="вариантов на уровень (по умолчанию 60)")
    build.add_argument("--family", action="append", metavar="ID", help="только это семейство; можно повторять")
    build.add_argument("--check-only", action="store_true", help="только проверка, без записи в базу")
    build.add_argument("--package", default=DEFAULT_PACKAGE, help="пакет с семействами (в тестах — учебный)")
    build.add_argument("--report", metavar="ФАЙЛ", help="записать отчёт bank_report.json")
    build.add_argument("--samples", metavar="КАТАЛОГ", help="выгрузить по 10 вариантов на уровень для ручной проверки")
    build.add_argument("--skip-oracle", action="store_true", help="не сверять ключи с внешним оракулом (локально)")
    build.add_argument("--no-time-check", action="store_true", help="не проверять пределы времени generate")
    build.add_argument("-v", "--verbose", action="store_true", help="печатать примеры брака и у принятых уровней")
    build.set_defaults(handler=_build)

    core = commands.add_parser("core", help="ядро P0: наименьший набор семейств и порядок написания")
    core.add_argument("--specialization", default="backend", choices=SPECIALIZATIONS)
    core.set_defaults(handler=_core)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    """Выполнить команду; возвращает код выхода (0 — успех, 1 — есть брак, 2 — запись в базу недоступна)."""
    args = parser().parse_args(argv)
    if getattr(args, "per_level", None) is not None and args.per_level < 1:
        print("--per-level должен быть положительным")
        return EXIT_USAGE
    return int(args.handler(args))


__all__ = ["main", "parser", "report_json"]
