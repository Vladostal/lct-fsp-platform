"""Фасад модуля `catalog` (Арх. 2.5): справочники в памяти.

Данные читает `loader.py` один раз за процесс. Состояние, которое меняется во время работы, — только числа
для `Catalog.limits` и доступные пары (специализация, грейд): их публикуют другие модули при старте.
Функции `skill_entries`, `role_entries`, `city_entries` сверх Арх. 2.5 нужны `textparse`: он строит индекс алиасов,
а читать файлы справочников напрямую ему нельзя (Арх. 2.4, п. 1).
"""

from __future__ import annotations

import re
from collections.abc import Collection
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.modules.catalog.dto import (
    Catalog,
    CatalogFeatures,
    CityEntry,
    GradeDTO,
    RoleEntry,
    SkillDTO,
    SkillEntry,
    SpecializationDTO,
)
from app.modules.catalog.loader import load
from app.modules.catalog.models import SkillMissLog
from app.shared.salary import PUBLIC_SALARY_LIMITS
from app.shared.schemas import CategoryRef, Ref

_data = load()

#: Версия справочника навыков (sha256 файла, первые 8 знаков); попадает в версии отчётов и снимков.
SKILLS_VERSION: str = _data.skills_version

#: Сколько суток хранятся нераспознанные термины (поправка R3-data-api-security-5).
MISS_LOG_RETENTION_DAYS = 90
#: Сколько новых терминов принимает один вызов `log_miss`.
MISS_LOG_MAX_TERMS = 10

_skills_by_code: dict[str, SkillEntry] = {skill.code: skill for skill in _data.skills}
_specializations = {spec.code: spec for spec in _data.specializations}
_grades = {grade.code: grade for grade in _data.grades}

_limits: dict[str, int | float] = {}
_available: set[tuple[str, str]] = set()


# ---------------------------------------------------------------------------------------------------------------------
# Справочники
# ---------------------------------------------------------------------------------------------------------------------


def get_catalog() -> Catalog:
    """Справочники целиком — ответ `GET /catalog` (Арх. 9.11).

    `limits`: правила вилки (`shared.salary`), срок повторной регистрации (`REREGISTER_COOLDOWN_DAYS`, запрос
    № 3 пакета F00) и числа, опубликованные модулями; опубликованное значение побеждает. Пока `assessment`
    не опубликовал доступные пары, всё недоступно и `available_categories` пуст.
    """
    settings = get_settings()
    limits: dict[str, int | float] = {
        **PUBLIC_SALARY_LIMITS,
        "reregister_cooldown_days": settings.reregister_cooldown_days,
        **_limits,
    }
    return Catalog(
        directions=list(_data.directions),
        specializations=[specialization(spec.code) for spec in _data.specializations],
        grades=grades_ordered(),
        skills=[SkillDTO(code=s.code, title=s.title, kind=s.kind, aliases=list(s.aliases)) for s in _data.skills],
        roles=[Ref(code=r.code, title=r.title) for r in _data.roles],
        available_categories=[
            f"{spec.code}:{grade.code}"
            for spec in _data.specializations
            for grade in _data.grades
            if (spec.code, grade.code) in _available
        ],
        limits=limits,
        features=CatalogFeatures(**settings.features),
    )


def category_ref(category_code: str) -> CategoryRef:
    """Категория «специализация:грейд» → `CategoryRef` («backend:middle» → «Backend · Middle»).

    Неизвестный код — `KeyError`: категории создаёт только `assessment` из проверенных пар.
    """
    spec_code, _, grade_code = category_code.partition(":")
    spec = _specializations.get(spec_code)
    grade = _grades.get(grade_code)
    if spec is None or grade is None:
        raise KeyError(category_code)
    return CategoryRef(
        code=f"{spec.code}:{grade.code}",
        title=f"{spec.title_short} · {grade.title}",
        specialization=Ref(code=spec.code, title=spec.title),
        grade=Ref(code=grade.code, title=grade.title),
    )


def skill_ref(code: str) -> Ref:
    """Навык → `Ref`. Неизвестный код — `KeyError`."""
    skill = _skills_by_code[code]
    return Ref(code=skill.code, title=skill.title)


def is_skill(code: str) -> bool:
    return code in _skills_by_code


def implies_closure(skill_code: str) -> frozenset[str]:
    """Все навыки, владение которыми следует из этого (без самого навыка): `fastapi` → `{python}`.

    Для неизвестного кода — пустое множество: подбор читает коды из старых снимков и не должен падать.
    """
    return _data.closure.get(skill_code, frozenset())


