"""Разбор резюме: процесс извлечения текста и правила полей (Арх. 6.14, 10.7; приложение B, §1.5).

Две части с разной ценой ошибки:

* `run_extract` запускает `extract.py` отдельным процессом и ждёт его не дольше бюджета (5 с), затем завершает
  принудительно; одновременно работают не больше двух таких процессов, остальные ждут очереди 10 с, потом 429;
* `build_result` — быстрые правила над готовым текстом в процессе API: поля без справочников (`fields.py`) и поля,
  которым нужны фасады `catalog` и `textparse` (роли, навыки, грейд, специализация, город по списку).

Нераспознанные термины в `skill_miss_log` не пишутся вовсе (поправка рецензии R3-data-api-security-5): в тексте резюме
телефоны, адреса и фамилии, а таблица не привязана к пользователю и не удаляется вместе с ним.
"""

from __future__ import annotations

import bisect
import json
import logging
import os
import subprocess
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from app.modules.catalog import service as catalog
from app.modules.profile import validation
from app.modules.profile.constants import (
    DECLARED_SKILLS_MAX,
    DECLARED_SOFT_SKILLS_MAX,
    RESUME_CHILD_MEMORY_BYTES,
    RESUME_FIELDS_TOTAL,
    RESUME_MAX_PAGES,
    RESUME_MIN_LETTER_SHARE,
    RESUME_MIN_LETTERS,
    RESUME_PAGE_CHAR_LIMIT,
    RESUME_PARSE_BUDGET_S,
    RESUME_PARSE_CONCURRENCY,
    RESUME_PARSER_VERSION,
    RESUME_QUEUE_WAIT_S,
    ROLES_MAX,
    SOFT_KIND,
)
from app.modules.profile.resume import fields as rules
from app.modules.profile.resume.fields import Confidence, Found
from app.modules.profile.resume.normalize import normalize
from app.modules.profile.resume.sections import split_sections
from app.modules.profile.schemas import ResumeField, ResumeMeta
from app.modules.textparse import service as textparse
from app.shared.schemas import Ref

log = logging.getLogger(__name__)

EXTRACT_SCRIPT = Path(__file__).with_name("extract.py")

#: Код ошибки → (HTTP-статус, текст для пользователя). Коды `resume_too_large`, `resume_not_pdf`
#: и `resume_rate_limited` поднимает загрузка до разбора.
ERRORS: dict[str, tuple[int, str]] = {
    "resume_too_large": (413, "Файл больше 5 МБ"),
    "resume_not_pdf": (415, "Нужен файл в формате PDF"),
    "resume_rate_limited": (429, "Слишком много загрузок резюме. Попробуйте позже"),
    "resume_encrypted": (422, "PDF защищён паролем. Снимите защиту и загрузите файл снова"),
    "resume_too_many_pages": (422, "В резюме больше 10 страниц"),
    "resume_no_text": (422, "В файле нет текста: похоже, это скан. Заполните профиль вручную"),
    "resume_unreadable": (422, "Не удалось прочитать файл. Заполните профиль вручную"),
    "resume_timeout": (422, "Файл разбирается слишком долго. Заполните профиль вручную"),
}


