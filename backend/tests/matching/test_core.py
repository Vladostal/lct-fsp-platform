"""Чистые ядра подбора: покрытие, сила, порядок, объяснение, различия, подсказки (Арх. 6.2–6.12, 12.3).

Тесты без базы: `rank_need` получает готовые `CandidateFeatures`, как и в валидации.
"""

from __future__ import annotations

import inspect
import json
import math
import random
import re
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import pytest

from app.modules.matching import constants as C
from app.modules.matching import ranking, scoring
from app.modules.matching.dto import ShortlistQuery
from app.modules.matching.explain import (
    ExplainContext,
    ReadRules,
    apply_read_rules,
    build_explanation,
    project_why,
)
from app.modules.matching.features import FEATURE_FIELDS, CandidateFeatures, SkillEvidence, merge_evidence
from app.modules.matching.ranking import (
    DEFAULT_KEY_ORDER,
    KEY_ORDER_V11,
    DiffInput,
    counterfactuals,
    diff_snapshots,
    rank_bank,
    rank_need,
    score_candidate,
    sort_key,
)
from app.modules.matching.scoring import ScoringParams, coverage, evidence_weight, first_failed_filter, sections_for
from app.shared.enums import EvidenceKind, FitBand, Relation, TestOutcome, WorkFormat
from app.shared.schemas import CategoryRef, Ref

GRADES = ["junior", "middle", "senior"]
IMPLIES = {"postgresql": frozenset({"sql"})}
SEED = "seed"
MOMENT = datetime(2026, 9, 1, tzinfo=UTC)


def closure(code: str) -> frozenset[str]:
    return IMPLIES.get(code, frozenset())


def ev(skill: str, kind: str = "test", full: bool = True) -> SkillEvidence:
    confirmed = None if kind == "declared" else MOMENT
    return SkillEvidence(skill_code=skill, kind=EvidenceKind(kind), full=full, confirmed_at=confirmed, ref_id="r1")


def cand(number: int, evidence: list[SkillEvidence] | None = None, **fields: Any) -> CandidateFeatures:
    base: dict[str, Any] = {
        "candidate_id": UUID(int=number),
        "specialization_code": "backend",
        "grade_code": "middle",
        "verdict": TestOutcome.CONFIRMED,
        "theta": 0.9,
        "se": 0.4,
        "se_eff": 0.4,
        "cut": 0.0,
        "width": 1.5,
        "tested_at": date(2026, 8, 20),
        "last_evidence_at": date(2026, 8, 20),
        "age_days": 12,
        "stale": False,
        "evidence": merge_evidence(evidence or []),
        "fsp_signal": 0.0,
        "fsp_band": "none",
        "fsp_verified": False,
        "work_formats": frozenset({"remote"}),
        "exposure_7d": 0,
    }
    base.update(fields)
    return CandidateFeatures(**base)


def query(**fields: Any) -> ShortlistQuery:
    base: dict[str, Any] = {
        "specialization_code": "backend",
        "grade_code": "middle",
        "must_skills": ["python", "postgresql", "kafka"],
        "nice_skills": ["docker"],
        "work_formats": [WorkFormat.REMOTE],
        "salary_from": 200_000,
        "salary_to": 280_000,
    }
    base.update(fields)
    return ShortlistQuery(**base)


def rank(q: ShortlistQuery, pool: list[CandidateFeatures], **kwargs: Any) -> ranking.RankResult:
    return rank_need(q, pool, SEED, grades=GRADES, closure=closure, **kwargs)


def order(q: ShortlistQuery, pool: list[CandidateFeatures], **kwargs: Any) -> list[UUID]:
    return [item.candidate_id for item in rank(q, pool, **kwargs).items]


def scored(features: CandidateFeatures, q: ShortlistQuery) -> ranking.Scored:
    return score_candidate(features, q, Relation.EXACT, closure)


def ctx(**fields: Any) -> ExplainContext:
    return ExplainContext(scorer_version="match-1+test", skill_title=str.title, grade_title=str.title, **fields)


WORKED = {
    "theta": 0.93,
    "se": 0.72,
    "se_eff": math.sqrt(0.72**2 + 0.75**2 * 12 / 180),
    "fsp_signal": 0.45,
    "fsp_band": "medium",
}


def worked(full: bool = True) -> CandidateFeatures:
    evidence = [ev("python", "test", full), ev("postgresql", "declared"), ev("kafka", "declared")]
    return cand(10042, evidence, **WORKED)


