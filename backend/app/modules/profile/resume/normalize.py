"""Нормализация извлечённого текста резюме (приложение B, §1.5)."""

from __future__ import annotations

import re
import unicodedata

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿­"))
_HYPHEN_BREAK = re.compile(r"(?<=[^\W\d_])-[ \t]*\n[ \t]*(?=[^\W\d_])")
_SPACES = re.compile(r"[ \t\f\v]+")
_BLANK_RUNS = re.compile(r"\n{3,}")


def normalize(text: str) -> str:
    """NFKC; неразрывные пробелы → пробел; склейка переносов `-\\n` между буквами; пробелы внутри строки
    схлопываются; пустые строки сохраняются как границы абзацев (подряд идущие сводятся к одной).
    """
    text = unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", "\n").replace(" ", "\n")
    text = _HYPHEN_BREAK.sub("", text)
    lines = [_SPACES.sub(" ", line).strip() for line in text.split("\n")]
    return _BLANK_RUNS.sub("\n\n", "\n".join(lines)).strip("\n")
