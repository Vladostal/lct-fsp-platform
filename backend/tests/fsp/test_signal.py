"""T1 и T3. Чистое ядро: формула сигнала (опорные строки без сборных, свойства), нормализация участия, показ."""

# ruff: noqa: C408  (dict(...) в таблицах параметров читается лучше литерала)

from __future__ import annotations

import itertools
import random
from dataclasses import replace
from datetime import date, timedelta
from uuid import uuid4

import pytest

from app.modules.fsp import constants as c
from app.modules.fsp import signal as sig

AS_OF = date(2026, 10, 20)


def participation(**overrides: object) -> sig.Participation:
    base = sig.Participation(
        entry_id="E1",
        member_role="athlete",
        is_captain=False,
        participation="individual",
        team_size=None,
        discipline_code="algo",
        level="national",
        kind="championship",
        stage="single",
        series_code=None,
        competition_status="finished",
        protocol_status="official",
        date_start=AS_OF - timedelta(days=1),
        date_end=AS_OF,
        entries_count=40,
        result_status="ok",
        place=1,
        place_to=None,
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def fact_from(item: sig.Participation, today: date = AS_OF) -> sig.Fact:
    normalized = sig.normalize_participation(item, today)
    return sig.Fact(
        id=uuid4(),
        entry_id=item.entry_id,
        discipline_code=item.discipline_code,
        level=item.level,
        stage=item.stage,
        tier=normalized.tier,
        participation=item.participation,
        member_role=item.member_role,
        is_captain=item.is_captain,
        result_bucket=normalized.result_bucket,
        event_date=normalized.event_date,
        verified=normalized.verified,
        counted=normalized.counted,
        base_points=normalized.base_points,
    )


def signal_of(
    *items: sig.Participation, specialization: str | None = "backend", as_of: date = AS_OF
) -> sig.SignalResult:
    return sig.compute_signal([fact_from(item) for item in items], [], specialization, as_of)


# --- T1: опорные строки Арх. 7.6 (свежий результат, R = 1, один факт) ---------------------------------------

REFERENCE_ROWS = [
    ("Чемпионат мира, личное, 1 из 60", dict(level="international", entries_count=60), 1.000, 0.92),
    ("Чемпионат России, личное, 1 из 40", dict(), 0.800, 0.86),
    (
        "Чемпионат России, команда 3, 1 из 14",
        dict(participation="team", team_size=3, entries_count=14),
        0.667,
        0.81,
    ),
    (
        "Чемпионат России, команда 5, 1 из 12",
        dict(participation="team", team_size=5, entries_count=12),
        0.571,
        0.76,
    ),
    (
        "Финал Кубка России, команда 5, 2 из 16",
        dict(participation="team", team_size=5, entries_count=16, kind="cup", stage="final", place=2),
        0.437,
        0.66,
    ),
    (
        "Чемпионат федерального округа, команда 3, 1 из 10",
        dict(participation="team", team_size=3, entries_count=10, level="interregional"),
        0.375,
        0.61,
    ),
    (
        "Чемпионат России, команда 5, 6 из 12",
        dict(participation="team", team_size=5, entries_count=12, place=6),
        0.252,
        0.47,
    ),
    (
        "Чемпионат субъекта, команда 3, 1 из 8",
        dict(participation="team", team_size=3, entries_count=8, level="regional"),
        0.208,
        0.41,
    ),
    (
        "Чемпионат России, команда 5, 12 из 12",
        dict(participation="team", team_size=5, entries_count=12, place=12),
        0.143,
        0.30,
    ),
    (
        "Чемпионат субъекта, команда 3, 1 из 3",
        dict(participation="team", team_size=3, entries_count=3, level="regional"),
        0.104,
        0.23,
    ),
    (
        "Отбор чемпионата России, команда 3, 40 из 120",
        dict(participation="team", team_size=3, entries_count=120, stage="qualification", place=40),
        0.097,
        0.22,
    ),
    (
        "Чемпионат субъекта, команда 3, 5 из 9",
        dict(participation="team", team_size=3, entries_count=9, level="regional", place=5),
        0.089,
        0.20,
    ),
    (
        "Муниципальные, команда 3, 1 из 8",
        dict(participation="team", team_size=3, entries_count=8, level="municipal"),
        0.083,
        0.19,
    ),
]


@pytest.mark.parametrize(("name", "fields", "points", "value"), REFERENCE_ROWS, ids=[row[0] for row in REFERENCE_ROWS])
def test_reference_rows(name: str, fields: dict[str, object], points: float, value: float) -> None:
    item = participation(**fields)
    normalized = sig.normalize_participation(item, AS_OF)
    assert normalized.counted and normalized.base_points == pytest.approx(points, abs=0.0015)
    assert signal_of(item).value == pytest.approx(value, abs=0.005)


def test_decay_multipliers() -> None:
    for years, expected in ((1, 0.71), (2, 0.50), (3, 0.35), (4, 0.25)):
        assert sig.decay(AS_OF - timedelta(days=round(365.25 * years)), AS_OF) == pytest.approx(expected, abs=0.005)


def test_decay_example_district_third_place() -> None:
    """3 место чемпионата округа (команда 3, поле 10) — 0.51 сразу, 0.22 через три года."""
    fields = dict(participation="team", team_size=3, entries_count=10, level="interregional", place=3)
    assert signal_of(participation(**fields)).value == pytest.approx(0.51, abs=0.01)
    old = participation(
        **fields, date_end=AS_OF - timedelta(days=round(365.25 * 3)), date_start=AS_OF - timedelta(days=1096)
    )
    assert signal_of(old).value == pytest.approx(0.22, abs=0.01)


# --- T1: свойства -------------------------------------------------------------------------------------------


def test_property_bounds_and_zero() -> None:
    assert signal_of().value == 0 and signal_of().band == "none"
    big = [participation(entry_id=f"E{i}", level="international", entries_count=60) for i in range(40)]
    assert 0 < signal_of(*big).value < 1
    assert sig.compute_signal([], [], None, AS_OF).value == 0.0


def test_property_monotonic_add_and_improve() -> None:
    first = participation(participation="team", team_size=3, entries_count=10, level="regional", place=4)
    second = participation(entry_id="E2", level="interregional", participation="team", team_size=3, entries_count=10)
    assert signal_of(first, second).value >= signal_of(first).value
    values = [signal_of(replace(first, place=place)).value for place in range(10, 0, -1)]
    assert values == sorted(values)


def test_property_not_growing_with_time() -> None:
    item = participation(level="interregional", participation="team", team_size=3, entries_count=10)
    values = [signal_of(item, as_of=AS_OF + timedelta(days=days)).value for days in (0, 100, 400, 1000)]
    assert values == sorted(values, reverse=True)


def test_property_quantity_does_not_replace_level() -> None:
    middle = dict(participation="team", team_size=3, entries_count=8, level="municipal", place=4)
    many = [participation(entry_id=f"M{i}", **middle) for i in range(20)]
    assert signal_of(*many).value == pytest.approx(0.21, abs=0.01)
    win = participation(participation="team", team_size=3, entries_count=8, level="regional")
    assert signal_of(win).value == pytest.approx(0.41, abs=0.01)
    assert signal_of(win).value > signal_of(*many).value


def test_property_order_does_not_matter() -> None:
    items = [
        participation(entry_id=f"E{i}", level=level, place=place, participation="team", team_size=3, entries_count=10)
        for i, (level, place) in enumerate(
            [("national", 3), ("regional", 1), ("interregional", 2), ("municipal", 5), ("national", 8)]
        )
    ]
    expected = signal_of(*items).value
    rng = random.Random(7)
    for _ in range(5):
        rng.shuffle(items)
        assert signal_of(*items).value == expected


def test_rank_is_floor_not_addend() -> None:
    rank = sig.Rank(uuid4(), "kms", "algo", AS_OF - timedelta(days=100), AS_OF + timedelta(days=900), None)
    assert sig.compute_signal([], [rank], "backend", AS_OF).value == c.RANK_FLOOR["kms"]
    strong = fact_from(participation(level="international", entries_count=60))
    assert (
        sig.compute_signal([strong], [rank], "backend", AS_OF).value
        == signal_of(participation(level="international", entries_count=60)).value
    )
    expired = replace(rank, valid_until=AS_OF - timedelta(days=1))
    assert sig.compute_signal([], [expired], "backend", AS_OF).value == 0
    revoked = replace(rank, revoked_on=AS_OF - timedelta(days=2))
    assert sig.compute_signal([], [revoked], "backend", AS_OF).value == 0


def test_relevance_matrix_and_default() -> None:
    algo = participation()
    assert signal_of(algo, specialization="backend").value > signal_of(algo, specialization="devops").value
    assert signal_of(algo, specialization=None).value == signal_of(algo, specialization="unknown_spec").value
    assert sig.relevance("other", "backend") == c.R_DEFAULT


# --- T3: нормализация ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        (dict(member_role="coach"), "role_not_athlete"),
        (dict(protocol_status="annulled"), "annulled"),
        (dict(result_status="annulled"), "annulled"),
        (dict(competition_status="in_progress"), "not_finished"),
        (dict(protocol_status="none"), "not_finished"),
        (dict(result_status="pending"), "not_finished"),
        (dict(result_status="dsq", place=None), "dsq"),
        (dict(result_status="dns", place=None), "dns"),
        (dict(level="district"), "unknown_level"),
        (dict(date_start=None, date_end=None), "no_date"),
        (dict(date_end=AS_OF + timedelta(days=3)), "no_date"),
    ],
)
def test_normalization_uncounted_rules(fields: dict[str, object], reason: str) -> None:
    fact = sig.normalize_participation(participation(**fields), AS_OF)
    assert not fact.counted and fact.uncounted_reason == reason