# --------------------------------------------------------------------------------------------------------------------
# Контрольный пример (Арх. 6.8)
# --------------------------------------------------------------------------------------------------------------------


def test_worked_example() -> None:
    item = scored(worked(), query())
    cov, power = item.coverage, item.strength
    assert (cov.pct, cov.confirmed_pct, cov.confirmed_band, cov.band) == (46, 29, 3, 5)
    assert cov.must_gap is False and item.fit_band == FitBand.GOOD
    assert power.t == pytest.approx(0.4153, abs=1e-4) and power.t_fresh == pytest.approx(0.4267, abs=1e-4)
    assert (power.value, power.band, power.label) == (42.6, 4, "medium")
    key = sort_key(item, SEED)
    assert key[:4] == (0, -4, -3, -5)  # раздел; сила, подтверждённое покрытие, покрытие с заявленным

    expl = build_explanation(item.features, query(), item, ctx(fsp_line="призёр", fsp_fact_id="f1"))
    points = {row.code: (row.points, row.max_points) for row in expl.contributions}
    assert points["test"] == (29.9, 70.0) and points["freshness"] == (-0.8, 0.0) and points["fsp"] == (13.5, 30.0)
    assert points["req:python"] == (28.6, 28.6) and points["req:postgresql"] == (8.6, 28.6)
    assert points["req:kafka"] == (8.6, 28.6) and points["req:docker"] == (0.0, 14.3)


def test_worked_example_single_item_weight() -> None:
    """Ошибся в одном задании из двух: `python` имеет вес 0.7 — меняется только второй ключ."""
    item = scored(worked(full=False), query())
    assert item.coverage.confirmed_band == 2
    assert sort_key(item, SEED)[1] == -4


def test_worked_example_without_declared() -> None:
    """Удалил заявленные навыки: меняется только третий ключ и подпись; из подборки не выпадает."""
    item = scored(cand(10042, [ev("python")], **WORKED), query())
    assert sort_key(item, SEED)[:4] == (0, -4, -3, -3)
    assert item.fit_band == FitBand.PARTIAL
    assert order(query(), [item.features]) == [item.features.candidate_id]


def test_test_evidence_weight_depends_on_full() -> None:
    assert evidence_weight(EvidenceKind.TEST, True) == 1.0
    assert evidence_weight(EvidenceKind.TEST, False) == 0.7
    assert evidence_weight(EvidenceKind.PULSE, True) == evidence_weight(EvidenceKind.FSP, True) == 0.7
    assert evidence_weight(EvidenceKind.DECLARED, True) == 0.3 and evidence_weight(EvidenceKind.NONE, True) == 0.0


def test_public_functions_have_formula_docstrings() -> None:
    """У публичных функций `scoring.py` и `ranking.py` есть docstring с номером раздела архитектуры."""
    for module in (scoring, ranking):
        for name, value in vars(module).items():
            if inspect.isfunction(value) and value.__module__ == module.__name__ and not name.startswith("_"):
                assert value.__doc__ and "Арх." in value.__doc__, f"{module.__name__}.{name}"


# --------------------------------------------------------------------------------------------------------------------
# Порядок ключей: сила → подтверждённое покрытие → заявленное (Арх. 6.7)
# --------------------------------------------------------------------------------------------------------------------


def test_key_order_strength_then_confirmed_then_declared() -> None:
    q = query()
    strong_empty = cand(1, [], theta=2.0)  # сила выше, покрытия нет вовсе
    weak_full = cand(2, [ev("python"), ev("postgresql"), ev("kafka"), ev("docker")], theta=0.9)
    assert scored(strong_empty, q).strength.band > scored(weak_full, q).strength.band
    assert order(q, [weak_full, strong_empty]) == [strong_empty.candidate_id, weak_full.candidate_id]

    more_confirmed = cand(3, [ev("python"), ev("postgresql")])
    less_confirmed = cand(
        4, [ev("python"), ev("postgresql", "declared"), ev("kafka", "declared"), ev("docker", "declared")]
    )
    assert scored(more_confirmed, q).strength.band == scored(less_confirmed, q).strength.band
    assert scored(more_confirmed, q).coverage.confirmed_band > scored(less_confirmed, q).coverage.confirmed_band
    assert order(q, [less_confirmed, more_confirmed]) == [more_confirmed.candidate_id, less_confirmed.candidate_id]

    declared_more = cand(5, [ev("python"), ev("kafka", "declared")])
    declared_less = cand(6, [ev("python")])
    assert order(q, [declared_less, declared_more]) == [declared_more.candidate_id, declared_less.candidate_id]


