"""Небольшой реестр для тестов: свои спортсмены, соревнования и строки протоколов вместо полного генератора.

Данные пишутся прямо в схему `fspmock` на сессии теста. Даты считаются от замороженного «сегодня» теста, поэтому
давность и сроки разрядов предсказуемы.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.fsp_mock.models import Athlete, Competition, Entry, EntryMember, RankAssignment

TODAY = date(2026, 10, 20)


@dataclass(frozen=True)
class Result:
    """Участие, добавленное спортсмену: название соревнования и место, как их должен показать интерфейс."""

    competition_id: str
    entry_id: str
    title: str


def add_athlete(
    db: Session,
    *,
    birth: date = date(1999, 3, 14),
    region: str = "RU-MOW",
    fsp_id: UUID | None = None,
    persona_key: str | None = None,
) -> UUID:
    fsp_id = fsp_id or uuid4()
    db.add(
        Athlete(
            fsp_id=fsp_id,
            last_name="Фамилиев",
            first_name="Имярек",
            middle_name="Отчествович",
            birth_date=birth,
            gender="m",
            region_code=region,
            status="active",
            persona_key=persona_key,
            latent_skill=0.0,
        )
    )
    db.flush()
    return fsp_id


def add_competition(
    db: Session,
    competition_id: str | None = None,
    *,
    title: str = "Чемпионат России по алгоритмическому программированию 2026",
    discipline: str = "algo",
    level: str = "national",
    kind: str = "championship",
    stage: str = "single",
    series_code: str | None = None,
    participation: str = "individual",
    status: str = "finished",
    protocol_status: str = "official",
    days_ago: int = 30,
    entries_count: int | None = 40,
    age_group: str = "adults",
    deadline_in_days: int | None = None,
    start_in_days: int | None = None,
) -> str:
    """Соревнование. `days_ago` — окончание в прошлом; `start_in_days` — будущее (для календаря)."""
    competition_id = competition_id or f"T-{uuid4().hex[:8]}"
    if start_in_days is not None:
        start = TODAY + timedelta(days=start_in_days)
        end = start + timedelta(days=1)
    else:
        end = TODAY - timedelta(days=days_ago)
        start = end - timedelta(days=1)
    db.add(
        Competition(
            competition_id=competition_id,
            ekp_number="DEMO-0001",
            title=title,
            discipline_code=discipline,
            level=level,
            kind=kind,
            stage=stage,
            series_code=series_code,
            age_group=age_group,
            participation=participation,
            team_size_min=3 if participation == "team" else None,
            team_size_max=5 if participation == "team" else None,
            format="onsite",
            status=status,
            protocol_status=protocol_status,
            date_start=start,
            date_end=end,
            registration_deadline=TODAY + timedelta(days=deadline_in_days) if deadline_in_days is not None else None,
            city="Москва",
            region_code="RU-MOW",
            organizer="Тестовая федерация",
            entries_count=entries_count,
            athletes_count=entries_count,
            regions_count=5,
            registration_url=f"https://fsp-demo.example.com/c/{competition_id}",
            protocol_url=f"https://fsp-demo.example.com/p/{competition_id}",
        )
    )
    db.flush()
    return competition_id


def add_entry(
    db: Session,
    competition_id: str,
    members: list[tuple[UUID, str, bool]],
    *,
    place: int | None = 1,
    place_to: int | None = None,
    result_status: str = "ok",
    team_name: str | None = None,
    entry_id: str | None = None,
    kind: str | None = None,
) -> str:
    """Строка протокола и её состав: `members` — `(fsp_id, роль, капитан)`."""
    entry_id = entry_id or f"E-{uuid4().hex[:10]}"
    competition = db.get(Competition, competition_id)
    assert competition is not None
    db.add(
        Entry(
            entry_id=entry_id,
            competition_id=competition_id,
            kind=kind or competition.participation,
            team_name=team_name,
            region_code="RU-MOW",
            result_status=result_status,
            place=place,
            place_to=place_to,
        )
    )
    db.flush()
    for fsp_id, role, captain in members:
        db.add(EntryMember(entry_id=entry_id, fsp_id=fsp_id, role=role, is_captain=captain))
    db.flush()
    return entry_id


def add_result(
    db: Session,
    fsp_id: UUID,
    *,
    title: str = "Чемпионат России по алгоритмическому программированию 2026",
    place: int = 1,
    place_to: int | None = None,
    days_ago: int = 30,
    entries_count: int | None = 40,
    team: int | None = None,
    role: str = "athlete",
    captain: bool = False,
    **competition: object,
) -> Result:
    """Одним вызовом: соревнование, строка протокола и участие спортсмена (командное при `team`)."""
    participation = "team" if team else "individual"
    cid = add_competition(
        db,
        title=title,
        days_ago=days_ago,
        entries_count=entries_count,
        participation=participation,
        **competition,  # type: ignore[arg-type]
    )
    members = [(fsp_id, role, captain)]
    if team:
        members += [(add_athlete(db), "athlete", False) for _ in range(team - 1)]
    entry_id = add_entry(
        db, cid, members, place=place, place_to=place_to, team_name="Тестовая команда" if team else None
    )
    return Result(cid, entry_id, title)


def add_rank(
    db: Session,
    fsp_id: UUID,
    code: str = "kms",
    *,
    assigned_days_ago: int = 100,
    valid_years: int | None = 3,
    discipline: str | None = "algo",
    revoked: bool = False,
) -> str:
    assigned = TODAY - timedelta(days=assigned_days_ago)
    rank_id = f"R-{uuid4().hex[:8]}"
    db.add(
        RankAssignment(
            rank_id=rank_id,
            fsp_id=fsp_id,
            rank_code=code,
            assigned_on=assigned,
            valid_until=assigned.replace(year=assigned.year + valid_years) if valid_years else None,
            order_number="DEMO-1",
            assigned_by="Тестовый орган",
            discipline_code=discipline,
            basis_entry_id=None,
            revoked_on=TODAY - timedelta(days=1) if revoked else None,
        )
    )
    db.flush()
    return rank_id
