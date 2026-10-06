"""Фикстуры тестов модуля `contact`.

Нижние модули (`profile`, `matching`, `company`, `assessment`, `catalog`) подменяются в памяти по сигнатурам
фасадов Арх. 2.5: класс `World` хранит их состояние и считает обращения к скрытому минимуму. Модуль `identity`
настоящий: пользователи лежат в `app_user`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from app.core.errors import not_found
from app.modules.assessment import service as assessment_service
from app.modules.assessment.dto import CategoryDTO
from app.modules.catalog import service as catalog_service
from app.modules.company import service as company_service
from app.modules.company.dto import CompanyDTO
from app.modules.contact import service
from app.modules.contact.dto import InvitationData, InvitationDTO
from app.modules.matching import service as matching_service
from app.modules.matching.dto import ExposureStats, InvitationExplain, InvitationWhy, NeedRefDTO
from app.modules.profile import service as profile_service
from app.modules.profile.dto import PoolProfile, PrivacySettingsDTO, VisibilityDTO
from app.shared.enums import (
    ContactKind,
    FitBand,
    PauseReason,
    TestOutcome,
    TrustLevel,
    VisibilityState,
    WorkFormat,
)
from app.shared.schemas import CategoryRef, ContactMethod, Ref

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def category_ref(code: str) -> CategoryRef:
    spec, _, grade = code.partition(":")
    return CategoryRef(
        code=code,
        title=f"{spec.title()} · {grade.title()}",
        specialization=Ref(code=spec, title=spec.title()),
        grade=Ref(code=grade, title=grade.title()),
    )


@dataclass
class FakeCandidate:
    min_salary: int | None = None
    formats: list[WorkFormat] = field(default_factory=lambda: [WorkFormat.REMOTE, WorkFormat.HYBRID])
    state: VisibilityState = VisibilityState.VISIBLE
    auto_paused_until: datetime | None = None
    persona: str | None = None
    filled: frozenset[str] = frozenset({"email", "phone"})
    privacy: PrivacySettingsDTO = field(default_factory=PrivacySettingsDTO)
    category: str = "backend:middle"
    public_code: str = "K-0000"


@dataclass
class World:
    """Состояние нижних модулей в памяти."""

    candidates: dict[UUID, FakeCandidate] = field(default_factory=dict)
    companies: dict[UUID, CompanyDTO] = field(default_factory=dict)
    needs: dict[UUID, NeedRefDTO] = field(default_factory=dict)
    disclosures: list[dict[str, Any]] = field(default_factory=list)
    access_log: list[dict[str, Any]] = field(default_factory=list)
    min_salary_calls: list[UUID] = field(default_factory=list)
    fit_band: FitBand | None = FitBand.STRONG
    exposure: ExposureStats = field(default_factory=ExposureStats)

    def add_candidate(self, candidate_id: UUID, **kwargs: Any) -> FakeCandidate:
        fake = FakeCandidate(public_code=f"K-{candidate_id.hex[:4].upper()}", **kwargs)
        self.candidates[candidate_id] = fake
        return fake

    def add_company(self, employer_id: UUID, *, trust: TrustLevel = TrustLevel.BASIC, name: str = "Орбита") -> None:
        self.companies[employer_id] = CompanyDTO(
            name=name,
            sphere="Финтех",
            description="Делаем платёжные сервисы для малого бизнеса.",
            site="https://example.com",
            city="Москва",
            contact_method=ContactMethod(kind=ContactKind.EMAIL, value="hr@example.com"),
            trust_level=trust,
            created_at=T0 - timedelta(days=100),
            is_complete=True,
        )

    def add_need(self, employer_id: UUID, category: str = "backend:middle") -> UUID:
        need_id = uuid4()
        self.needs[need_id] = NeedRefDTO(
            need_id=need_id,
            employer_id=employer_id,
            title="Backend-разработчик",
            category_code=category,
            work_formats=[WorkFormat.REMOTE],
            salary_from=150_000,
            salary_to=200_000,
            snapshot_id=uuid4(),
        )
        return need_id

    # --- profile ---------------------------------------------------------------------------------------------------
    def _visibility(self, db: Session, candidate_id: UUID, now: datetime) -> VisibilityDTO:
        fake = self.candidates[candidate_id]
        if fake.auto_paused_until is not None and fake.auto_paused_until > now:
            return VisibilityDTO(
                state=VisibilityState.PAUSED,
                pause_reason=PauseReason.AUTO_SILENCE,
                auto_paused_until=fake.auto_paused_until,
            )
        return VisibilityDTO(state=fake.state)

    def _pool_view(self, db: Session, candidate_ids: Any, now: datetime) -> dict[UUID, PoolProfile]:
        result = {}
        for candidate_id in candidate_ids:
            fake = self.candidates.get(candidate_id)
            if fake is None:
                continue
            visibility = self._visibility(db, candidate_id, now)
            result[candidate_id] = PoolProfile(
                public_code=fake.public_code,
                visible=visibility.state == VisibilityState.VISIBLE,
                visibility=visibility,
                privacy=fake.privacy,
                work_formats=fake.formats,
            )
        return result

    def _min_salary(self, db: Session, candidate_id: UUID) -> int | None:
        self.min_salary_calls.append(candidate_id)
        return self.candidates[candidate_id].min_salary

    def _disclose(self, db: Session, employer_id: UUID, candidate_id: UUID, **kwargs: Any) -> None:
        self.disclosures.append({"employer_id": employer_id, "candidate_id": candidate_id, **kwargs})

    def _is_disclosed(self, db: Session, employer_id: UUID, candidate_id: UUID) -> bool:
        return any(d["employer_id"] == employer_id and d["candidate_id"] == candidate_id for d in self.disclosures)

    def _log_access(self, db: Session, candidate_id: UUID, employer_id: UUID, kind: Any, ref_id: Any, now: Any) -> None:
        self.access_log.append({"candidate_id": candidate_id, "employer_id": employer_id, "kind": kind})

    def _set_auto_pause(self, db: Session, candidate_id: UUID, at: datetime, until: datetime) -> None:
        self.candidates[candidate_id].auto_paused_until = until

    def _clear_auto_pause(self, db: Session, candidate_id: UUID) -> None:
        self.candidates[candidate_id].auto_paused_until = None

    # --- matching --------------------------------------------------------------------------------------------------
    def _need_ref(self, db: Session, employer_id: UUID, need_id: UUID, snapshot_id: UUID | None = None) -> NeedRefDTO:
        need = self.needs.get(need_id)
        if need is None or need.employer_id != employer_id:
            raise not_found()
        return need

    def _explain(
        self, db: Session, employer_id: UUID, candidate_id: UUID, need_id: Any, snapshot_id: Any, now: Any
    ) -> Any:
        fake = self.candidates[candidate_id]
        return InvitationExplain(
            why=InvitationWhy(
                source="need" if need_id else "bank",
                target=category_ref(fake.category),
                employer_saw=["категорию и интервал уровня"],
            ),
            fit_band=self.fit_band,
            scorer_version="test-1",
        )

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        p, m = profile_service, matching_service
        monkeypatch.setattr(p, "visibility", self._visibility)
        monkeypatch.setattr(p, "pool_view", self._pool_view)
        monkeypatch.setattr(p, "privacy", lambda db, cid: self.candidates[cid].privacy)
        monkeypatch.setattr(p, "filled_channels", lambda db, cid: self.candidates[cid].filled)
        monkeypatch.setattr(p, "hidden_from_employer", lambda db, eid, cids: set())
        monkeypatch.setattr(p, "min_salary", self._min_salary)
        monkeypatch.setattr(p, "is_disclosed", self._is_disclosed)
        monkeypatch.setattr(p, "display_names", lambda db, eid, cids: {})
        monkeypatch.setattr(p, "disclose", self._disclose)
        monkeypatch.setattr(p, "log_access", self._log_access)
        monkeypatch.setattr(p, "set_auto_pause", self._set_auto_pause)
        monkeypatch.setattr(p, "clear_auto_pause", self._clear_auto_pause)
        monkeypatch.setattr(p, "auto_pause_until", lambda db, cid: self.candidates[cid].auto_paused_until)
        monkeypatch.setattr(p, "demo_persona", lambda db, cid: self.candidates[cid].persona)
        monkeypatch.setattr(m, "need_ref", self._need_ref)
        monkeypatch.setattr(m, "explain_for_invitation", self._explain)
        monkeypatch.setattr(m, "relaxation_hints", lambda db, eid, nid, kinds, now: [])
        monkeypatch.setattr(m, "exposure_stats", lambda db, cid, since, now: self.exposure)
        monkeypatch.setattr(company_service, "get_company", lambda db, eid: self.companies.get(eid))
        monkeypatch.setattr(
            company_service, "is_complete", lambda db, eid: eid in self.companies and self.companies[eid].is_complete
        )
        monkeypatch.setattr(assessment_service, "get_category", lambda db, cid: self._category(cid))
        monkeypatch.setattr(
            assessment_service,
            "get_categories",
            lambda db, cids: {cid: cat for cid in cids if (cat := self._category(cid)) is not None},
        )
        monkeypatch.setattr(catalog_service, "category_ref", category_ref)
        monkeypatch.setattr(catalog_service, "skill_ref", lambda code: Ref(code=code, title=code.title()))

    def _category(self, candidate_id: UUID) -> CategoryDTO | None:
        fake = self.candidates.get(candidate_id)
        if fake is None:
            return None
        spec, _, grade = fake.category.partition(":")
        return CategoryDTO(
            specialization_code=spec,
            grade_code=grade,
            category_code=fake.category,
            verdict=next(iter(TestOutcome)),
            assigned_at=T0 - timedelta(days=10),
            level_session_id=uuid4(),
        )


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    instance = World()
    instance.install(monkeypatch)
    return instance


def offer(candidate_id: UUID, **overrides: Any) -> dict[str, Any]:
    """Тело `InvitationCreate` с допустимыми значениями."""
    body: dict[str, Any] = {
        "candidate_id": str(candidate_id),
        "title": "Backend-разработчик в платежи",
        "description": "Развивать платёжное ядро: Python, PostgreSQL, очереди. Команда из шести человек.",
        "salary_from": 150_000,
        "salary_to": 200_000,
        "work_format": "remote",
        "city": None,
        "contact_method": {"kind": "email", "value": "hr@example.com"},
        "message": "Будем рады пообщаться",
    }
    body.update(overrides)
    return body


def send(
    db: Session, now: datetime, employer_id: UUID, candidate_id: UUID, *, is_demo: bool = False, **overrides: Any
) -> InvitationDTO:
    """Отправить приглашение фасадом (как сид) и «зафиксировать» точку сохранения теста."""
    data = InvitationData.model_validate(offer(candidate_id, **overrides))
    result = service.send_invitation(db, now, employer_id, data, str(uuid4()), is_demo=is_demo)
    db.commit()
    return result


@dataclass
class Pair:
    employer: Any
    candidate: Any


@pytest.fixture
def actors(make_user: Callable[..., Any], world: World) -> Callable[..., Any]:
    """Фабрика участников: `actors.employer()`, `actors.candidate(min_salary=...)` — пользователь и его мир."""

    class Factory:
        def employer(self, *, is_demo: bool = False, trust: TrustLevel = TrustLevel.BASIC, **kw: Any) -> Any:
            user = make_user("employer", is_demo=is_demo, **kw)
            world.add_company(user.id, trust=trust)
            return user

        def candidate(self, *, is_demo: bool = False, **fake: Any) -> Any:
            user = make_user("candidate", is_demo=is_demo)
            world.add_candidate(user.id, **fake)
            return user

        def pair(self, **fake: Any) -> Pair:
            return Pair(self.employer(), self.candidate(**fake))

    return Factory()  # type: ignore[return-value]


@pytest.fixture
def now(freeze_now: Any) -> Iterator[datetime]:
    """Замороженное время сервиса: `T0`; сдвиг — `freeze_now.tick(...)`."""
    yield freeze_now(T0)