def test_key_order_is_a_parameter_only_for_ablations() -> None:
    assert inspect.signature(rank_need).parameters["key_order"].default == DEFAULT_KEY_ORDER
    assert DEFAULT_KEY_ORDER == ("strength", "confirmed", "coverage")
    q = query()
    strong_empty = cand(1, [], theta=2.0)
    weak_full = cand(2, [ev("python"), ev("postgresql"), ev("kafka")], theta=0.9)
    assert order(q, [strong_empty, weak_full], key_order=KEY_ORDER_V11) == [
        weak_full.candidate_id,
        strong_empty.candidate_id,
    ]


def test_declared_stuffing() -> None:
    """Добавление любых заявленных навыков не поднимает кандидата выше того, у кого больше сила либо при
    равной силе больше подтверждено.
    """
    q = query()
    rng = random.Random(7)
    skills = ["python", "postgresql", "kafka", "docker", "sql", "redis"]
    pool = []
    for number in range(1, 61):
        evidence = [
            ev(skill, rng.choice(["test", "pulse", "declared"]), rng.random() < 0.6)
            for skill in rng.sample(skills, rng.randint(0, 4))
        ]
        pool.append(cand(number, evidence, theta=rng.uniform(-0.5, 2.5), se=rng.uniform(0.3, 0.6), se_eff=0.6))
    for target in pool[:12]:
        stuffed_evidence = [*target.evidence.values(), *(ev(skill, "declared") for skill in skills)]
        stuffed = replace(target, evidence=merge_evidence(stuffed_evidence))
        before, after = scored(target, q), scored(stuffed, q)
        assert (after.strength.band, after.coverage.confirmed_band) == (
            before.strength.band,
            before.coverage.confirmed_band,
        )
        new_pool = [stuffed if item.candidate_id == target.candidate_id else item for item in pool]
        ranked = order(q, new_pool, section_limits={})
        place = ranked.index(target.candidate_id)
        by_id = {item.candidate_id: item for item in new_pool}
        for other_id in ranked[place + 1 :]:
            other = scored(by_id[other_id], q)
            stronger = other.strength.band > after.strength.band
            more_confirmed = (
                other.strength.band == after.strength.band
                and other.coverage.confirmed_band > after.coverage.confirmed_band
            )
            assert not stronger and not more_confirmed


def test_declared_only_gives_at_most_partial() -> None:
    all_declared = cand(1, [ev(skill, "declared") for skill in ("python", "postgresql", "kafka", "docker")])
    item = scored(all_declared, query())
    assert item.coverage.pct == 30 and item.coverage.confirmed_band == 0 and item.fit_band == FitBand.PARTIAL


def test_no_filter_by_must_coverage() -> None:
    """Кандидат без заявленных и подтверждённых навыков остаётся в подборке — с риском."""
    empty = cand(1, [])
    result = rank(query(), [empty])
    assert [item.candidate_id for item in result.items] == [empty.candidate_id] and result.must_ok == 0
    expl = build_explanation(empty, query(), result.items[0].scored, ctx())
    assert expl.risk is not None and expl.risk.code == "must_missing"
    assert result.items[0].scored.coverage.band <= C.GAP_CAP_BAND


def test_implies_transfers_only_upwards() -> None:
    cov = coverage(merge_evidence([ev("postgresql")]), ["sql"], [], closure)
    assert cov.requirements[0].kind == EvidenceKind.TEST and cov.requirements[0].via_skill_code == "postgresql"
    assert coverage(merge_evidence([ev("sql")]), ["postgresql"], [], closure).requirements[0].kind == EvidenceKind.NONE


# --------------------------------------------------------------------------------------------------------------------
# Поведенческие тесты (Арх. 12.3)
# --------------------------------------------------------------------------------------------------------------------


def band_key(features: CandidateFeatures, q: ShortlistQuery) -> tuple[int | str, ...]:
    return sort_key(scored(features, q), SEED)[1:4]


def test_monotonicity() -> None:
    q = query()
    base = cand(1, [ev("python", "declared")], se_eff=0.5)
    better = [
        replace(base, evidence=merge_evidence([ev("python", "declared"), ev("kafka", "declared")])),
        replace(base, evidence=merge_evidence([ev("python", "pulse")])),
        replace(base, evidence=merge_evidence([ev("python", "test")])),
        replace(base, theta=base.theta + 0.6),
        replace(base, se=0.2, se_eff=0.2),
        replace(base, fsp_signal=0.8),
    ]
    for variant in better:
        assert band_key(variant, q) <= band_key(base, q)
    older = replace(base, se_eff=0.9, age_days=200)
    assert band_key(older, q) >= band_key(base, q)
    chain = [
        band_key(replace(base, evidence=merge_evidence([ev("python", kind)])), q)
        for kind in ("declared", "pulse", "test")
    ]
    assert chain == sorted(chain, reverse=True)


