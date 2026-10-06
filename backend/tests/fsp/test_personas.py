"""Типовые персонажи демо-реестра (приложение D, §8.3) на полном генераторе: привязка, сигнал, подтверждения навыков.

Полный реестр записывается в базу один раз на тест (около трёх секунд), поэтому проверок в тесте много.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.fsp_mock import generator
from app.fsp_mock.models import Athlete
from app.fsp_mock.personas import persona_fsp_id
from app.modules.fsp import service, sync
from app.modules.fsp.dto import FspSubject
from app.modules.fsp.views import history_of, last_attempt, load

AS_OF = date(2026, 10, 20)

#: Значения приложения D, §8.3 с допуском 0.02: без нормативов и судейства они сходятся (Арх. 15.1, № 47).
EXPECTED = [
    ("anna", "backend", 0.71),
    ("anna", "frontend", 0.67),
    ("mikhail", "backend", 0.91),
    ("dasha", "frontend", 0.11),
    ("oleg", "backend", 0.26),
    ("rustam", "infosec", 0.47),
    ("rustam", "backend", 0.32),
    ("zarina", "embedded", 0.78),
    ("zarina", "backend", 0.53),
    ("edge", "backend", 0.36),
    ("olga", "backend", 0.0),
    ("elena", "backend", 0.0),
    ("pavel", "backend", 0.0),
]


@pytest.mark.slow
def test_personas(db: Session, make_user: Callable[..., object]) -> None:
    generator.reset(db)
    db.commit()
    users: dict[str, UUID] = {}
    for key in {key for key, _, _ in EXPECTED}:
        user = make_user("candidate")
        users[key] = user.id  # type: ignore[attr-defined]
        service.seed_link(db, users[key], str(persona_fsp_id(key)))
    with pytest.raises(ValueError):  # несовершеннолетний: привязка отклонена
        service.seed_link(db, make_user("candidate").id, str(persona_fsp_id("timur")))  # type: ignore[attr-defined]

    mismatches = []
    for key, specialization, expected in EXPECTED:
        subject = FspSubject(user_id=users[key], specialization=specialization, show_summary=True)
        value = service.get_signals(db, [subject], as_of=AS_OF)[users[key]].value
        if abs(value - expected) > 0.02:
            mismatches.append((key, specialization, expected, value))
    assert not mismatches, mismatches

    def state(key: str) -> tuple[str | None, str | None]:
        data = load(db, [users[key]], only_evidence=False)[users[key]]
        assert data.identity is not None
        history = history_of(data, sync.current_snapshot(db, data.identity.id), last_attempt(db, users[key]), AS_OF)  # type: ignore[arg-type]
        assert history is not None
        return history.status, history.reason

    assert state("olga") == ("no_history", "no_results")
    assert state("pavel") == ("no_history", "no_counted_results")
    assert state("elena") == ("has_history", None)
    assert state("anna") == ("has_history", None)

    anna = FspSubject(user_id=users["anna"], specialization="backend", show_summary=True)
    skills = {item.skill_code for item in service.get_skill_evidence(db, [anna], as_of=AS_OF)[users["anna"]]}
    assert {"algorithms", "data_structures", "teamwork", "mvp_delivery", "leadership"} <= skills
    signal = service.get_signals(db, [anna], as_of=AS_OF)[users["anna"]]
    assert signal.leadership_level == "basic" and signal.public is not None and signal.band == "high"
    assert signal.public.level == 3  # у реестра хватает спортсменов для всех четырёх признаков

    elena = FspSubject(user_id=users["elena"], specialization="backend", show_summary=True)
    elena_signal = service.get_signals(db, [elena], as_of=AS_OF)[users["elena"]]
    assert elena_signal.value == 0 and elena_signal.leadership_level == "strong"
    assert elena_signal.verified is False  # поправка R3-tz-compliance-8: одна роль тренера фильтр не проходит
    assert elena_signal.public is not None and elena_signal.public.level == 1
    elena_skills = {item.skill_code for item in service.get_skill_evidence(db, [elena], as_of=AS_OF)[users["elena"]]}
    assert elena_skills == {"mentoring"}


@pytest.mark.slow
def test_signal_bands_of_free_adults(db: Session, make_user: Callable[..., object]) -> None:
    """Доли полос сигнала у взрослых с историей (специализация `backend`) — в границах приложения D, §11.1, T10."""
    generator.reset(db)
    db.commit()
    adults = db.scalars(select(Athlete.fsp_id).where(Athlete.persona_key.is_(None)).order_by(Athlete.fsp_id)).all()
    users: list[UUID] = []
    for fsp_id in adults[:300]:
        user = make_user("candidate")
        try:
            service.seed_link(db, user.id, str(fsp_id))  # type: ignore[attr-defined]
        except ValueError:
            continue  # несовершеннолетние в реестре есть, привязка им недоступна
        users.append(user.id)  # type: ignore[attr-defined]
    subjects = [FspSubject(user_id=uid, specialization="backend", show_summary=True) for uid in users]
    signals = service.get_signals(db, subjects, as_of=AS_OF)
    bands = {"low": 0, "medium": 0, "high": 0}
    for item in signals.values():
        if item.value > 0:
            bands[item.band] += 1  # type: ignore[index]
    total = sum(bands.values())
    assert total >= 80, bands
    assert 0.35 <= bands["low"] / total <= 0.60, bands
    assert 0.25 <= bands["medium"] / total <= 0.50, bands
    assert 0.08 <= bands["high"] / total <= 0.20, bands
