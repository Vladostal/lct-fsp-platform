"""`python -m app.seed [catalog-check|fsp|demo|scenario|all] [--reset]` (Арх. 13.5)."""

from __future__ import annotations

import argparse
import sys

from app.core.config import get_settings
from app.core.db import dispose_engine, session_scope
from app.core.logging import setup_logging
from app.modules.fsp import service as fsp
from app.modules.identity import service as identity
from app.seed import common as C
from app.seed import companies, declared, demo, population, scenario


def _catalog_check() -> int:
    if not C.ensure_ready():
        print("недоступна специализация backend: соберите банк заданий (make bank)")
        return 1
    print("доступные грейды backend:", ", ".join(C.available_grades()))
    return 0


def _fsp_check() -> int:
    history, empty = len(fsp.demo_athlete_pool(with_history=True)), len(fsp.demo_athlete_pool(with_history=False))
    print(f"демо-реестр ФСП: спортсменов с участиями {history}, без участий {empty}")
    return 0 if history else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.seed", description=__doc__)
    parser.add_argument(
        "command", nargs="?", default="all", choices=["catalog-check", "fsp", "demo", "scenario", "all"]
    )
    parser.add_argument("--reset", action="store_true", help="удалить демо-аккаунты и создать сид заново")
    args = parser.parse_args(argv)
    setup_logging(get_settings().log_level)
    try:
        if args.command == "catalog-check":
            return _catalog_check()
        if args.command == "fsp":
            return _fsp_check()
        if args.reset:
            with session_scope() as db:
                for user_id in identity.demo_user_ids(db):
                    identity.delete_user(db, user_id)
        if args.command == "demo":
            print(
                {
                    "population": population.seed_population(),
                    "declared": declared.seed_declared(),
                    "companies": companies.seed_companies(),
                }
            )
        elif args.command == "scenario":
            print({"named": scenario.seed_named(), "orbita": scenario.seed_orbita()})
        else:
            print(demo.run_all())
        return 0
    finally:
        dispose_engine()


if __name__ == "__main__":
    sys.exit(main())