def test_feature_whitelist_gives_invariance() -> None:
    """Имени, пола, возраста, города, зарплаты, занятости входящих и отзывчивости в признаках нет."""
    assert set(FEATURE_FIELDS) == {
        "candidate_id", "specialization_code", "grade_code", "verdict", "theta", "se", "se_eff", "cut", "width",
        "tested_at", "last_evidence_at", "age_days", "stale", "evidence", "fsp_signal", "fsp_band", "fsp_verified",
        "work_formats", "exposure_7d",
    }  # fmt: skip


def test_salary_change_does_not_change_result() -> None:
    pool = [cand(number, [ev("python")], theta=0.2 * number) for number in range(1, 12)]
    first = rank(query(), pool)
    second = rank(query(salary_from=90_000, salary_to=120_000), pool)
    assert [item.key for item in first.items] == [item.key for item in second.items]


def test_determinism() -> None:
    rng = random.Random(3)
    pool = [
        cand(number, [ev("python", rng.choice(["test", "declared"]))], theta=rng.uniform(0, 2))
        for number in range(1, 40)
    ]
    first = rank(query(), pool)
    second = rank(query(), list(reversed(pool)))
    assert [item.candidate_id for item in first.items] == [item.candidate_id for item in second.items]
    dump = [
        json.dumps(
            build_explanation(item.scored.features, query(), item.scored, ctx()).model_dump(mode="json"), sort_keys=True
        )
        for item in first.items
    ]
    again = [
        json.dumps(
            build_explanation(item.scored.features, query(), item.scored, ctx()).model_dump(mode="json"), sort_keys=True
        )
        for item in second.items
    ]
    assert dump == again


def test_filters() -> None:
    q = query()
    sections = sections_for(q, GRADES)
    assert list(sections.items()) == [
        ("middle", Relation.EXACT),
        ("junior", Relation.LOWER_WITH_MARGIN),
        ("senior", Relation.HIGHER),
    ]
    assert first_failed_filter(None, q, sections) == "unavailable"
    assert first_failed_filter(cand(1, specialization_code="frontend"), q, sections) == "category_excluded"
    assert first_failed_filter(cand(1, grade_code="junior"), q, sections) == "margin_required"
    assert (
        first_failed_filter(cand(1, grade_code="junior", verdict=TestOutcome.CONFIRMED_WITH_MARGIN), q, sections)
        is None
    )
    assert first_failed_filter(cand(1, work_formats=frozenset({"office"})), q, sections) == "format"
    assert first_failed_filter(cand(1), query(require_fsp=True), sections) == "require_fsp"
    assert first_failed_filter(cand(1, fsp_verified=True), query(require_fsp=True), sections) is None

    office = cand(2, work_formats=frozenset({"office"}))
    assert order(q, [office]) == []
    wider = query(work_formats=[WorkFormat.REMOTE, WorkFormat.OFFICE])
    pool = [cand(1), office, cand(3, work_formats=frozenset({"hybrid"}))]
    assert set(order(q, pool)) <= set(order(wider, pool))
    assert set(order(query(must_skills=["python", "postgresql", "kafka", "redis"]), pool)) == set(order(q, pool))
    narrowed = sections_for(query(grade_codes=["middle"]), GRADES)
    assert list(narrowed) == ["middle"]


def test_section_limit_and_sections_do_not_mix() -> None:
    pool = [cand(number, theta=0.1 * number) for number in range(1, 36)]
    pool.append(cand(100, grade_code="senior", theta=3.0, cut=1.5))
    result = rank(query(), pool)
    assert result.shown == C.SECTION_LIMITS["exact"] == 30
    assert sum(1 for reason in result.rejected.values() if reason == "below_limit") == 5
    assert result.items[-1].candidate_id == UUID(int=100) and result.items[-1].position == 31


