"""Фикстуры тестов подбора: учебный мир вместо нижних модулей.

Модули `assessment`, `fsp`, `profile`, `catalog`, `company`, `textparse` пишутся параллельно, поэтому их фасады
подменяются по сигнатурам Арх. 2.5 (план работ, раздел 0, п. 3). Боевой код обращается к фасадам через атрибуты
модулей `service`, так что подмена действует на весь модуль `matching`. `identity` — настоящий.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import ApiException
from app.modules.assessment import service as assessment
from app.modules.assessment.dto import LevelDTO, LevelView, SurveyDeclared, TestSkillEvidence
from app.modules.catalog import service as catalog
from app.modules.catalog.dto import Catalog, GradeDTO, SpecializationDTO
from app.modules.company import service as company
from app.modules.fsp import service as fsp
from app.modules.fsp.dto import (
    FspContribution,
    FspEmployerBlock,
    FspPublicSummary,
    FspSignal,
    FspSkillEvidence,
    FspSubject,
)
from app.modules.matching.dto import NeedData
from app.modules.profile import service as profile
from app.modules.profile.dto import ContactsDTO, PoolProfile, PrivacySettingsDTO, ProfilePdfModel, VisibilityDTO
from app.modules.textparse import service as textparse
from app.modules.textparse.dto import NeedDraft
from app.shared.enums import CategoryBasis, EvidenceSource, PauseReason, TestOutcome, VisibilityState, WorkFormat
from app.shared.schemas import CategoryRef, Ref

GRADES = ["junior", "middle", "senior"]
SPECS = ["backend", "frontend", "mobile"]
SKILLS = {
    "python": "Python",
    "sql": "SQL",
    "postgresql": "PostgreSQL",
    "kafka": "Kafka",
    "docker": "Docker",
    "redis": "Redis",
    "algorithms": "Алгоритмы",
    "react": "React",
}
IMPLIES = {"postgresql": frozenset({"sql"})}
#: Навыки по специализациям (`catalog.is_skill_relevant`); `algorithms` — общий навык, ни к одной не привязан.
SKILL_SPECS = {
    "python": ("backend",),
    "sql": ("backend",),
    "postgresql": ("backend",),
    "kafka": ("backend",),
    "docker": ("backend", "mobile"),
    "redis": ("backend",),
    "algorithms": (),
    "react": ("frontend", "mobile"),
}
#: Пары без теста: потребность по ним создаётся, кандидаты там — с заявленным грейдом (`Cand.basis = declared`).
UNAVAILABLE = {("mobile", "junior"), ("mobile", "middle"), ("mobile", "senior")}
FSP_FULL_TEXT = "1 место, Кубок России по спортивному программированию 2025"


@dataclass
class Cand:
    """Кандидат учебного мира: всё, что отдают подбору нижние модули."""

    id: UUID
    public_code: str
    spec: str = "backend"
    grade: str = "middle"
    #: `declared` — грейд заявлен, теста не было: уровня, вердикта и давности у кандидата нет.
    basis: CategoryBasis = CategoryBasis.TEST
    verdict: TestOutcome = TestOutcome.CONFIRMED
    theta: float = 0.9
    se: float = 0.4
    se_eff: float | None = None
    cut: float = 0.0
    width: float = 1.5
    age_days: int = 10
    stale: bool = False
    #: Навык → группа подтверждена целиком (вес 1.0) либо решено одно задание (0.7).
    test: dict[str, bool] = field(default_factory=dict)
    pulse: list[str] = field(default_factory=list)
    fsp_skills: list[str] = field(default_factory=list)
    declared: list[str] = field(default_factory=list)
    custom_skills: list[str] = field(default_factory=list)
    fsp_value: float = 0.0
    fsp_band: str = "none"
    fsp_linked: bool = False
    formats: tuple[str, ...] = ("remote",)
    state: VisibilityState = VisibilityState.VISIBLE
    privacy: PrivacySettingsDTO = field(default_factory=PrivacySettingsDTO)
    is_demo: bool = False
    city: str | None = "Казань"
    experience_years: float | None = 4.0
    first_name: str = "Тест"
    last_name: str = "Кандидатов"
    about: str | None = "Пишу сервисы"
    #: Работодатель → раскрытые поля.
    disclosed: dict[UUID, frozenset[str]] = field(default_factory=dict)
    fact_id: UUID = field(default_factory=uuid4)


class World:
    """Учебный мир: кандидаты, справочник и подменённые фасады."""

    def __init__(self, make_user: Callable[..., Any]) -> None:
        self._make_user = make_user
        self.cands: dict[UUID, Cand] = {}
        self.company_complete = True
        self.access_log: list[tuple[UUID, UUID, str]] = []
        self.calls: dict[str, int] = {}
        self._code = 10000

    # --- наполнение ---------------------------------------------------------------------------------------------

    def add(self, **fields: Any) -> Cand:
        user = self._make_user("candidate", is_demo=bool(fields.get("is_demo", False)))
        self._code += 1
        cand = Cand(id=user.id, public_code=f"К-{self._code}", **fields)
        self.cands[cand.id] = cand
        return cand

    def pause(self, cand: Cand) -> None:
        cand.state = VisibilityState.PAUSED

    def unpublish(self, cand: Cand) -> None:
        cand.state = VisibilityState.UNPUBLISHED

    def need_data(self, **changes: Any) -> NeedData:
        base: dict[str, Any] = {
            "title": "Backend-разработчик",
            "team_description": "Команда платёжного сервиса, шесть человек",
            "specialization_code": "backend",
            "grade_code": "middle",
            "must_skills": ["python", "postgresql"],
            "nice_skills": ["docker"],
            "work_formats": [WorkFormat.REMOTE],
            "salary_from": 200_000,
            "salary_to": 280_000,
        }
        base.update(changes)
        return NeedData.model_validate(base)

    # --- assessment ---------------------------------------------------------------------------------------------

    def get_levels(
        self,
        db: Session,
        *,
        specialization_code: str | None = None,
        grade_codes: Collection[str] | None = None,
        candidate_ids: Collection[UUID] | None = None,
        now: datetime,
    ) -> list[LevelDTO]:
        self.calls["get_levels"] = self.calls.get("get_levels", 0) + 1
        rows = []
        for cand in self.cands.values():
            if specialization_code is not None and cand.spec != specialization_code:
                continue
            if grade_codes is not None and cand.grade not in grade_codes:
                continue
            if candidate_ids is not None and cand.id not in candidate_ids:
                continue
            if cand.basis == CategoryBasis.DECLARED:
                rows.append(
                    LevelDTO(
                        candidate_id=cand.id,
                        specialization_code=cand.spec,
                        grade_code=cand.grade,
                        basis=CategoryBasis.DECLARED,
                        cut=cand.cut,
                        cut_next=cand.cut + cand.width,
                        width=cand.width,
                    )
                )
                continue
            tested = now - timedelta(days=cand.age_days)
            rows.append(
                LevelDTO(
                    candidate_id=cand.id,
                    specialization_code=cand.spec,
                    grade_code=cand.grade,
                    verdict=cand.verdict,
                    theta=cand.theta,
                    se=cand.se,
                    se_eff=cand.se_eff if cand.se_eff is not None else cand.se,
                    cut=cand.cut,
                    cut_next=cand.cut + cand.width,
                    width=cand.width,
                    tested_at=tested,
                    last_evidence_at=tested,
                    age_days=cand.age_days,
                    stale=cand.stale,
                )
            )
        return rows

    def level_views(self, db: Session, candidate_ids: Collection[UUID], now: datetime) -> dict[UUID, LevelView]:
        result = {}
        for cid in candidate_ids:
            cand = self.cands.get(cid)
            # Как в боевом фасаде: у заявленного грейда уровня по тесту нет, записи не будет.
            if cand is None or cand.basis == CategoryBasis.DECLARED:
                continue
            tested = now - timedelta(days=cand.age_days)
            result[cid] = LevelView(
                point=60.0,
                lower=50.0,
                upper=70.0,
                thresholds=[],
                verdict=cand.verdict,
                verdict_label="подтверждён",
                stale=cand.stale,
                tested_at=tested,
                last_evidence_at=tested,
            )
        return result

    def skill_evidence(self, db: Session, candidate_ids: Collection[UUID]) -> dict[UUID, list[TestSkillEvidence]]:
        result: dict[UUID, list[TestSkillEvidence]] = {}
        moment = clock.now(db) - timedelta(days=5)
        for cid in candidate_ids:
            cand = self.cands[cid]
            rows = [
                TestSkillEvidence(
                    skill_code=skill,
                    source=EvidenceSource.TEST,
                    full=full,
                    group_code="g",
                    ref_id=None,
                    detail="задания теста",
                    confirmed_at=moment,
                )
                for skill, full in cand.test.items()
            ]
            rows += [
                TestSkillEvidence(
                    skill_code=skill,
                    source=EvidenceSource.PULSE,
                    full=False,
                    group_code="g",
                    detail="короткое задание",
                    confirmed_at=moment,
                )
                for skill in cand.pulse
            ]
            result[cid] = rows
        return result

    def survey_declared(self, db: Session, candidate_ids: Collection[UUID]) -> dict[UUID, SurveyDeclared]:
        return {cid: SurveyDeclared(industry_domains=["fintech"]) for cid in candidate_ids}

    # --- profile ------------------------------------------------------------------------------------------------

    def pool_view(self, db: Session, candidate_ids: Collection[UUID], now: datetime) -> dict[UUID, PoolProfile]:
        self.calls["pool_view"] = self.calls.get("pool_view", 0) + 1
        result = {}
        for cid in candidate_ids:
            cand = self.cands.get(cid)
            if cand is None:
                continue
            privacy = cand.privacy
            result[cid] = PoolProfile(
                public_code=cand.public_code,
                visible=cand.state == VisibilityState.VISIBLE,
                visibility=VisibilityDTO(
                    state=cand.state,
                    pause_reason=PauseReason.MANUAL if cand.state == VisibilityState.PAUSED else None,
                ),
                privacy=privacy,
                work_formats=[WorkFormat(item) for item in cand.formats],
                declared_skills=list(cand.declared) if privacy.show_declared_stack else [],
                custom_skills=list(cand.custom_skills),
                city=cand.city if privacy.show_city else None,
                experience_years=cand.experience_years if privacy.show_experience else None,
                is_demo=cand.is_demo,
            )
        return result

    def disclosed_map(
        self, db: Session, employer_id: UUID, candidate_ids: Collection[UUID]
    ) -> dict[UUID, frozenset[str]]:
        return {
            cid: self.cands[cid].disclosed[employer_id]
            for cid in candidate_ids
            if cid in self.cands and employer_id in self.cands[cid].disclosed
        }

    def display_names(self, db: Session, employer_id: UUID, candidate_ids: Collection[UUID]) -> dict[UUID, str | None]:
        return {
            cid: f"{self.cands[cid].first_name} {self.cands[cid].last_name}"
            for cid in candidate_ids
            if employer_id in self.cands[cid].disclosed
        }

    def _contacts(self, cand: Cand) -> ContactsDTO:
        return ContactsDTO(
            candidate_id=cand.id,
            public_code=cand.public_code,
            first_name=cand.first_name,
            last_name=cand.last_name,
            about=cand.about,
            email=f"cand-{cand.public_code[2:]}@example.com",
            custom_skills=list(cand.custom_skills),
        )

    def contacts_for_pair(self, db: Session, employer_id: UUID, candidate_id: UUID) -> ContactsDTO | None:
        cand = self.cands.get(candidate_id)
        if cand is None or employer_id not in cand.disclosed:
            return None
        return self._contacts(cand)

    def own_contacts(self, db: Session, candidate_id: UUID) -> ContactsDTO:
        cand = self.cands.get(candidate_id)
        if cand is None:
            raise ApiException(404, "not_found")
        return self._contacts(cand)

    def render_profile_pdf(self, model: ProfilePdfModel) -> bytes:
        self.last_pdf_model = model
        return b"%PDF-1.7 test"

    def log_access(
        self, db: Session, candidate_id: UUID, employer_id: UUID, kind: Any, ref_id: UUID | None, now: datetime
    ) -> None:
        self.access_log.append((candidate_id, employer_id, str(kind)))

    # --- fsp ----------------------------------------------------------------------------------------------------

    def get_signals(self, db: Session, subjects: Sequence[FspSubject], *, as_of: date) -> dict[UUID, FspSignal]:
        self.calls["get_signals"] = self.calls.get("get_signals", 0) + 1
        result = {}
        for subject in subjects:
            cand = self.cands[subject.user_id]
            has = (cand.fsp_value > 0 or cand.fsp_linked) and subject.show_summary
            result[cand.id] = FspSignal(
                user_id=cand.id,
                value=cand.fsp_value if has else 0.0,
                counted=1 if has and cand.fsp_value > 0 else 0,
                contributions=(
                    [
                        FspContribution(
                            fact_id=cand.fact_id, p=1.0, base_points=1.0, decay=1.0, relevance=1.0, order_weight=1.0
                        )
                    ]
                    if has and cand.fsp_value > 0
                    else []
                ),
                band=cand.fsp_band if has else "none",  # type: ignore[arg-type]
                visible=has,
                verified=has,
                public=(
                    FspPublicSummary(level=2, headline="призёр всероссийских соревнований", short="призёр, всеросс.")
                    if has
                    else None
                ),
                version="fsp-signal-test",
            )
        return result

    def get_skill_evidence(
        self, db: Session, subjects: Sequence[FspSubject], *, as_of: date
    ) -> dict[UUID, list[FspSkillEvidence]]:
        result = {}
        for subject in subjects:
            cand = self.cands[subject.user_id]
            if not subject.show_summary:
                continue
            result[cand.id] = [
                FspSkillEvidence(
                    skill_code=skill,
                    source="discipline",
                    fact_id=cand.fact_id,
                    confirmed_at=as_of - timedelta(days=100),
                    detail_public="достижение ФСП · алгоритмическое программирование",
                    detail_full=FSP_FULL_TEXT,
                )
                for skill in cand.fsp_skills
            ]
        return result

    def employer_block(self, db: Session, user_id: UUID, **kwargs: Any) -> FspEmployerBlock:
        return FspEmployerBlock(mode="none", neutral_text="Подтверждённых достижений ФСП в профиле нет")

    def pdf_block(self, db: Session, user_id: UUID, **kwargs: Any) -> FspEmployerBlock:
        return FspEmployerBlock(mode="none")

    def render_evidence(
        self, db: Session, user_id: UUID, fact_ids: Collection[UUID], **kwargs: Any
    ) -> dict[UUID, str | None]:
        cand = self.cands[user_id]
        visible = bool(kwargs.get("show_summary")) and (cand.fsp_value > 0 or cand.fsp_linked)
        return dict.fromkeys(fact_ids, FSP_FULL_TEXT if visible else None)


def _category_ref(code: str) -> CategoryRef:
    spec, _, grade = code.partition(":")
    return CategoryRef(
        code=code,
        title=f"{spec.title()} · {grade.title()}",
        specialization=Ref(code=spec, title=spec.title()),
        grade=Ref(code=grade, title=grade.title()),
    )


def _skill_ref(code: str) -> Ref:
    return Ref(code=code, title=SKILLS[code])


@pytest.fixture
def world(db: Session, make_user: Callable[..., Any], monkeypatch: pytest.MonkeyPatch) -> World:
    """Учебный мир с подменёнными фасадами нижних модулей."""
    instance = World(make_user)
    for name in ("get_levels", "level_views", "skill_evidence", "survey_declared"):
        monkeypatch.setattr(assessment, name, getattr(instance, name))
    for name in (
        "pool_view",
        "disclosed_map",
        "display_names",
        "contacts_for_pair",
        "own_contacts",
        "render_profile_pdf",
        "log_access",
    ):
        monkeypatch.setattr(profile, name, getattr(instance, name))
    for name in ("get_signals", "get_skill_evidence", "employer_block", "pdf_block", "render_evidence"):
        monkeypatch.setattr(fsp, name, getattr(instance, name))

    grades = [GradeDTO(code=code, title=code.title(), order=index + 1) for index, code in enumerate(GRADES)]
    specs = [
        SpecializationDTO(code=code, title=code.title(), title_short=code.title(), direction_code="dev")
        for code in SPECS
    ]
    monkeypatch.setattr(catalog, "SKILLS_VERSION", "test")
    monkeypatch.setattr(catalog, "skill_ref", _skill_ref)
    monkeypatch.setattr(catalog, "is_skill", lambda code: code in SKILLS)
    monkeypatch.setattr(catalog, "is_skill_relevant", lambda code, spec: spec in SKILL_SPECS.get(code, ()))
    monkeypatch.setattr(catalog, "implies_closure", lambda code: IMPLIES.get(code, frozenset()))
    monkeypatch.setattr(catalog, "grades_ordered", lambda: grades)
    monkeypatch.setattr(catalog, "category_ref", _category_ref)
    monkeypatch.setattr(
        catalog,
        "get_catalog",
        lambda: Catalog(specializations=specs, grades=grades, roles=[Ref(code="dev", title="Dev")]),
    )
    monkeypatch.setattr(
        catalog, "is_available", lambda spec, grade=None: spec in SPECS and (spec, grade) not in UNAVAILABLE
    )
    monkeypatch.setattr(catalog, "log_miss", lambda db, terms, source: None)
    monkeypatch.setattr(company, "is_complete", lambda db, employer_id: instance.company_complete)
    monkeypatch.setattr(
        textparse,
        "parse_need_text",
        lambda text: NeedDraft(specialization_code="backend", must_skills=["python"], unknown_terms=["фубар"]),
    )
    return instance
