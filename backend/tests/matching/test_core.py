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
    KEY_ORDER_V12,
    DiffInput,
    counterfactuals,
    diff_snapshots,
    rank_bank,
    rank_need,
    score_candidate,
    sort_key,
)
from app.modules.matching.scoring import (
    ScoringParams,
    coverage,
    evidence_weight,
    experience_note,
    first_failed_filter,
    sections_for,
    strength,
)
from app.shared.enums import CategoryBasis, EvidenceKind, FitBand, Relation, TestOutcome, WorkFormat
from app.shared.schemas import CategoryRef, Ref
from app.shared.text import NBSP

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
    return ExplainContext(scorer_version="match-3+test", skill_title=str.title, grade_title=str.title, **fields)


WORKED = {
    "theta": 0.93,
    "se": 0.72,
    "se_eff": math.sqrt(0.72**2 + 0.75**2 * 12 / 180),
    "fsp_signal": 0.45,
    "fsp_band": "medium",
    # Заявлено: стаж 3 года и два навыка своей специализации (postgresql, kafka).
    "experience_years": 3.0,
    "declared_relevant": 2,
}


def declared_cand(number: int, evidence: list[SkillEvidence] | None = None, **fields: Any) -> CandidateFeatures:
    """Кандидат специализации без теста: грейд заявлен, оценки, вердикта и дат нет."""
    base: dict[str, Any] = {
        "specialization_code": "frontend",
        "basis": CategoryBasis.DECLARED,
        "verdict": None,
        "theta": None,
        "se": None,
        "se_eff": None,
        "tested_at": None,
        "last_evidence_at": None,
        "age_days": None,
    }
    base.update(fields)
    return cand(number, evidence, **base)


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
    # se_eff = sqrt(0.72² + 0.75²·12/180) = sqrt(0.5184 + 0.0375) = 0.745587; (1 + UNDER)·width = 2.25
    # T       = (0.93 − 0.745587 + 0.75) / 2.25 = 0.415295;  T_fresh = (0.93 − 0.72 + 0.75) / 2.25 = 0.426667
    # F = 0.45;  X = 3 / 5 (полный стаж middle — 5 лет) = 0.6;  S = 2 / 6 = 0.333333
    # сила = 100·(0.10·0.415295 + 0.30·0.45 + 0.35·0.6 + 0.25·0.333333)
    #      = 4.15295 + 13.5 + 21.0 + 8.33333 = 46.98628 → 47.0; полоса 4; 35 ≤ 47.0 < 65 → medium
    assert power.t == pytest.approx(0.4153, abs=1e-4) and power.t_fresh == pytest.approx(0.4267, abs=1e-4)
    assert (power.f, power.x) == (0.45, 0.6) and power.s == pytest.approx(1 / 3) and power.tested is True
    assert (power.value, power.band, power.label) == (47.0, 4, "medium")
    key = sort_key(item, SEED)
    # раздел; обязательных без данных, подтверждённое покрытие, сила, покрытие с заявленным
    assert key[:5] == (0, 0, -3, -4, -5)

    expl = build_explanation(item.features, query(), item, ctx(fsp_line="призёр", fsp_fact_id="f1"))
    points = {row.code: (row.points, row.max_points) for row in expl.contributions}
    # test = 10·0.426667 = 4.27 → 4.3 из 10; freshness = 10·(0.415295 − 0.426667) = −0.114 → −0.1;
    # fsp = 30·0.45 = 13.5 из 30; experience = 35·0.6 = 21.0 из 35; skills = 25·0.333333 = 8.33 → 8.3 из 25.
    # Сумма строк 4.3 − 0.1 + 13.5 + 21.0 + 8.3 = 47.0 — та же сила.
    assert points["test"] == (4.3, 10.0) and points["freshness"] == (-0.1, 0.0) and points["fsp"] == (13.5, 30.0)
    assert points["experience"] == (21.0, 35.0) and points["skills"] == (8.3, 25.0)
    sources = {row.code: row.source for row in expl.contributions}
    assert sources["test"] == sources["freshness"] == sources["fsp"] == "confirmed"
    assert sources["experience"] == sources["skills"] == "declared" and sources["req:python"] is None
    confirmed_max = sum(row.max_points for row in expl.contributions if row.source == "confirmed")
    declared_max = sum(row.max_points for row in expl.contributions if row.source == "declared")
    assert (confirmed_max, declared_max) == (40.0, 60.0)
    assert points["req:python"] == (28.6, 28.6) and points["req:postgresql"] == (8.6, 28.6)
    assert points["req:kafka"] == (8.6, 28.6) and points["req:docker"] == (0.0, 14.3)


