"""Объяснение выдачи: модель, доводы, риск, вклады и проекции (Арх. 6.10, 4.9).

`build_explanation` — чистая функция: результат хранится в `shortlist_item.explanation` вместе с готовыми
текстами, поэтому версия показывает то же объяснение, что и в момент создания. Поверх сохранённого при каждом
чтении применяются правила перепроверки (`apply_read_rules`, Арх. 6.11): скрытое заявленное и недоступные
сведения ФСП из сохранённой версии не отдаются.

В текстах нет чисел балла, процентов и сравнений с другими кандидатами. Для доказательств и доводов вида `fsp`
хранится только идентификатор факта и обобщённый текст: подробный строится при чтении и только раскрытой паре.
Файл не обращается к базе и фасадам: названия навыков и грейдов приходят через `ExplainContext`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel

from app.modules.matching import constants as C
from app.modules.matching.dto import InvitationWhy, ShortlistQuery, UnconfirmedSkill
from app.modules.matching.features import CONFIRMED_KINDS, KIND_ORDER, CandidateFeatures, SkillEvidence, nominal_weight
from app.modules.matching.ranking import Scored
from app.modules.matching.schemas import (
    CoverageView,
    EvidenceRefView,
    MatchExplanationEmployerView,
    ReasonView,
    RiskView,
)
from app.modules.matching.scoring import DEFAULT_PARAMS, ScoringParams, Strength, round1
from app.shared.enums import EvidenceKind, FitBand, Relation, TestOutcome, WorkFormat
from app.shared.schemas import CategoryRef, Contribution, EvidenceItem, Ref
from app.shared.text import NBSP, count_phrase, fmt_date, join_titles

# --------------------------------------------------------------------------------------------------------------------
# Подписи
# --------------------------------------------------------------------------------------------------------------------

RELATION_LABELS: dict[Relation, str] = {
    Relation.EXACT: "основная",
    Relation.LOWER_WITH_MARGIN: "грейд ниже, подтверждён с запасом",
    Relation.HIGHER: "грейд выше",
}

FORMAT_LABELS: dict[str, str] = {"office": "офис", "hybrid": "гибрид", "remote": "удалённо"}

#: Тексты причин «выпал из подборки» (Арх. 6.4).
REASON_TEXTS: dict[str, str] = {
    "unavailable": "профиль скрыт или снят с публикации",
    "category_excluded": "грейд исключён из запроса",
    "margin_required": "грейд ниже запрошенного, подтверждён без запаса",
    "format": "формат работы не совпадает",
    "require_fsp": "нет подтверждённых достижений ФСП",
    "below_limit": "не вошёл в первые {limit} раздела",
    "other_version": "нет в этой версии подборки",
}

DECLARED_DETAIL = "Заявлено кандидатом"
DECLARED_DETAIL_OWN = "указано вами в профиле"
FSP_GENERIC_DETAIL = "достижение ФСП"

SOURCE_TYPES: dict[EvidenceKind, str] = {
    EvidenceKind.TEST: "test_session",
    EvidenceKind.PULSE: "pulse_assignment",
    EvidenceKind.FSP: "fsp_fact",
    EvidenceKind.DECLARED: "profile",
}


def kind_label(kind: EvidenceKind | str, full: bool = True) -> str:
    """Подпись вида доказательства (Арх. 6.2): два веса `test` различаются подписью."""
    kind = EvidenceKind(kind)
    if kind == EvidenceKind.TEST:
        return "подтверждено тестом" if full else "решено задание теста"
    return {
        EvidenceKind.PULSE: "короткое задание",
        EvidenceKind.FSP: "достижение ФСП",
        EvidenceKind.DECLARED: "заявлено кандидатом",
        EvidenceKind.NONE: "нет данных",
    }[kind]


def reason_text(code: str, *, limit: int | None = None) -> str:
    """Текст причины невхождения в подборку по коду фильтра."""
    template = REASON_TEXTS.get(code, REASON_TEXTS["unavailable"])
    return template.format(limit=limit if limit is not None else "")


def days_ago(days: int) -> str:
    """«сегодня» либо «N дней назад» с верным склонением."""
    if days <= 0:
        return "сегодня"
    return f"{count_phrase(days, 'день', 'дня', 'дней')} назад"


# --------------------------------------------------------------------------------------------------------------------
# Хранимая модель объяснения
# --------------------------------------------------------------------------------------------------------------------


class SourceRef(BaseModel):
    """Источник доказательства или довода."""

    type: str
    id: str | None = None


class ExplCoverage(BaseModel):
    """Покрытие требований на момент создания версии."""

    pct: int | None = None
    band: int | None = None
    confirmed_pct: int | None = None
    confirmed_band: int | None = None
    must_total: int = 0
    must_covered: int = 0
    must_confirmed: int = 0
    nice_total: int = 0
    nice_covered: int = 0
    must_gap: bool = False
    capped: bool = False


class ExplStrength(BaseModel):
    """Сила подтверждённого профиля на момент создания версии."""

    value: float
    band: int
    label: Literal["high", "medium", "base"]


class ExplLevel(BaseModel):
    """Уровень категории кандидата на момент создания версии."""

    grade_code: str
    verdict: TestOutcome
    tested_at: date
    last_evidence_at: date
    age_days: int
    stale: bool


class ExplRequirement(BaseModel):
    """Требование запроса и чем оно подкреплено. Подробного текста ФСП здесь нет (Арх. 6.10)."""

    skill_code: str
    skill_title: str
    priority: Literal["must", "nice"]
    kind: EvidenceKind
    kind_label: str
    weight: float
    via_skill_code: str | None = None
    via_skill_title: str | None = None
    source_ref: SourceRef | None = None
    confirmed_at: datetime | None = None
    detail_public: str | None = None


class ExplReason(BaseModel):
    """Довод «за»: код, параметры, готовый текст и источник."""

    code: str
    params: dict[str, Any] = {}
    text: str
    evidence_ref: SourceRef


class ExplRisk(BaseModel):
    """Риск: код, параметры и готовый текст."""

    code: str
    params: dict[str, Any] = {}
    text: str


class MatchExplanation(BaseModel):
    """Объяснение места кандидата в подборке (Арх. 6.10); хранится в `shortlist_item.explanation`."""

    scorer_version: str
    relation: Relation
    fit_band: FitBand | None = None
    coverage: ExplCoverage
    strength: ExplStrength
    level: ExplLevel
    requirements: list[ExplRequirement] = []
    contributions: list[Contribution] = []
    reasons: list[ExplReason] = []
    risk: ExplRisk | None = None
    formats_common: list[str] = []


@dataclass(frozen=True, slots=True)
class ExplainContext:
    """Всё, что нужно объяснению сверх признаков ранжирования: версия оценщика, названия и обобщённая строка ФСП."""

    scorer_version: str
    skill_title: Callable[[str], str]
    grade_title: Callable[[str], str]
    #: `FspSignal.public.headline` — обобщённо, без года, места и названия соревнования.
    fsp_line: str | None = None
    #: Факт с наибольшим вкладом в сигнал.
    fsp_fact_id: str | None = None
    params: ScoringParams = DEFAULT_PARAMS


# --------------------------------------------------------------------------------------------------------------------
# Вклады
# --------------------------------------------------------------------------------------------------------------------


def strength_contributions(
    strength: Strength, fsp_signal: float, params: ScoringParams = DEFAULT_PARAMS
) -> list[Contribution]:
    """Вклады в силу профиля (Арх. 6.10).

    `test = round1(100·W_TEST·T_fresh)` (макс. 70), `freshness = round1(100·W_TEST·(T − T_fresh)) ≤ 0`,
    `fsp = round1(100·W_FSP·F)` (макс. 30). Строка ФСП при нуле не создаётся: отрицательных меток для
    кандидатов без ФСП нет (Арх. 15.1, № 14).
    """
    rows = [
        Contribution(
            group="strength",
            code="test",
            label="Результат теста (нижняя граница)",
            points=round1(100 * params.w_test * strength.t_fresh),
            max_points=round1(100 * params.w_test),
        ),
        Contribution(
            group="strength",
            code="freshness",
            label="Давность подтверждения",
            points=min(0.0, round1(100 * params.w_test * (strength.t - strength.t_fresh))),
            max_points=0.0,
        ),
    ]
    fsp_points = round1(100 * params.w_fsp * max(0.0, min(1.0, fsp_signal)))
    if fsp_points > 0:
        rows.append(
            Contribution(
                group="strength",
                code="fsp",
                label="Достижения ФСП",
                points=fsp_points,
                max_points=round1(100 * params.w_fsp),
            )
        )
    return rows


def _coverage_contributions(requirements: Sequence[ExplRequirement], params: ScoringParams) -> list[Contribution]:
    """`points_r = round1(100·w_r·e_r/Σw)`, `max_points_r = round1(100·w_r/Σw)` (Арх. 6.10)."""
    total = sum(params.w_must if item.priority == "must" else params.w_nice for item in requirements)
    rows: list[Contribution] = []
    for item in requirements:
        w = params.w_must if item.priority == "must" else params.w_nice
        rows.append(
            Contribution(
                group="coverage",
                code=f"req:{item.skill_code}",
                label=item.skill_title,
                points=round1(100 * w * item.weight / total),
                max_points=round1(100 * w / total),
            )
        )
    return rows


# --------------------------------------------------------------------------------------------------------------------
# Построение
# --------------------------------------------------------------------------------------------------------------------


def _titles(items: Sequence[ExplRequirement]) -> str:
    return join_titles([item.skill_title for item in items])


def _codes(items: Sequence[ExplRequirement]) -> list[str]:
    return [item.skill_code for item in items]


def _is_full_test(item: ExplRequirement, params: ScoringParams) -> bool:
    return item.kind == EvidenceKind.TEST and item.weight >= params.e_test and params.e_test > params.e_test_single


def _other_confirmation_text(items: Sequence[ExplRequirement]) -> str:
    """«{skills}: решено задание теста / подтверждено коротким заданием / достижением ФСП» — по видам."""
    phrases = (
        (EvidenceKind.TEST, "решено задание теста"),
        (EvidenceKind.PULSE, "подтверждено коротким заданием"),
        (EvidenceKind.FSP, "подтверждено достижением ФСП"),
    )
    parts = []
    for kind, phrase in phrases:
        group = [item for item in items if item.kind == kind]
        if group:
            parts.append(f"{_titles(group)}: {phrase}")
    return "; ".join(parts)


def _requirements(scored: Scored, ctx: ExplainContext) -> list[ExplRequirement]:
    rows: list[ExplRequirement] = []
    for item in scored.coverage.requirements:
        evidence = item.evidence
        source: SourceRef | None = None
        detail: str | None = None
        confirmed_at: datetime | None = None
        full = True
        if evidence is not None:
            full = evidence.full
            source = SourceRef(type=evidence.ref_type or SOURCE_TYPES[evidence.kind], id=evidence.ref_id)
            if evidence.kind == EvidenceKind.DECLARED:
                detail = DECLARED_DETAIL
            elif evidence.kind == EvidenceKind.FSP:
                # Дата и подробности факта до раскрытия не показываются: в версии их нет вовсе.
                detail = evidence.detail or FSP_GENERIC_DETAIL
            else:
                detail = evidence.detail
                confirmed_at = evidence.confirmed_at
        rows.append(
            ExplRequirement(
                skill_code=item.skill_code,
                skill_title=ctx.skill_title(item.skill_code),
                priority=item.priority,
                kind=item.kind,
                kind_label=kind_label(item.kind, full),
                weight=item.weight,
                via_skill_code=item.via_skill_code,
                via_skill_title=ctx.skill_title(item.via_skill_code) if item.via_skill_code else None,
                source_ref=source,
                confirmed_at=confirmed_at,
                detail_public=detail,
            )
        )
    return rows


def _reasons(
    features: CandidateFeatures, scored: Scored, requirements: Sequence[ExplRequirement], ctx: ExplainContext
) -> list[ExplReason]:
    """Доводы «за» — первые три применимых по порядку таблицы Арх. 6.10."""
    params = ctx.params
    must = [item for item in requirements if item.priority == "must"]
    nice = [item for item in requirements if item.priority == "nice"]
    grade = ctx.grade_title(features.grade_code)
    tested = fmt_date(features.tested_at)
    level_ref = SourceRef(type="level", id=None)
    profile_ref = SourceRef(type="profile", id=None)
    fsp_ref = SourceRef(type="fsp_fact", id=ctx.fsp_fact_id)
    reasons: list[ExplReason] = []

    full_test = [item for item in must if _is_full_test(item, params)]
    if full_test:
        head = (
            "Обязательный навык подтверждён тестом"
            if len(full_test) == 1
            else "Обязательные навыки подтверждены тестом"
        )
        reasons.append(
            ExplReason(
                code="must_confirmed_test",
                params={"skills": _codes(full_test)},
                text=f"{head}: {_titles(full_test)}",
                evidence_ref=full_test[0].source_ref or level_ref,
            )
        )

    if features.verdict == TestOutcome.CONFIRMED_WITH_MARGIN:
        reasons.append(
            ExplReason(
                code="level_margin",
                params={"grade": grade, "date": features.tested_at.isoformat()},
                text=f"Грейд {grade} подтверждён с запасом, тест {tested}",
                evidence_ref=level_ref,
            )
        )
    else:
        reasons.append(
            ExplReason(
                code="level_confirmed",
                params={"grade": grade, "date": features.tested_at.isoformat()},
                text=f"Грейд {grade} подтверждён тестом {tested}",
                evidence_ref=level_ref,
            )
        )

    if features.fsp_band in ("medium", "high") and ctx.fsp_line:
        reasons.append(
            ExplReason(
                code="fsp",
                params={"fact_id": ctx.fsp_fact_id or ""},
                text=f"Достижение ФСП: {ctx.fsp_line}",
                evidence_ref=fsp_ref,
            )
        )

    other = [
        item
        for item in must
        if item.kind in (EvidenceKind.PULSE, EvidenceKind.FSP)
        or (item.kind == EvidenceKind.TEST and not _is_full_test(item, params))
    ]
    if other:
        reasons.append(
            ExplReason(
                code="must_confirmed_other",
                params={"skills": _codes(other)},
                text=_other_confirmation_text(other),
                evidence_ref=other[0].source_ref or level_ref,
            )
        )

    nice_confirmed = [item for item in nice if item.kind in CONFIRMED_KINDS and item.weight >= params.e_test_single]
    if nice_confirmed:
        reasons.append(
            ExplReason(
                code="nice_confirmed",
                params={"skills": _codes(nice_confirmed)},
                text=f"Желательные навыки подтверждены: {_titles(nice_confirmed)}",
                evidence_ref=nice_confirmed[0].source_ref or level_ref,
            )
        )

    cov = scored.coverage
    if cov.must_total >= 2 and cov.must_covered == cov.must_total:
        reasons.append(
            ExplReason(
                code="must_all_covered",
                params={"n": cov.must_total},
                text=f"Есть данные по всем обязательным навыкам: {cov.must_total} из {cov.must_total}",
                evidence_ref=profile_ref,
            )
        )

    if features.age_days <= 30:
        reasons.append(
            ExplReason(
                code="fresh",
                params={"n": features.age_days},
                text=f"Уровень подтверждён недавно: {days_ago(features.age_days)}",
                evidence_ref=level_ref,
            )
        )

    if features.fsp_band == "low" and ctx.fsp_line:
        reasons.append(
            ExplReason(
                code="fsp_low",
                params={"fact_id": ctx.fsp_fact_id or ""},
                text=f"Есть опыт соревнований ФСП: {ctx.fsp_line}",
                evidence_ref=fsp_ref,
            )
        )

    declared = [item for item in requirements if item.kind == EvidenceKind.DECLARED]
    if declared:
        reasons.append(
            ExplReason(
                code="declared_match",
                params={"skills": _codes(declared)},
                text=f"Заявлено кандидатом: {_titles(declared)}",
                evidence_ref=profile_ref,
            )
        )

    if not requirements and scored.strength.label == "high":
        reasons.append(
            ExplReason(
                code="strength_high",
                params={},
                text="Высокая сила подтверждённого профиля в категории",
                evidence_ref=level_ref,
            )
        )
    return reasons[: C.REASONS_LIMIT]


def _missing_risk(items: Sequence[ExplRequirement]) -> ExplRisk:
    head = "Нет данных по обязательному навыку" if len(items) == 1 else "Нет данных по обязательным навыкам"
    return ExplRisk(code="must_missing", params={"skills": _codes(items)}, text=f"{head}: {_titles(items)}")


def _risk(
    features: CandidateFeatures, scored: Scored, requirements: Sequence[ExplRequirement], ctx: ExplainContext
) -> ExplRisk | None:
    """Риск — один, первый применимый по порядку таблицы Арх. 6.10."""
    must = [item for item in requirements if item.priority == "must"]
    nice = [item for item in requirements if item.priority == "nice"]
    grade = ctx.grade_title(features.grade_code)

    missing = [item for item in must if item.kind == EvidenceKind.NONE]
    if missing:
        return _missing_risk(missing)
    declared = [item for item in must if item.kind == EvidenceKind.DECLARED]
    if declared:
        return ExplRisk(
            code="must_declared_only",
            params={"skills": _codes(declared)},
            text=f"{_titles(declared)} — заявлено кандидатом, тестом не проверено",
        )
    if features.verdict in (TestOutcome.BORDERLINE, TestOutcome.NOT_CONFIRMED):
        return ExplRisk(
            code="verdict_weakened",
            params={},
            text="Повторный тест не подтвердил уровень: результат на границе грейда",
        )
    if features.stale:
        return ExplRisk(
            code="stale",
            params={"n": features.age_days},
            text=f"Уровень давно не подтверждался: {days_ago(features.age_days)}",
        )
    if scored.relation == Relation.LOWER_WITH_MARGIN:
        return ExplRisk(
            code="grade_lower",
            params={"grade": grade},
            text=f"Грейд ниже запрошенного: {grade}, подтверждён с запасом",
        )
    if scored.relation == Relation.HIGHER:
        return ExplRisk(code="grade_higher", params={}, text="Грейд выше запрошенного: вилка может не подойти")
    nice_missing = [item for item in nice if item.kind == EvidenceKind.NONE]
    if nice_missing:
        return ExplRisk(
            code="nice_missing",
            params={"skills": _codes(nice_missing)},
            text=f"Нет данных по желательным: {_titles(nice_missing)}",
        )
    return None


def build_explanation(
    features: CandidateFeatures, query: ShortlistQuery, scored: Scored, ctx: ExplainContext
) -> MatchExplanation:
    """Собрать объяснение места кандидата (Арх. 6.10). Чистая функция: тот же вход — побайтно тот же JSON."""
    cov = scored.coverage
    requirements = _requirements(scored, ctx)
    contributions = _coverage_contributions(requirements, ctx.params) if requirements else []
    contributions += strength_contributions(scored.strength, features.fsp_signal, ctx.params)
    query_formats = {str(item) for item in query.work_formats}
    return MatchExplanation(
        scorer_version=ctx.scorer_version,
        relation=scored.relation,
        fit_band=scored.fit_band,
        coverage=ExplCoverage(
            pct=cov.pct,
            band=cov.band if cov.has_requirements else None,
            confirmed_pct=cov.confirmed_pct,
            confirmed_band=cov.confirmed_band if cov.has_requirements else None,
            must_total=cov.must_total,
            must_covered=cov.must_covered,
            must_confirmed=cov.must_confirmed,
            nice_total=cov.nice_total,
            nice_covered=cov.nice_covered,
            must_gap=cov.must_gap,
            capped=cov.capped,
        ),
        strength=ExplStrength(value=scored.strength.value, band=scored.strength.band, label=scored.strength.label),
        level=ExplLevel(
            grade_code=features.grade_code,
            verdict=features.verdict,
            tested_at=features.tested_at,
            last_evidence_at=features.last_evidence_at,
            age_days=features.age_days,
            stale=features.stale,
        ),
        requirements=requirements,
        contributions=contributions,
        reasons=_reasons(features, scored, requirements, ctx),
        risk=_risk(features, scored, requirements, ctx),
        formats_common=sorted(features.work_formats & query_formats),
    )


# --------------------------------------------------------------------------------------------------------------------
# Правила чтения сохранённого объяснения (Арх. 6.11)
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReadRules:
    """Живое состояние кандидата и пары на момент чтения версии."""

    #: Кандидат сейчас выключил `show_declared_stack`: заявленное из сохранённой версии не отдаётся.
    declared_hidden: bool = False
    #: Сигнал ФСП сейчас видим (ФСП ID привязан, достижения не скрыты); иначе доводы и подтверждения `fsp` убираются.
    fsp_visible: bool = True
    #: Подробные тексты фактов для раскрытой пары с `fsp_details` (`fsp.render_evidence`); `None` — пара не раскрыта.
    #: Значение `None` у факта означает, что факта больше нет: довод не выводится.
    fsp_texts: Mapping[str, str | None] | None = None


def _to_none(item: ExplRequirement) -> ExplRequirement:
    return item.model_copy(
        update={
            "kind": EvidenceKind.NONE,
            "kind_label": kind_label(EvidenceKind.NONE),
            "weight": 0.0,
            "via_skill_code": None,
            "via_skill_title": None,
            "source_ref": None,
            "confirmed_at": None,
            "detail_public": None,
        }
    )


def apply_read_rules(expl: MatchExplanation, rules: ReadRules) -> MatchExplanation:
    """Перепроверить сохранённое объяснение на момент чтения (Арх. 6.11); сама версия не меняется.

    * Кандидат выключил `show_declared_stack`: требования вида `declared` отдаются как `none`, довод
      `declared_match` не выводится, риск `must_declared_only` заменяется на `must_missing` с теми же навыками.
      Довод «есть данные по всем обязательным» и счётчики покрытия пересчитываются без заявленного — иначе они
      выдавали бы скрытое. Сохранённые порядок и полоса совпадения не меняются.
    * Сведения ФСП недоступны (отвязка, скрытие, факта больше нет): требования `fsp` отдаются как `none`, доводы
      `fsp` и `fsp_low` не выводятся; на их место следующий по порядку довод не подставляется.
    * Раскрытая пара с `fsp_details`: в доводе и детали требования — подробный текст факта.
    """
    declared_must_hidden = rules.declared_hidden and any(
        item.kind == EvidenceKind.DECLARED and item.priority == "must" for item in expl.requirements
    )
    requirements: list[ExplRequirement] = []
    for item in expl.requirements:
        if item.kind == EvidenceKind.DECLARED and rules.declared_hidden:
            requirements.append(_to_none(item))
        elif item.kind == EvidenceKind.FSP:
            fact_id = item.source_ref.id if item.source_ref else None
            if not rules.fsp_visible:
                requirements.append(_to_none(item))
            elif rules.fsp_texts is not None and fact_id is not None and fact_id in rules.fsp_texts:
                text = rules.fsp_texts[fact_id]
                requirements.append(_to_none(item) if text is None else item.model_copy(update={"detail_public": text}))
            else:
                requirements.append(item)
        else:
            requirements.append(item)

    reasons: list[ExplReason] = []
    for reason in expl.reasons:
        if reason.code == "declared_match" and rules.declared_hidden:
            continue
        if reason.code == "must_all_covered" and declared_must_hidden:
            continue
        if reason.code in ("fsp", "fsp_low"):
            if not rules.fsp_visible:
                continue
            fact_id = reason.evidence_ref.id
            if rules.fsp_texts is not None and fact_id is not None and fact_id in rules.fsp_texts:
                text = rules.fsp_texts[fact_id]
                if text is None:
                    continue
                head = "Достижение ФСП" if reason.code == "fsp" else "Есть опыт соревнований ФСП"
                reason = reason.model_copy(update={"text": f"{head}: {text}"})
        if reason.code in ("must_confirmed_other", "nice_confirmed"):
            # Довод перечисляет навыки: остаются только те, чьё доказательство по-прежнему отдаётся.
            listed = reason.params.get("skills", [])
            kept = [item for item in requirements if item.skill_code in listed and item.kind != EvidenceKind.NONE]
            if not kept:
                continue
            if len(kept) != len(listed):
                text = (
                    _other_confirmation_text(kept)
                    if reason.code == "must_confirmed_other"
                    else f"Желательные навыки подтверждены: {_titles(kept)}"
                )
                reason = reason.model_copy(update={"params": {"skills": _codes(kept)}, "text": text})
        reasons.append(reason)

    # Риск — первый применимый: если после перепроверки обязательных без данных стало больше, это `must_missing`
    # (для скрытого заявленного — с теми же навыками, что были в `must_declared_only`).
    risk = expl.risk
    missing_now = [item for item in requirements if item.priority == "must" and item.kind == EvidenceKind.NONE]
    missing_before = [item for item in expl.requirements if item.priority == "must" and item.kind == EvidenceKind.NONE]
    if len(missing_now) != len(missing_before):
        risk = _missing_risk(missing_now)
    elif risk is not None and risk.code == "nice_missing":
        nice_missing = [item for item in requirements if item.priority == "nice" and item.kind == EvidenceKind.NONE]
        risk = ExplRisk(
            code="nice_missing",
            params={"skills": _codes(nice_missing)},
            text=f"Нет данных по желательным: {_titles(nice_missing)}",
        )

    if requirements == expl.requirements and reasons == expl.reasons and risk == expl.risk:
        return expl

    must = [item for item in requirements if item.priority == "must"]
    nice = [item for item in requirements if item.priority == "nice"]
    coverage = expl.coverage.model_copy(
        update={
            "pct": expl.coverage.confirmed_pct if rules.declared_hidden else expl.coverage.pct,
            "must_covered": sum(1 for item in must if item.kind != EvidenceKind.NONE),
            "must_confirmed": sum(1 for item in must if item.kind in CONFIRMED_KINDS),
            "nice_covered": sum(1 for item in nice if item.kind != EvidenceKind.NONE),
        }
    )
    by_code = {f"req:{item.skill_code}": item for item in requirements}
    contributions = [
        row.model_copy(update={"points": 0.0})
        if row.group == "coverage" and row.code in by_code and by_code[row.code].kind == EvidenceKind.NONE
        else row
        for row in expl.contributions
    ]
    return expl.model_copy(
        update={
            "requirements": requirements,
            "reasons": reasons,
            "risk": risk,
            "coverage": coverage,
            "contributions": contributions,
        }
    )


# --------------------------------------------------------------------------------------------------------------------
# Проекции
# --------------------------------------------------------------------------------------------------------------------


def evidence_item(item: ExplRequirement, *, own: bool = False) -> EvidenceItem:
    """Требование → `EvidenceItem`. `own = True` — проекция кандидата: у заявленного текст «указано вами в профиле»."""
    detail = item.detail_public
    if own and item.kind == EvidenceKind.DECLARED:
        detail = DECLARED_DETAIL_OWN
    return EvidenceItem(
        skill=Ref(code=item.skill_code, title=item.skill_title),
        priority=item.priority,
        kind=item.kind,
        kind_label=item.kind_label,
        via_skill=Ref(code=item.via_skill_code, title=item.via_skill_title or item.via_skill_code)
        if item.via_skill_code
        else None,
        detail=detail,
        confirmed_at=item.confirmed_at,
    )


def skill_item(
    evidence: SkillEvidence, title: str, *, own: bool = False, detail_override: str | None = None
) -> EvidenceItem:
    """Навык кандидата вне контекста потребности (`priority = None`): карточка, банк, свой кабинет."""
    if evidence.kind == EvidenceKind.DECLARED:
        detail: str | None = DECLARED_DETAIL_OWN if own else DECLARED_DETAIL
    elif evidence.kind == EvidenceKind.FSP:
        detail = detail_override or evidence.detail or FSP_GENERIC_DETAIL
    else:
        detail = evidence.detail
    return EvidenceItem(
        skill=Ref(code=evidence.skill_code, title=title),
        priority=None,
        kind=evidence.kind,
        kind_label=kind_label(evidence.kind, evidence.full),
        via_skill=None,
        detail=detail,
        # Дата факта ФСП до раскрытия не показывается.
        confirmed_at=None if evidence.kind in (EvidenceKind.FSP, EvidenceKind.DECLARED) else evidence.confirmed_at,
    )


def sorted_skills(evidence: Mapping[str, SkillEvidence], title: Callable[[str], str]) -> list[SkillEvidence]:
    """Навыки кандидата: сначала сильнейшие доказательства, внутри вида — по алфавиту названий."""
    return sorted(
        evidence.values(),
        key=lambda item: (
            -nominal_weight(item),
            KIND_ORDER[item.kind],
            title(item.skill_code).lower(),
            item.skill_code,
        ),
    )


def top_evidence(requirements: Sequence[ExplRequirement]) -> tuple[list[EvidenceItem], int]:
    """Строки доказательств для строки подборки: обязательные по убыванию веса, затем желательные; не больше
    четырёх, остаток — числом (`evidence_more`).
    """
    ordered = sorted(
        requirements,
        key=lambda item: (0 if item.priority == "must" else 1, -item.weight, KIND_ORDER[EvidenceKind(item.kind)]),
    )
    shown = ordered[: C.TOP_EVIDENCE_LIMIT]
    return [evidence_item(item) for item in shown], max(0, len(ordered) - len(shown))


def project_employer(
    expl: MatchExplanation, *, position: int | None, in_snapshot: bool
) -> MatchExplanationEmployerView:
    """Проекция работодателя (Арх. 6.10): позиция, полоса, доводы, риск, требования, вклады.

    Вызывается после `apply_read_rules`. Минимума зарплаты, чужих баллов и сравнений в модели нет.
    """
    return MatchExplanationEmployerView(
        fit_band=expl.fit_band,
        relation=expl.relation,
        position=position,
        in_snapshot=in_snapshot,
        coverage=CoverageView(
            pct=expl.coverage.pct,
            must_total=expl.coverage.must_total,
            must_covered=expl.coverage.must_covered,
            must_confirmed=expl.coverage.must_confirmed,
            nice_total=expl.coverage.nice_total,
            nice_covered=expl.coverage.nice_covered,
        ),
        reasons=[
            ReasonView(
                code=reason.code,
                text=reason.text,
                evidence=EvidenceRefView(type=reason.evidence_ref.type, id=reason.evidence_ref.id),
            )
            for reason in expl.reasons
        ],
        risk=RiskView(code=expl.risk.code, text=expl.risk.text) if expl.risk else None,
        formats_common=[WorkFormat(item) for item in expl.formats_common],
        requirements=[evidence_item(item) for item in expl.requirements],
        contributions=list(expl.contributions),
        scorer_version=expl.scorer_version,
    )


def project_why(expl: MatchExplanation, target: CategoryRef, employer_saw: Sequence[str]) -> InvitationWhy:
    """«Почему вас пригласили» по потребности — проекция кандидата (Арх. 4.9).

    `matched` — только подкреплённые требования: обязательные, затем желательные; внутри — `test`, `pulse`,
    `fsp`, `declared`. Требования с `kind = none`, доводы, риск, вклады и позиция в проекцию не попадают.
    """
    matched = sorted(
        (item for item in expl.requirements if item.kind != EvidenceKind.NONE),
        key=lambda item: (0 if item.priority == "must" else 1, KIND_ORDER[EvidenceKind(item.kind)], item.skill_title),
    )
    unconfirmed = next(
        (item for item in expl.requirements if item.priority == "must" and item.kind == EvidenceKind.DECLARED), None
    )
    return InvitationWhy(
        source="need",
        target=target,
        matched=[evidence_item(item, own=True) for item in matched],
        unconfirmed=UnconfirmedSkill(skill=Ref(code=unconfirmed.skill_code, title=unconfirmed.skill_title))
        if unconfirmed
        else None,
        interest=None,
        employer_saw=list(employer_saw),
    )


def project_why_bank(
    evidence: Mapping[str, SkillEvidence],
    target: CategoryRef,
    employer_saw: Sequence[str],
    title: Callable[[str], str],
) -> InvitationWhy:
    """«Почему вас пригласили» из банка: до шести сильнейших подтверждённых навыков (Арх. 4.9; 15.1, № 18)."""
    confirmed = [item for item in sorted_skills(evidence, title) if item.kind in CONFIRMED_KINDS]
    return InvitationWhy(
        source="bank",
        target=target,
        matched=[skill_item(item, title(item.skill_code), own=True) for item in confirmed[: C.WHY_BANK_SKILLS_LIMIT]],
        unconfirmed=None,
        interest=None,
        employer_saw=list(employer_saw),
    )


# --------------------------------------------------------------------------------------------------------------------
# Тексты версии: отличия запросов и подсказки
# --------------------------------------------------------------------------------------------------------------------


def _thousands(value: int | None) -> str:
    return "—" if value is None else f"{value // 1000}"


def query_changes_text(
    old: ShortlistQuery,
    new: ShortlistQuery,
    *,
    skill_title: Callable[[str], str],
    grade_title: Callable[[str], str],
    old_grades: Sequence[str],
    new_grades: Sequence[str],
) -> str:
    """Отличия запроса от родительского словами, фрагменты через «; » (Арх. 6.11).

    Примеры: «Kafka → желательные; формат: + удалённо». Запросы равны — «состав обновлён» (изменились данные
    кандидатов).
    """
    parts: list[str] = []
    old_must, new_must = set(old.must_skills), set(new.must_skills)
    old_nice, new_nice = set(old.nice_skills), set(new.nice_skills)
    for skill in sorted(new_must | new_nice | old_must | old_nice, key=lambda code: skill_title(code).lower()):
        name = skill_title(skill)
        if skill in old_must and skill in new_nice:
            parts.append(f"{name} → желательные")
        elif skill in old_nice and skill in new_must:
            parts.append(f"{name} → обязательные")
        elif skill in new_must and skill not in old_must:
            parts.append(f"+ обязательный: {name}")
        elif skill in old_must and skill not in new_must:
            parts.append(f"− обязательный: {name}")
        elif skill in new_nice and skill not in old_nice:
            parts.append(f"+ желательный: {name}")
        elif skill in old_nice and skill not in new_nice:
            parts.append(f"− желательный: {name}")
    for grade in new_grades:
        if grade not in old_grades:
            parts.append(f"+ грейд: {grade_title(grade)}")
    for grade in old_grades:
        if grade not in new_grades:
            parts.append(f"− грейд: {grade_title(grade)}")
    old_formats = {str(item) for item in old.work_formats}
    new_formats = {str(item) for item in new.work_formats}
    format_parts = [f"+ {FORMAT_LABELS.get(item, item)}" for item in sorted(new_formats - old_formats)]
    format_parts += [f"− {FORMAT_LABELS.get(item, item)}" for item in sorted(old_formats - new_formats)]
    if format_parts:
        parts.append("формат: " + ", ".join(format_parts))
    if (old.salary_from, old.salary_to) != (new.salary_from, new.salary_to):
        parts.append(
            f"вилка: {_thousands(old.salary_from)}–{_thousands(old.salary_to)} → "
            f"{_thousands(new.salary_from)}–{_thousands(new.salary_to)}{NBSP}тыс.{NBSP}₽"
        )
    if old.require_fsp != new.require_fsp:
        parts.append("только с ФСП: " + ("включено" if new.require_fsp else "выключено"))
    return "; ".join(parts) if parts else "состав обновлён"


def hint_text(code: str, value: str | None, gain: int, *, skill_title: Callable[[str], str]) -> str:
    """Готовый текст подсказки (Арх. 6.12): действие и прирост числа кандидатов."""
    candidates = count_phrase(gain, "кандидат", "кандидата", "кандидатов")
    if code == "move_must_to_nice":
        closes = "закрывает" if gain % 10 == 1 and gain % 100 != 11 else "закрывают"
        return (
            f"Возможно, стоит перенести {skill_title(value or '')} в желательные: "
            f"+{candidates} {closes} все обязательные"
        )
    if code == "add_format":
        return f"Добавьте формат «{FORMAT_LABELS.get(value or '', value or '')}»: +{candidates}"
    return f"Снимите условие «только с достижениями ФСП»: +{candidates}"


def as_datetime(value: date) -> datetime:
    """Дата → момент начала суток UTC (для полей `confirmed_at` из источников, которые отдают дату)."""
    return datetime(value.year, value.month, value.day, tzinfo=UTC)
