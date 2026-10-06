"""Обновление снимков ФСП для cron на стенде: `python -m app.scripts.fsp_resync --older-than-hours 168 --limit 200`.

Триггер синхронизации — `cli` (Арх. 7.5): последовательно, с паузой 100 мс между пользователями. Обновляются привязки
без снимка и со снимком старше заданного срока; сбой одного пользователя остальных не останавливает, данные при сбое
не меняются. В журнал пишутся только число пользователей и счётчик исходов, без идентификаторов.
"""

from __future__ import annotations

import argparse
import logging
import sys

from app.core.db import session_scope
from app.core.logging import setup_logging
from app.modules.fsp import service

log = logging.getLogger("app.fsp")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Обновить снимки ФСП (триггер cli)")
    parser.add_argument("--older-than-hours", type=float, default=168, help="обновлять снимки старше этого срока")
    parser.add_argument("--limit", type=int, default=200, help="не больше стольких пользователей за запуск")
    parser.add_argument("--pause", type=float, default=0.1, help="пауза между пользователями, секунд")
    args = parser.parse_args(argv)
    setup_logging("info")
    with session_scope() as db:
        outcomes = service.resync_batch(
            db, older_than_hours=args.older_than_hours, limit=args.limit, pause_s=args.pause
        )
    summary = ", ".join(f"{name}: {count}" for name, count in sorted(outcomes.items())) or "обновлять нечего"
    log.info("обновление снимков ФСП: %s", summary)
    print(f"fsp_resync: {summary}")
    return 1 if any(name.startswith("error:") for name in outcomes) else 0


if __name__ == "__main__":
    sys.exit(main())
