"""Синтетические кандидаты специализаций без теста: категория с заявленным грейдом (`basis = declared`).

Теста по этим специализациям ещё нет, поэтому путь по движку не симулируется: профиль, опрос и заявленный грейд
записываются фасадами (`profile.save_*`, `assessment.seed_declared`), затем публикация и привязка ФСП. Специализация
`backend` сюда не попадает никогда: её категорию даёт только тест (`seed.population`).

Детерминированность: у каждой специализации свой датчик `C.rng_for(DECLARED_OFFSET + номер)`, пулы навыков —
кортежи в порядке справочника, спортсмены ФСП отсортированы по `fsp_id`. Шаг идёт после `population`: тот уже
выдал своим кандидатам разрешения в реестре, и `fsp.demo_athlete_pool` возвращает только свободных спортсменов.
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.core.db import session_scope
from app.modules.assessment import service as assessment
from app.modules.catalog import service as catalog
from app.modules.fsp import service as fsp
from app.modules.identity import service as identity
from app.modules.profile import service as profile
from app.modules.profile.dto import ConditionsData, DeclaredSkill, PrivacyData, ProfileData
from app.seed import common as C
from app.seed import people
from app.shared.enums import ConsentKind, Role, WorkFormat

DECLARED_OFFSET = 100
#: Номера для телефонов и ссылок: не пересекаются с популяцией `backend` и именованными кандидатами.
INDEX_BASE = 1000

#: Должность профиля по специализации; специализация без строки здесь в сид не попадает.
ROLES: dict[str, str] = {
    "frontend": "frontend_developer",
    "fullstack": "fullstack_developer",
    "mobile": "mobile_developer",
    "data_ml": "data_scientist",
    "analyst": "system_analyst",
    "qa": "qa_engineer",
    "devops": "devops_engineer",
    "infosec": "security_engineer",
    "embedded": "embedded_developer",
}
#: Ядро стека: эти навыки есть у большинства кандидатов специализации (иначе по потребности с обязательными
#: `react` и `typescript` в подборке не оказалось бы ни одного закрытого). По умолчанию — первые четыре навыка
#: специализации в порядке справочника.
CORE_SKILLS: dict[str, tuple[str, ...]] = {
    "frontend": ("javascript", "typescript", "react", "html", "css"),
    "qa": ("testing", "test_automation", "pytest", "manual_testing"),
}
CORE_DEFAULT = 4
#: Вероятность каждого навыка ядра и число навыков профиля по грейду (без гибких).
CORE_SHARE: dict[str, float] = {"junior": 0.6, "middle": 0.8, "senior": 0.9}
SKILL_COUNT: dict[str, tuple[int, int]] = {"junior": (4, 6), "middle": (6, 9), "senior": (8, 12)}
#: Стаж опроса по грейду (варианты `assessment.survey_schema.EXPERIENCE`).
EXPERIENCE_BAND: dict[str, str] = {"junior": "1_2", "middle": "2_4", "senior": "4_plus"}
FORMATS: tuple[tuple[WorkFormat, ...], ...] = (
    (WorkFormat.REMOTE,),
    (WorkFormat.REMOTE, WorkFormat.HYBRID),
    (WorkFormat.HYBRID,),
    (WorkFormat.OFFICE, WorkFormat.HYBRID, WorkFormat.REMOTE),
)


@dataclass
class DeclaredPerson:
    key: str
    index: int
    specialization: str
    grade: str
    last_name: str
    first_name: str
    city: str
    experience_years: float
    skills: list[str]
    about: str
    min_salary: int | None
    formats: list[WorkFormat]
    relocation: bool
    privacy: PrivacyData
    declared_at: datetime
    publish: bool
    fsp_id: str | None = None

    @property
    def email(self) -> str:
        return C.email_for(self.key)


def per_specialization() -> int:
    return int(os.environ.get("SEED_DECLARED_PER_SPECIALIZATION", C.DEFAULT_DECLARED))


def specializations() -> list[str]:
    """Специализации справочника без теста, в порядке справочника."""
    return [code for code in catalog.specialization_codes() if code in ROLES and not catalog.is_available(code)]


def declared_key(specialization: str, number: int) -> str:
    return f"decl_{specialization}_{number:02d}"


def _grades(count: int) -> list[str]:
    """Грейды по порядку: треть `junior`, четверть `senior`, остальные `middle` (12 → 4, 5, 3)."""
    junior, senior = round(count / 3), round(count / 4)
    return ["junior"] * junior + ["middle"] * max(count - junior - senior, 0) + ["senior"] * senior


def _skills(rng: random.Random, specialization: str, grade: str) -> list[str]:
    """Заявленные навыки: ядро стека, затем остальные навыки специализации, 1–2 общих и 1–2 гибких."""
    tagged = list(catalog.skills_for_specialization(specialization))
    generic = list(catalog.generic_skills())
    soft = [entry.code for entry in catalog.skill_entries() if entry.kind == catalog.SOFT_KIND]
    total = rng.randint(*SKILL_COUNT[grade])
    generic_n = min(rng.randint(1, 2), len(generic))
    core = [code for code in CORE_SKILLS.get(specialization, tuple(tagged[:CORE_DEFAULT])) if code in tagged]
    chosen = [code for code in core if rng.random() < CORE_SHARE[grade]][: total - generic_n]
    rest = [code for code in tagged if code not in chosen]
    chosen += rng.sample(rest, k=min(max(total - generic_n - len(chosen), 0), len(rest)))
    # Навыков специализации может не хватить (у `infosec` их пять) — добираем общими.
    chosen += rng.sample(generic, k=min(max(total - len(chosen), generic_n), len(generic)))
    chosen += rng.sample(soft, k=min(rng.randint(1, 2), len(soft)))
    return chosen


def _person(
    rng: random.Random, specialization: str, number: int, index: int, grade: str, now: datetime, role_title: str
) -> DeclaredPerson:
    surname, first = C.full_name(rng)
    low, high = people.EXPERIENCE[grade]
    skills = _skills(rng, specialization, grade)
    titles = [catalog.skill_ref(code).title for code in skills[:2]]
    return DeclaredPerson(
        key=declared_key(specialization, number),
        index=index,
        specialization=specialization,
        grade=grade,
        last_name=surname,
        first_name=first,
        city=rng.choice(C.CITIES),
        experience_years=round(rng.uniform(low, high) * 2) / 2,
        skills=skills,
        about=f"{role_title}. Работаю с {' и '.join(titles)}.",
        min_salary=None if rng.random() < 0.25 else people.snap_salary(rng, grade),
        formats=list(rng.choice(FORMATS)),
        relocation=rng.random() < 0.2,
        privacy=PrivacyData(
            reveal_phone=rng.random() < 0.3, reveal_telegram=rng.random() < 0.2, reveal_link=rng.random() < 0.1
        ),
        declared_at=now - timedelta(days=rng.uniform(10, 80)),
        publish=index % 16 != 0,
    )


def build(now: datetime, count: int, history_ids: list[str], empty_ids: list[str]) -> list[DeclaredPerson]:
    """Все кандидаты с заявленным грейдом; спортсмены ФСП раздаются подряд из отсортированных свободных."""
    role_titles = {entry.code: entry.title for entry in catalog.role_entries()}
    history_n, empty_n = round(count * C.FSP_HISTORY_SHARE), round(count * C.FSP_EMPTY_SHARE)
    result: list[DeclaredPerson] = []
    for spec_index, specialization in enumerate(specializations()):
        rng = C.rng_for(DECLARED_OFFSET + spec_index)
        fsp_ids = history_ids[spec_index * history_n :][:history_n] + empty_ids[spec_index * empty_n :][:empty_n]
        order = list(range(count))
        rng.shuffle(order)
        fsp_by_position = dict(zip(order, fsp_ids, strict=False))
        for position, grade in enumerate(_grades(count)):
            index = INDEX_BASE + len(result) + 1
            person = _person(
                rng, specialization, position + 1, index, grade, now, role_titles[ROLES[specialization]]
            )
            person.fsp_id = fsp_by_position.get(position)
            result.append(person)
    return result


def create_candidate(db: Session, person: DeclaredPerson) -> None:
    """Записать кандидата: аккаунт, профиль, заявленный грейд, условия, приватность, публикация, привязка ФСП."""
    now = clock.now(db)
    saved_at = person.declared_at - timedelta(days=5)
    user_id = identity.create_user(
        db,
        person.email,
        get_settings().demo_password,
        Role.CANDIDATE,
        verified=True,
        is_demo=True,
        demo_key=person.key,
    )
    profile.save_profile(
        db,
        user_id,
        ProfileData(
            last_name=person.last_name,
            first_name=person.first_name,
            city=person.city,
            phone=C.phone_for(person.index),
            telegram=C.telegram_for(person.index),
            link=C.link_for(person.index),
            experience_years=person.experience_years,
            roles=[ROLES[person.specialization]],
            about=person.about,
            declared_skills=[DeclaredSkill(code=code) for code in person.skills],
        ),
        saved_at,
    )
    assessment.seed_declared(
        db,
        candidate_id=user_id,
        specialization_code=person.specialization,
        grade_code=person.grade,
        now=person.declared_at,
        experience_band=EXPERIENCE_BAND[person.grade],
    )
    profile.save_conditions(
        db,
        user_id,
        ConditionsData(min_salary=person.min_salary, work_formats=person.formats, relocation_ready=person.relocation),
        saved_at,
    )
    profile.save_privacy(db, user_id, person.privacy, saved_at)
    if person.publish:
        version = identity.current_consent(ConsentKind.PUBLICATION).version
        profile.set_publication(
            db, user_id, granted=True, version=version, now=min(person.declared_at + timedelta(hours=1), now),
            source="seed",
        )  # fmt: skip
    if person.fsp_id is not None:
        fsp.seed_link(db, user_id, person.fsp_id)


def seed_declared(count: int | None = None) -> int:
    """Создать кандидатов с заявленным грейдом по всем специализациям без теста; вернуть число созданных сейчас."""
    count = per_specialization() if count is None else count
    if count <= 0 or not C.ensure_ready():
        return 0
    with session_scope() as db:
        now = clock.now(db)
        keys = [declared_key(spec, number) for spec in specializations() for number in range(1, count + 1)]
        missing = [key for key in keys if not identity.demo_user_ids(db, [key])]
    if not missing:
        return 0
    # Свободных спортсменов берём после популяции `backend`: её разрешения в реестре уже записаны (`seed_link`
    # фиксирует их сразу), так что пересечений нет. Порядок — по `fsp_id`. При продолжении недописанного сида
    # занятые спортсмены из пула уже выбыли, поэтому оставшимся кандидатам достаются только свободные.
    history = sorted(item.fsp_id for item in fsp.demo_athlete_pool(with_history=True))
    empty = sorted(item.fsp_id for item in fsp.demo_athlete_pool(with_history=False))
    wanted = set(missing)
    people_list = [person for person in build(now, count, history, empty) if person.key in wanted]
    created = 0
    for start in range(0, len(people_list), C.BATCH):
        with session_scope() as db:
            for person in people_list[start : start + C.BATCH]:
                if identity.demo_user_ids(db, [person.key]):
                    continue
                create_candidate(db, person)
                created += 1
        C.log.info("сид: заявленные грейды %d/%d", min(start + C.BATCH, len(people_list)), len(people_list))
    return created