def test_empty_requirements_order_equals_bank_order() -> None:
    rng = random.Random(5)
    pool = [
        cand(number, [ev("python")], theta=rng.uniform(-0.5, 2.5), fsp_signal=rng.choice([0.0, 0.6]))
        for number in range(1, 25)
    ]
    q = query(must_skills=[], nice_skills=[])
    result = rank(q, pool)
    assert all(item.scored.coverage.pct is None and item.scored.fit_band is None for item in result.items)
    assert all(item.key[2] == 0 and item.key[3] == 0 for item in result.items)
    bank = rank_bank(pool, SEED, specializations=["backend"], grades=GRADES)
    assert [item.candidate_id for item in result.items] == [row.features.candidate_id for row in bank]
    nobody = rank(query(must_skills=["redis"], nice_skills=[]), pool)
    assert all(item.scored.coverage.pct == 0 for item in nobody.items)


def test_no_penalty_without_fsp() -> None:
    q = query()
    without = cand(1, [ev("python")])
    with_fsp = replace(without, candidate_id=UUID(int=2), fsp_signal=0.9, fsp_band="high", fsp_verified=True)
    expl = build_explanation(without, q, scored(without, q), ctx())
    assert all(row.code != "fsp" for row in expl.contributions)
    assert all(row.points >= 0 for row in expl.contributions if row.code != "freshness")
    assert order(q, [without, with_fsp])[0] == with_fsp.candidate_id
    assert scored(with_fsp, q).coverage == scored(without, q).coverage
    assert scored(with_fsp, q).relation == scored(without, q).relation


def test_contributions_converge() -> None:
    rng = random.Random(11)
    skills = ["python", "postgresql", "kafka", "docker"]
    for number in range(1, 40):
        evidence = [
            ev(skill, rng.choice(["test", "pulse", "fsp", "declared"]), rng.random() < 0.5)
            for skill in rng.sample(skills, rng.randint(0, 4))
        ]
        features = cand(number, evidence, theta=rng.uniform(-1, 3), fsp_signal=rng.choice([0.0, 0.3, 0.9]), se_eff=0.7)
        item = scored(features, query())
        expl = build_explanation(features, query(), item, ctx(fsp_line="участник", fsp_fact_id="f"))
        cover = sum(row.points for row in expl.contributions if row.group == "coverage")
        power = sum(row.points for row in expl.contributions if row.group == "strength")
        assert cover == pytest.approx(item.coverage.pct or 0, abs=0.5 + 0.05 * 4)
        assert power == pytest.approx(item.strength.value, abs=0.2)
        assert len(expl.reasons) <= 3
        texts = [reason.text for reason in expl.reasons] + ([expl.risk.text] if expl.risk else [])
        assert not any(re.search(r"\d+\s?%|балл", text) for text in texts)
        if any(req.priority == "must" and req.kind in ("none", "declared") for req in expl.requirements):
            assert expl.risk is not None


def test_diff_is_symmetric() -> None:
    base = [DiffInput(UUID(int=n), n, (0, -5, -3, -4)) for n in range(1, 6)]
    new = [
        DiffInput(UUID(int=2), 1, (0, -6, -3, -4)),
        DiffInput(UUID(int=3), 2, (0, -5, -3, -4)),
        DiffInput(UUID(int=5), 3, (0, -4, -3, -4)),
        DiffInput(UUID(int=9), 4, (0, -4, -3, -4)),
    ]
    forward, backward = diff_snapshots(base, new), diff_snapshots(new, base)
    assert forward.added == backward.dropped_count == 1 and forward.dropped_count == backward.added == 2
    assert (forward.moved_up, forward.moved_down) == (backward.moved_down, backward.moved_up) == (1, 1)
    assert forward.entries[UUID(int=3)].mark == "same" and forward.entries[UUID(int=3)].delta is None
    assert forward.entries[UUID(int=2)].delta == 1


# --------------------------------------------------------------------------------------------------------------------
# Перепроверка при чтении и проекции (Арх. 6.11, 4.9)
# --------------------------------------------------------------------------------------------------------------------


def test_declared_hidden_after_snapshot() -> None:
    """Кандидат выключил `show_declared_stack`: `declared` отдаётся как `none`, довода `declared_match` нет,
    риск заменён на `must_missing` с теми же навыками; сохранённая полоса совпадения не меняется.
    """
    q = query(must_skills=["python", "kafka"], nice_skills=["docker"])
    features = cand(1, [ev("python", "declared"), ev("kafka", "declared"), ev("docker", "declared")], age_days=90)
    expl = build_explanation(features, q, scored(features, q), ctx())
    assert expl.risk is not None and expl.risk.code == "must_declared_only"
    assert "declared_match" in [reason.code for reason in expl.reasons]
    hidden = apply_read_rules(expl, ReadRules(declared_hidden=True))
    assert [item.kind for item in hidden.requirements] == [EvidenceKind.NONE] * 3
    assert all(reason.code not in ("declared_match", "must_all_covered") for reason in hidden.reasons)
    assert hidden.risk is not None and hidden.risk.code == "must_missing"
    assert hidden.risk.params["skills"] == expl.risk.params["skills"]
    assert hidden.fit_band == expl.fit_band and hidden.coverage.must_covered == 0
    assert apply_read_rules(expl, ReadRules()) is expl


