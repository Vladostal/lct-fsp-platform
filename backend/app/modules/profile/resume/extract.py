"""Извлечение текста из PDF — работает в отдельном процессе (Арх. 10.7; приложение B, §1.5).

Файл самодостаточен: ничего из `app` он не импортирует (кроме стандартной библиотеки, `pypdf` и `pdfplumber`),
потому что дочерний процесс запускается как скрипт — `python -I -B extract.py '<параметры JSON>'` — и не должен
тянуть за собой приложение целиком: оно не уложилось бы в предел адресного пространства `RLIMIT_AS`.
Протокол: параметры — в `argv[1]` (JSON), байты PDF — в `stdin`, ответ — одна строка JSON в `stdout`:

* `{"ok": true, "engine": "pypdf" | "pdfplumber", "pages": N, "text": "…"}`;
* `{"ok": false, "error": "resume_encrypted" | "resume_too_many_pages" | "resume_no_text" | "resume_unreadable" |
  "resume_timeout"}`.

Родитель ждёт ответ не дольше бюджета и затем завершает процесс принудительно: одну «тяжёлую» страницу проверка
времени между страницами не остановила бы, а убитый процесс — остановит.
"""

from __future__ import annotations

import io
import json
import sys
import time
from typing import Any

#: Значения по умолчанию совпадают с `constants.py`; родитель всё равно передаёт свои в параметрах.
DEFAULTS: dict[str, Any] = {
    "budget_s": 5.0,
    "max_pages": 10,
    "page_char_limit": 20_000,
    "min_letters": 100,
    "min_letter_share": 0.5,
    "memory_bytes": 256 * 1024 * 1024,
    #: Порядок движков; в рабочем режиме всегда оба (параметр нужен тестам предела памяти второго движка).
    "engines": ["pypdf", "pdfplumber"],
}


class ExtractError(Exception):
    """Ошибка с кодом ответа API (`resume_*`)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def letter_stats(text: str) -> tuple[int, float]:
    """Число букв и их доля среди непробельных знаков."""
    letters = sum(1 for ch in text if ch.isalpha())
    visible = sum(1 for ch in text if not ch.isspace())
    return letters, (letters / visible if visible else 0.0)


def is_usable(text: str, min_letters: int, min_share: float) -> bool:
    """Пригодный текст: достаточно букв и их доля не меньше порога (скан даёт пустоту либо мусор)."""
    letters, share = letter_stats(text)
    return letters >= min_letters and share >= min_share


def _check_budget(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise ExtractError("resume_timeout")


def _with_pypdf(data: bytes, params: dict[str, Any], deadline: float) -> tuple[int, str]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data), strict=False)
    if reader.is_encrypted:
        raise ExtractError("resume_encrypted")
    total = len(reader.pages)
    if total > params["max_pages"]:
        raise ExtractError("resume_too_many_pages")
    limit = params["page_char_limit"]
    parts: list[str] = []
    for page in reader.pages:
        _check_budget(deadline)
        parts.append((page.extract_text() or "")[:limit])
    return total, "\n".join(parts)


def _with_pdfplumber(data: bytes, params: dict[str, Any], deadline: float) -> tuple[int, str]:
    import pdfplumber

    limit = params["page_char_limit"]
    parts: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        total = len(pdf.pages)
        if total > params["max_pages"]:
            raise ExtractError("resume_too_many_pages")
        for page in pdf.pages:
            _check_budget(deadline)
            parts.append((page.extract_text() or "")[:limit])
    return total, "\n".join(parts)


def extract(data: bytes, **overrides: Any) -> dict[str, Any]:
    """Двойной движок: `pypdf`, при непригодном тексте — `pdfplumber`; оба непригодны — `resume_no_text`.

    Любое исключение библиотек — `resume_unreadable`; если упал только первый движок, пробуем второй.
    """
    params = {**DEFAULTS, **overrides}
    deadline = time.monotonic() + float(params["budget_s"])
    min_letters, min_share = params["min_letters"], params["min_letter_share"]
    failures = 0
    pages = 0
    engines = {"pypdf": _with_pypdf, "pdfplumber": _with_pdfplumber}
    selected = [(name, engines[name]) for name in params["engines"]]
    for engine, run in selected:
        try:
            pages, text = run(data, params, deadline)
        except ExtractError:
            raise
        except MemoryError:
            raise
        except Exception:
            failures += 1
            continue
        if is_usable(text, min_letters, min_share):
            return {"ok": True, "engine": engine, "pages": pages, "text": text}
    if failures == len(selected):
        raise ExtractError("resume_unreadable")
    raise ExtractError("resume_no_text")


def _limit_memory(limit: int) -> None:
    """Предел адресного пространства процесса. Где `RLIMIT_AS` не поддерживается (macOS) — тихо пропускается:
    предел проверяется в контейнере `api` (Linux).
    """
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except (ImportError, ValueError, OSError):
        pass


def _selftest_memory() -> dict[str, Any]:
    """Проверка предела памяти: пытается занять вдвое больше разрешённого."""
    try:
        import resource

        soft = resource.getrlimit(resource.RLIMIT_AS)[0]
    except (ImportError, ValueError, OSError):
        return {"limit": None, "allocated": None}
    try:
        block = bytearray(int(soft) * 2) if soft > 0 else b""
    except MemoryError:
        return {"limit": soft, "allocated": False}
    return {"limit": soft, "allocated": len(block) > 0}


def main(argv: list[str]) -> int:
    params = {**DEFAULTS, **(json.loads(argv[1]) if len(argv) > 1 else {})}
    _limit_memory(int(params["memory_bytes"]))
    try:
        if len(argv) > 2 and argv[2] == "--selftest-memory":
            result: dict[str, Any] = _selftest_memory()
        else:
            result = extract(sys.stdin.buffer.read(), **params)
    except ExtractError as exc:
        result = {"ok": False, "error": exc.code}
    except MemoryError:
        result = {"ok": False, "error": "resume_unreadable"}
    except Exception:
        result = {"ok": False, "error": "resume_unreadable"}
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
