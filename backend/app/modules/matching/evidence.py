"""Доказательства навыков и пул кандидатов (Арх. 6.1, 6.2).

`load_pool` делает по одному пакетному вызову фасадов `assessment`, `profile`, `fsp`; кэша нет: отзыв согласия и
пауза действуют немедленно. Общей таблицы доказательств нет — источники объединяются при чтении (`collect`).

Правило демо-стенда (поправка рецензии R3-tz-compliance-1): работодатель с `app_user.is_demo = true` видит только
кандидатов с `app_user.is_demo = true`. Правило применяется здесь, в единственной точке входа в пул, поэтому
действует сразу на подборку, банк, карточку и чтение сохранённых версий.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core import clock
from app.modules.assessment import service as assessment
from app.modules.assessment.dto import LevelDTO, TestSkillEvidence
from app.modules.catalog import service as catalog
from app.modules.fsp import service as fsp
from app.modules.fsp.dto import FspSignal, FspSkillEvidence, FspSubject
from app.modules.identity import service as identity
from app.modules.matching import constants as C
from app.modules.matching import exposure
from app.modules.matching.explain import as_datetime
from app.modules.matching.features import CandidateFeatures, SkillEvidence, merge_evidence
from app.modules.profile import service as profile
from app.modules.profile.dto import PoolProfile
from app.shared.enums import EvidenceKind, EvidenceSource

#: Не больше стольких заявленных навыков справочника участвует в подборе (Арх. 6.2, `DECLARED_SKILLS_MAX`).
DECLARED_LIMIT = 30


def collect(
    test_items: Sequence[TestSkillEvidence], fsp_items: Sequence[FspSkillEvidence], declared: Sequence[str]
) -> dict[str, SkillEvidence]:
    """Объединить источники одного кандидата: по навыку остаётся запись с наибольшим весом (Арх. 6.2)."""
    items: list[SkillEvidence] = []
    for row in test_items:
        is_test = row.source == EvidenceSource.TEST
        items.append(
            SkillEvidence(
                skill_code=row.skill_code,
                kind=EvidenceKind.TEST if is_test else EvidenceKind.PULSE,
                full=row.full if is_test else True,
                confirmed_at=row.confirmed_at,
                ref_type="test_session" if is_test else "pulse_assignment",
                ref_id=str(row.ref_id) if row.ref_id else None,
                detail=row.detail,
            )
        )
    for fact in fsp_items:
        items.append(
            SkillEvidence(
                skill_code=fact.skill_code,
                kind=EvidenceKind.FSP,
                confirmed_at=as_datetime(fact.confirmed_at),
                ref_type="fsp_fact",
                ref_id=str(fact.fact_id),
                detail=fact.detail_public,
            )
        )
    for code in list(declared)[:DECLARED_LIMIT]:
        items.append(SkillEvidence(skill_code=code, kind=EvidenceKind.DECLARED, ref_type="profile"))
    return merge_evidence(items)


@dataclass(slots=True)
class Pool:
    """Кандидаты запроса с живыми данными нижних модулей.

    `features` — только те, кого работодателю можно показывать (см. `load_pool`); `levels` и `profiles` — все
    найденные, включая скрытых: по ним считаются воронка и состояние показа, наружу их данные не отдаются.
    """

    as_of: datetime
    today: date
    features: dict[UUID, CandidateFeatures] = field(default_factory=dict)
    levels: dict[UUID, LevelDTO] = field(default_factory=dict)
    profiles: dict[UUID, PoolProfile] = field(default_factory=dict)
    signals: dict[UUID, FspSignal] = field(default_factory=dict)
    #: Кандидаты, которых этот работодатель не видит по правилу демо-стенда.
    demo_blocked: set[UUID] = field(default_factory=set)

    def visible(self) -> list[CandidateFeatures]:
        """Признаки кандидатов с состоянием показа `visible` — вход ранжирования."""
        return [item for cid, item in self.features.items() if self.profiles[cid].visible]

    def fsp_line(self, candidate_id: UUID) -> str | None:
        signal = self.signals.get(candidate_id)
        return signal.public.headline if signal and signal.visible and signal.public else None

    def fsp_short(self, candidate_id: UUID) -> str | None:
        signal = self.signals.get(candidate_id)
        return signal.public.short if signal and signal.visible and signal.public else None

    def fsp_fact_id(self, candidate_id: UUID) -> str | None:
        """Факт с наибольшим вкладом в сигнал — на него ссылается довод `fsp`."""
        signal = self.signals.get(candidate_id)
        if not signal or not signal.visible or not signal.contributions:
            return None
        return str(max(signal.contributions, key=lambda item: (item.p, str(item.fact_id))).fact_id)

    def fsp_version(self) -> str:
        for signal in self.signals.values():
            if signal.version:
                return signal.version
        return C.FSP_SIGNAL_VERSION_FALLBACK

    def scorer_version(self) -> str:
        """`"match-2+{fsp_signal.version}+skills-{SKILLS_VERSION}"` (Арх. 6.10)."""
        return f"{C.SCORER_VERSION}+{self.fsp_version()}+skills-{catalog.SKILLS_VERSION}"


def fsp_verified(signal: FspSignal | None) -> bool:
    """Фильтр «есть достижения ФСП» (Арх. 6.4, № 5).

    Поправка рецензии R3-tz-compliance-8: подтверждённым считается только зачтённый результат либо разряд;
    одна роль тренера (сигнал 0, зачтённых фактов нет) фильтр не проходит.
    """
    return bool(signal and signal.verified and (signal.counted > 0 or signal.floor_source is not None))


def blocked_for_demo(db: Session, employer_id: UUID | None, candidate_ids: Collection[UUID]) -> set[UUID]:
    """Кого из кандидатов не видит этот работодатель по правилу демо-стенда (R3-tz-compliance-1)."""
    if employer_id is None or not candidate_ids:
        return set()
    users = identity.users(db, [employer_id, *candidate_ids])
    employer = users.get(employer_id)
    if employer is None or not employer.is_demo:
        return set()
    return {cid for cid in candidate_ids if not (cid in users and users[cid].is_demo)}


def subjects_for(levels: Mapping[UUID, LevelDTO], profiles: Mapping[UUID, PoolProfile]) -> list[FspSubject]:
    return [
        FspSubject(
            user_id=cid,
            specialization=levels[cid].specialization_code if cid in levels else None,
            show_summary=item.privacy.show_fsp_summary,
        )
        for cid, item in profiles.items()
    ]


def load_pool(
    db: Session,
    employer_id: UUID | None,
    now: datetime,
    *,
    specialization_code: str | None = None,
    grade_codes: Collection[str] | None = None,
    candidate_ids: Collection[UUID] | None = None,
    include_hidden: bool = False,
) -> Pool:
    """Собрать пул: уровни категории → профили → сигнал и навыки ФСП → навыки теста → показы.

    Признаки строятся для кандидатов с состоянием показа `visible`; `include_hidden` добавляет скрытых (карточка
    раскрытой пары, собственный кабинет кандидата). `employer_id = None` — запрос самого кандидата: правило
    демо-стенда и учёт показов этого работодателя не применяются.
    """
    today = clock.to_local_date(now)
    pool = Pool(as_of=now, today=today)
    if candidate_ids is not None and not candidate_ids:
        return pool
    levels = assessment.get_levels(
        db,
        specialization_code=specialization_code,
        grade_codes=list(grade_codes) if grade_codes is not None else None,
        candidate_ids=list(candidate_ids) if candidate_ids is not None else None,
        now=now,
    )
    pool.levels = {item.candidate_id: item for item in levels}
    if not pool.levels:
        return pool
    pool.demo_blocked = blocked_for_demo(db, employer_id, list(pool.levels))
    for cid in pool.demo_blocked:
        del pool.levels[cid]
    ids = list(pool.levels)
    pool.profiles = profile.pool_view(db, ids, now)
    shown = [cid for cid in ids if cid in pool.profiles and (include_hidden or pool.profiles[cid].visible)]
    if not shown:
        return pool
    subjects = subjects_for(pool.levels, {cid: pool.profiles[cid] for cid in shown})
    pool.signals = fsp.get_signals(db, subjects, as_of=today)
    fsp_skills = fsp.get_skill_evidence(db, subjects, as_of=today)
    test_skills = assessment.skill_evidence(db, shown)
    shows = exposure.exposure_7d(db, shown, today)
    for cid in shown:
        level, item, signal = pool.levels[cid], pool.profiles[cid], pool.signals.get(cid)
        visible_signal = signal if signal and signal.visible else None
        declared = [code for code in item.declared_skills if catalog.is_skill(code)]
        pool.features[cid] = CandidateFeatures(
            candidate_id=cid,
            specialization_code=level.specialization_code,
            grade_code=level.grade_code,
            verdict=level.verdict,
            theta=level.theta,
            se=level.se,
            se_eff=level.se_eff,
            cut=level.cut,
            width=level.width,
            tested_at=clock.to_local_date(level.tested_at),
            last_evidence_at=clock.to_local_date(level.last_evidence_at),
            age_days=level.age_days,
            stale=level.stale,
            evidence=collect(test_skills.get(cid, []), fsp_skills.get(cid, []) if visible_signal else [], declared),
            fsp_signal=visible_signal.value if visible_signal else 0.0,
            fsp_band=visible_signal.band if visible_signal else "none",
            fsp_verified=fsp_verified(visible_signal),
            work_formats=frozenset(str(value) for value in item.work_formats),
            exposure_7d=shows.get(cid, 0),
        )
    return pool
