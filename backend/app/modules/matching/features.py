"""Признаки кандидата — единственный вход ранжирования (Арх. 6.1, 6.2).

Файл чистый: без SQLAlchemy и без обращений к фасадам. Структуры собирает `pool.load_pool` (рабочий сервис)
и `app.eval.matching.observe` (валидация) — ранжирование не отличает одно от другого.

Белый список полей `CandidateFeatures` закреплён тестом: имени, пола, возраста, города, зарплаты, занятости
входящих и отзывчивости в структуре нет, поэтому инвариантность выдачи к ним обеспечена конструкцией.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from app.shared.enums import EvidenceKind, TestOutcome

FspBand = Literal["none", "low", "medium", "high"]

#: Порядок видов при равном весе и дате: `test, pulse, fsp, declared` (Арх. 6.2).
KIND_ORDER: dict[EvidenceKind, int] = {
    EvidenceKind.TEST: 0,
    EvidenceKind.PULSE: 1,
    EvidenceKind.FSP: 2,
    EvidenceKind.DECLARED: 3,
    EvidenceKind.NONE: 4,
}

#: Виды, которые считаются подтверждением (входят в `confirmed_pct`, Арх. 6.5).
CONFIRMED_KINDS: frozenset[EvidenceKind] = frozenset({EvidenceKind.TEST, EvidenceKind.PULSE, EvidenceKind.FSP})


@dataclass(frozen=True, slots=True)
class SkillEvidence:
    """Лучшее доказательство одного навыка кандидата (Арх. 6.2).

    `full` различает два веса вида `test`: группа подтверждена целиком (1.0) либо решено одно задание (0.7).
    Вес не хранится: его назначает `scoring.evidence_weight` по константам, чтобы абляции меняли вес, не трогая
    признаки. `ref_type`, `ref_id`, `detail` нужны только объяснению.
    """

    skill_code: str
    kind: EvidenceKind
    full: bool = True
    #: Момент подтверждения (с часовым поясом); у заявленного — `None`.
    confirmed_at: datetime | None = None
    ref_type: str | None = None
    ref_id: str | None = None
    #: Обобщённая подпись источника, которую можно показывать до раскрытия.
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class CandidateFeatures:
    """Признаки кандидата для ранжирования (Арх. 6.1). Скорер видит только это."""

    candidate_id: UUID
    specialization_code: str
    grade_code: str
    #: Текущий вердикт уровня категории.
    verdict: TestOutcome
    # Из `assessment.get_levels` (Арх. 5.6): подбор неопределённость не пересчитывает.
    theta: float
    se: float
    se_eff: float
    cut: float
    width: float
    tested_at: date
    last_evidence_at: date
    age_days: int
    stale: bool
    evidence: Mapping[str, SkillEvidence]
    #: 0..1; 0, если истории нет, ФСП ID не привязан или достижения скрыты.
    fsp_signal: float
    fsp_band: FspBand
    fsp_verified: bool
    work_formats: frozenset[str]
    exposure_7d: int


#: Белый список полей (тест `test_features_whitelist`).
FEATURE_FIELDS: tuple[str, ...] = tuple(field.name for field in fields(CandidateFeatures))


def evidence_preference(item: SkillEvidence, weight: float) -> tuple[float, float, int]:
    """Ключ «какое доказательство лучше»: больший вес, затем более поздняя дата, затем порядок вида."""
    moment = item.confirmed_at.timestamp() if item.confirmed_at is not None else float("-inf")
    return (weight, moment, -KIND_ORDER[item.kind])


def nominal_weight(item: SkillEvidence) -> float:
    """Номинальный вес вида по Арх. 6.2 — только для объединения источников; оценку считает `scoring`."""
    if item.kind == EvidenceKind.TEST:
        return 1.0 if item.full else 0.7
    if item.kind in (EvidenceKind.PULSE, EvidenceKind.FSP):
        return 0.7
    return 0.3 if item.kind == EvidenceKind.DECLARED else 0.0


def merge_evidence(items: Iterable[SkillEvidence]) -> dict[str, SkillEvidence]:
    """Объединить источники: по навыку остаётся запись с наибольшим весом (Арх. 6.2).

    При равенстве веса — с более поздней `confirmed_at`, затем по порядку `test, pulse, fsp, declared`.
    Общей таблицы доказательств нет: объединение выполняется при чтении.
    """
    best: dict[str, SkillEvidence] = {}
    for item in items:
        if item.kind == EvidenceKind.NONE:
            continue
        current = best.get(item.skill_code)
        if current is None or evidence_preference(item, nominal_weight(item)) > evidence_preference(
            current, nominal_weight(current)
        ):
            best[item.skill_code] = item
    return best
