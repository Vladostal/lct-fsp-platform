"""Выгрузка схем OpenAPI без запуска сервера: `python -m app.scripts.export_openapi` (Арх. 9.1, 7.3).

Пишет `docs/api/openapi.json` (платформа) и, если демо-ФСП уже есть, `docs/fsp-registry-openapi.json`. База не
нужна. Схема выгружается с включёнными демо-режимом и демо-ФСП: клиенту нужны и эти эндпоинты, а эндпоинты
усилений за флагами в схеме есть всегда. Файл сортируется по ключам, поэтому повторная выгрузка без изменений
кода даёт тот же файл. Команду запускает сборочный пакет (`make openapi`); руками файл не правится.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Окружение задаётся до импорта приложения: настройки читаются один раз. Секреты здесь — заглушки, в схему они
# не попадают; настоящие значения из окружения, если заданы, не перезаписываются.
os.environ.setdefault("ASSESSMENT_SECRET", "dev-only-openapi-export")
os.environ.setdefault("ADMIN_TOKEN", "dev-only-openapi-export")
os.environ["DEMO_MODE"] = "true"
os.environ["FSP_MOCK_ENABLED"] = "true"
os.environ["BACKGROUND_ENABLED"] = "false"
os.environ.setdefault("LOG_LEVEL", "warning")
# Модули пишутся параллельно: недостающий не должен мешать выгрузить остальные. Строгая выгрузка — явно:
# WIRING_STRICT=true make openapi.
os.environ.setdefault("WIRING_STRICT", "false")

from app import wiring
from app.core.config import REPO_ROOT
from app.main import app as platform_app

DEFAULT_PLATFORM_PATH = REPO_ROOT / "docs" / "api" / "openapi.json"
DEFAULT_FSP_PATH = REPO_ROOT / "docs" / "fsp-registry-openapi.json"


def dump(schema: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def platform_schema() -> dict[str, Any]:
    """Схема платформы (`/api/v1`). Смонтированное демо-ФСП в неё не входит: у него своя схема."""
    return platform_app.openapi()


def fsp_mock_schema() -> dict[str, Any] | None:
    """Схема демо-ФСП либо `None`, пока его приложения нет."""
    mock_app = wiring.try_load(wiring.FSP_MOCK_APP, strict=False, optional=True)
    if mock_app is None or not hasattr(mock_app, "openapi"):
        return None
    schema: dict[str, Any] = mock_app.openapi()
    return schema


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Выгрузить схемы OpenAPI платформы и демо-ФСП")
    parser.add_argument("--out", type=Path, default=DEFAULT_PLATFORM_PATH, help="файл схемы платформы")
    parser.add_argument("--fsp-out", type=Path, default=DEFAULT_FSP_PATH, help="файл схемы демо-ФСП")
    args = parser.parse_args(argv)

    schema = platform_schema()
    dump(schema, args.out)
    schemas = schema.get("components", {}).get("schemas", {})
    print(f"{args.out}: путей — {len(schema.get('paths', {}))}, схем — {len(schemas)}")

    mock = fsp_mock_schema()
    if mock is None:
        print("демо-ФСП ещё не подключён: его схема не выгружена", file=sys.stderr)
    else:
        dump(mock, args.fsp_out)
        print(f"{args.fsp_out}: путей — {len(mock.get('paths', {}))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