def grades_ordered() -> list[GradeDTO]:
    """Грейды от младшего к старшему; `available` — есть хотя бы одна доступная пара с этим грейдом."""
    return [
        GradeDTO(
            code=g.code,
            title=g.title,
            order=g.order,
            description=g.description,
            available=any(pair_grade == g.code for _, pair_grade in _available),
        )
        for g in _data.grades
    ]


def specialization(code: str) -> SpecializationDTO:
    """Специализация по коду; `available` — доступен хотя бы один её грейд. Неизвестный код — `KeyError`."""
    spec = _specializations[code]
    return SpecializationDTO(
        code=spec.code,
        title=spec.title,
        title_short=spec.title_short,
        direction_code=spec.direction_code,
        available=is_available(spec.code),
    )


def specialization_codes() -> tuple[str, ...]:
    """Коды специализаций в порядке справочника (им же разрешаются ничьи при голосовании)."""
    return tuple(spec.code for spec in _data.specializations)


def skill_entries() -> tuple[SkillEntry, ...]:
    """Навыки со всеми алиасами — для индекса `textparse`."""
    return _data.skills


def role_entries() -> tuple[RoleEntry, ...]:
    return _data.roles


def city_entries() -> tuple[CityEntry, ...]:
    return _data.cities


# ---------------------------------------------------------------------------------------------------------------------
# Нераспознанные термины
# ---------------------------------------------------------------------------------------------------------------------

# Термин, похожий на название навыка: начинается с буквы, до 30 знаков, внутри буквы, цифры и `+#.-_`.
_TERM_RE = re.compile(r"^[a-zа-яё][a-zа-яё0-9+#._-]{1,29}$")
MAX_DIGITS_IN_TERM = 3


def _looks_like_skill(term: str) -> bool:
    """Отсеять из терминов e-mail, телефоны, ссылки и прочее, что не похоже на название навыка."""
    if not _TERM_RE.fullmatch(term) or "@" in term or term.startswith("www."):
        return False
    return sum(ch.isdigit() for ch in term) <= MAX_DIGITS_IN_TERM


def log_miss(db: Session, terms: Collection[str], source: str) -> None:
    """Записать нераспознанные термины в `skill_miss_log` (очередь на пополнение словаря).

    Поправка R3-data-api-security-5 (152-ФЗ): из резюме (`source = "resume"`) не пишется ничего — в нём
    фамилии, телефоны и названия компаний; из текста потребности — только то, что похоже на название навыка
    (буквы, до 30 знаков, не e-mail, не телефон), не больше `MISS_LOG_MAX_TERMS` терминов за вызов. Строки
    старше `MISS_LOG_RETENTION_DAYS` суток удаляются здесь же, при каждой записи.
    """
    if source == "resume":
        return
    if source != "need":
        raise ValueError(f"неизвестный источник терминов: {source!r}")
    clean: list[str] = []
    for term in terms:
        key = " ".join(term.split()).lower()
        if key and key not in clean and _looks_like_skill(key):
            clean.append(key)
    now = clock.now(db)
    purge_miss_log(db, now)
    for key in clean[:MISS_LOG_MAX_TERMS]:
        statement = insert(SkillMissLog).values(term=key, source=source, cnt=1, last_seen_at=now)
        db.execute(
            statement.on_conflict_do_update(
                index_elements=[SkillMissLog.term, SkillMissLog.source],
                set_={"cnt": SkillMissLog.cnt + 1, "last_seen_at": now},
            )
        )


def purge_miss_log(db: Session, now: datetime) -> int:
    """Удалить термины, не встречавшиеся `MISS_LOG_RETENTION_DAYS` суток. Возвращает число удалённых строк."""
    cutoff = now - timedelta(days=MISS_LOG_RETENTION_DAYS)
    result = db.execute(delete(SkillMissLog).where(SkillMissLog.last_seen_at < cutoff))
    return result.rowcount or 0  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------------------------------------------------
# Публикация чисел и доступности другими модулями
# ---------------------------------------------------------------------------------------------------------------------


def publish_limits(**limits: int | float) -> None:
    """Модули публикуют числа для `Catalog.limits` (их собирает `app.wiring.publish_limits`)."""
    _limits.update(limits)


def publish_availability(pairs: set[tuple[str, str]]) -> None:
    """`assessment` при старте публикует доступные пары (специализация, грейд), Арх. 5.2."""
    _available.clear()
    _available.update(pairs)


def is_available(specialization_code: str, grade_code: str | None = None) -> bool:
    """Доступен ли тест специализации (и грейда, если он назван)."""
    if grade_code is None:
        return any(spec == specialization_code for spec, _ in _available)
    return (specialization_code, grade_code) in _available
