"""Синтетический мир валидации подбора: латентная истина, шумные наблюдения, потребности (приложение B, §9.1–9.3).

`LatentCandidate` скореру не передаётся: `observe` превращает его в `CandidateFeatures`, и только они попадают
в `rank_need`. Все случайные числа — из `random.Random(seed)`: один сид — один мир.

Модель наблюдений — запасная из приложения B, §9.2 (`observation_model = "simplified"`): оценка теста и
подтверждения навыков порождаются формулами, а не прогоном движка `assessment`; сигнал ФСП — формулой с
насыщением, а не фактами демо-реестра. Это названо в паспорте отчёта и в «Угрозах валидности».
Навыки мира заданы здесь же (ядро — то, что проверяет тест категории; остальное — инструменты).
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from uuid import UUID

from app.modules.matching.dto import ShortlistQuery
from app.modules.matching.features import CandidateFeatures, SkillEvidence, merge_evidence
from app.shared.enums import CategoryBasis, EvidenceKind, TestOutcome, WorkFormat

OBSERVATION_MODEL = "simplified"
AS_OF = date(2026, 10, 1)

GRADES: list[str] = ["junior", "middle", "senior"]
#: Пороги и ширина грейда — те же, что у модуля теста (`assessment/config.py`).
CUTS: dict[str, float] = {"junior": -1.5, "middle": 0.0, "senior": 1.5}
WIDTH = 1.5
DRIFT_SD_PER_180D = 0.75
SE_EFF_MAX = 1.5
SALARY_MEDIAN: dict[str, int] = {"junior": 90_000, "middle": 190_000, "senior": 320_000}
FORMATS: list[str] = [item.value for item in WorkFormat]

#: Специализация → (ядро, инструменты). Частный навык `a>b` означает «из a следует b» (перенос только вверх).
SPECIALIZATIONS: dict[str, tuple[list[str], list[str]]] = {
    "backend": (
        ["python", "sql", "algorithms", "http"],
        ["postgresql>sql", "kafka", "docker", "redis", "fastapi>python", "kubernetes", "grpc", "clickhouse>sql"],
    ),
    "frontend": (
        ["javascript", "html_css", "algorithms", "http"],
        ["typescript>javascript", "react>javascript", "vue>javascript", "webpack", "nextjs>javascript", "graphql"],
    ),
    "data_ml": (
        ["python", "sql", "statistics", "ml_basics"],
        ["pandas>python", "pytorch>python", "spark", "airflow", "clickhouse>sql", "mlflow"],
    ),
    "qa": (
        ["test_design", "sql", "http", "python"],
        ["pytest>python", "selenium", "postman", "allure", "k6", "docker"],
    ),
}


def _split(tool: str) -> tuple[str, str | None]:
    name, _, general = tool.partition(">")
    return name, general or None


IMPLIES: dict[str, frozenset[str]] = {
    name: frozenset({general})
    for _, tools in SPECIALIZATIONS.values()
    for name, general in map(_split, tools)
    if general
}


def closure(skill: str) -> frozenset[str]:
    """`implies_closure` мира валидации."""
    return IMPLIES.get(skill, frozenset())


def core_skills(spec: str) -> list[str]:
    return list(SPECIALIZATIONS[spec][0])


def tool_skills(spec: str) -> list[str]:
    return [_split(tool)[0] for tool in SPECIALIZATIONS[spec][1]]


def sigmoid(value: float) -> float:
    return 1 / (1 + math.exp(-value))


def tool_difficulty(skill: str) -> float:
    """Сложность инструмента: равномерно на [−1.0; 1.5], детерминированно из `sha256(skill_code)`."""
    share = int(hashlib.sha256(skill.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return -1.0 + 2.5 * share


@dataclass(frozen=True, slots=True)
class Regime:
    """Режим допущений: доля приукрашивающих, сила приукрашивания, глубина теста."""

    name: str
    inflators: float
    inflate_p: float
    probe_declared: int


REGIMES: dict[str, Regime] = {
    "honest": Regime("честно, тест со стеком", 0.0, 0.0, 2),
    "moderate": Regime("умеренно, тест со стеком", 0.25, 0.35, 2),
    "strong": Regime("сильно, тест со стеком", 0.50, 0.60, 2),
    "honest_core": Regime("честно, тест без стека", 0.0, 0.0, 0),
    "moderate_core": Regime("умеренно, тест без стека", 0.25, 0.35, 0),
    "strong_core": Regime("сильно, тест без стека", 0.50, 0.60, 0),
}
#: Основной режим объявлен заранее.
MAIN_REGIME = "moderate"


@dataclass(frozen=True, slots=True)
class LatentCandidate:
    """Латентная истина о кандидате. В `CandidateFeatures` не попадает ничего, кроме наблюдений."""

    candidate_id: UUID
    spec: str
    theta_true: float
    #: Навык → уровень владения 1..3 (2 — рабочий уровень); отсутствующего навыка в словаре нет.
    skills: dict[str, int]
    formats: frozenset[str]
    min_salary: int
    # Для тестов инвариантности: в признаки не попадают.
    name: str
    gender: str
    birth_year: int


@dataclass(frozen=True, slots=True)
class Observed:
    """Наблюдения по кандидату: признаки для скорера и то, что видят бейзлайны (заявленный стек, текст)."""

    latent: LatentCandidate
    features: CandidateFeatures
    declared: frozenset[str]
    text: str


@dataclass(frozen=True, slots=True)
class EvalNeed:
    """Синтетическая потребность."""

    need_id: UUID
    query: ShortlistQuery
    salary_mid: int
    #: Все обязательные навыки проверяются тестом категории (страта поправки R3-tz-compliance-5).
    must_tested: bool
    text: str


@dataclass(slots=True)
class World:
    seed: int
    regime: Regime
    latents: list[LatentCandidate] = field(default_factory=list)
    observed: list[Observed] = field(default_factory=list)
    #: Те же кандидаты с другой формой теста («близнецы»): меняется только шум теста.
    twins: dict[UUID, CandidateFeatures] = field(default_factory=dict)
    #: Те же люди как кандидаты специализации без теста: все с заявленным грейдом (блок отчёта `declared_basis`).
    declared_pool: list[Observed] = field(default_factory=list)
    needs: list[EvalNeed] = field(default_factory=list)


def true_grade(theta: float) -> str:
    """Старший грейд с `cut ≤ theta_true`; ниже младшего порога — младший."""
    result = GRADES[0]
    for grade in GRADES:
        if CUTS[grade] <= theta:
            result = grade
    return result


def make_latent(rng: random.Random, spec: str, number: int, seed: int) -> LatentCandidate:
    theta = rng.gauss(0.0, 1.0)
    skills: dict[str, int] = {}

    def level() -> int:
        return 1 + int(theta + rng.gauss(0, 0.6) > -0.6) + int(theta + rng.gauss(0, 0.6) > 0.6)

    for skill in core_skills(spec):
        if rng.random() < sigmoid(2.5 * (theta + 1.8)):
            skills[skill] = level()
    for tool in SPECIALIZATIONS[spec][1]:
        name, general = _split(tool)
        if general is not None:
            # Частный навык возможен, только если есть общий.
            if general in skills and rng.random() < 0.45:
                skills[name] = level()
        elif rng.random() < 0.8 * sigmoid(1.2 * (theta - tool_difficulty(name))):
            skills[name] = level()
    formats = frozenset(rng.sample(FORMATS, rng.randint(1, len(FORMATS))))
    grade = true_grade(theta)
    salary = SALARY_MEDIAN[grade] * math.exp(rng.gauss(0, 0.2))
    return LatentCandidate(
        candidate_id=UUID(int=seed * 1_000_000 + number),
        spec=spec,
        theta_true=theta,
        skills=skills,
        formats=formats,
        min_salary=int(salary // 20_000) * 20_000,
        name=f"Кандидат {number}",
        gender=rng.choice(["f", "m"]),
        birth_year=rng.randint(1975, 2005),
    )


def _outcome(theta: float, cut: float) -> TestOutcome:
    if theta < cut - 0.15 * WIDTH:
        return TestOutcome.NOT_CONFIRMED
    if theta < cut + 0.15 * WIDTH:
        return TestOutcome.BORDERLINE
    if theta < cut + 0.75 * WIDTH:
        return TestOutcome.CONFIRMED
    return TestOutcome.CONFIRMED_WITH_MARGIN


@dataclass(frozen=True, slots=True)
class _Profile:
    """Часть наблюдений, не зависящая от формы теста: общая у «близнецов»."""

    claimed_grade: int
    declared: frozenset[str]
    age_days: int
    fsp_signal: float
    pulse: tuple[str, ...]
    #: Заявленный стаж, лет: растёт с уровнем, шумит, у приукрашивающих завышен.
    experience_years: float = 0.0


def _profile(rng: random.Random, latent: LatentCandidate, regime: Regime) -> _Profile:
    index = GRADES.index(true_grade(latent.theta_true))
    roll = rng.random()
    claimed = index if roll < 0.60 else index + 1 if roll < 0.85 else index - 1
    inflator = rng.random() < regime.inflators
    declared = set()
    for skill in [*core_skills(latent.spec), *tool_skills(latent.spec)]:
        if skill in latent.skills:
            chance = 0.85
        else:
            chance = regime.inflate_p if inflator else 0.03
        if rng.random() < chance:
            declared.add(skill)
    signal = 0.0
    if rng.random() < 0.40:
        x = max(0.0, 0.8 + 0.6 * latent.theta_true + rng.gauss(0, 0.7))
        signal = 1 - math.exp(-x / 1.5)
    pulse: tuple[str, ...] = ()
    if rng.random() < 0.20:
        working = [skill for skill, lat in latent.skills.items() if lat >= 2]
        pulse = tuple(rng.sample(working, min(len(working), rng.randint(1, 3))))
    age_days = rng.randint(0, 300)
    # Стаж разыгрывается последним: все прежние случайные числа профиля остаются теми же, что и до версии 3.
    # `g` — уровень в ширинах грейда над порогом junior: на пороге junior в среднем 1 год, middle — 3.5, senior — 6.
    g = (latent.theta_true - CUTS["junior"]) / WIDTH
    years = max(0.0, 1.0 + 2.5 * g + rng.gauss(0, 1.5))
    if inflator:
        years += rng.uniform(1, 4)
    return _Profile(
        claimed_grade=max(0, min(len(GRADES) - 1, claimed)),
        declared=frozenset(declared),
        age_days=age_days,
        fsp_signal=signal,
        pulse=pulse,
        experience_years=max(0.0, min(40.0, round(years * 2) / 2)),
    )


def _fsp_band(signal: float) -> str:
    if signal <= 0:
        return "none"
    return "low" if signal < 0.35 else "medium" if signal < 0.65 else "high"


def _take_test(
    rng: random.Random, latent: LatentCandidate, profile: _Profile, regime: Regime
) -> CandidateFeatures | None:
    """Одна форма теста: оценка уровня, путь по грейдам, подтверждённые навыки. `None` — категории нет."""
    se = rng.uniform(0.40, 0.60) * WIDTH
    theta = latent.theta_true + rng.gauss(0, se)
    grade_index: int | None = None
    verdict = TestOutcome.NOT_CONFIRMED
    for index in range(profile.claimed_grade, -1, -1):
        outcome = _outcome(theta, CUTS[GRADES[index]])
        if outcome in (TestOutcome.CONFIRMED, TestOutcome.CONFIRMED_WITH_MARGIN):
            grade_index, verdict = index, outcome
            break
    if grade_index is None:
        return None
    if verdict == TestOutcome.CONFIRMED_WITH_MARGIN and grade_index + 1 < len(GRADES) and rng.random() < 0.5:
        higher = _outcome(theta, CUTS[GRADES[grade_index + 1]])
        if higher in (TestOutcome.CONFIRMED, TestOutcome.CONFIRMED_WITH_MARGIN):
            grade_index, verdict = grade_index + 1, higher
    cut = CUTS[GRADES[grade_index]]

    probed = core_skills(latent.spec)
    tools = sorted(skill for skill in profile.declared if skill in tool_skills(latent.spec))
    probed += rng.sample(tools, min(len(tools), regime.probe_declared))
    evidence: list[SkillEvidence] = []
    for skill in probed:
        lat = latent.skills.get(skill)
        chance = 0.04 if lat is None else sigmoid(1.5 * (latent.theta_true - cut) / WIDTH + 0.8 + 0.6 * (lat - 2))
        if rng.random() < chance:
            # Группа подтверждена целиком (вес 1.0) либо решено одно задание с тегом навыка (0.7), Арх. 5.6.
            evidence.append(SkillEvidence(skill, EvidenceKind.TEST, full=rng.random() < 0.6))
    tested = {item.skill_code for item in evidence}
    evidence += [SkillEvidence(skill, EvidenceKind.PULSE) for skill in profile.pulse if skill not in tested]
    evidence += [SkillEvidence(skill, EvidenceKind.DECLARED) for skill in sorted(profile.declared)]
    se_eff = min(math.sqrt(se**2 + DRIFT_SD_PER_180D**2 * profile.age_days / 180), SE_EFF_MAX)
    tested_at = AS_OF - timedelta(days=profile.age_days)
    return CandidateFeatures(
        candidate_id=latent.candidate_id,
        specialization_code=latent.spec,
        grade_code=GRADES[grade_index],
        verdict=verdict,
        theta=theta,
        se=se,
        se_eff=se_eff,
        cut=cut,
        width=WIDTH,
        tested_at=tested_at,
        last_evidence_at=tested_at,
        age_days=profile.age_days,
        stale=profile.age_days > 180,
        evidence=merge_evidence(evidence),
        fsp_signal=profile.fsp_signal,
        fsp_band=_fsp_band(profile.fsp_signal),  # type: ignore[arg-type]
        fsp_verified=profile.fsp_signal > 0,
        work_formats=latent.formats,
        exposure_7d=0,
        basis=CategoryBasis.TEST,
        experience_years=profile.experience_years,
        declared_relevant=len(profile.declared),
    )


def declared_features(latent: LatentCandidate, profile: _Profile) -> CandidateFeatures:
    """Тот же кандидат в специализации без теста: грейд заявлен, оценки и подтверждений тестом нет.

    Остаются заявленные навыки, стаж и сигнал ФСП. Категорию получает каждый — отсева тестом нет.
    """
    grade = GRADES[profile.claimed_grade]
    evidence = [SkillEvidence(skill, EvidenceKind.DECLARED) for skill in sorted(profile.declared)]
    return CandidateFeatures(
        candidate_id=latent.candidate_id,
        specialization_code=latent.spec,
        grade_code=grade,
        verdict=None,
        theta=None,
        se=None,
        se_eff=None,
        cut=CUTS[grade],
        width=WIDTH,
        tested_at=None,
        last_evidence_at=None,
        age_days=None,
        stale=False,
        evidence=merge_evidence(evidence),
        fsp_signal=profile.fsp_signal,
        fsp_band=_fsp_band(profile.fsp_signal),  # type: ignore[arg-type]
        fsp_verified=profile.fsp_signal > 0,
        work_formats=latent.formats,
        exposure_7d=0,
        basis=CategoryBasis.DECLARED,
        experience_years=profile.experience_years,
        declared_relevant=len(profile.declared),
    )


def make_need(rng: random.Random, number: int, seed: int) -> EvalNeed:
    spec = rng.choice(sorted(SPECIALIZATIONS))
    grade = rng.choices(GRADES, weights=[0.30, 0.45, 0.25])[0]
    core, tools = core_skills(spec), tool_skills(spec)
    must = [rng.choice(core)]
    specific = [name for name in tools if name in IMPLIES]
    plain = [name for name in tools if name not in IMPLIES]
    if specific and rng.random() < 0.8:
        must.append(rng.choice(specific))
    must += rng.sample(plain, min(len(plain), rng.randint(0, 2)))
    rest = [skill for skill in [*core, *tools] if skill not in must]
    nice = rng.sample(rest, min(len(rest), rng.randint(0, 3)))
    formats = rng.sample(FORMATS, rng.randint(1, 2))
    middle = int(SALARY_MEDIAN[grade] * rng.uniform(0.9, 1.3))
    query = ShortlistQuery(
        specialization_code=spec,
        grade_code=grade,
        must_skills=sorted(must),
        nice_skills=sorted(nice),
        work_formats=sorted((WorkFormat(item) for item in formats), key=lambda item: item.value),
        salary_from=int(middle * 0.85),
        salary_to=int(middle * 1.15),
    )
    return EvalNeed(
        need_id=UUID(int=seed * 1_000_000 + 900_000 + number),
        query=query,
        salary_mid=middle,
        must_tested=all(skill in core for skill in must),
        text=" ".join([spec, grade, *must, *must, *nice]),
    )


def build_world(seed: int, regime: Regime, *, candidates: int = 400, needs: int = 30) -> World:
    """Мир одного сида: кандидаты поровну по специализациям, их наблюдения, «близнецы» и потребности.

    Потоки случайных чисел разделены: латентная истина и потребности не зависят от режима допущений, а форма
    теста — от профиля, поэтому режимы сравниваются на одних и тех же людях.
    """
    world = World(seed=seed, regime=regime)
    latent_rng = random.Random(f"latent:{seed}")
    specs = sorted(SPECIALIZATIONS)
    for number in range(candidates):
        world.latents.append(make_latent(latent_rng, specs[number % len(specs)], number, seed))
    for latent in world.latents:
        profile = _profile(random.Random(f"profile:{seed}:{regime.name}:{latent.candidate_id}"), latent, regime)
        features = _take_test(random.Random(f"form-a:{seed}:{latent.candidate_id}"), latent, profile, regime)
        text = " ".join([latent.spec, *sorted(profile.declared)])
        world.declared_pool.append(
            Observed(latent=latent, features=declared_features(latent, profile), declared=profile.declared, text=text)
        )
        if features is None:
            continue  # никто не подтвердился — кандидат без категории, в пул не входит
        world.observed.append(Observed(latent=latent, features=features, declared=profile.declared, text=text))
        twin = _take_test(random.Random(f"form-b:{seed}:{latent.candidate_id}"), latent, profile, regime)
        if twin is not None:
            world.twins[latent.candidate_id] = twin
    need_rng = random.Random(f"needs:{seed}")
    world.needs = [make_need(need_rng, number, seed) for number in range(needs)]
    return world
