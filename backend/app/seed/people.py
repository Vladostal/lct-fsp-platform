"""Синтетический человек и его запись через фасады модулей (Арх. 13.5).

`Person` — всё, что сид знает о кандидате; `create_candidate` записывает его только функциями записи фасадов:
`identity.create_user`, `profile.save_*`, `assessment.seed_result`, `profile.set_publication`, `fsp.seed_link`.
Во внутренности модулей сид не обращается.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.eval.testing.bank import SimBank
from app.eval.testing.pathsim import PathResult, simulate_path, to_seed_sessions, with_theta
from app.modules.assessment import service as assessment
from app.modules.assessment.dto import SeedResult, SeedSession
from app.modules.assessment.service import get_config
from app.modules.catalog import service as catalog
from app.modules.fsp import service as fsp
from app.modules.identity import service as identity
from app.modules.profile import service as profile
from app.modules.profile.dto import ConditionsData, DeclaredSkill, PrivacyData, ProfileData
from app.seed import common as C
from app.shared.enums import ConsentKind, DemoPersona, Role, WorkFormat
from app.shared.salary import min_salary_ladder
from app.simulation import population as sim
from app.simulation.population import ItemWorld

GRADES = ("junior", "middle", "senior")
EXPERIENCE = {"junior": (0.5, 2.0), "middle": (2.0, 5.0), "senior": (5.0, 12.0)}


@dataclass
class Person:
    key: str
    index: int
    last_name: str
    first_name: str
    claimed_grade: str
    language: str
    sessions: list[SeedSession]
    finished_at: datetime
    city: str | None = None
    experience_years: float | None = None
    skills: list[str] = field(default_factory=list)
    about: str | None = None
    phone: str | None = None
    telegram: str | None = None
    link: str | None = None
    min_salary: int | None = None
    formats: list[WorkFormat] = field(default_factory=lambda: [WorkFormat.REMOTE])
    relocation: bool = False
    privacy: PrivacyData = field(default_factory=PrivacyData)
    persona: DemoPersona | None = None
    publish: bool = True
    fsp_id: str | None = None

    @property
    def email(self) -> str:
        return C.email_for(self.key)


def theta_band(grade: str) -> tuple[float, float]:
    """Интервал истинного уровня, в котором виртуальный кандидат уверенно подтверждает грейд."""
    cuts = get_config().theta_cut
    index = GRADES.index(grade)
    low = cuts[grade] + 0.25
    high = cuts[GRADES[index + 1]] - 0.25 if index + 1 < len(GRADES) else cuts[grade] + 1.6
    return low, max(high, low + 0.3)


def snap_salary(rng: random.Random, grade: str) -> int:
    target = sim.SALARY_MEDIAN[grade] * math.exp(rng.gauss(0, 0.2))
    return min(min_salary_ladder(), key=lambda step: (abs(step - target), step))


def simulate(
    bank: SimBank,
    world: ItemWorld,
    rng: random.Random,
    index: int,
    grade: str,
    finished_at: datetime,
    *,
    theta: float | None = None,
    max_sessions: int | None = None,
    accept: Callable[[PathResult], bool] | None = None,
) -> tuple[sim.VirtualCandidate, PathResult, list[SeedSession]]:
    """Виртуальный кандидат целевого грейда и его путь по настоящему движку; повтор, пока путь не годится."""
    low, high = theta_band(grade)
    for _ in range(200):
        base = sim.generate(1, ["backend"], rng, first_id=index)[0]
        value = theta if theta is not None else rng.uniform(low, high)
        candidate = with_theta(base, value, claimed=grade, new_id=index)
        path = simulate_path(candidate, bank, rng, world=world, max_sessions=max_sessions)
        if accept(path) if accept else path.grade is not None:
            return candidate, path, to_seed_sessions(path, finished_at)
    raise RuntimeError(f"сид: не удалось получить путь теста для грейда {grade}")


def build_person(
    key: str, index: int, candidate: sim.VirtualCandidate, path: PathResult, sessions: list[SeedSession],
    rng: random.Random, finished_at: datetime, *, claimed: str, publish: bool = True,
) -> Person:  # fmt: skip
    """Профиль, условия и приватность синтетического кандидата по его виртуальной модели."""
    grade = path.grade or claimed
    surname, first = C.full_name(rng)
    low, high = EXPERIENCE[grade]
    skills = [C.LANGUAGE_SKILL.get(candidate.main_language, "python")]
    extras = [code for code in C.EXTRA_SKILLS if catalog.is_skill(code)]
    skills += rng.sample(extras, k=rng.randint(3, 7))
    roll = rng.random()
    about = rng.choice(C.ABOUT_WITH_CONTACTS) if roll < 0.15 else rng.choice(C.ABOUT_PLAIN) if roll < 0.70 else None
    privacy = PrivacyData(
        reveal_phone=rng.random() < 0.3, reveal_telegram=rng.random() < 0.2, reveal_link=rng.random() < 0.1
    )
    return Person(
        key=key,
        index=index,
        last_name=surname,
        first_name=first,
        claimed_grade=claimed,
        language=candidate.main_language,
        sessions=sessions,
        finished_at=finished_at,
        city=rng.choice(C.CITIES),
        experience_years=round(rng.uniform(low, high) * 2) / 2,
        skills=list(dict.fromkeys(skills)),
        about=about,
        phone=C.phone_for(index),
        telegram=C.telegram_for(index),
        link=C.link_for(index),
        min_salary=None if rng.random() < 0.25 else snap_salary(rng, grade),
        formats=[WorkFormat(item) for item in candidate.work_formats],
        relocation=rng.random() < 0.2,
        privacy=privacy,
        persona=DemoPersona(candidate.persona),
        publish=publish,
    )


def create_candidate(db: Session, person: Person) -> None:
    """Записать кандидата: аккаунт, профиль, результат теста, условия, приватность, публикация, привязка ФСП."""
    now = clock.now(db)
    saved_at = person.finished_at - timedelta(days=5)
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
            phone=person.phone,
            telegram=person.telegram,
            link=person.link,
            experience_years=person.experience_years,
            roles=["backend_developer"],
            about=person.about,
            declared_skills=[DeclaredSkill(code=code) for code in person.skills],
        ),
        saved_at,
    )
    assessment_result = SeedResult(
        candidate_id=user_id,
        specialization_code="backend",
        grade_code=person.claimed_grade,
        main_language=person.language,
        sessions=person.sessions,
    )
    assessment.seed_result(db, assessment_result)
    profile.save_conditions(
        db,
        user_id,
        ConditionsData(min_salary=person.min_salary, work_formats=person.formats, relocation_ready=person.relocation),
        saved_at,
    )
    profile.save_privacy(db, user_id, person.privacy, saved_at)
    if person.persona is not None:
        profile.set_demo_persona(db, user_id, person.persona)
    if person.publish and assessment.get_category(db, user_id) is not None:
        version = identity.current_consent(ConsentKind.PUBLICATION).version
        profile.set_publication(
            db, user_id, granted=True, version=version, now=min(person.finished_at + timedelta(hours=1), now),
            source="seed",
        )  # fmt: skip
    if person.fsp_id is not None:
        fsp.seed_link(db, user_id, person.fsp_id)
