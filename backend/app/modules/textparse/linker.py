"""`SkillLinker`: текст → упоминания навыков справочника (Арх. 6.14; приложение B, §1.4).

Одна реализация для резюме и для текста потребности. Чистая функция: справочник берётся из памяти
(`catalog.service`), в базу ничего не пишется; нераспознанные термины возвращаются вызывающему, а в
`skill_miss_log` их пишет `catalog.service.log_miss` с фильтром (поправка R3-data-api-security-5).

Шаги:

1. Нормализация копии текста: NFKC, `ё → е`, длинные тире → `-`, удаление символов нулевой ширины. Исходный
   регистр сохраняется для алиасов с регистром. Смещения упоминаний относятся к исходному тексту: каждому
   знаку копии сопоставлен знак оригинала.
2. Токены `\\.?[A-Za-zА-Яа-я0-9][A-Za-zА-Яа-я0-9+#./-]*` без хвостовых `. , / -`: так сохраняются `c++`, `c#`,
   `node.js`, `ci/cd`, `.net`.
3. Просмотр слева направо, окно 4 → 1 токен, побеждает самое длинное совпадение, совпадения не пересекаются.
   Для окна: (а) алиас в нижнем регистре (`exact`); (б) алиас с регистром — только в перечислении (`case`);
   (в) окно с кириллицей — леммы `pymorphy3` (`lemma`). Токены окна разделены только пробелами: запятая, точка
   и перевод строки окно разрывают («машинное, обучение» — не «машинное обучение»).
4. Опечатки: несовпавший латинский токен длиной ≥ 5 — `rapidfuzz.fuzz.ratio ≥ 90`; принимается, только если
   все кандидаты ведут к одному навыку (`fuzzy`). Слова из `STOP_TERMS` не сравниваются.
5. Составной токен, не найденный целиком (`HTML/CSS`, `Python-разработчик`), делится по `/`, `-` и `+` между
   буквами, и части ищутся отдельно.
6. Нераспознанные термины: латинские токены с заглавной буквой, цифрой или знаками `+#.`, не из `STOP_TERMS`,
   в контексте перечисления; до 10 штук, без повторов.

Контекст перечисления: строка из `enumeration_lines` либо строка с запятой, где найдено не меньше двух навыков.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from itertools import pairwise

from rapidfuzz import fuzz, process

from app.modules.catalog import service as catalog
from app.modules.textparse.dto import SkillMention
from app.modules.textparse.lexicon import STOP_TERMS, has_cyrillic, lemma_key

MAX_WINDOW = 4
FUZZY_MIN_LEN = 5
FUZZY_CUTOFF = 90
MAX_UNKNOWN_TERMS = 10
#: Знаки, которые NFKC не меняет, а разбору мешают: тире разной длины.
_DASHES = {"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-", "−": "-"}
_ZERO_WIDTH = {"​", "‌", "‍", "⁠", "﻿", "­", "\r"}

_TOKEN_RE = re.compile(r"\.?[A-Za-zА-Яа-я0-9][A-Za-zА-Яа-я0-9+#./-]*")
_SPLIT_RE = re.compile(r"[/-]|(?<=[A-Za-zА-Яа-я0-9])\+(?=[A-Za-zА-Яа-я0-9])")
_GAP_RE = re.compile(r"[ \t ]+")
_SUB_GAP_RE = re.compile(r"[ \t /+-]+")
_LATIN_RE = re.compile(r"[A-Za-z]")
_CYRILLIC_ANY_RE = re.compile(r"[А-Яа-я]")


@dataclass(frozen=True, slots=True)
class _Token:
    text: str  # с исходным регистром (в нормализованной копии)
    lower: str
    start: int  # смещения в нормализованной копии
    end: int
    line: int


@dataclass(frozen=True)
class _Index:
    exact: dict[str, str]
    case: dict[str, str]
    lemma: dict[str, str]
    fuzzy_choices: tuple[str, ...]
    fuzzy_codes: tuple[str, ...]


@lru_cache(maxsize=1)
def _index() -> _Index:
    """Индекс алиасов справочника (строится один раз; справочник неизменяем)."""
    exact: dict[str, str] = {}
    case: dict[str, str] = {}
    lemma: dict[str, str] = {}
    choices: list[str] = []
    codes: list[str] = []
    for skill in catalog.skill_entries():
        for alias in skill.aliases:
            exact[alias] = skill.code
            if has_cyrillic(alias):
                lemma.setdefault(lemma_key(alias.split()), skill.code)
            elif len(alias) >= FUZZY_MIN_LEN and " " not in alias and alias.isascii() and alias.isalpha():
                choices.append(alias)
                codes.append(skill.code)
        for alias in skill.case_aliases:
            case[alias] = skill.code
    return _Index(exact, case, lemma, tuple(choices), tuple(codes))


def _normalize(text: str) -> tuple[str, list[int]]:
    """Копия текста для разбора и карта «знак копии → знак оригинала»."""
    out: list[str] = []
    origin: list[int] = []
    for i, ch in enumerate(text):
        if ch in _ZERO_WIDTH:
            continue
        for piece in unicodedata.normalize("NFKC", ch):
            piece = _DASHES.get(piece, piece)
            piece = "е" if piece == "ё" else "Е" if piece == "Ё" else piece
            out.append(piece)
            origin.append(i)
    return "".join(out), origin


def _tokenize(norm: str) -> list[_Token]:
    tokens: list[_Token] = []
    line = 0
    cursor = 0
    for match in _TOKEN_RE.finditer(norm):
        line += norm.count("\n", cursor, match.start())
        cursor = match.start()
        raw = match.group().rstrip("./-")
        if not raw or raw == ".":
            continue
        tokens.append(_Token(raw, raw.lower(), match.start(), match.start() + len(raw), line))
    return tokens


def _fuzzy(token: _Token, index: _Index) -> str | None:
    """Навык по опечатке: все кандидаты с `ratio ≥ 90` должны вести к одному навыку."""
    word = token.lower
    if len(word) < FUZZY_MIN_LEN or word in STOP_TERMS or not word.isascii() or not word.isalpha():
        return None
    hits = process.extract(word, index.fuzzy_choices, scorer=fuzz.ratio, score_cutoff=FUZZY_CUTOFF, limit=5)
    found = {index.fuzzy_codes[position] for _, _, position in hits}
    return next(iter(found)) if len(found) == 1 else None


def _contiguous(window: list[_Token], gap: re.Pattern[str], norm: str) -> bool:
    """Токены окна разделены только допустимыми пробелами."""
    return all(gap.fullmatch(norm[a.end : b.start]) for a, b in pairwise(window))


def _match_window(window: list[_Token], index: _Index) -> tuple[str, str, bool] | None:
    """Код навыка, способ и признак «нужен контекст перечисления» для окна токенов."""
    key = " ".join(token.lower for token in window)
    if key in index.exact:
        return index.exact[key], "exact", False
    first = window[0]
    if first.lower.startswith("."):  # «...Python»: точка предложения прилипла к токену
        stripped = " ".join([first.lower.lstrip("."), *[t.lower for t in window[1:]]])
        if stripped in index.exact:
            return index.exact[stripped], "exact", False
    case_key = " ".join(token.text for token in window)
    if case_key in index.case:
        return index.case[case_key], "case", True
    if has_cyrillic(key):
        code = index.lemma.get(lemma_key(key.split()))
        if code is not None:
            return code, "lemma", False
    return None


def _scan(
    tokens: list[_Token], norm: str, index: _Index, gap: re.Pattern[str], max_window: int
) -> tuple[list[tuple[str, str, int, int, int, bool]], set[int]]:
    """Просмотр токенов: найденные (код, способ, начало, конец, строка, нужен ли контекст) и номера занятых токенов."""
    found: list[tuple[str, str, int, int, int, bool]] = []
    used: set[int] = set()
    i = 0
    while i < len(tokens):
        for size in range(min(max_window, len(tokens) - i), 0, -1):
            window = tokens[i : i + size]
            if size > 1 and not _contiguous(window, gap, norm):
                continue
            hit = _match_window(window, index)
            if hit is None:
                continue
            code, method, needs_context = hit
            found.append((code, method, window[0].start, window[-1].end, window[0].line, needs_context))
            used.update(range(i, i + size))
            i += size
            break
        else:
            i += 1
    return found, used


def _split_token(token: _Token) -> list[_Token]:
    """Части составного токена по `/`, `-` и `+` между буквами; позиции — в той же нормализованной копии."""
    parts: list[_Token] = []
    position = 0
    for match in [*_SPLIT_RE.finditer(token.text), None]:
        end = match.start() if match else len(token.text)
        piece = token.text[position:end]
        if piece:
            parts.append(_Token(piece, piece.lower(), token.start + position, token.start + end, token.line))
        position = match.end() if match else end
    return parts if len(parts) > 1 else []


def link(text: str, *, enumeration_lines: set[int] | None = None) -> tuple[list[SkillMention], list[str]]:
    """Упоминания навыков и нераспознанные термины (см. описание модуля)."""
    index = _index()
    norm, origin = _normalize(text)
    tokens = _tokenize(norm)
    found, used = _scan(tokens, norm, index, _GAP_RE, MAX_WINDOW)

    for position, token in enumerate(tokens):
        if position in used:
            continue
        sub_found: list[tuple[str, str, int, int, int, bool]] = []
        if parts := _split_token(token):
            sub_found, _ = _scan(parts, norm, index, _SUB_GAP_RE, 2)
        if sub_found:
            found.extend(sub_found)
            used.add(position)
        elif (code := _fuzzy(token, index)) is not None:
            found.append((code, "fuzzy", token.start, token.end, token.line, False))
            used.add(position)

    # Контекст перечисления: заданные строки и строки с запятой, где найдено не меньше двух навыков.
    per_line = Counter(line for _, method, _, _, line, _ in found if method != "case")
    lines = norm.split("\n")

    def in_enumeration(line: int) -> bool:
        if enumeration_lines is not None and line in enumeration_lines:
            return True
        return per_line[line] >= 2 and "," in lines[line]

    mentions = [
        SkillMention(
            skill_code=code,
            start=origin[start],
            end=origin[end - 1] + 1,
            surface=text[origin[start] : origin[end - 1] + 1],
            method=method,
        )
        for code, method, start, end, line, needs_context in sorted(found, key=lambda item: item[2])
        if not needs_context or in_enumeration(line)
    ]

    unknown: list[str] = []
    seen: set[str] = set()
    for position, token in enumerate(tokens):
        if position in used or len(unknown) >= MAX_UNKNOWN_TERMS:
            continue
        if _is_unknown_candidate(token, norm) and in_enumeration(token.line) and token.lower not in seen:
            seen.add(token.lower)
            unknown.append(text[origin[token.start] : origin[token.end - 1] + 1])
    return mentions, unknown


def _is_unknown_candidate(token: _Token, norm: str) -> bool:
    """Похоже на название технологии: латиница с заглавной буквой, цифрой или знаком `+#.`; не слово из стоп-списка."""
    word = token.text
    if _CYRILLIC_ANY_RE.search(word) or len(_LATIN_RE.findall(word)) < 2 or "/" in word:
        return False
    if token.lower in STOP_TERMS or word.lower().startswith(("www.", "http")):
        return False
    if token.start > 0 and norm[token.start - 1] in "@/:":  # хвост адреса или ссылки
        return False
    return any(ch.isupper() or ch.isdigit() or ch in "+#." for ch in word)
