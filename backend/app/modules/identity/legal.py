"""Тексты согласий и политики (Арх. 9.4 `GET /legal/{doc}`, 10.5).

Тексты лежат файлами `legal/<doc>.md`: первые строки — «ключ: значение» (`version`, `title`), затем строка `---`
и сам текст (абзацы разделены пустой строкой, строка с «#» — заголовок раздела). В согласии сохраняются версия и
SHA-256 текста, поэтому текст читается один раз на процесс: изменение файла без смены `version` обнаружит тест.

Текст согласия `fsp_data` здесь не лежит: им владеет модуль `fsp` (`GET /fsp/consent`).
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from app.modules.identity.dto import ConsentTextDTO
from app.shared.enums import ConsentKind

LEGAL_DIR = Path(__file__).resolve().parent / "legal"

#: Документы, которые отдаёт `GET /legal/{doc}`.
LEGAL_DOCS: tuple[str, ...] = ("processing", "publication", "privacy")

#: Какой документ является текстом согласия данного вида.
_CONSENT_DOCS: dict[ConsentKind, str] = {
    ConsentKind.PROCESSING: "processing",
    ConsentKind.PUBLICATION: "publication",
}

_SEPARATOR = "---"


def text_sha256(text: str) -> str:
    """SHA-256 текста согласия в hex — значение `consent.text_sha256`."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@lru_cache(maxsize=len(LEGAL_DOCS))
def _load(doc: str) -> ConsentTextDTO:
    raw = (LEGAL_DIR / f"{doc}.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    header, separator, body = raw.partition(f"\n{_SEPARATOR}\n")
    if not separator:
        raise ValueError(f"legal/{doc}.md: нет строки-разделителя «{_SEPARATOR}» между шапкой и текстом")
    meta: dict[str, str] = {}
    for line in header.splitlines():
        key, colon, value = line.partition(":")
        if colon:
            meta[key.strip()] = value.strip()
    missing = [key for key in ("version", "title") if not meta.get(key)]
    if missing:
        raise ValueError(f"legal/{doc}.md: в шапке нет полей {missing}")
    text = body.strip()
    return ConsentTextDTO(version=meta["version"], title=meta["title"], text=text, sha256=text_sha256(text))


def get_doc(doc: str) -> ConsentTextDTO | None:
    """Документ по имени из `LEGAL_DOCS` либо `None` для неизвестного имени."""
    if doc not in LEGAL_DOCS:
        return None
    return _load(doc)


def consent_text(kind: ConsentKind) -> ConsentTextDTO:
    """Действующий текст согласия вида `kind`. Для `fsp_data` — `LookupError`: текст принадлежит модулю `fsp`."""
    doc = _CONSENT_DOCS.get(ConsentKind(kind))
    if doc is None:
        raise LookupError(f"текст согласия «{kind}» хранит не identity: для fsp_data — модуль fsp (GET /fsp/consent)")
    return _load(doc)
