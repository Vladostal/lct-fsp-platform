"""Разбор свободного текста потребности без LLM: `RuleNeedParser` (Арх. 6.14; приложение B, §2.2).

Чистая функция текста: в базу ничего не пишет, не читает время и случайные числа — один текст всегда даёт один
`NeedDraft`. К справочникам обращается только через память (`catalog.service`), в том числе за доступностью
пары «специализация — грейд»: недоступный тест даёт предупреждение `specialization_unavailable`, а не отказ.

Порядок (приложение B, §2.2): строки без маркеров списков → разделы по словарю заголовков → навыки по корзинам
→ голосование за специализацию → грейд → форматы и город → вилка → описание команды → заголовок.

Отличия от приложения B, которые вносит архитектура: грейд по стажу — пороги 1.5 и 4 года (Арх. 15.1 № 19);
специализация без теста не исключается из голосования, а помечается предупреждением (Арх. 6.14).
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal

from app.modules.catalog import service as catalog
from app.modules.textparse import lexicon
from app.modules.textparse.dto import NeedDraft
from app.modules.textparse.lexicon import lemma_key, norm_lower, words_of
from app.modules.textparse.linker import link

PARSER_VERSION = "need-rules-1"

#: Сколько навыков переносится из `nice` в `must`, если раздела требований нет.
MUST_FALLBACK_K = 3
MAX_MUST = 8
MAX_NICE = 12
MAX_UNKNOWN = 10
TITLE_MAX_LEN = 100
HEADING_MAX_LEN = 60
TEAM_MAX_LEN = 1000

Confidence = Literal["high", "medium", "low"]

#: Словарь заголовков разделов (приложение B, §2.2); сравнение по леммам.
_HEADINGS: dict[str, tuple[str, ...]] = {
    "required": (
        "требования", "требования к кандидату", "требования к навыкам", "мы ждем", "мы ждем от вас",
        "мы ожидаем", "мы ожидаем от вас", "что нужно", "нам важно", "обязательно", "необходимо",
        "requirements", "must have", "hard skills", "ключевые навыки", "ожидания", "наши ожидания", "от вас",
        "что от вас требуется", "что для этого нужно", "вы нам подходите, если",
    ),
    "nice": (
        "будет плюсом", "плюсом будет", "желательно", "приветствуется", "преимуществом будет", "будет преимуществом",
        "nice to have", "дополнительно", "будет плюс", "как плюс", "плюсом", "опционально",
    ),
    "tasks": (
        "обязанности", "задачи", "чем предстоит заниматься", "что нужно делать", "responsibilities",
        "чем вы будете заниматься", "что предстоит делать", "что вы будете делать", "ваши задачи", "основные задачи",
    ),
    "about": ("о компании", "о команде", "о проекте", "о нас", "about", "кто мы", "о продукте"),
    "offer": ("условия", "мы предлагаем", "что мы предлагаем", "we offer", "мы предложим", "предлагаем"),
}  # fmt: skip

#: Маркеры желательности в предложении: всё предложение уходит в `nice`.
_NICE_MARKER_RE = re.compile(
    r"будет плюсом|плюсом будет|плюсом|желательно|приветствуется|как плюс|опционально|nice to have|is a plus"
    r"|будет преимуществом|преимуществом будет|будет плюс"
)

_BULLET_RE = re.compile(r"^\s*(?:[•·▪●◦■□►▶]\s*|[*+\-–—]\s+|\d{1,2}[.)]\s+)")
_CLAUSE_RE = re.compile(r"(?<=[;!?])\s+|(?<=\.)\s+(?=[A-ZА-ЯЁ])")
_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿­\r"))

_YEARS_RE = re.compile(
    r"(?:от\s+)?(\d+(?:[.,]\d+)?)(?:\s*(?:-|до)\s*\d+(?:[.,]\d+)?)?\s*\+?\s*(?:лет|год\w*|years?|yrs?)\b"
)
_EXPERIENCE_RE = re.compile(r"опыт|стаж|experience")

_FORMATS = {
    "remote": re.compile(r"удаленн\w*|remote|дистанционн\w*|из дома"),
    "hybrid": re.compile(r"гибрид\w*|hybrid"),
    "office": re.compile(r"офис\w*|on-?site"),
}
_FORMAT_ORDER = ("office", "hybrid", "remote")


@dataclass
class _Chunk:
    """Фрагмент текста: предложение с известным разделом."""

    section: str
    body: str
    is_title: bool = False


@dataclass
class _Skills:
    must: list[str] = field(default_factory=list)
    nice: list[str] = field(default_factory=list)
    counts: Counter[str] = field(default_factory=Counter)
    in_title: set[str] = field(default_factory=set)
    unknown: list[str] = field(default_factory=list)
    has_required: bool = False
    fallback: bool = False


# ---------------------------------------------------------------------------------------------------------------------
# Строки и разделы
# ---------------------------------------------------------------------------------------------------------------------


def _clean(text: str) -> str:
    """NFKC, без символов нулевой ширины и `\\r`, тире — дефисом."""
    text = unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH)
    return re.sub(r"[‐‑‒–—―−]", "-", text)


@lru_cache(maxsize=1)
def _heading_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for section, phrases in _HEADINGS.items():
        for phrase in phrases:
            index.setdefault(lemma_key(words_of(phrase)), section)
    return index


def _heading_of(head: str) -> str | None:
    words = words_of(head)
    if not words or len(head.strip()) >= HEADING_MAX_LEN:
        return None
    return _heading_index().get(lemma_key(words))


def _match_heading(clause: str) -> tuple[str, str] | None:
    """Раздел и остаток предложения, если оно начинается с заголовка («Требования: …») или целиком им является."""
    colon = clause.find(":")
    if 0 < colon < HEADING_MAX_LEN and (section := _heading_of(clause[:colon])):
        return section, clause[colon + 1 :]
    bare = clause.strip().rstrip(":.-").strip()
    if bare and (section := _heading_of(bare)):
        return section, ""
    return None


def _split_text(text: str) -> tuple[str | None, list[_Chunk], dict[str, list[str]]]:
    """Заголовок вакансии, фрагменты с разделами и строки по разделам."""
    title: str | None = None
    chunks: list[_Chunk] = []
    by_section: dict[str, list[str]] = {}
    section = "head"
    first_seen = False
    for raw in text.split("\n"):
        line = _BULLET_RE.sub("", raw).strip()
        if not line:
            continue
        if not first_seen:
            first_seen = True
            if len(line) <= TITLE_MAX_LEN and _match_heading(line) is None:
                title = line
                chunks.append(_Chunk("head", line, is_title=True))
                continue
        for clause in _CLAUSE_RE.split(line):
            matched = _match_heading(clause)
            if matched:
                section, body = matched
            else:
                body = clause
            body = body.strip()
            if body:
                chunks.append(_Chunk(section, body))
                by_section.setdefault(section, []).append(body)
    return title, chunks, by_section


# ---------------------------------------------------------------------------------------------------------------------
# Навыки
# ---------------------------------------------------------------------------------------------------------------------


def _collect_skills(chunks: list[_Chunk]) -> _Skills:
    """Корзины навыков: маркер желательности → `nice`; иначе по разделу (требования и заголовок → `must`)."""
    kinds = {s.code: s.kind for s in catalog.skill_entries()}
    result = _Skills()
    must_seen: set[str] = set()
    nice_seen: set[str] = set()
    for chunk in chunks:
        result.has_required = result.has_required or chunk.section == "required"
        listed = chunk.section in ("required", "nice") or chunk.is_title
        mentions, unknown = link(chunk.body, enumeration_lines={0} if listed else None)
        for term in unknown:
            if term.lower() not in {u.lower() for u in result.unknown} and len(result.unknown) < MAX_UNKNOWN:
                result.unknown.append(term)
        marker = _NICE_MARKER_RE.search(norm_lower(chunk.body)) is not None
        for mention in mentions:
            code = mention.skill_code
            result.counts[code] += 1
            if chunk.is_title:
                result.in_title.add(code)
            as_must = not marker and (chunk.section == "required" or chunk.is_title) and kinds[code] != "soft"
            if as_must:
                if code not in must_seen:
                    must_seen.add(code)
                    result.must.append(code)
            elif code not in nice_seen:
                nice_seen.add(code)
                result.nice.append(code)
    result.nice = [code for code in result.nice if code not in must_seen]  # в обеих корзинах — остаётся `must`
    if not result.has_required and not result.must:
        _fallback_must(result, kinds)
    if len(result.must) > MAX_MUST:
        result.nice = [*result.must[MAX_MUST:], *result.nice]
        result.must = result.must[:MAX_MUST]
    result.nice = result.nice[:MAX_NICE]
    return result


def _fallback_must(result: _Skills, kinds: dict[str, str]) -> None:
    """Раздела требований нет: первые `MUST_FALLBACK_K` навыков (заголовок, число упоминаний, позиция) → `must`."""
    position = {code: i for i, code in enumerate(result.nice)}
    candidates = sorted(
        (code for code in result.nice if kinds[code] != "soft"),
        key=lambda code: (code not in result.in_title, -result.counts[code], position[code]),
    )
    chosen = candidates[:MUST_FALLBACK_K]
    if chosen:
        result.must = [code for code in result.nice if code in chosen]
        result.nice = [code for code in result.nice if code not in chosen]
        result.fallback = True


# ---------------------------------------------------------------------------------------------------------------------
# Грейд, форматы, вилка, описание
# ---------------------------------------------------------------------------------------------------------------------


def _years(chunks: list[_Chunk]) -> float | None:
    """Требуемый стаж: первое «N лет» в предложении, где речь об опыте."""
    for chunk in chunks:
        lowered = norm_lower(chunk.body)
        if not _EXPERIENCE_RE.search(lowered):
            continue
        match = _YEARS_RE.search(lowered)
        if match:
            return float(match.group(1).replace(",", "."))
    return None


def _grade(title: str | None, body: str, chunks: list[_Chunk]) -> tuple[str | None, list[str], Confidence | None]:
    """Грейд: заголовок → тело текста (без общих слов) → стаж."""
    if title:
        grade, alternatives = lexicon.grade_from_text(title)
        if grade:
            return grade, alternatives, "high"
    found = lexicon.grade_words(body, strict=True)
    if found:
        return found[0], found[1:], "medium"
    years = _years(chunks)
    if years is not None:
        return lexicon.grade_from_years(years), [], "low"
    return None, [], None


def _formats(chunks: list[_Chunk]) -> list[str]:
    """Форматы работы; «гибрид» в предложении снимает «офис» из него же («гибрид, 2 дня в офисе»)."""
    found: set[str] = set()
    for chunk in chunks:
        lowered = norm_lower(chunk.body)
        here = {name for name, pattern in _FORMATS.items() if pattern.search(lowered)}
        if "hybrid" in here:
            here.discard("office")
        found |= here
    return [name for name in _FORMAT_ORDER if name in found]


_NUM = r"(\d{1,3}(?: \d{3})+|\d+(?:[.,]\d+)?)"
_MULT = r"(?:\s*(тыс\.?|тр\.?|т\.\s?р\.?|к|k|млн\.?)(?![a-zа-я0-9]))?"
_RANGE_RE = re.compile(rf"(?:от\s*)?{_NUM}{_MULT}\s*(?:до|-)\s*{_NUM}{_MULT}")
_FROM_RE = re.compile(rf"\bот\s*{_NUM}{_MULT}")
_TO_RE = re.compile(rf"\bдо\s*{_NUM}{_MULT}")
_SALARY_CONTEXT_RE = re.compile(
    r"зарплат|оклад|вилка|з/п|\bзп\b|доход|на руки|до вычета|gross|\bnet\b|₽|руб|\bтыс"
    r"|\$|€|£|usd|eur|\brub\b|\d\s*[кk]\b"
)
_FOREIGN_RE = re.compile(r"\$|€|£|usd|eur|gbp|долл|евро")
_RUBLE_RE = re.compile(r"₽|руб|\brub\b|\bр\.|тыс\.?\s*р")


def _scale(mult: str | None) -> int:
    if mult is None:
        return 1
    return 1_000_000 if mult.startswith("млн") else 1000


def _amount(number: str, mult: str | None) -> float | None:
    """Сумма в рублях; число меньше 1000 без множителя — не деньги («от 2 лет»)."""
    value = float(number.replace(" ", "").replace(",", "."))
    if mult is None and value < 1000:
        return None
    return value * _scale(mult)


def _find_bounds(lowered: str) -> tuple[int | None, int | None] | None:
    """Границы вилки в предложении: `от X до Y`, `X-Y`, `от X`, `до Y`."""
    for match in _RANGE_RE.finditer(lowered):
        n1, m1, n2, m2 = match.groups()
        m1 = m1 or (m2 if float(n1.replace(" ", "").replace(",", ".")) < 1000 else None)  # «150-250 тыс.»
        low, high = _amount(n1, m1), _amount(n2, m2)
        if low is not None and high is not None:
            return round(low), round(high)
    low_match = _FROM_RE.search(lowered)
    high_match = _TO_RE.search(lowered)
    low = _amount(*low_match.groups()) if low_match else None
    high = _amount(*high_match.groups()) if high_match else None
    if low is None and high is None:
        return None
    return (round(low) if low is not None else None, round(high) if high is not None else None)


def _salary(chunks: list[_Chunk]) -> tuple[int | None, int | None, list[str]]:
    """Вилка в рублях и предупреждения `salary_currency` и `salary_single_bound`."""
    foreign = False
    for chunk in chunks:
        lowered = norm_lower(chunk.body)
        if not _SALARY_CONTEXT_RE.search(lowered):
            continue
        if _FOREIGN_RE.search(lowered) and not _RUBLE_RE.search(lowered):
            foreign = True
            continue
        bounds = _find_bounds(lowered)
        if bounds is None:
            continue
        low, high = bounds
        return low, high, ([] if low is not None and high is not None else ["salary_single_bound"])
    return None, None, (["salary_currency"] if foreign else [])


def _truncate(text: str, limit: int = TEAM_MAX_LEN) -> str:
    """Не длиннее `limit` знаков, по границе предложения (иначе — по границе слова)."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    ends = [m.end() for m in re.finditer(r"[.!?](?=\s|$)", cut)]
    if ends and ends[-1] >= limit // 3:
        return cut[: ends[-1]].strip()
    return cut.rsplit(" ", 1)[0].strip()


