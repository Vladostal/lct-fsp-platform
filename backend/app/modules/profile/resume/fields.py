"""Поля резюме, которые находятся правилами без справочников (приложение B, §1.5).

Всё здесь — чистые функции над строками нормализованного текста: ни базы, ни фасадов других модулей. Поля, которым
нужен справочник (роли, навыки, грейд, специализация), собирает `parser.py`.

У каждого результата есть `confidence` и `snippet` — строка-источник не длиннее 120 знаков. Все выражения
регистронезависимы и работают с Unicode; регистр сохраняется там, где он часть признака (имена, города).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from itertools import pairwise
from typing import Literal

from app.modules.profile import validation
from app.modules.profile.constants import ABOUT_MAX, EXPERIENCE_MAX_YEARS
from app.modules.profile.resume.sections import SECTION_HEADINGS, heading_of
from app.shared.contact_method import normalize_email

Confidence = Literal["high", "medium", "low"]
SNIPPET_MAX = 120
_FLAGS = re.IGNORECASE | re.UNICODE


@dataclass(frozen=True)
class Found:
    """Найденное значение: само значение, уверенность и строка-источник."""

    value: str | float
    confidence: Confidence
    snippet: str | None


def snippet_of(line: str) -> str:
    line = " ".join(line.split())
    return line if len(line) <= SNIPPET_MAX else line[: SNIPPET_MAX - 1] + "…"


# --- e-mail, телефон, Telegram, ссылка -------------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", _FLAGS)
# Перед номером не цифра: иначе «8» в конце года («2018») начинало бы «телефон» из следующих за ним чисел.
_PHONE_RU_RE = re.compile(r"(?<!\d)(?:\+7|8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\d)", _FLAGS)
_PHONE_ANY_RE = re.compile(r"\+\d[\d\s()-]{8,16}", _FLAGS)
_TG_LINK_RE = re.compile(r"t\.me/([A-Za-z0-9_]{5,32})", _FLAGS)
_TG_AT_RE = re.compile(r"(?<![\w.@])@([A-Za-z0-9_]{5,32})(?![\w@]|\.\w)", _FLAGS)
_TG_WORDS_RE = re.compile(r"telegram|\btg\b|телеграм|\bтг\b", _FLAGS)
_URL_RE = re.compile(
    r"(?:https?://|www\.)[^\s<>\"']+|(?:github\.com|gitlab\.com|career\.habr\.com|linkedin\.com)/[^\s<>\"']+", _FLAGS
)
_LINK_PRIORITY = ("github.com", "gitlab.com", "career.habr.com", "linkedin.com")
#: Продолжение адреса, перенесённое на следующую строку: одно слово без пробелов.
_URL_TAIL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._~-]{1,60}")
_TRAILING = ".,;:)]}»"


def find_email(lines: Sequence[str]) -> Found | None:
    for line in lines:
        for match in _EMAIL_RE.finditer(line):
            email = normalize_email(match.group(0))
            if email:
                return Found(email, "high", snippet_of(line))
    return None


def find_phone(lines: Sequence[str]) -> Found | None:
    """Телефон: сначала в отдельных строках, затем в парах соседних строк.

    Второй проход нужен резюме в две колонки: узкая колонка контактов рвёт номер переносом («8 912 345 67» и
    «89» на следующей строке). Уверенность у склеенного номера ниже.
    """
    joined = [f"{first} {second}" for first, second in pairwise(lines)]
    passes: tuple[tuple[Sequence[str], Confidence], ...] = ((lines, "high"), (joined, "medium"))
    for candidates, confidence in passes:
        for pattern in (_PHONE_RU_RE, _PHONE_ANY_RE):
            for line in candidates:
                for match in pattern.finditer(line):
                    try:
                        phone = validation.phone(match.group(0).strip())
                    except ValueError:
                        continue
                    if phone:
                        return Found(phone, confidence, snippet_of(line))
    return None


def find_telegram(lines: Sequence[str], head: Sequence[str]) -> Found | None:
    for line in lines:
        link = _TG_LINK_RE.search(line)
        if link:
            return Found("@" + link.group(1), "high", snippet_of(line))
    head_set = set(head)
    for line in lines:
        match = _TG_AT_RE.search(line)
        if match is None:
            continue
        if _TG_WORDS_RE.search(line):
            return Found("@" + match.group(1), "high", snippet_of(line))
        if line in head_set:
            return Found("@" + match.group(1), "medium", snippet_of(line))
    return None


def find_link(lines: Sequence[str]) -> Found | None:
    """Первая ссылка по приоритету доменов: github, gitlab, habr, linkedin, прочие. Без схемы — `https://`."""
    best: tuple[int, str, str] | None = None
    for index, line in enumerate(lines):
        for match in _URL_RE.finditer(line):
            url = match.group(0).rstrip(_TRAILING)
            if "@" in url:
                continue
            # Адрес оборван переносом строки сразу после «/»: хвост — одиночное слово на следующей строке.
            # Слово с заглавной буквы или заголовок раздела («Skills», «Summary») хвостом адреса не считается.
            tail = lines[index + 1].strip() if index + 1 < len(lines) else ""
            wrapped = url.endswith("/") and match.end() == len(line.rstrip()) and _URL_TAIL_RE.fullmatch(tail)
            if wrapped and tail == tail.lower() and heading_of(tail) is None:
                url += tail
            if not url.lower().startswith("http"):
                url = "https://" + url
            try:
                url = validation.link(url) or ""
            except ValueError:
                continue
            if not url:
                continue
            host = url.split("/")[2].lower().removeprefix("www.")
            rank = _LINK_PRIORITY.index(host) if host in _LINK_PRIORITY else len(_LINK_PRIORITY)
            if best is None or rank < best[0]:
                best = (rank, url, snippet_of(line))
    return Found(best[1], "high", best[2]) if best else None


# --- ФИО -------------------------------------------------------------------------------------------------------------

_NAME_WORD_RE = re.compile(r"^[A-ZА-ЯЁ][a-zа-яё]+(?:-[A-ZА-ЯЁ][a-zа-яё]+)?$")
#: То же слово, набранное прописными: «ДАРЬЯ», «ОРЛОВА-ПЕТРОВА».
_NAME_CAPS_RE = re.compile(r"^[A-ZА-ЯЁ]{2,}(?:-[A-ZА-ЯЁ]{2,})?$")
_NAME_STOP = frozenset(
    {"резюме", "curriculum", "vitae", "cv", "resume"}
    | {word for headings in SECTION_HEADINGS.values() for heading in headings for word in heading.split()}
)
_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")


@dataclass(frozen=True)
class NameCandidate:
    words: tuple[str, ...]
    line: str


def name_candidate(head: Sequence[str]) -> NameCandidate | None:
    """Первая из восьми первых непустых строк `head`, похожая на ФИО: 2–3 слова с заглавной буквы, без цифр и `@`,
    без слов стоп-списка («резюме», названия разделов).
    """
    for line in [item for item in head if item.strip()][:8]:
        words = line.replace(",", " ").split()
        if not 2 <= len(words) <= 3 or any(ch.isdigit() or ch == "@" for ch in line):
            continue
        if any(word.lower() in _NAME_STOP for word in words):
            continue
        if all(_NAME_WORD_RE.match(word) for word in words):
            return NameCandidate(tuple(words), line)
        if all(_NAME_CAPS_RE.match(word) for word in words):
            # Прописными в резюме набирают и заголовки («ЯЗЫКИ ПРОГРАММИРОВАНИЯ»). Кириллическая строка считается
            # именем, только если словарь узнаёт в ней имя или фамилию; без словаря — не считается.
            # Латиница прописными не принимается вовсе: словаря имён для неё нет, а «CONTACT INFORMATION»
            # от «JOHN SMITH» по форме не отличить.
            titled = tuple("-".join(part.capitalize() for part in word.split("-")) for word in words)
            if not _CYRILLIC_RE.search(line) or not any({"Name", "Surn"} & _tags(word) for word in titled):
                continue
            return NameCandidate(titled, line)
    return None


def name_by_dictionary(lines: Sequence[str], limit: int = 40) -> tuple[NameCandidate, str | None] | None:
    """Запасной поиск ФИО вне шапки — для резюме в две колонки, где текст начинается с колонки контактов.

    Среди первых `limit` непустых строк берётся строка из 2–3 слов, в которой словарь узнаёт и имя, и фамилию.
    Вместе с кандидатом возвращается следующая строка: в таких резюме под именем стоит должность.
    """
    for index, line in enumerate(lines[:limit]):
        candidate = name_candidate([line])
        if candidate is None or not _CYRILLIC_RE.search(line):
            continue
        tags = [_tags(word) for word in candidate.words]
        has_name = any("Name" in found for found in tags)
        has_surname = any("Surn" in found for found in tags)
        if has_name and has_surname:
            return candidate, (lines[index + 1] if index + 1 < len(lines) else None)
    return None


@lru_cache(maxsize=1)
def _morph() -> object | None:
    try:
        import pymorphy3

        return pymorphy3.MorphAnalyzer()
    except Exception:  # словарей нет или библиотека недоступна: работает порядок слов
        return None


def _tags(word: str) -> set[str]:
    """Метки `Surn`, `Name`, `Patr`, возможные у слова (`pymorphy3`); пусто, если анализатора нет."""
    morph = _morph()
    if morph is None:
        return set()
    found: set[str] = set()
    for variant in morph.parse(word):  # type: ignore[attr-defined]
        for tag in ("Surn", "Name", "Patr"):
            if tag in variant.tag:
                found.add(tag)
    return found


def split_name(candidate: NameCandidate) -> dict[str, Found]:
    """Распределить слова по `last_name`, `first_name`, `middle_name`.

    Кириллица: роль слова определяют метки `pymorphy3`; уверенность `high`, если определены и имя, и фамилия.
    Меток нет — порядок «Фамилия Имя Отчество» при трёх словах и «Имя Фамилия» при двух (`medium`).
    Латиница: «Имя Фамилия».
    """
    words = list(candidate.words)
    snippet = snippet_of(candidate.line)
    roles: dict[str, str] = {}
    confidence: Confidence = "medium"
    if _CYRILLIC_RE.search(candidate.line):
        tagged = {word: _tags(word) for word in words}
        patronymic = next((w for w in words if "Patr" in tagged[w]), None)
        rest = [w for w in words if w != patronymic]
        surname = next((w for w in rest if "Surn" in tagged[w]), None)
        name = next((w for w in rest if "Name" in tagged[w] and w != surname), None)
        if surname and name and (len(words) == 2 or patronymic):
            roles = {"last_name": surname, "first_name": name}
            if patronymic:
                roles["middle_name"] = patronymic
            confidence = "high"
        elif len(words) == 3:
            roles = {"last_name": words[0], "first_name": words[1], "middle_name": words[2]}
        else:
            roles = {"first_name": words[0], "last_name": words[1]}
    else:
        roles = {"first_name": words[0], "last_name": words[-1]}
    return {key: Found(value, confidence, snippet) for key, value in roles.items()}


# --- город -----------------------------------------------------------------------------------------------------------

_CITY_RE = re.compile(r"(?i:проживает|город|г\.)\s*:?\s*([А-ЯЁ][а-яё-]+(?:\s[А-ЯЁ][а-яё-]+)?)")


def find_city_by_label(lines: Sequence[str]) -> Found | None:
    """Город после слов «проживает», «город», «г.». Поиск по первой лемме из списка городов — в `parser.py`."""
    for line in lines:
        match = _CITY_RE.search(line)
        if match:
            try:
                city = validation.city(match.group(1))
            except ValueError:
                continue
            if city:
                return Found(city, "high", snippet_of(line))
    return None


# --- стаж ------------------------------------------------------------------------------------------------------------

_EXPLICIT_RES = (
    re.compile(r"опыт\s+работы\s*[—–:-]?\s*(\d{1,2})\s*(?:год|года|лет)(?:\s*(\d{1,2})\s*мес\w*)?", _FLAGS),
    re.compile(r"стаж\s*:?\s*(\d{1,2})", _FLAGS),
    re.compile(r"(\d{1,2})\+?\s*years?\s+of\s+experience", _FLAGS),
)
_MONTHS = {
    **{
        name: number
        for number, name in enumerate(
            ("янв", "фев", "мар", "апр", "ма", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"), 1
        )
    },
    **{
        name: number
        for number, name in enumerate(
            ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1
        )
    },
}
_NOW = r"настоящее\s+время|по\s+наст\w*|н\.\s?в\.|present|now|current"
_SEP = r"\s*[—–-]\s*"
_INTERVAL_RES = (
    re.compile(
        rf"(?P<m1>[A-Za-zА-Яа-яЁё]{{3,9}})\.?\s+(?P<y1>(?:19|20)\d{{2}}){_SEP}"
        rf"(?:(?P<m2>[A-Za-zА-Яа-яЁё]{{3,9}})\.?\s+(?P<y2>(?:19|20)\d{{2}})|(?P<now>{_NOW}))",
        _FLAGS,
    ),
    re.compile(
        rf"(?P<m1>\d{{2}})\.(?P<y1>(?:19|20)\d{{2}}){_SEP}(?:(?P<m2>\d{{2}})\.(?P<y2>(?:19|20)\d{{2}})|(?P<now>{_NOW}))",
        _FLAGS,
    ),
    re.compile(rf"(?P<y1>(?:19|20)\d{{2}}){_SEP}(?:(?P<y2>(?:19|20)\d{{2}})|(?P<now>{_NOW}))", _FLAGS),
)


def _month_number(token: str | None) -> int | None:
    if token is None:
        return None
    if token.isdigit():
        value = int(token)
        return value if 1 <= value <= 12 else None
    low = token.lower()
    for prefix, number in _MONTHS.items():
        if low.startswith(prefix):
            return number
    return None


def _round_years(months: float) -> float:
    return min(float(EXPERIENCE_MAX_YEARS), round(months / 12 * 2) / 2)


def date_intervals(line: str, today: date) -> list[tuple[int, int]]:
    """Интервалы работы строки как пары «номер месяца» (год·12 + месяц − 1), конец включительно."""
    result: list[tuple[int, int]] = []
    for index, pattern in enumerate(_INTERVAL_RES):
        for match in pattern.finditer(line):
            groups = match.groupdict()
            year1 = int(groups["y1"])
            month1 = _month_number(groups.get("m1")) if index < 2 else 1
            if month1 is None:
                continue
            if groups.get("now"):
                end = today.year * 12 + today.month - 1
            else:
                month2 = _month_number(groups.get("m2")) if index < 2 else 12
                if month2 is None:
                    continue
                end = int(groups["y2"]) * 12 + month2 - 1
            start = year1 * 12 + month1 - 1
            if end >= start and start >= 1950 * 12:
                result.append((start, end))
    return result


def merge_months(intervals: Sequence[tuple[int, int]]) -> int:
    """Сумма месяцев по объединению интервалов: пересечения и стыки сливаются."""
    total = 0
    current: tuple[int, int] | None = None
    for start, end in sorted(intervals):
        if current is None or start > current[1] + 1:
            if current is not None:
                total += current[1] - current[0] + 1
            current = (start, end)
        else:
            current = (current[0], max(current[1], end))
    if current is not None:
        total += current[1] - current[0] + 1
    return total


def find_experience(lines: Sequence[str], experience_lines: Sequence[str], today: date) -> Found | None:
    """Стаж: явная сумма (`high`) либо объединение интервалов дат раздела «опыт» (`medium`); шаг 0,5, потолок 40."""
    for line in lines:
        for pattern in _EXPLICIT_RES:
            match = pattern.search(line)
            if match:
                years = int(match.group(1))
                months = int(match.group(2)) if match.lastindex and match.lastindex >= 2 and match.group(2) else 0
                return Found(_round_years(years * 12 + months), "high", snippet_of(line))
    intervals: list[tuple[int, int]] = []
    first_line = None
    for line in experience_lines:
        found = date_intervals(line, today)
        if found and first_line is None:
            first_line = line
        intervals.extend(found)
    if intervals:
        return Found(_round_years(merge_months(intervals)), "medium", snippet_of(first_line or ""))
    return None


# --- «О себе» --------------------------------------------------------------------------------------------------------

_SENTENCE_END_RE = re.compile(r"[.!?…](?=\s|$)")


def find_about(about_lines: Sequence[str]) -> Found | None:
    """Текст раздела «о себе», не длиннее 1000 знаков, обрезка по границе предложения."""
    text = " ".join(line.strip() for line in about_lines if line.strip())
    if not text:
        return None
    if len(text) > ABOUT_MAX:
        head = text[:ABOUT_MAX]
        ends = [m.end() for m in _SENTENCE_END_RE.finditer(head)]
        text = head[: ends[-1]] if ends and ends[-1] >= ABOUT_MAX // 3 else head.rstrip()
    return Found(text, "high", snippet_of(text))


# --- грейд по словарю ------------------------------------------------------------------------------------------------

_GRADE_RES = (
    ("senior", re.compile(r"\b(?:senior|сеньор\w*|синьор\w*|старш\w*|ведущ\w*|lead|лид\w*|principal)\b", _FLAGS)),
    ("middle", re.compile(r"\b(?:middle|мидл\w*|миддл\w*)\b", _FLAGS)),
    ("junior", re.compile(r"\b(?:junior|джун\w*|младш\w*|стаж[её]р\w*|intern)\b", _FLAGS)),
)


def grade_by_dictionary(text: str) -> str | None:
    """Грейд по словарю: самое раннее вхождение в тексте; нет совпадений — `None`."""
    best: tuple[int, str] | None = None
    for grade, pattern in _GRADE_RES:
        match = pattern.search(text)
        if match and (best is None or match.start() < best[0]):
            best = (match.start(), grade)
    return best[1] if best else None