def test_explanation_keeps_only_generic_fsp_text() -> None:
    q = query(must_skills=["algorithms"], nice_skills=[])
    fact = SkillEvidence(
        "algorithms", EvidenceKind.FSP, confirmed_at=MOMENT, ref_id="fact-1", detail="достижение ФСП · алгоритмы"
    )
    features = cand(1, [fact], fsp_signal=0.6, fsp_band="medium", fsp_verified=True)
    expl = build_explanation(
        features, q, scored(features, q), ctx(fsp_line="призёр всероссийских соревнований", fsp_fact_id="fact-1")
    )
    raw = json.dumps(expl.model_dump(mode="json"), ensure_ascii=False)
    assert "fact-1" in raw and "detail_full" not in raw and "2025" not in raw
    assert expl.requirements[0].confirmed_at is None  # дата факта до раскрытия не хранится
    gone = apply_read_rules(expl, ReadRules(fsp_visible=False))
    assert gone.requirements[0].kind == EvidenceKind.NONE and all(r.code != "fsp" for r in gone.reasons)
    full = apply_read_rules(expl, ReadRules(fsp_texts={"fact-1": "1 место, Кубок 2025"}))
    assert "Кубок 2025" in next(r.text for r in full.reasons if r.code == "fsp")
    assert all(r.code != "fsp" for r in apply_read_rules(expl, ReadRules(fsp_texts={"fact-1": None})).reasons)


def test_why_projection_has_no_position_or_risk() -> None:
    q = query()
    item = scored(worked(), q)
    expl = build_explanation(item.features, q, item, ctx())
    target = CategoryRef(
        code="backend:middle",
        title="Backend · Middle",
        specialization=Ref(code="backend", title="Backend"),
        grade=Ref(code="middle", title="Middle"),
    )
    why = project_why(expl, target, ["категория"])
    assert [row.skill.code for row in why.matched] == ["python", "kafka", "postgresql"]
    assert why.unconfirmed is not None and why.unconfirmed.skill.code == "postgresql"
    assert set(why.model_dump()) == {"source", "target", "matched", "unconfirmed", "interest", "employer_saw"}


# --------------------------------------------------------------------------------------------------------------------
# Подсказки (Арх. 6.12)
# --------------------------------------------------------------------------------------------------------------------


def test_counterfactuals_gain() -> None:
    q = query(must_skills=["python", "kafka"], nice_skills=[], require_fsp=False)
    pool = [cand(number, [ev("python")]) for number in range(1, 6)]  # закрывают всё, кроме kafka
    pool += [cand(number, [ev("python")], work_formats=frozenset({"office"})) for number in range(6, 10)]
    found = {
        (item.code, item.value): item
        for item in counterfactuals(
            q,
            pool,
            ["move_must_to_nice", "add_format"],
            grades=GRADES,
            closure=closure,
            all_formats=["office", "hybrid", "remote"],
        )
    }
    move = found[("move_must_to_nice", "kafka")]
    assert move.gain == 5  # прирост числа кандидатов без пробела в обязательных, состав не меняется
    assert move.query.must_skills == ["python"] and move.query.nice_skills == ["kafka"]
    assert found[("add_format", "office")].gain == 4
    assert ("move_must_to_nice", "python") not in found  # прирост меньше HINT_MIN_GAIN
    with_fsp = counterfactuals(
        replace_fsp(q), pool, ["drop_require_fsp"], grades=GRADES, closure=closure, all_formats=[]
    )
    assert [(item.code, item.gain) for item in with_fsp] == [("drop_require_fsp", 5)]


def replace_fsp(q: ShortlistQuery) -> ShortlistQuery:
    return q.model_copy(update={"require_fsp": True})


def test_scoring_params_do_not_leak_between_calls() -> None:
    features = cand(1, [ev("python", "declared")])
    zero = ScoringParams(e_declared=0.0)
    assert coverage(features.evidence, ["python"], [], closure, zero).pct == 0
    assert coverage(features.evidence, ["python"], [], closure).pct == 30