def _team(by_section: dict[str, list[str]]) -> str | None:
    """Описание команды: раздел «о команде», иначе «задачи», иначе вводный абзац (до первого заголовка)."""
    for section in ("about", "tasks", "head"):
        if by_section.get(section):
            return _truncate(" ".join(by_section[section]))
    return None


# ---------------------------------------------------------------------------------------------------------------------
# Сборка черновика
# ---------------------------------------------------------------------------------------------------------------------


def parse(text: str) -> NeedDraft:
    """Разобрать текст вакансии в черновик потребности (см. описание модуля)."""
    cleaned = _clean(text)
    title, chunks, by_section = _split_text(cleaned)
    skills = _collect_skills(chunks)
    confidence: dict[str, Confidence] = {}
    warnings: list[str] = []

    if title:
        confidence["title"] = "high"
    body_chunks = [c for c in chunks if not c.is_title]
    body_text = "\n".join(c.body for c in body_chunks)

    title_roles = lexicon.find_roles(title) if title else []
    voters = (title_roles, lexicon.find_roles(body_text), [*skills.must, *skills.nice])
    spec, margin = lexicon.vote_specialization(*voters)
    if spec:
        confidence["specialization_code"] = "high" if margin >= 0.5 else "medium"
    elif any(votes > 0 for votes in lexicon.vote_table(*voters).values()):
        warnings.append("spec_ambiguous")

    grade, alternatives, grade_confidence = _grade(title, body_text, chunks)
    if grade and grade_confidence:
        confidence["grade_code"] = grade_confidence

    if skills.must:
        confidence["must_skills"] = "low" if skills.fallback else ("high" if skills.has_required else "medium")
    if skills.nice:
        confidence["nice_skills"] = "medium"
    if not skills.must and not skills.nice:
        warnings.append("no_skills")

    formats = _formats(chunks)
    if formats:
        confidence["work_formats"] = "high"
    city = lexicon.find_city(cleaned)
    if city:
        confidence["city"] = "medium"

    salary_from, salary_to, salary_warnings = _salary(chunks)
    warnings.extend(salary_warnings)
    if salary_from is not None or salary_to is not None:
        confidence["salary"] = "high" if salary_from is not None and salary_to is not None else "medium"

    team = _team(by_section)
    if team:
        confidence["team_description"] = "medium"

    if spec and not (catalog.is_available(spec, grade) if grade else catalog.is_available(spec)):
        warnings.append("specialization_unavailable")

    return NeedDraft(
        title=title,
        team_description=team,
        specialization_code=spec,
        grade_code=grade,
        grade_alternatives=alternatives,
        must_skills=skills.must,
        nice_skills=skills.nice,
        work_formats=formats,
        city=city,
        salary_from=salary_from,
        salary_to=salary_to,
        confidence=confidence,
        unknown_terms=skills.unknown,
        warnings=warnings,
        parser="rules",
        parser_version=PARSER_VERSION,
    )