def test_normalization_verified_for_coach_and_first_rule_wins() -> None:
    coach = sig.normalize_participation(participation(member_role="coach"), AS_OF)
    assert coach.verified and not coach.counted and coach.base_points == 0
    both = sig.normalize_participation(participation(member_role="coach", protocol_status="annulled"), AS_OF)
    assert both.uncounted_reason == "role_not_athlete" and not both.verified


def test_normalization_shared_place_and_buckets() -> None:
    shared = sig.normalize_participation(participation(place=2, place_to=3, entries_count=10), AS_OF)
    assert shared.place_eff == 2.5 and shared.result_bucket == "medal"
    assert sig.result_bucket(3.0, 4) == "participant"
    assert sig.result_bucket(3.0, None) == "medal"
    assert sig.result_bucket(None, 10) == "participant"
    assert sig.result_bucket(5.0, 10) == "top_half"


def test_normalization_unknown_enums_fall_back() -> None:
    unknown_kind = sig.normalize_participation(participation(kind="exotic"), AS_OF)
    other = sig.normalize_participation(participation(kind="other"), AS_OF)
    assert unknown_kind.counted and unknown_kind.base_points == other.base_points
    unknown_stage = sig.normalize_participation(participation(stage="exotic"), AS_OF)
    qualification = sig.normalize_participation(participation(stage="qualification"), AS_OF)
    assert unknown_stage.base_points == qualification.base_points
    assert sig.relevance("exotic", "backend") == c.R_DEFAULT