def test_worked_example_single_item_weight() -> None:
    """Ошибся в одном задании из двух: `python` имеет вес 0.7 — меняется только ключ подтверждённого покрытия."""
    item = scored(worked(full=False), query())
    assert item.coverage.confirmed_band == 2
    assert sort_key(item, SEED)[:4] == (0, 0, -2, -4)


def test_worked_example_without_declared() -> None:
    """Удалил заявленные навыки: два обязательных остались без данных — меняются первый и последний ключи
    и подпись; подтверждённое покрытие то же; сила теряет вклад навыков; из подборки кандидат не выпадает.
    """
    item = scored(cand(10042, [ev("python")], **{**WORKED, "declared_relevant": 0}), query())
    # сила = 4.15295 + 13.5 + 21.0 + 0 = 38.65295 → 38.7; полоса 3 (было 4)
    assert item.strength.value == 38.7
    assert sort_key(item, SEED)[:5] == (0, 2, -3, -3, -3)
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
# Порядок ключей: закрытые обязательные → подтверждённое покрытие → сила → заявленное (Арх. 6.7)
# --------------------------------------------------------------------------------------------------------------------


def test_key_order_must_then_confirmed_then_strength_then_declared() -> None:
    q = query()
    # 1. Соответствие потребности важнее силы: сильный без единого навыка потребности — ниже слабого с полным набором.
    # Сила различается заявленным стажем: 5 лет у middle — это полные 35 баллов (полоса 4 против 0).
    strong_empty = cand(1, [], experience_years=5.0)
    weak_full = cand(2, [ev("python"), ev("postgresql"), ev("kafka"), ev("docker")])
    assert scored(strong_empty, q).strength.band > scored(weak_full, q).strength.band
    assert order(q, [strong_empty, weak_full]) == [weak_full.candidate_id, strong_empty.candidate_id]

    # 2. Заявленный навык закрывает пробел в обязательных: полный набор «со слов» выше двух подтверждённых из трёх.
    two_confirmed = cand(3, [ev("python"), ev("postgresql")])
    all_covered = cand(4, [ev("python"), ev("postgresql", "declared"), ev("kafka", "declared")])
    assert scored(two_confirmed, q).coverage.confirmed_band > scored(all_covered, q).coverage.confirmed_band
    assert order(q, [two_confirmed, all_covered]) == [all_covered.candidate_id, two_confirmed.candidate_id]

    # 3. При равном числе закрытых обязательных подтверждённое важнее силы.
    declared_strong = cand(
        5,
        [ev(skill, "declared") for skill in ("python", "postgresql", "kafka")],
        experience_years=5.0,
        declared_relevant=3,
    )
    confirmed_weak = cand(6, [ev("python"), ev("postgresql", "declared"), ev("kafka", "declared")])
    assert scored(declared_strong, q).strength.band > scored(confirmed_weak, q).strength.band
    assert order(q, [declared_strong, confirmed_weak]) == [confirmed_weak.candidate_id, declared_strong.candidate_id]

    # 4. При равном соответствии решает сила профиля.
    evidence = [ev("python"), ev("postgresql"), ev("kafka")]
    stronger, weaker = cand(7, evidence, experience_years=5.0), cand(8, evidence)
    assert order(q, [weaker, stronger]) == [stronger.candidate_id, weaker.candidate_id]

    # 5. Заявленное по желательным — последним: только среди равных по трём ключам выше.
    declared_more = cand(9, [*evidence, ev("docker", "declared")])
    declared_less = cand(10, evidence)
    assert order(q, [declared_less, declared_more]) == [declared_more.candidate_id, declared_less.candidate_id]


def test_key_order_is_a_parameter_only_for_ablations() -> None:
    assert inspect.signature(rank_need).parameters["key_order"].default == DEFAULT_KEY_ORDER
    assert DEFAULT_KEY_ORDER == ("must", "confirmed", "strength", "coverage")
    q = query()
    strong_empty = cand(1, [], theta=2.0, experience_years=5.0)
    weak_full = cand(2, [ev("python"), ev("postgresql"), ev("kafka")], theta=0.9)
    # Прежний порядок «сила первой» остаётся только абляцией отчёта.
    assert order(q, [strong_empty, weak_full], key_order=KEY_ORDER_V12) == [
        strong_empty.candidate_id,
        weak_full.candidate_id,
    ]
    assert order(q, [strong_empty, weak_full], key_order=KEY_ORDER_V11) == [
        weak_full.candidate_id,
        strong_empty.candidate_id,
    ]