class ResumeFailure(Exception):
    """Разбор не удался; `code` — код ответа API из `ERRORS`."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# --- процесс извлечения текста ---------------------------------------------------------------------------------------

_SLOTS = threading.BoundedSemaphore(RESUME_PARSE_CONCURRENCY)


def _params(budget_s: float, memory_bytes: int, engines: Sequence[str] = ("pypdf", "pdfplumber")) -> dict[str, Any]:
    return {
        "engines": list(engines),
        "budget_s": budget_s,
        "max_pages": RESUME_MAX_PAGES,
        "page_char_limit": RESUME_PAGE_CHAR_LIMIT,
        "min_letters": RESUME_MIN_LETTERS,
        "min_letter_share": RESUME_MIN_LETTER_SHARE,
        "memory_bytes": memory_bytes,
    }


def _run_child(
    stdin: bytes, params: dict[str, Any], *, budget_s: float, extra_args: Sequence[str] = ()
) -> dict[str, Any] | None:
    """Запустить `extract.py` и получить его ответ; `None` — процесс не уложился в бюджет (убит) либо упал."""
    command = [sys.executable, "-I", "-B", str(EXTRACT_SCRIPT), json.dumps(params), *extra_args]
    # Окружение пустое: дочернему процессу не нужны ни секреты приложения, ни адрес базы.
    env = {"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8", "PYTHONIOENCODING": "utf-8"}
    with subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env
    ) as process:
        try:
            out, _ = process.communicate(stdin, timeout=budget_s)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise ResumeFailure("resume_timeout") from None
    try:
        parsed = json.loads(out.decode("utf-8")) if out else None
    except (UnicodeDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def run_extract(
    data: bytes, *, budget_s: float = RESUME_PARSE_BUDGET_S, memory_bytes: int = RESUME_CHILD_MEMORY_BYTES
) -> dict[str, Any]:
    """Извлечь текст PDF в отдельном процессе: `{"engine", "pages", "text"}` либо `ResumeFailure`.

    Очередь: не больше `RESUME_PARSE_CONCURRENCY` процессов одновременно; ожидание свободного места — до
    `RESUME_QUEUE_WAIT_S`, затем `ResumeFailure("resume_rate_limited")` (429). Время очереди в бюджет разбора не входит.
    """
    if not _SLOTS.acquire(timeout=RESUME_QUEUE_WAIT_S):
        raise ResumeFailure("resume_rate_limited")
    try:
        answer = _run_child(data, _params(budget_s, memory_bytes), budget_s=budget_s)
    finally:
        _SLOTS.release()
    if answer is None:
        raise ResumeFailure("resume_unreadable")  # процесс упал (например, не хватило памяти)
    if not answer.get("ok"):
        code = answer.get("error")
        raise ResumeFailure(code if isinstance(code, str) and code in ERRORS else "resume_unreadable")
    return answer


# --- разбор текста ---------------------------------------------------------------------------------------------------


@dataclass
class ParsedResume:
    fields: dict[str, ResumeField]
    recognized: int
    unknown_terms: list[str]
    meta: ResumeMeta


def _field(found: Found | None) -> ResumeField | None:
    return ResumeField(value=found.value, confidence=found.confidence, snippet=found.snippet) if found else None


def _safely[T](name: str, call: Callable[[], T], default: T) -> T:
    """Обогащение из фасада — предзаполнение, а не обязательство: сбой соседнего модуля поля не убивает."""
    try:
        return call()
    except Exception:
        log.warning("resume: шаг «%s» пропущен из-за ошибки", name, exc_info=True)
        return default


def _catalog_indexes() -> tuple[dict[str, Any], dict[str, Ref], set[str]]:
    data = catalog.get_catalog()
    return {s.code: s for s in data.skills}, {r.code: r for r in data.roles}, {g.code for g in data.grades}


def _job_titles(experience: list[tuple[int, str]], lines: list[str], today: date) -> list[tuple[int, str]]:
    """Строки-должности раздела «опыт»: строка сразу после интервала дат. Возвращает `(конец интервала, строка)`."""
    titles: list[tuple[int, str]] = []
    for index, line in experience:
        intervals = rules.date_intervals(line, today)
        if not intervals:
            continue
        for follow in range(index + 1, min(index + 3, len(lines))):
            if lines[follow].strip():
                titles.append((max(end for _, end in intervals), lines[follow]))
                break
    return titles


def _skills(
    text: str,
    lines: list[str],
    enumeration: set[int],
    skills_section: set[int],
    skill_index: dict[str, Any],
) -> tuple[ResumeField | None, ResumeField | None, list[str], list[str]]:
    """Навыки и софт-скиллы через `SkillLinker`; порядок — сначала найденные в разделе «навыки», затем по числу
    упоминаний. Возвращает поля `declared_skills`, `soft_skills`, коды навыков (для голосования), нераспознанное.
    """
    mentions, unknown = textparse.link_skills(text, enumeration_lines=enumeration or None)
    starts: list[int] = []
    offset = 0
    for line in lines:
        starts.append(offset)
        offset += len(line) + 1
    first: dict[str, int] = {}
    count: Counter[str] = Counter()
    in_section: dict[str, bool] = {}
    fuzzy_only: dict[str, bool] = {}
    for mention in mentions:
        code = mention.skill_code
        if code not in skill_index:
            continue
        count[code] += 1
        first.setdefault(code, mention.start)
        line_index = bisect.bisect_right(starts, mention.start) - 1
        if line_index in skills_section and mention.method != "fuzzy":
            in_section[code] = True
        fuzzy_only[code] = fuzzy_only.get(code, True) and mention.method == "fuzzy"
    ordered = sorted(count, key=lambda c: (not in_section.get(c, False), -count[c], first[c]))
    hard = [c for c in ordered if skill_index[c].kind != SOFT_KIND][:DECLARED_SKILLS_MAX]
    soft = [c for c in ordered if skill_index[c].kind == SOFT_KIND][:DECLARED_SOFT_SKILLS_MAX]

    def make(codes: list[str]) -> ResumeField | None:
        if not codes:
            return None
        confidence: Confidence
        if any(in_section.get(c) for c in codes):
            confidence = "high"
        elif all(fuzzy_only.get(c) for c in codes):
            confidence = "low"
        else:
            confidence = "medium"
        titles = ", ".join(skill_index[c].title for c in codes[:6])
        return ResumeField(
            value=[Ref(code=c, title=skill_index[c].title) for c in codes],
            confidence=confidence,
            snippet=rules.snippet_of(titles),
        )

    return make(hard), make(soft), list(count), list(unknown)[:10]


def build_result(text: str, *, today: date, pages: int, engine: str, started: float) -> ParsedResume:
    """Все поля `ResumeParseResult` из нормализованного текста. `today` нужен для «по настоящее время»."""
    text = normalize(text)
    lines = text.split("\n")
    sections = split_sections(lines)
    head = [line for _, line in sections["head"]]
    experience = sections.get("experience", [])
    experience_texts = [line for _, line in experience]
    skills_lines = {i for i, _ in sections.get("skills", [])}
    enumeration = skills_lines | {i for i, _ in sections.get("soft", [])}
    non_empty = [line for line in lines if line.strip()]

    found: dict[str, Found | ResumeField | None] = {}
    candidate = rules.name_candidate(head)
    if candidate is not None:
        found.update(rules.split_name(candidate))
    found["email"] = rules.find_email(non_empty)
    found["phone"] = rules.find_phone(non_empty)
    found["telegram"] = rules.find_telegram(non_empty, head)
    found["link"] = rules.find_link(non_empty)
    city = rules.find_city_by_label(non_empty)
    if city is None:
        guess = _safely("город", lambda: textparse.find_city("\n".join(non_empty[:15])), None)
        city = Found(validation.city(guess) or "", "medium", rules.snippet_of(guess)) if guess else None
    found["city"] = city if city and city.value else None
    experience_found = rules.find_experience(non_empty, experience_texts, today)
    found["experience_years"] = experience_found
    about = rules.find_about([line for _, line in sections.get("about", [])])
    found["about"] = about

    # --- справочники ---
    unknown: list[str] = []
    skill_codes: list[str] = []
    try:
        skill_index, role_index, grade_codes = _catalog_indexes()
    except Exception:
        log.warning("resume: справочник недоступен, поля навыков, ролей и грейда пропущены", exc_info=True)
        skill_index, role_index, grade_codes = {}, {}, set()
    if skill_index:
        no_skills: tuple[ResumeField | None, ResumeField | None, list[str], list[str]] = (None, None, [], [])
        hard_field, soft_field, skill_codes, unknown = _safely(
            "навыки", lambda: _skills(text, lines, enumeration, skills_lines, skill_index), no_skills
        )
        found["declared_skills"], found["soft_skills"] = hard_field, soft_field

    position_text = "\n".join(line for _, line in sections.get("position", []))
    titles = _job_titles(experience, lines, today)
    titles_text = "\n".join(title for _, title in titles)

    def roles_of(source: str) -> list[str]:
        return (
            _safely("роли", lambda: [c for c in textparse.find_roles(source) if c in role_index], []) if source else []
        )

    roles_position = roles_of(position_text)
    roles_jobs = roles_of(titles_text)
    role_codes = list(dict.fromkeys([*roles_position, *roles_jobs]))[:ROLES_MAX]
    if role_codes:
        found["roles"] = ResumeField(
            value=[role_index[c] for c in role_codes],
            confidence="high" if roles_position else "medium",
            snippet=rules.snippet_of(", ".join(role_index[c].title for c in role_codes)),
        )

    grade = rules.grade_by_dictionary(position_text) if position_text else None
    grade_source = position_text
    grade_confidence: Confidence = "medium"
    if grade is None and titles:
        grade_source = max(titles, key=lambda item: item[0])[1]
        grade = rules.grade_by_dictionary(grade_source)
    if grade is None and experience_found is not None and isinstance(experience_found.value, float):
        years = experience_found.value
        grade = _safely("грейд по стажу", lambda: textparse.grade_from_years(years), None)
        grade_source, grade_confidence = f"стаж {years:g} лет", "low"
    if grade is not None and grade in grade_codes:
        found["grade_hint"] = Found(grade, grade_confidence, rules.snippet_of(grade_source.split("\n")[0]))

    if role_codes or skill_codes:
        text_roles = roles_of(text)
        no_vote: tuple[str | None, float] = (None, 0.0)
        spec, _ = _safely(
            "специализация",
            lambda: textparse.vote_specialization([*roles_position, *roles_jobs], text_roles, skill_codes),
            no_vote,
        )
        if spec:
            found["specialization_hint"] = Found(spec, "medium", None)

    fields: dict[str, ResumeField] = {}
    for key, value in found.items():
        if value is None:
            continue
        fields[key] = value if isinstance(value, ResumeField) else _field(value)  # type: ignore[assignment]
    counted = (
        ("last_name", "first_name"),
        ("email",),
        ("phone",),
        ("city",),
        ("experience_years",),
        ("roles",),
        ("declared_skills",),
        ("soft_skills",),
        ("grade_hint",),
    )
    recognized = sum(1 for group in counted if any(name in fields for name in group))
    assert len(counted) == RESUME_FIELDS_TOTAL
    return ParsedResume(
        fields=fields,
        recognized=recognized,
        unknown_terms=unknown,
        meta=ResumeMeta(
            pages=pages,
            chars=len(text),
            engine=engine,
            ms=int((time.monotonic() - started) * 1000),
            parser_version=RESUME_PARSER_VERSION,
        ),
    )