def test_series_supersedes_lower_facts() -> None:
    stage = participation(entry_id="S", series_code="2026-cup", kind="cup", stage="stage", place=3, entries_count=18)
    final = participation(entry_id="F", series_code="2026-cup", kind="cup", stage="final", place=2, entries_count=16)
    facts = sig.normalize_all([stage, final], AS_OF)
    by_entry = {fact.entry_id: fact for fact in facts}
    assert by_entry["F"].counted and not by_entry["S"].counted
    assert by_entry["S"].uncounted_reason == "superseded_in_series" and by_entry["S"].base_points > 0


def test_duplicates_take_last() -> None:
    first = participation(place=9)
    second = participation(place=1)
    (fact,) = sig.normalize_all([first, second], AS_OF)
    assert fact.place_eff == 1


# --- показ, лидерство, навыки -------------------------------------------------------------------------------


def test_display_mode_matrix() -> None:
    for linked, verified, show, reveal, disclosed in itertools.product([True, False], repeat=5):
        mode = sig.display_mode(
            linked=linked, has_verified=verified, show_summary=show, reveal_details=reveal, disclosed=disclosed
        )
        if not linked or not verified:
            assert mode == "none"
        elif disclosed and reveal:
            assert mode == "detailed"
        elif show:
            assert mode == "summary"
        else:
            assert mode == "none"


