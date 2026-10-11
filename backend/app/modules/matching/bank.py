"""Банк кандидатов (Арх. 6.9): все видимые кандидаты, фильтры, порядок по силе профиля, курсор, суточный лимит."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.errors import ApiException
from app.core.pagination import decode_cursor, encode_cursor
from app.modules.assessment import service as assessment
from app.modules.assessment.dto import LevelView
from app.modules.catalog import service as catalog
from app.modules.identity import service as identity
from app.modules.matching import constants as C
from app.modules.matching import exposure, support
from app.modules.matching.evidence import Pool, load_pool
from app.modules.matching.explain import skill_item, sorted_skills
from app.modules.matching.features import CONFIRMED_KINDS, CandidateFeatures
from app.modules.matching.ranking import BankRanked, rank_bank
from app.modules.matching.schemas import BankItemView, BankPage, BankSection
from app.modules.matching.scoring import bank_seed, resolve_requirement
from app.modules.profile import service as profile
from app.shared.enums import ExposureSource, TestOutcome, WorkFormat

_CODE_RE = re.compile(r"^[КK]-\d{4,6}$")
_DAY_SECONDS = 86_400


@dataclass(frozen=True, slots=True)
class BankFilters:
    """Фильтры банка, соединяются по «и». `category` заменяет `specialization` и `grade`."""

    specialization: str | None = None
    grades: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    skills_confirmed_only: bool = False
    has_fsp: bool = False
    code: str | None = None

    def digest(self) -> str:
        """Хэш канонических фильтров для курсора: чужой курсор к другим фильтрам не подходит."""
        raw = json.dumps(
            [
                self.specialization,
                sorted(self.grades),
                sorted(self.skills),
                self.skills_confirmed_only,
                self.has_fsp,
                self.code,
            ],
            ensure_ascii=False,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _split(value: str | None) -> list[str]:
    return list(dict.fromkeys(part.strip() for part in (value or "").split(",") if part.strip()))


def parse_filters(
    *,
    category: str | None,
    specialization: str | None,
    grade: str | None,
    skills: str | None,
    skills_confirmed_only: bool,
    has_fsp: bool,
    code: str | None,
) -> BankFilters:
    """Разобрать и проверить параметры запроса; ошибка — 422 `filter_invalid` с именем параметра."""
    grades = _split(grade)
    if category:
        spec, separator, one_grade = category.partition(":")
        if not separator or not spec or not one_grade:
            raise support.api_error(422, "filter_invalid", field="category")
        specialization, grades = spec, [one_grade]
    specialization = (specialization or "").strip() or None
    if specialization is not None and specialization not in set(support.specialization_codes()):
        raise support.api_error(422, "filter_invalid", field="category" if category else "specialization")
    if not set(grades) <= set(support.grade_codes()):
        raise support.api_error(422, "filter_invalid", field="category" if category else "grade")
    skill_codes = _split(skills)
    if len(skill_codes) > C.BANK_SKILLS_MAX or any(not catalog.is_skill(item) for item in skill_codes):
        raise support.api_error(422, "filter_invalid", field="skills")
    code = (code or "").strip().upper() or None
    if code is not None:
        if not _CODE_RE.match(code):
            raise support.api_error(422, "filter_invalid", field="code")
        code = "К-" + code[2:]  # латинская K, набранная с клавиатуры, — тот же код
    return BankFilters(
        specialization=specialization,
        grades=tuple(grades),
        skills=tuple(skill_codes),
        skills_confirmed_only=skills_confirmed_only,
        has_fsp=has_fsp,
        code=code,
    )


def _has_skills(features: CandidateFeatures, filters: BankFilters) -> bool:
    """У кандидата есть доказательство по каждому навыку фильтра с учётом `implies`; при
    `skills_confirmed_only` — подтверждённое (тест, короткое задание, ФСП: `e ≥ 0.7`).
    """
    for skill in filters.skills:
        found = resolve_requirement(features.evidence, skill, "must", support.closure)
        if found.weight <= 0:
            return False
        if filters.skills_confirmed_only and (found.kind not in CONFIRMED_KINDS or found.weight < C.E_TEST_SINGLE):
            return False
    return True


def _take_page_budget(db: Session, employer_id: UUID) -> None:
    """Суточный лимит страниц банка (Арх. 6.9): дальше — 429 `bank_page_limit`.

    Демо-аккаунты общие для всех посетителей стенда, поэтому лимит к ним не применяется: вместо него их пул
    ограничен демо-кандидатами (R3-tz-compliance-1).
    """
    if support.is_demo_account(db, employer_id):
        return
    try:
        identity.throttle(
            db,
            C.BANK_PAGE_THROTTLE_KIND,
            user_id=employer_id,
            limit=C.BANK_PAGES_LIMIT_PER_DAY,
            window_s=_DAY_SECONDS,
        )
    except ApiException as exc:
        if exc.status != 429:
            raise
        raise support.api_error(429, "bank_page_limit", params=exc.params) from None


def _cursor(position: dict[str, object] | None, filters: BankFilters, today: date) -> tuple[date, int]:
    """День (он фиксирует жребий и окно показов на всё пролистывание) и смещение из курсора."""
    if position is None:
        return today, 0
    try:
        day = date.fromisoformat(str(position["d"]))
        offset = int(position["o"])  # type: ignore[call-overload]
    except (KeyError, TypeError, ValueError):
        raise support.api_error(422, "cursor_invalid") from None
    if position.get("f") != filters.digest() or offset < 0 or not today - timedelta(days=1) <= day <= today:
        raise support.api_error(422, "cursor_invalid")
    return day, offset


def _row(db_names: dict[UUID, str | None], pool: Pool, row: BankRanked, level: LevelView | None) -> BankItemView:
    features = row.features
    cid = features.candidate_id
    person = pool.profiles[cid]
    confirmed = [item for item in sorted_skills(features.evidence, support.skill_title) if item.kind in CONFIRMED_KINDS]
    return BankItemView(
        candidate_id=cid,
        public_code=person.public_code,
        display_name=db_names.get(cid),
        is_demo=person.is_demo,
        category=support.category_ref(features.specialization_code, features.grade_code, features.basis),
        grade_margin=features.verdict == TestOutcome.CONFIRMED_WITH_MARGIN,
        strength_label=row.strength.label,
        level=level,
        confirmed_skills=[
            skill_item(item, support.skill_title(item.skill_code)) for item in confirmed[: C.BANK_CONFIRMED_LIMIT]
        ],
        confirmed_more=max(0, len(confirmed) - C.BANK_CONFIRMED_LIMIT),
        fsp_summary=pool.fsp_short(cid),
        work_formats=[WorkFormat(value) for value in person.work_formats],
        relocation_ready=person.relocation_ready,
        freshness_days=features.age_days,
        stale=features.stale,
    )


def page(
    db: Session,
    employer_id: UUID,
    filters: BankFilters,
    position: dict[str, object] | None,
    limit: int,
    now: datetime,
) -> BankPage:
    """Страница банка: потребность не нужна, версия не создаётся. Формат и вилка не фильтруются."""
    limit = max(1, min(limit, C.BANK_PAGE_MAX))
    pool = load_pool(
        db,
        employer_id,
        now,
        specialization_code=filters.specialization,
        grade_codes=list(filters.grades) if filters.grades else None,
    )
    day, offset = _cursor(position, filters, pool.today)
    _take_page_budget(db, employer_id)

    matched = [
        item
        for item in pool.visible()
        if _has_skills(item, filters)
        and (filters.code is None or pool.profiles[item.candidate_id].public_code == filters.code)
    ]
    hidden_by_fsp: int | None = None
    if filters.has_fsp:
        with_fsp = [item for item in matched if item.fsp_verified]
        hidden_by_fsp = len(matched) - len(with_fsp)
        matched = with_fsp
    ranked = rank_bank(
        matched,
        bank_seed(employer_id, day),
        specializations=support.specialization_codes(),
        grades=support.grade_codes(),
    )
    sections: dict[tuple[str, str], int] = {}
    for row in ranked:
        key = (row.features.specialization_code, row.features.grade_code)
        sections[key] = sections.get(key, 0) + 1

    rows = ranked[offset : offset + limit]
    ids = [row.features.candidate_id for row in rows]
    levels = assessment.level_views(db, ids, now) if ids else {}
    disclosed = profile.disclosed_map(db, employer_id, ids) if ids else {}
    opened = [cid for cid in ids if disclosed.get(cid)]
    names = dict(profile.display_names(db, employer_id, opened)) if opened else {}
    if offset == 0:
        exposure.record_shown(db, employer_id, ids, pool.today, ExposureSource.BANK)
    has_more = offset + limit < len(ranked)
    return BankPage(
        # У заявленного грейда уровня по тесту нет: `level_views` такого кандидата не возвращает.
        items=[_row(names, pool, row, levels.get(row.features.candidate_id)) for row in rows],
        next_cursor=(
            encode_cursor({"d": day.isoformat(), "o": offset + limit, "f": filters.digest()}) if has_more else None
        ),
        sections=[
            BankSection(category=support.category_ref(spec, grade), count=count)
            for (spec, grade), count in sections.items()
        ],
        total=len(ranked),
        hidden_by_fsp=hidden_by_fsp,
    )


def parse_cursor(cursor: str | None) -> dict[str, object] | None:
    """Битый курсор — 422 `cursor_invalid`."""
    return decode_cursor(cursor)