def test_declared_stuffing() -> None:
    """Накрутка заявленного не меняет подтверждённое покрытие, поднимает полосу силы не больше чем на три
    (навыки дают до 25 баллов из 100) и не поднимает кандидата выше того, у кого обязательных закрыто не меньше,
    а подтверждено больше (либо подтверждено столько же при большей силе). Пробел в обязательных заявленный навык
    закрывает — это цена первого ключа, она названа в отчёте валидации.
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
        pool.append(
            cand(
                number,
                evidence,
                theta=rng.uniform(-0.5, 2.5),
                se=rng.uniform(0.3, 0.6),
                se_eff=0.6,
                experience_years=rng.choice([None, 1.0, 3.0, 6.0]),
                declared_relevant=sum(1 for item in evidence if item.kind == EvidenceKind.DECLARED),
            )
        )

    def missing(item: ranking.Scored) -> int:
        return item.coverage.must_total - item.coverage.must_covered

    for target in pool[:12]:
        stuffed_evidence = [*target.evidence.values(), *(ev(skill, "declared") for skill in skills)]
        # Накрутивший заявляет все шесть навыков: счётчик заявленных навыков специализации упирается в SKILLS_FULL.
        stuffed = replace(target, evidence=merge_evidence(stuffed_evidence), declared_relevant=len(skills))
        before, after = scored(target, q), scored(stuffed, q)
        assert after.coverage.confirmed_band == before.coverage.confirmed_band
        assert 0 <= after.strength.band - before.strength.band <= 3
        assert after.strength.s == 1.0 and (after.strength.t, after.strength.f) == (
            before.strength.t,
            before.strength.f,
        )
        # Сверх насыщения накрутка не даёт ничего: 30 навыков и 6 навыков — одна и та же сила.
        assert scored(replace(stuffed, declared_relevant=30), q).strength == after.strength
        assert missing(after) == 0
        new_pool = [stuffed if item.candidate_id == target.candidate_id else item for item in pool]
        ranked = order(q, new_pool, section_limits={})
        place = ranked.index(target.candidate_id)
        by_id = {item.candidate_id: item for item in new_pool}
        for other_id in ranked[place + 1 :]:
            other = scored(by_id[other_id], q)
            if missing(other) > missing(after):
                continue  # у обойдённого остался пробел в обязательных — это и есть цена первого ключа
            more_confirmed = other.coverage.confirmed_band > after.coverage.confirmed_band
            stronger = (
                other.coverage.confirmed_band == after.coverage.confirmed_band
                and other.strength.band > after.strength.band
            )
            assert not more_confirmed and not stronger


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
    return sort_key(scored(features, q), SEED)[1:5]


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
        replace(base, experience_years=4.0),
        replace(base, declared_relevant=3),
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
        "work_formats", "exposure_7d", "basis", "experience_years", "declared_relevant",
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
    # Без требований ключи соответствия нулевые: порядок задаёт только сила — как в банке.
    assert all(item.key[1] == 0 and item.key[2] == 0 and item.key[4] == 0 for item in result.items)
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
    # Без истории ФСП F = 0 и ничего не вычитается: T = (0.9 − 0.4 + 0.75) / 2.25 = 0.555556,
    # сила = 100·0.10·0.555556 = 5.5556 → 5.6. С сигналом 0.9 прибавляется 30·0.9 = 27: 32.5556 → 32.6.
    assert scored(without, q).strength.f == 0.0 and scored(without, q).strength.value == 5.6
    assert scored(with_fsp, q).strength.value == 32.6
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
        features = cand(
            number,
            evidence,
            theta=rng.uniform(-1, 3),
            fsp_signal=rng.choice([0.0, 0.3, 0.9]),
            se_eff=0.7,
            experience_years=rng.choice([None, 0.5, 2.0, 4.5, 12.0]),
            declared_relevant=rng.randint(0, 9),
        )
        item = scored(features, query())
        expl = build_explanation(features, query(), item, ctx(fsp_line="участник", fsp_fact_id="f"))
        cover = sum(row.points for row in expl.contributions if row.group == "coverage")
        power = sum(row.points for row in expl.contributions if row.group == "strength")
        assert cover == pytest.approx(item.coverage.pct or 0, abs=0.5 + 0.05 * 4)
        # До пяти строк силы, каждая округлена до 0.1 (ошибка ≤ 0.05), и сама сила округлена до 0.1.
        assert power == pytest.approx(item.strength.value, abs=0.3)
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


# --------------------------------------------------------------------------------------------------------------------
# Сила версии 3 и заявленный грейд
# --------------------------------------------------------------------------------------------------------------------


def test_declared_without_fsp_is_never_high() -> None:
    """Одним заявленным без ФСП не набрать больше 60 баллов: подпись `high` (от 65) требует теста или ФСП."""
    # Предел накрутки: стаж 40 лет (X = 1) и 30 навыков (S = 1): 100·(0.35 + 0.25) = 60.0 < 65 → medium.
    top = strength(declared_cand(1, experience_years=40.0, declared_relevant=30))
    assert (top.value, top.label, top.tested) == (60.0, "medium", False) and (top.t, top.t_fresh) == (0.0, 0.0)
    rng = random.Random(21)
    for number in range(2, 60):
        grade = rng.choice(GRADES)
        item = declared_cand(
            number,
            grade_code=grade,
            experience_years=rng.choice([None, 0.0, 1.5, 4.0, 9.0, 40.0]),
            declared_relevant=rng.randint(0, 30),
        )
        assert strength(item).label != "high" and strength(item).value <= 60.0
    # С ФСП `high` достижим и без теста: 60 + 30·0.5 = 75.0. С тестом и без ФСП потолок — 10 + 60 = 70.0 → high.
    with_fsp = declared_cand(60, experience_years=40.0, declared_relevant=30, fsp_signal=0.5)
    assert (strength(with_fsp).value, strength(with_fsp).label) == (75.0, "high")
    tested = cand(61, theta=5.0, experience_years=40.0, declared_relevant=30)
    assert (strength(tested).value, strength(tested).label) == (70.0, "high")


def test_strength_saturation_and_hidden_fields() -> None:
    # Полный стаж по грейдам: junior 2, middle 5, senior 8 лет. Без теста и ФСП сила = 35·X + 25·S.
    assert strength(declared_cand(1, grade_code="junior", experience_years=1.0)).value == 17.5  # 35·1/2
    assert strength(declared_cand(1, grade_code="middle", experience_years=1.0)).value == 7.0  # 35·1/5
    assert strength(declared_cand(1, grade_code="senior", experience_years=4.0)).value == 17.5  # 35·4/8
    assert strength(declared_cand(1, declared_relevant=3)).value == 12.5  # 25·3/6
    # Скрытый стаж (None) и скрытый стек (0 навыков) дают ноль вклада, а не штраф.
    hidden = strength(declared_cand(1))
    assert (hidden.value, hidden.x, hidden.s, hidden.label) == (0.0, 0.0, 0.0, "base")


def test_declared_candidate_sections() -> None:
    """Заявленный грейд не бывает «подтверждён с запасом»: в раздел «грейд ниже» такой кандидат не попадает."""
    q = query(specialization_code="frontend")
    sections = sections_for(q, GRADES)
    assert first_failed_filter(declared_cand(1, grade_code="junior"), q, sections) == "margin_required"
    assert first_failed_filter(declared_cand(1, grade_code="middle"), q, sections) is None
    assert first_failed_filter(declared_cand(1, grade_code="senior"), q, sections) is None
    pool = [declared_cand(n, grade_code=grade) for n, grade in enumerate(GRADES, start=1)]
    result = rank(q, pool)
    assert [item.scored.relation for item in result.items] == [Relation.EXACT, Relation.HIGHER]


def test_declared_explanation() -> None:
    """Заявленный грейд: первым доводом всегда `level_declared`; про тест, свежесть и давность — ни слова."""
    q = query(specialization_code="frontend", must_skills=["python"], nice_skills=[])
    features = declared_cand(1, [ev("python", "declared")], experience_years=3.0, declared_relevant=1)
    item = scored(features, q)
    expl = build_explanation(features, q, item, ctx())
    assert expl.reasons[0].code == "level_declared"
    assert expl.reasons[0].text == "Грейд Middle заявлен кандидатом: тест по специализации готовится"
    codes = [reason.code for reason in expl.reasons]
    assert not {"level_confirmed", "level_margin", "fresh"} & set(codes)
    assert expl.risk is not None and expl.risk.code == "must_declared_only"
    assert expl.level.basis == CategoryBasis.DECLARED and expl.level.age_days is None
    assert expl.level.verdict is None and expl.level.last_evidence_at is None and expl.level.stale is False
    strength_rows = [row for row in expl.contributions if row.group == "strength"]
    assert [row.code for row in strength_rows] == ["test", "experience", "skills"]
    assert strength_rows[0].label == "Тест по специализации готовится"
    assert (strength_rows[0].points, strength_rows[0].max_points) == (0.0, 10.0)
    # Сохранённое объяснение прежней версии оценщика (без `basis`) читается как подтверждённое тестом.
    old = expl.model_dump(mode="json")
    old["level"] = {
        "grade_code": "middle",
        "verdict": "confirmed",
        "tested_at": "2026-08-20",
        "last_evidence_at": "2026-08-20",
        "age_days": 12,
        "stale": False,
    }
    assert type(expl).model_validate(old).level.basis == CategoryBasis.TEST
    # Абляция с прибавкой за свежесть не падает на кандидате без давности.
    assert order(q, [features], key_order=("additive",)) == [features.candidate_id]


def test_experience_grade_mismatch_note() -> None:
    """Стаж ниже обычного для грейда и неизвестный стаж при заявленном грейде — строка объяснения, не ключ."""
    assert experience_note(cand(1, experience_years=1.0)) == ("experience_below_grade", 2.0)
    assert experience_note(cand(1, experience_years=2.0)) is None
    assert experience_note(cand(1, grade_code="senior", experience_years=4.5)) == ("experience_below_grade", 5.0)
    assert experience_note(cand(1, grade_code="junior", experience_years=0.0)) is None
    assert experience_note(cand(1)) is None  # стаж скрыт, но грейд подтверждён тестом — пометки нет
    assert experience_note(declared_cand(1)) == ("experience_unknown", 2.0)
    assert experience_note(declared_cand(1, experience_years=3.0)) is None

    q = query(must_skills=["python"], nice_skills=[])
    # Другого риска нет: пометка занимает место риска и в доводы не дублируется.
    clean = cand(1, [ev("python")], experience_years=1.0)
    expl = build_explanation(clean, q, scored(clean, q), ctx())
    assert expl.risk is not None and expl.risk.code == "experience_below_grade"
    assert expl.risk.text == f"Заявленный стаж 1{NBSP}год — ниже обычного для грейда Middle (от 2{NBSP}лет)"
    assert "experience_below_grade" not in [reason.code for reason in expl.reasons]
    # Риск уже есть: пометка идёт строкой сразу после довода об уровне и в лимит трёх строк попадает.
    gap = cand(2, [], experience_years=1.5)
    expl_gap = build_explanation(gap, q, scored(gap, q), ctx())
    assert expl_gap.risk is not None and expl_gap.risk.code == "must_missing"
    assert [reason.code for reason in expl_gap.reasons][:2] == ["level_confirmed", "experience_below_grade"]
    assert f"1,5{NBSP}года" in expl_gap.reasons[1].text
    # Заявленный грейд без стажа.
    unknown = declared_cand(3, [ev("python", "fsp")], fsp_signal=0.6, fsp_band="medium", fsp_verified=True)
    q_front = query(specialization_code="frontend", must_skills=["python"], nice_skills=[])
    expl_unknown = build_explanation(unknown, q_front, scored(unknown, q_front), ctx())
    assert expl_unknown.risk is not None and expl_unknown.risk.code == "experience_unknown"
    assert expl_unknown.risk.text == "Стаж не указан: грейд заявлен без подтверждения"
    # Пометка не ключ: порог «обычного стажа» не меняет ни ключ порядка, ни силу.
    other = ScoringParams(exp_expected_min={"junior": 0.0, "middle": 0.0, "senior": 0.0})
    assert sort_key(score_candidate(clean, q, Relation.EXACT, closure, other), SEED) == sort_key(scored(clean, q), SEED)
    # Кандидат позже скрыл стаж: число лет из сохранённой версии не отдаётся, вклад стажа — ноль.
    hidden = apply_read_rules(expl, ReadRules(experience_hidden=True))
    assert hidden.risk is None
    assert next(row for row in hidden.contributions if row.code == "experience").points == 0.0
    hidden_gap = apply_read_rules(expl_gap, ReadRules(experience_hidden=True))
    assert "experience_below_grade" not in [reason.code for reason in hidden_gap.reasons]