def test_leadership_and_skills() -> None:
    captain = fact_from(
        participation(participation="team", team_size=3, is_captain=True, level="interregional", place=1)
    )
    coach = fact_from(participation(entry_id="C", member_role="coach", level="regional"))
    assert sig.leadership_level([captain], AS_OF) == "basic"
    assert sig.leadership_level([coach], AS_OF) == "basic"
    strong_coach = fact_from(participation(entry_id="C2", member_role="coach", level="national"))
    assert sig.leadership_level([strong_coach], AS_OF) == "strong"
    skills = {item.skill_code for item in sig.skill_evidence([captain, coach], AS_OF)}
    assert {"algorithms", "data_structures", "teamwork", "leadership", "mentoring"} <= skills
    languages = {"python", "java", "react"}
    assert not skills & languages
    assert sig.leadership_level([], AS_OF) == "none"


def test_skill_evidence_threshold_and_unknown_skills() -> None:
    weak = fact_from(participation(level="municipal", participation="team", team_size=3, place=8, entries_count=8))
    assert sig.skill_evidence([weak], AS_OF) == []
    strong = fact_from(participation())
    known = {"algorithms"}
    codes = {item.skill_code for item in sig.skill_evidence([strong], AS_OF, lambda code: code in known)}
    assert codes == known


def test_has_verified_facts_includes_coach_and_expired_rank() -> None:
    coach = fact_from(participation(member_role="coach"))
    assert sig.has_verified_facts([coach], [])
    expired = sig.Rank(uuid4(), "r2", "algo", date(2020, 1, 1), date(2022, 1, 1), None)
    assert sig.has_verified_facts([], [expired])
    revoked = replace(expired, revoked_on=date(2021, 1, 1))
    assert not sig.has_verified_facts([], [revoked])


def test_public_summary_levels() -> None:
    def anon(fact: sig.Fact, k_a: int | None, k_b: int | None) -> sig.Fact:
        period = sig.period_of(fact.event_date, AS_OF) if fact.event_date else None
        return replace(fact, anon_period=period, anon_k_a=k_a, anon_k_b=k_b)

    base = fact_from(participation(level="national", participation="team", team_size=5, place=1, entries_count=12))
    level3 = sig.public_summary([anon(base, 25, 40)], [], "backend", AS_OF, 20)
    level2 = sig.public_summary([anon(base, 5, 40)], [], "backend", AS_OF, 20)
    level1 = sig.public_summary([anon(base, 5, 7)], [], "backend", AS_OF, 20)
    assert (level3.level, level2.level, level1.level) == (3, 2, 1)  # type: ignore[union-attr]
    assert level1.headline == c.SUMMARY_GENERIC_HEADLINE  # type: ignore[union-attr]
    assert "призовое место" in level3.headline  # type: ignore[union-attr]
    assert "призовое" not in level2.headline  # type: ignore[union-attr]
    assert sig.public_summary([], [], None, AS_OF, 20) is None
