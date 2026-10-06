"""Фасад модуля `reports` (Арх. 2.5). Другим модулям `reports` ничего не предоставляет.

Читает сводки отчётов валидации с диска: `<VALIDATION_DIR>/<механика>/report.json`, ключ `summary` (Арх. 9.4, 12).
Модуль не импортирует валидацию (Арх. 2.4, п. 7): между ними только файлы. Файлы небольшие и меняются редко
(их пишут команды `make eval-*`), поэтому разобранная секция кэшируется по времени изменения и размеру файла.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.modules.reports.schemas import ContactSummary, MatchingSummary, TestingSummary, ValidationSummary

log = logging.getLogger("app.reports")

#: Имя каталога механики → модель её секции.
SECTIONS: dict[str, type[BaseModel]] = {
    "testing": TestingSummary,
    "matching": MatchingSummary,
    "contact": ContactSummary,
}
REPORT_FILE = "report.json"

_cache: dict[Path, tuple[tuple[int, int], BaseModel | None]] = {}


def _read_section(path: Path, model: type[BaseModel]) -> BaseModel | None:
    """Секция из файла либо `None`: файла нет, он повреждён или `summary` не соответствует модели (в журнал)."""
    try:
        stat = path.stat()
    except OSError:
        _cache.pop(path, None)
        return None
    stamp = (stat.st_mtime_ns, stat.st_size)
    cached = _cache.get(path)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    section: BaseModel | None = None
    try:
        document: Any = json.loads(path.read_text(encoding="utf-8"))
        summary = document.get("summary") if isinstance(document, dict) else None
        if summary is None:
            log.warning("отчёт %s: нет секции summary", path)
        else:
            section = model.model_validate(summary)
    except (OSError, ValueError, ValidationError) as exc:
        log.warning("отчёт %s не прочитан: %s", path, str(exc)[:500])
    _cache[path] = (stamp, section)
    return section


def validation_summary() -> ValidationSummary:
    """Сводки отчётов трёх механик; отсутствующая секция — `None` (клиент показывает «отчёт не сформирован»)."""
    root = get_settings().validation_path
    sections = {name: _read_section(root / name / REPORT_FILE, model) for name, model in SECTIONS.items()}
    return ValidationSummary.model_validate(sections)
