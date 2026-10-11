"""Живое состояние кандидатов поверх сохранённых данных (Арх. 6.9, 6.11).

Единственное место, где решается, можно ли отдать работодателю строку кандидата: кандидат сейчас `visible` либо
пара раскрыта. Скрытый кандидат нераскрытой пары не отдаётся ни в одном списке — только числом `hidden_count`.
Правило демо-стенда (R3-tz-compliance-1) действует здесь же: живой кандидат для демо-работодателя скрыт всегда.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy.orm import Session

from app.core import clock
from app.modules.fsp import service as fsp
from app.modules.fsp.dto import FspSignal, FspSubject
from app.modules.matching.evidence import blocked_for
from app.modules.matching.explain import MatchExplanation, ReadRules, apply_read_rules
from app.modules.profile import service as profile
from app.modules.profile.dto import PoolProfile
from app.shared.enums import DiscloseField, EvidenceKind, VisibilityState


@dataclass(slots=True)
class Live:
    """Состояние показа, раскрытие, имена и видимость ФСП для набора кандидатов — на момент чтения."""

    profiles: dict[UUID, PoolProfile] = field(default_factory=dict)
    disclosed: dict[UUID, frozenset[str]] = field(default_factory=dict)
    names: dict[UUID, str | None] = field(default_factory=dict)
    signals: dict[UUID, FspSignal] = field(default_factory=dict)
    blocked: set[UUID] = field(default_factory=set)

    def is_disclosed(self, candidate_id: UUID) -> bool:
        return candidate_id not in self.blocked and bool(self.disclosed.get(candidate_id))

    def available(self, candidate_id: UUID) -> bool:
        item = self.profiles.get(candidate_id)
        return bool(item and item.visible and candidate_id not in self.blocked)

    def shown(self, candidate_id: UUID) -> bool:
        """Можно ли отдавать строку кандидата этому работодателю."""
        if candidate_id not in self.profiles or candidate_id in self.blocked:
            return False
        return self.available(candidate_id) or self.is_disclosed(candidate_id)

    def unavailable_reason(self, candidate_id: UUID) -> Literal["paused", "withdrawn"] | None:
        if self.available(candidate_id):
            return None
        state = self.profiles[candidate_id].visibility.state
        return "paused" if state == VisibilityState.PAUSED else "withdrawn"

    def display_name(self, candidate_id: UUID) -> str | None:
        return self.names.get(candidate_id) if self.is_disclosed(candidate_id) else None

    def fsp_visible(self, candidate_id: UUID) -> bool:
        signal = self.signals.get(candidate_id)
        return bool(signal and signal.visible)

    def fsp_short(self, candidate_id: UUID) -> str | None:
        signal = self.signals.get(candidate_id)
        return signal.public.short if signal and signal.visible and signal.public else None

    def reveal_fsp_details(self, candidate_id: UUID) -> bool:
        return self.is_disclosed(candidate_id) and DiscloseField.FSP_DETAILS.value in {
            str(item) for item in self.disclosed.get(candidate_id, frozenset())
        }


def load_live(
    db: Session,
    employer_id: UUID,
    specializations: Mapping[UUID, str | None],
    now: datetime,
) -> Live:
    """Живое состояние кандидатов `specializations` (кандидат → код его специализации) — по одному вызову
    каждого фасада на весь набор.
    """
    ids = list(specializations)
    if not ids:
        return Live()
    live = Live(blocked=blocked_for(db, employer_id, ids))
    live.profiles = profile.pool_view(db, ids, now)
    present = [cid for cid in ids if cid in live.profiles and cid not in live.blocked]
    if not present:
        return live
    live.disclosed = dict(profile.disclosed_map(db, employer_id, present))
    opened = [cid for cid in present if live.is_disclosed(cid)]
    live.names = dict(profile.display_names(db, employer_id, opened)) if opened else {}
    shown = [cid for cid in present if live.shown(cid)]
    if shown:
        subjects = [
            FspSubject(
                user_id=cid,
                specialization=specializations[cid],
                show_summary=live.profiles[cid].privacy.show_fsp_summary,
            )
            for cid in shown
        ]
        live.signals = fsp.get_signals(db, subjects, as_of=clock.to_local_date(now))
    return live


def fsp_fact_ids(expl: MatchExplanation) -> list[UUID]:
    """Факты ФСП, на которые ссылается сохранённое объяснение."""
    found: list[str] = []
    for item in expl.requirements:
        if item.kind == EvidenceKind.FSP and item.source_ref and item.source_ref.id:
            found.append(item.source_ref.id)
    for reason in expl.reasons:
        if reason.code in ("fsp", "fsp_low") and reason.evidence_ref.id:
            found.append(reason.evidence_ref.id)
    result: list[UUID] = []
    for value in dict.fromkeys(found):
        try:
            result.append(UUID(value))
        except ValueError:
            continue
    return result


def fsp_texts(db: Session, live: Live, candidate_id: UUID, fact_ids: Collection[UUID]) -> dict[str, str | None] | None:
    """Подробные тексты фактов ФСП — только раскрытой паре с `fsp_details` (Арх. 6.10); иначе `None`."""
    if not fact_ids or not live.reveal_fsp_details(candidate_id):
        return None
    texts = fsp.render_evidence(
        db,
        candidate_id,
        list(fact_ids),
        show_summary=live.profiles[candidate_id].privacy.show_fsp_summary,
        reveal_details=True,
        disclosed=True,
    )
    return {str(fact_id): texts.get(fact_id) for fact_id in fact_ids}


def read_explanation(db: Session, live: Live, candidate_id: UUID, stored: Mapping[str, object]) -> MatchExplanation:
    """Сохранённое объяснение с перепроверкой на момент чтения (Арх. 6.11): скрытое заявленное и недоступные
    сведения ФСП не отдаются; раскрытой паре с `fsp_details` — подробный текст фактов.
    """
    expl = MatchExplanation.model_validate(stored)
    rules = ReadRules(
        declared_hidden=not live.profiles[candidate_id].privacy.show_declared_stack,
        experience_hidden=not live.profiles[candidate_id].privacy.show_experience,
        fsp_visible=live.fsp_visible(candidate_id),
        fsp_texts=fsp_texts(db, live, candidate_id, fsp_fact_ids(expl)),
    )
    return apply_read_rules(expl, rules)
