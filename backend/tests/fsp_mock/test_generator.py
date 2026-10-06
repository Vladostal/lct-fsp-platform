"""T10. Генератор демо-реестра: инварианты приложения D §1.3, объёмы §8.1 (±10 %), персонажи, детерминизм."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.fsp_mock import generator
from app.fsp_mock import reference as ref
from app.fsp_mock.models import Athlete, Competition, Entry, EntryMember, RankAssignment
from app.fsp_mock.personas import PERSONAS, persona_fsp_id

TODAY = generator.SEED_DATE


@pytest.fixture(scope="module")
def registry() -> generator.Registry:
    return generator.generate(seed=20261005, today=TODAY)


def test_volumes_within_ten_percent(registry: generator.Registry) -> None:
    """Объёмы §8.1: ориентир с допуском ±10 % (спортсмены — 1500 случайных + 11 персонажей)."""
    finished = [c for c in registry.competitions if c.status == "finished"]
    upcoming = [c for c in registry.competitions if c.status != "finished"]
    roles = Counter(member.role for member in registry.members)
    expected = {
        "athletes": (len(registry.athletes), 1511),
        "finished": (len(finished), 162),
        "upcoming": (len(upcoming), 16),
        "entries": (len([e for e in registry.entries if e.result_status != "pending"]), 1850),
        "athlete_members": (roles["athlete"], 5100),
        "coaches": (roles["coach"], 490),
    }
    for name, (actual, target) in expected.items():
        assert abs(actual - target) <= 0.1 * target + 1, f"{name}: {actual} вместо ≈{target}"
    assert 40 <= len(registry.ranks) <= 80


def test_no_participation_and_minors_share(registry: generator.Registry) -> None:
    with_roles = {member.fsp_id for member in registry.members if member.role == "athlete"}
    random_ids = {a.fsp_id for a in registry.athletes if a.persona_key is None}
    without = len(random_ids - with_roles)
    assert 180 <= without <= 320, without
    minors = sum(1 for a in registry.athletes if a.persona_key is None and _age(a.birth_date) < 18)
    assert 0.9 * 260 <= minors <= 1.1 * 260 + 10, minors


def _age(birth: date) -> int:
    return TODAY.year - birth.year - ((TODAY.month, TODAY.day) < (birth.month, birth.day))


def test_invariant_1_kind_and_team_size(registry: generator.Registry) -> None:
    competitions = {c.competition_id: c for c in registry.competitions}
    members: dict[str, list[EntryMember]] = defaultdict(list)
    for member in registry.members:
        members[member.entry_id].append(member)
    for entry in registry.entries:
        competition = competitions[entry.competition_id]
        assert entry.kind == competition.participation
        athletes = [m for m in members[entry.entry_id] if m.role == "athlete"]
        assert sum(1 for m in athletes if m.is_captain) <= 1
        if entry.kind == "team" and competition.team_size_min and entry.result_status != "pending":
            assert competition.team_size_min <= len(athletes) <= (competition.team_size_max or 99), entry.entry_id


def test_invariant_2_one_row_per_athlete_in_competition(registry: generator.Registry) -> None:
    competition_of = {e.entry_id: e.competition_id for e in registry.entries}
    seen: set[tuple[str, object]] = set()
    for member in registry.members:
        if member.role != "athlete":
            continue
        key = (competition_of[member.entry_id], member.fsp_id)
        assert key not in seen, key
        seen.add(key)


def test_invariant_3_protocol_and_places(registry: generator.Registry) -> None:
    by_competition: dict[str, list[Entry]] = defaultdict(list)
    for entry in registry.entries:
        by_competition[entry.competition_id].append(entry)
    for competition in registry.competitions:
        rows = by_competition[competition.competition_id]
        if competition.protocol_status == "official":
            assert all(row.result_status != "pending" for row in rows)
        if competition.entries_count is not None:
            assert len(rows) <= competition.entries_count
        if competition.status != "finished" or competition.level not in ref.LEVELS:
            continue
        ok = [row for row in rows if row.result_status == "ok"]
        assert all(row.place is not None for row in ok)
        if competition.level == "international":
            continue  # у международных в выгрузке только российские участники: места с пропусками
        places = Counter()
        for row in ok:
            assert row.place is not None
            high = row.place_to or row.place
            for place in range(row.place, high + 1):
                places[place] += 1
        assert sorted(places) == list(range(1, len(places) + 1)), competition.competition_id
        for row in rows:
            if row.result_status != "ok":
                assert row.place is None


def test_invariant_4_dates_and_statuses(registry: generator.Registry) -> None:
    for competition in registry.competitions:
        if competition.status == "finished":
            assert competition.date_end <= TODAY
        else:
            assert competition.status in {"scheduled", "registration_open", "registration_closed"}
            assert competition.date_start > TODAY
            assert competition.protocol_status == "none"


def test_invariant_5_regions_count(registry: generator.Registry) -> None:
    regions: dict[str, set[str]] = defaultdict(set)
    for entry in registry.entries:
        regions[entry.competition_id].add(entry.region_code)
    for competition in registry.competitions:
        if competition.regions_count is not None:
            assert competition.regions_count >= len(regions[competition.competition_id])


def test_invariant_6_rank_validity(registry: generator.Registry) -> None:
    for rank in registry.ranks:
        years = ref.RANK_VALIDITY_YEARS.get(rank.rank_code)
        if years is None:
            assert rank.valid_until is None
        else:
            assert rank.valid_until is not None and rank.valid_until.year == rank.assigned_on.year + years


def test_personas_exist_with_fixed_ids(registry: generator.Registry) -> None:
    ids = {a.fsp_id: a for a in registry.athletes}
    for persona in PERSONAS:
        athlete = ids[persona_fsp_id(persona.key)]
        assert athlete.persona_key == persona.key
    assert _age(ids[persona_fsp_id("timur")].birth_date) < 18
    anna_places = sorted(
        (e.place, e.competition_id)
        for e in registry.entries
        for m in registry.members
        if m.entry_id == e.entry_id and m.fsp_id == persona_fsp_id("anna") and m.role == "athlete"
    )
    assert [place for place, _ in anna_places] == [1, 2, 2, 3]


def test_deterministic_ids(registry: generator.Registry) -> None:
    again = generator.generate(seed=20261005, today=TODAY)
    assert [a.fsp_id for a in again.athletes] == [a.fsp_id for a in registry.athletes]
    assert [e.entry_id for e in again.entries] == [e.entry_id for e in registry.entries]
    assert [(e.entry_id, e.place) for e in again.entries] == [(e.entry_id, e.place) for e in registry.entries]


def test_free_adults_with_counted_result(registry: generator.Registry) -> None:
    """Не меньше 200 свободных взрослых спортсменов с зачтённым результатом (членам жюри и валидации)."""
    competitions = {c.competition_id: c for c in registry.competitions}
    entries = {e.entry_id: e for e in registry.entries}
    athletes = {a.fsp_id: a for a in registry.athletes}
    counted: set[object] = set()
    for member in registry.members:
        entry = entries[member.entry_id]
        competition = competitions[entry.competition_id]
        if (
            member.role == "athlete"
            and entry.result_status == "ok"
            and competition.status == "finished"
            and competition.protocol_status == "official"
            and competition.level in ref.TIER
            and athletes[member.fsp_id].persona_key is None
            and _age(athletes[member.fsp_id].birth_date) >= 18
        ):
            counted.add(member.fsp_id)
    assert len(counted) >= 200, len(counted)


def test_persist_and_reset_keep_seed_grants(db: Session) -> None:
    """Запись в базу и сброс: данные пересоздаются, разрешения сида сохраняются, прочие снимаются."""
    from app.core import clock
    from app.fsp_mock.models import AccessGrant

    view = generator.reset(db)
    assert db.scalar(select(func.count()).select_from(Athlete)) == view.athletes == 1511
    assert not generator.is_empty(db)
    anna = persona_fsp_id("anna")
    now = clock.real_now()
    db.add_all(
        [
            AccessGrant(fsp_id=anna, client_id=ref.CLIENT_ID, scope=ref.SCOPE, source="seed", granted_at=now),
            AccessGrant(fsp_id=persona_fsp_id("olga"), client_id=ref.CLIENT_ID, scope=ref.SCOPE, source="oidc",
                        granted_at=now),
        ]
    )  # fmt: skip
    db.flush()
    generator.reset(db)
    grants = {g.fsp_id for g in db.scalars(select(AccessGrant))}
    assert grants == {anna}
    assert db.scalar(select(func.count()).select_from(Competition)) == view.competitions
    assert db.scalar(select(func.count()).select_from(Entry)) == view.entries
    assert db.scalar(select(func.count()).select_from(RankAssignment)) == len(generator.generate().ranks)
