"""Фикстуры тестов модуля `profile`.

Нижние модули (`catalog`, `assessment`, `textparse`, `company`) в этих тестах не нужны целиком, поэтому их фасады
подменяются по сигнатурам Арх. 2.5: тест проверяет `profile`, а не соседей. `identity` настоящий.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from app.modules.assessment import service as assessment
from app.modules.assessment.dto import CategoryDTO
from app.modules.catalog import service as catalog
from app.modules.catalog.dto import Catalog, GradeDTO, SkillDTO
from app.modules.company import service as company
from app.modules.company.dto import CompanyDTO
from app.modules.profile import service as profile
from app.modules.profile.dto import ConditionsData, ProfileData
from app.modules.textparse import service as textparse
from app.modules.textparse.dto import SkillMention
from app.shared.enums import CategoryBasis, ConsentKind, ContactKind, TestOutcome, WorkFormat
from app.shared.schemas import ContactMethod, Ref

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)

HARD = {
    "python": ("Python", ["python", "питон"]),
    "fastapi": ("FastAPI", ["fastapi"]),
    "django": ("Django", ["django"]),
    "postgresql": ("PostgreSQL", ["postgresql", "postgres"]),
    "redis": ("Redis", ["redis"]),
    "docker": ("Docker", ["docker"]),
    "git": ("Git", ["git"]),
    "rest_api": ("REST API", ["rest api"]),
    "sql": ("SQL", ["sql"]),
    "pytest": ("pytest", ["pytest"]),
}
SOFT = {
    "communication": ("Коммуникабельность", ["коммуникабельность"]),
    "responsibility": ("Ответственность", ["ответственность"]),
    "teamwork": ("Работа в команде", ["работа в команде"]),
    "mentoring": ("Наставничество", ["наставничество"]),
}
FILLER = {f"tech_{i:02d}": (f"Технология {i}", []) for i in range(40)}
SOFT_FILLER = {f"soft_{i:02d}": (f"Качество {i}", []) for i in range(12)}
ROLES = {"backend_dev": "Backend-разработчик", "python_dev": "Python-разработчик"}


def make_catalog() -> Catalog:
    skills = [SkillDTO(code=c, title=t, kind="tech", aliases=a) for c, (t, a) in {**HARD, **FILLER}.items()]
    skills += [SkillDTO(code=c, title=t, kind="soft", aliases=a) for c, (t, a) in {**SOFT, **SOFT_FILLER}.items()]
    grades = [GradeDTO(code=c, title=c.title(), order=i) for i, c in enumerate(("junior", "middle", "senior"))]
    return Catalog(skills=skills, roles=[Ref(code=c, title=t) for c, t in ROLES.items()], grades=grades)


@dataclass
class World:
    """Состояние подменённых соседей: у кого есть категория, какие у работодателей компании."""

    categories: set[UUID] = field(default_factory=set)
    company_names: dict[UUID, str] = field(default_factory=dict)
    unknown_terms: list[str] = field(default_factory=list)
    #: Кандидаты, получившие категорию быстрым демо-тестом (`is_demo_result = true`), аккаунт при этом живой.
    demo_results: set[UUID] = field(default_factory=set)
    #: Кандидаты с заявленным грейдом в специализации без теста (`basis = declared`).
    declared: set[UUID] = field(default_factory=set)

    def category(self, candidate_id: UUID) -> CategoryDTO | None:
        if candidate_id in self.declared:
            return CategoryDTO(
                specialization_code="qa",
                grade_code="middle",
                category_code="qa:middle",
                basis=CategoryBasis.DECLARED,
                assigned_at=NOW,
            )
        if candidate_id not in self.categories:
            return None
        return CategoryDTO(
            specialization_code="backend",
            grade_code="middle",
            category_code="backend:middle",
            verdict=TestOutcome.CONFIRMED,
            assigned_at=NOW,
            level_session_id=uuid4(),
            is_demo_result=candidate_id in self.demo_results,
        )


@pytest.fixture(autouse=True)
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    state = World()
    data = make_catalog()
    monkeypatch.setattr(catalog, "get_catalog", lambda: data)

    monkeypatch.setattr(assessment, "get_category", lambda db, candidate_id: state.category(candidate_id))
    monkeypatch.setattr(
        assessment,
        "get_categories",
        lambda db, ids: {i: c for i in ids if (c := state.category(i)) is not None},
    )

    def get_company(db: Session, employer_id: UUID) -> CompanyDTO | None:
        name = state.company_names.get(employer_id)
        if name is None:
            return None
        return CompanyDTO(
            name=name,
            sphere="ИТ",
            description="Описание",
            contact_method=ContactMethod(kind=ContactKind.EMAIL, value="hr@example.com"),
            created_at=NOW,
            is_complete=True,
        )

    monkeypatch.setattr(company, "get_company", get_company)

    aliases = {alias: code for code, (_, names) in {**HARD, **SOFT}.items() for alias in names}

    def link_skills(text: str, *, enumeration_lines: set[int] | None = None) -> tuple[list[SkillMention], list[str]]:
        found: list[SkillMention] = []
        for alias, code in aliases.items():
            for match in re.finditer(rf"(?<!\w){re.escape(alias)}(?!\w)", text, re.IGNORECASE):
                found.append(
                    SkillMention(
                        skill_code=code, start=match.start(), end=match.end(), surface=match.group(0), method="exact"
                    )
                )
        found.sort(key=lambda m: m.start)
        return found, list(state.unknown_terms)

    def find_roles(text: str) -> list[str]:
        low = text.lower()
        hits = [
            (low.find(key), code) for key, code in (("backend", "backend_dev"), ("python-разработчик", "python_dev"))
        ]
        return [code for pos, code in sorted(hits) if pos >= 0]

    def find_city(text: str) -> str | None:
        return next((city for city in ("Казань", "Москва", "Самара") if city in text), None)

    def grade_from_years(years: float) -> str:
        return "junior" if years < 1.5 else "middle" if years < 4 else "senior"

    def vote_specialization(
        title_roles: Collection[str], text_roles: Collection[str], skill_codes: Collection[str]
    ) -> tuple[str | None, float]:
        return ("backend", 0.9) if title_roles or text_roles or skill_codes else (None, 0.0)

    monkeypatch.setattr(textparse, "link_skills", link_skills)
    monkeypatch.setattr(textparse, "find_roles", find_roles)
    monkeypatch.setattr(textparse, "find_city", find_city)
    monkeypatch.setattr(textparse, "grade_from_years", grade_from_years)
    monkeypatch.setattr(textparse, "vote_specialization", vote_specialization)
    return state


@dataclass(frozen=True)
class Candidate:
    id: UUID
    email: str


@pytest.fixture
def now(freeze_now: Any) -> datetime:
    """Время сервиса теста: заморожено, чтобы сроки паузы и суточные записи были предсказуемы."""
    return freeze_now(NOW)  # type: ignore[no-any-return]


def profile_data(**overrides: Any) -> ProfileData:
    values: dict[str, Any] = {
        "last_name": "Смирнова",
        "first_name": "Анна",
        "middle_name": "Сергеевна",
        "city": "Казань",
        "phone": "+79171234567",
        "telegram": "@anna_dev",
        "link": "https://github.com/anna-demo",
        "experience_years": 4.0,
        "roles": ["backend_dev"],
        "about": "Пишу серверный код. Пишите на anna@example.com",
        "declared_skills": [{"code": "python"}, {"code": "fastapi"}, {"custom_label": "Tarantool"}],
    }
    values.update(overrides)
    return ProfileData(**values)


@pytest.fixture
def make_candidate(db: Session, make_user: Callable[..., Any], world: World, now: datetime) -> Callable[..., Candidate]:
    """Кандидат с заполненным профилем; по умолчанию с категорией (но без согласия на публикацию)."""

    def factory(
        *, category: bool = True, published: bool = False, filled: bool = True, is_demo: bool = False, **fields: Any
    ) -> Candidate:
        user = make_user("candidate", is_demo=is_demo)
        if filled:
            profile.save_profile(db, user.id, profile_data(**fields), now)
            profile.save_conditions(db, user.id, ConditionsData(work_formats=[WorkFormat.REMOTE]), now)
        if category:
            world.categories.add(user.id)
        if published:
            profile.set_publication(db, user.id, granted=True, version=publication_version(), now=now, source="seed")
        db.commit()
        return Candidate(id=user.id, email=user.email)

    return factory


def publication_version() -> str:
    from app.modules.identity import service as identity

    return identity.current_consent(ConsentKind.PUBLICATION).version


@pytest.fixture
def make_employer(db: Session, make_user: Callable[..., Any], world: World) -> Callable[..., Any]:
    def factory(*, name: str = "ООО «Пример»", is_demo: bool = False) -> Any:
        user = make_user("employer", is_demo=is_demo)
        world.company_names[user.id] = name
        return user

    return factory


@pytest.fixture
def later(now: datetime) -> Iterator[Callable[..., datetime]]:
    def shift(**delta: float) -> datetime:
        return now + timedelta(**delta)

    yield shift
