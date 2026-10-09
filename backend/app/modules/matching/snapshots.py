"""Версии подборки: создание, чтение с живыми полями, сравнение, закрепление, подсказки (Арх. 6.11, 6.12).

Строки `shortlist_snapshot` и `shortlist_item` после вставки не обновляются. Всё, что зависит от текущего
состояния кандидата (видимость, имя, закрепление, скрытое заявленное, сведения ФСП), накладывается при чтении
(`live.py`). Состояние пары (приглашение, блокировка) в ответ версии не входит: подбор о приглашениях не знает.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import not_found
from app.modules.matching import constants as C
from app.modules.matching import exposure, needs, support
from app.modules.matching.dto import RelaxationHint, ShortlistItemView, ShortlistQuery, ShortlistRefinement
from app.modules.matching.evidence import Pool, load_pool
from app.modules.matching.explain import (
    RELATION_LABELS,
    ExplainContext,
    MatchExplanation,
    build_explanation,
    hint_text,
    query_changes_text,
    reason_text,
    top_evidence,
)
from app.modules.matching.features import CandidateFeatures
from app.modules.matching.live import Live, load_live, read_explanation
from app.modules.matching.models import Need, NeedPin, ShortlistItem, ShortlistSnapshot
from app.modules.matching.ranking import (
    Counterfactual,
    DiffInput,
    RankedItem,
    Scored,
    band_key,
    counterfactuals,
    diff_snapshots,
    rank_need,
)
from app.modules.matching.schemas import (
    DiffCounts,
    DiffRow,
    DroppedItem,
    ShortlistSnapshotView,
    ShortlistVersionBrief,
    SnapshotCategory,
    SnapshotDiffView,
    SnapshotFunnel,
)
from app.modules.matching.scoring import first_failed_filter, sections_for, shortlist_seed
from app.shared.enums import DiffMark, ExposureSource, FitBand, NeedStatus, Relation, TestOutcome, WorkFormat

ALL_HINT_KINDS: tuple[str, ...] = ("move_must_to_nice", "add_format", "drop_require_fsp")


# --------------------------------------------------------------------------------------------------------------------
# Общие помощники
# --------------------------------------------------------------------------------------------------------------------


def explain_context(pool: Pool, candidate_id: UUID) -> ExplainContext:
    return ExplainContext(
        scorer_version=pool.scorer_version(),
        skill_title=support.skill_title,
        grade_title=support.grade_title,
        fsp_line=pool.fsp_line(candidate_id),
        fsp_fact_id=pool.fsp_fact_id(candidate_id),
    )


def explain(pool: Pool, query: ShortlistQuery, scored: Scored) -> MatchExplanation:
    """Объяснение для кандидата пула (Арх. 6.10)."""
    features = scored.features
    return build_explanation(features, query, scored, explain_context(pool, features.candidate_id))


def to_hints(found: Sequence[Counterfactual], query: ShortlistQuery) -> list[RelaxationHint]:
    """Контрфакты → подсказки с готовым уточнением для кнопки «Применить» (Арх. 6.12)."""
    hints: list[RelaxationHint] = []
    for item in found:
        if item.code == "move_must_to_nice":
            refinement = ShortlistRefinement(
                must_skills=list(item.query.must_skills), nice_skills=list(item.query.nice_skills)
            )
        elif item.code == "add_format":
            refinement = ShortlistRefinement(work_formats=list(item.query.work_formats))
        else:
            refinement = ShortlistRefinement(require_fsp=False)
        hints.append(
            RelaxationHint(
                code=item.code,
                value=item.value,
                text=hint_text(item.code, item.value, item.gain, skill_title=support.skill_title),
                gain=item.gain,
                refinement=refinement,
            )
        )
    return hints


def hints_for(
    query: ShortlistQuery, pool: Sequence[CandidateFeatures], kinds: Collection[str], grades: Sequence[str]
) -> list[RelaxationHint]:
    found = counterfactuals(
        query,
        pool,
        kinds,
        grades=grades,
        closure=support.closure,
        all_formats=[item.value for item in WorkFormat],
    )
    return to_hints(found, query)


def get_owned_snapshot(db: Session, employer_id: UUID, snapshot_id: UUID) -> ShortlistSnapshot:
    snapshot = db.get(ShortlistSnapshot, snapshot_id)
    if snapshot is None or snapshot.employer_id != employer_id:
        raise not_found()
    return snapshot


def _items(db: Session, snapshot_id: UUID) -> list[ShortlistItem]:
    return list(
        db.scalars(
            select(ShortlistItem).where(ShortlistItem.snapshot_id == snapshot_id).order_by(ShortlistItem.position)
        )
    )


def _must_missing(item: ShortlistItem) -> int:
    """Обязательных навыков без доказательств в сохранённой строке: счётчики лежат в `explanation.coverage`."""
    cov = item.explanation.get("coverage") or {}
    return max(0, int(cov.get("must_total", 0)) - int(cov.get("must_covered", 0)))


def _diff_input(item: ShortlistItem) -> DiffInput:
    band = band_key(
        Relation(item.relation),
        _must_missing(item),
        item.confirmed_band or 0,
        item.strength_band,
        item.coverage_band or 0,
    )
    return DiffInput(candidate_id=item.candidate_id, position=item.position, band=band)


def _grade_of(item: ShortlistItem) -> str:
    return str(item.explanation["level"]["grade_code"])


# --------------------------------------------------------------------------------------------------------------------
# Создание версии
# --------------------------------------------------------------------------------------------------------------------


def _dropped_rows(
    db: Session,
    employer_id: UUID,
    now: datetime,
    query: ShortlistQuery,
    sections: Mapping[str, Relation],
    parent_items: Mapping[UUID, ShortlistItem],
    dropped: Sequence[UUID],
    rejected: Mapping[UUID, str],
) -> list[dict[str, Any]]:
    """Выпавшие относительно родителя с причиной `first_failed_filter` на момент создания новой версии."""
    missing = [cid for cid in dropped if cid not in rejected]
    extra = load_pool(db, employer_id, now, candidate_ids=missing) if missing else None
    rows: list[dict[str, Any]] = []
    for cid in dropped:
        code = rejected.get(cid)
        if code is None:
            features = extra.features.get(cid) if extra else None
            code = first_failed_filter(features, query, sections) or "unavailable"
        grade = _grade_of(parent_items[cid])
        relation = sections.get(grade)
        limit = C.SECTION_LIMITS.get(relation.value) if relation else None
        rows.append(
            {
                "candidate_id": str(cid),
                "category_code": support.category_code(query.specialization_code, grade),
                "reason_code": code,
                "reason_text": reason_text(code, limit=limit),
            }
        )
    return rows


def create(
    db: Session,
    employer_id: UUID,
    need_id: UUID,
    now: datetime,
    *,
    parent_id: UUID | None = None,
    refinement: ShortlistRefinement | None = None,
) -> tuple[ShortlistSnapshot, bool]:
    """Создать версию подборки (Арх. 6.11, шаги 1–7). Возвращает версию и признак «создана сейчас»
    (`False` — повтор того же запроса в пределах `SNAPSHOT_DEDUP_MINUTES`: возвращена последняя версия).
    """
    # Блокировка строки потребности: номера версий и `latest_snapshot_id` меняются последовательно.
    need = needs.get_owned(db, employer_id, need_id, lock=True)
    if need.status == NeedStatus.ARCHIVED:
        raise support.api_error(409, "need_archived")
    parent: ShortlistSnapshot | None = None
    if parent_id is not None:
        parent = db.get(ShortlistSnapshot, parent_id)
        if parent is None or parent.need_id != need.id:
            raise support.api_error(409, "parent_mismatch")
    if refinement is not None:
        if parent is None:
            # Уточняется конкретная версия: без `parent_id` непонятно, какую из них меняет работодатель.
            raise support.api_error(422, "parent_required")
        query = needs.refine(ShortlistQuery.model_validate(parent.query), refinement, need)
    else:
        query = needs.query_from_need(need)
    needs.validate_query(query)

    grades = support.grade_codes()
    sections = sections_for(query, grades)
    if sections:
        pool = load_pool(
            db, employer_id, now, specialization_code=query.specialization_code, grade_codes=list(sections)
        )
    else:
        pool = Pool(as_of=now, today=clock.to_local_date(now))
    scorer_version = pool.scorer_version()
    qhash = needs.query_hash(query)

    latest = db.scalar(
        select(ShortlistSnapshot)
        .where(ShortlistSnapshot.need_id == need.id)
        .order_by(ShortlistSnapshot.version_no.desc())
        .limit(1)
    )
    if (
        latest is not None
        and latest.query_hash == qhash
        and latest.scorer_version == scorer_version
        and now - latest.created_at < timedelta(minutes=C.SNAPSHOT_DEDUP_MINUTES)
    ):
        return latest, False

    # Демо-аккаунты общие для всех посетителей стенда: лимит версий к ним не применяется (R3-tz-compliance-1).
    if not support.is_demo_account(db, employer_id):
        recent = db.scalar(
            select(func.count())
            .select_from(ShortlistSnapshot)
            .where(
                ShortlistSnapshot.employer_id == employer_id,
                ShortlistSnapshot.created_at > now - timedelta(hours=1),
            )
        )
        if int(recent or 0) >= C.SNAPSHOT_RATE_PER_HOUR:
            raise support.api_error(429, "shortlist_rate_limited", params={"retry_after": 3600})

    seed = shortlist_seed(employer_id, need.id)
    visible = pool.visible()
    ranked = rank_need(query, visible, seed, grades=grades, closure=support.closure)

    parent_items = {item.candidate_id: item for item in _items(db, parent.id)} if parent else {}
    diff = None
    dropped_rows: list[dict[str, Any]] = []
    query_changes: str | None = None
    if parent is not None:
        diff = diff_snapshots(
            [_diff_input(item) for item in parent_items.values()],
            [
                DiffInput(
                    row.candidate_id,
                    row.position,
                    band_key(
                        row.scored.relation,
                        row.scored.coverage.must_total - row.scored.coverage.must_covered,
                        row.scored.coverage.confirmed_band,
                        row.scored.strength.band,
                        row.scored.coverage.band,
                    ),
                )
                for row in ranked.items
            ],
        )
        dropped_rows = _dropped_rows(db, employer_id, now, query, sections, parent_items, diff.dropped, ranked.rejected)
        parent_query = ShortlistQuery.model_validate(parent.query)
        query_changes = query_changes_text(
            parent_query,
            query,
            skill_title=support.skill_title,
            grade_title=support.grade_title,
            old_grades=list(sections_for(parent_query, grades)),
            new_grades=list(sections),
        )

    hints: list[RelaxationHint] = []
    if ranked.shown < C.HINT_MIN_ITEMS or ranked.must_ok < C.HINT_MIN_ITEMS:
        hints = hints_for(query, visible, ALL_HINT_KINDS, grades)

    snapshot = ShortlistSnapshot(
        id=uuid4(),
        need_id=need.id,
        employer_id=employer_id,
        version_no=(latest.version_no if latest else 0) + 1,
        parent_id=parent.id if parent else None,
        query=query.model_dump(mode="json"),
        query_hash=qhash,
        query_changes=query_changes,
        scorer_version=scorer_version,
        as_of=now,
        seed=seed,
        categories=[
            {
                "category_code": support.category_code(query.specialization_code, grade),
                "relation": relation.value,
                "count": ranked.section_counts.get(relation, 0),
            }
            for grade, relation in sections.items()
        ],
        funnel={
            "category_total": sum(1 for level in pool.levels.values() if level.grade_code == query.grade_code),
            "available": ranked.available,
            "format_ok": ranked.format_ok,
            "must_ok": ranked.must_ok,
            "shown": ranked.shown,
        },
        diff=(
            {
                "added": diff.added,
                "dropped": diff.dropped_count,
                "moved_up": diff.moved_up,
                "moved_down": diff.moved_down,
            }
            if diff
            else None
        ),
        dropped=dropped_rows,
        hints=[hint.model_dump(mode="json") for hint in hints],
        created_at=now,
    )
    db.add(snapshot)
    db.flush()
    if ranked.items:
        rows = [_item_row(snapshot.id, row, pool, query, diff) for row in ranked.items]
        db.execute(insert(ShortlistItem).values(rows))
    exposure.record_shown(
        db, employer_id, [row.candidate_id for row in ranked.items], pool.today, ExposureSource.SHORTLIST
    )
    need.latest_snapshot_id = snapshot.id
    db.flush()
    return snapshot, True


def _item_row(snapshot_id: UUID, row: RankedItem, pool: Pool, query: ShortlistQuery, diff: Any) -> dict[str, Any]:
    scored = row.scored
    has_requirements = scored.coverage.has_requirements
    entry = diff.entries.get(row.candidate_id) if diff else None
    return {
        "snapshot_id": snapshot_id,
        "candidate_id": row.candidate_id,
        "position": row.position,
        "relation": scored.relation.value,
        "coverage_pct": scored.coverage.pct,
        "coverage_band": scored.coverage.band if has_requirements else None,
        "confirmed_band": scored.coverage.confirmed_band if has_requirements else None,
        "strength": Decimal(scored.strength.x10) / 10,
        "strength_band": scored.strength.band,
        "fit_band": scored.fit_band.value if scored.fit_band else None,
        "diff_mark": (entry.mark if entry else DiffMark.SAME).value,
        "diff_delta": entry.delta if entry else None,
        "explanation": explain(pool, query, scored).model_dump(mode="json"),
    }


# --------------------------------------------------------------------------------------------------------------------
# Чтение версии
# --------------------------------------------------------------------------------------------------------------------


def item_view(
    db: Session,
    live: Live,
    specialization_code: str,
    item: ShortlistItem,
    *,
    pinned: bool,
    today: Any,
    outside: bool = False,
) -> ShortlistItemView:
    """Строка версии: сохранённые позиция, полосы и объяснение + живые поля (Арх. 6.11)."""
    cid = item.candidate_id
    expl = read_explanation(db, live, cid, item.explanation)
    evidence, more = top_evidence(expl.requirements)
    person = live.profiles[cid]
    return ShortlistItemView(
        candidate_id=cid,
        public_code=person.public_code,
        display_name=live.display_name(cid),
        is_demo=person.is_demo,
        category=support.category_ref(specialization_code, expl.level.grade_code),
        relation=Relation(item.relation),
        grade_margin=expl.level.verdict == TestOutcome.CONFIRMED_WITH_MARGIN,
        position=item.position,
        fit_band=FitBand(item.fit_band) if item.fit_band else None,
        strength_label=expl.strength.label,
        must_covered=expl.coverage.must_covered,
        must_total=expl.coverage.must_total,
        top_evidence=evidence,
        evidence_more=more,
        fsp_summary=live.fsp_short(cid),
        formats_common=[WorkFormat(value) for value in expl.formats_common],
        freshness_days=max(0, (today - expl.level.last_evidence_at).days),
        stale=expl.level.stale,
        risk=expl.risk.text if expl.risk else None,
        diff_mark=DiffMark.SAME if outside else DiffMark(item.diff_mark),
        diff_delta=None if outside else item.diff_delta,
        pinned=pinned,
        available=live.available(cid),
        unavailable_reason=live.unavailable_reason(cid),
    )


def _latest_rows(db: Session, need_id: UUID, candidate_ids: Collection[UUID]) -> dict[UUID, ShortlistItem]:
    """Строка кандидата из самой поздней версии потребности, где он был."""
    if not candidate_ids:
        return {}
    rows = db.execute(
        select(ShortlistItem)
        .join(ShortlistSnapshot, ShortlistSnapshot.id == ShortlistItem.snapshot_id)
        .where(ShortlistSnapshot.need_id == need_id, ShortlistItem.candidate_id.in_(list(candidate_ids)))
        .order_by(ShortlistSnapshot.version_no.desc())
    ).scalars()
    found: dict[UUID, ShortlistItem] = {}
    for row in rows:
        found.setdefault(row.candidate_id, row)
    return found


def pinned_ids(db: Session, need_id: UUID) -> list[UUID]:
    return list(db.scalars(select(NeedPin.candidate_id).where(NeedPin.need_id == need_id).order_by(NeedPin.pinned_at)))


def _dropped_view(live: Live, specialization_code: str, rows: Sequence[Mapping[str, Any]]) -> list[DroppedItem]:
    result: list[DroppedItem] = []
    for row in rows:
        cid = UUID(str(row["candidate_id"]))
        if not live.shown(cid):
            continue
        grade = str(row["category_code"]).split(":", 1)[-1]
        result.append(
            DroppedItem(
                candidate_id=cid,
                public_code=live.profiles[cid].public_code,
                category=support.category_ref(specialization_code, grade),
                reason_code=str(row["reason_code"]),
                reason_text=str(row["reason_text"]),
            )
        )
    return result


def view(db: Session, employer_id: UUID, snapshot_id: UUID, now: datetime) -> ShortlistSnapshotView:
    """Версия подборки глазами работодателя на момент чтения (Арх. 6.11, «Чтение версии»)."""
    snapshot = get_owned_snapshot(db, employer_id, snapshot_id)
    need = db.get(Need, snapshot.need_id)
    query = ShortlistQuery.model_validate(snapshot.query)
    spec = query.specialization_code
    items = _items(db, snapshot.id)
    in_version = {item.candidate_id for item in items}
    pins = pinned_ids(db, snapshot.need_id)
    outside = _latest_rows(db, snapshot.need_id, [cid for cid in pins if cid not in in_version])
    dropped_ids = [UUID(str(row["candidate_id"])) for row in snapshot.dropped]
    live = load_live(db, employer_id, dict.fromkeys([*in_version, *outside, *dropped_ids], spec), now)
    today = clock.to_local_date(now)
    pin_set = set(pins)

    rows = [
        item_view(db, live, spec, item, pinned=item.candidate_id in pin_set, today=today)
        for item in items
        if live.shown(item.candidate_id)
    ]
    outside_rows = [
        item_view(db, live, spec, outside[cid], pinned=True, today=today, outside=True)
        for cid in pins
        if cid in outside and live.shown(cid)
    ]
    hidden = {cid for cid in [*in_version, *outside] if not live.shown(cid)}
    return ShortlistSnapshotView(
        id=snapshot.id,
        need_id=snapshot.need_id,
        version_no=snapshot.version_no,
        parent_id=snapshot.parent_id,
        is_latest=bool(need and need.latest_snapshot_id == snapshot.id),
        created_at=snapshot.created_at,
        scorer_version=snapshot.scorer_version,
        query=query,
        query_changes=snapshot.query_changes,
        categories=[
            SnapshotCategory(
                category=support.category_ref(*str(row["category_code"]).split(":", 1)),
                relation=Relation(row["relation"]),
                relation_label=RELATION_LABELS[Relation(row["relation"])],
                count=int(row["count"]),
            )
            for row in snapshot.categories
        ],
        funnel=SnapshotFunnel.model_validate(snapshot.funnel),
        items=rows,
        pinned_outside=outside_rows,
        hidden_count=len(hidden),
        diff=DiffCounts.model_validate(snapshot.diff) if snapshot.diff else None,
        dropped=_dropped_view(live, spec, snapshot.dropped),
        hints=[RelaxationHint.model_validate(row) for row in snapshot.hints],
    )


def versions(db: Session, employer_id: UUID, need_id: UUID) -> list[ShortlistVersionBrief]:
    """Версии потребности без строк, новые раньше — для переключателя версий."""
    need = needs.get_owned(db, employer_id, need_id)
    rows = db.execute(
        select(ShortlistSnapshot, func.count(ShortlistItem.candidate_id))
        .outerjoin(ShortlistItem, ShortlistItem.snapshot_id == ShortlistSnapshot.id)
        .where(ShortlistSnapshot.need_id == need.id)
        .group_by(ShortlistSnapshot.id)
        .order_by(ShortlistSnapshot.version_no.desc())
    ).all()
    return [
        ShortlistVersionBrief(
            id=snapshot.id,
            version_no=snapshot.version_no,
            created_at=snapshot.created_at,
            items_count=int(count),
            query_changes=snapshot.query_changes,
            is_latest=need.latest_snapshot_id == snapshot.id,
        )
        for snapshot, count in rows
    ]


# --------------------------------------------------------------------------------------------------------------------
# Сравнение версий
# --------------------------------------------------------------------------------------------------------------------


def diff_view(db: Session, employer_id: UUID, snapshot_id: UUID, base_id: UUID, now: datetime) -> SnapshotDiffView:
    """Сравнение двух версий одной потребности. Строк скрытых сейчас кандидатов в списках нет: счётчики
    остаются числами без идентификаторов (Арх. 6.11).
    """
    snapshot = get_owned_snapshot(db, employer_id, snapshot_id)
    base = get_owned_snapshot(db, employer_id, base_id)
    if snapshot.need_id != base.need_id:
        raise support.api_error(409, "different_need")
    query = ShortlistQuery.model_validate(snapshot.query)
    base_query = ShortlistQuery.model_validate(base.query)
    spec = query.specialization_code
    new_items = {item.candidate_id: item for item in _items(db, snapshot.id)}
    base_items = {item.candidate_id: item for item in _items(db, base.id)}
    diff = diff_snapshots(
        [_diff_input(item) for item in base_items.values()], [_diff_input(item) for item in new_items.values()]
    )
    live = load_live(db, employer_id, dict.fromkeys([*new_items, *base_items], spec), now)
    # Причина выпадения известна, только если база — родитель сравниваемой версии: она сохранена при создании.
    stored = {UUID(str(row["candidate_id"])): row for row in snapshot.dropped} if snapshot.parent_id == base.id else {}

    def row_of(cid: UUID, mark: DiffMark, delta: int | None, **extra: Any) -> DiffRow:
        source = new_items.get(cid) or base_items[cid]
        return DiffRow(
            candidate_id=cid,
            public_code=live.profiles[cid].public_code,
            category=support.category_ref(spec, _grade_of(source)),
            diff_mark=mark,
            diff_delta=delta,
            position=new_items[cid].position if cid in new_items else None,
            base_position=base_items[cid].position if cid in base_items else None,
            **extra,
        )

    added: list[DiffRow] = []
    moved: list[DiffRow] = []
    for entry in sorted(diff.entries.values(), key=lambda item: item.position):
        if not live.shown(entry.candidate_id):
            continue
        if entry.mark == DiffMark.NEW:
            added.append(row_of(entry.candidate_id, DiffMark.NEW, None))
        elif entry.mark in (DiffMark.UP, DiffMark.DOWN):
            moved.append(row_of(entry.candidate_id, entry.mark, entry.delta))
    dropped: list[DiffRow] = []
    for cid in diff.dropped:
        if not live.shown(cid):
            continue
        saved = stored.get(cid)
        code = str(saved["reason_code"]) if saved else "other_version"
        text = str(saved["reason_text"]) if saved else reason_text("other_version")
        dropped.append(row_of(cid, DiffMark.SAME, None, reason_code=code, reason_text=text))
    grades = support.grade_codes()
    return SnapshotDiffView(
        snapshot_id=snapshot.id,
        base_id=base.id,
        diff=DiffCounts(
            added=diff.added, dropped=diff.dropped_count, moved_up=diff.moved_up, moved_down=diff.moved_down
        ),
        query_changes=query_changes_text(
            base_query,
            query,
            skill_title=support.skill_title,
            grade_title=support.grade_title,
            old_grades=list(sections_for(base_query, grades)),
            new_grades=list(sections_for(query, grades)),
        ),
        added=added,
        dropped=dropped,
        moved=moved,
        hidden_count=len({cid for cid in [*new_items, *base_items] if not live.shown(cid)}),
    )


# --------------------------------------------------------------------------------------------------------------------
# Закрепление
# --------------------------------------------------------------------------------------------------------------------


def pin(db: Session, employer_id: UUID, need_id: UUID, candidate_id: UUID, now: datetime) -> None:
    """Закрепить кандидата за потребностью: идемпотентно; на порядок не влияет (Арх. 6.11)."""
    need = needs.get_owned(db, employer_id, need_id, lock=True)
    row = _latest_rows(db, need.id, [candidate_id]).get(candidate_id)
    live = load_live(db, employer_id, {candidate_id: need.specialization_code}, now) if row else None
    # Скрытый сейчас кандидат нераскрытой пары неотличим от того, кого в подборках не было.
    if row is None or live is None or not live.shown(candidate_id):
        raise support.api_error(404, "candidate_not_in_need")
    if db.get(NeedPin, (need.id, candidate_id)) is not None:
        return
    count = db.scalar(select(func.count()).select_from(NeedPin).where(NeedPin.need_id == need.id))
    if int(count or 0) >= C.PIN_LIMIT:
        raise support.api_error(409, "pin_limit", params={"limit": C.PIN_LIMIT})
    db.add(NeedPin(need_id=need.id, candidate_id=candidate_id, snapshot_id=row.snapshot_id, pinned_at=now))
    db.flush()


def unpin(db: Session, employer_id: UUID, need_id: UUID, candidate_id: UUID) -> None:
    need = needs.get_owned(db, employer_id, need_id)
    row = db.get(NeedPin, (need.id, candidate_id))
    if row is not None:
        db.delete(row)
        db.flush()


# --------------------------------------------------------------------------------------------------------------------
# Подсказки для сводки причин
# --------------------------------------------------------------------------------------------------------------------


def current_query(db: Session, need: Need) -> ShortlistQuery:
    """Запрос последней версии потребности; версий нет — запрос из её полей."""
    if need.latest_snapshot_id:
        latest = db.get(ShortlistSnapshot, need.latest_snapshot_id)
        if latest is not None:
            return ShortlistQuery.model_validate(latest.query)
    return needs.query_from_need(need)


def relaxation_hints(
    db: Session, employer_id: UUID, need_id: UUID, kinds: Collection[str], now: datetime
) -> list[RelaxationHint]:
    """Подсказки заданных видов для запроса последней версии (Арх. 6.12): только `gain ≥ HINT_MIN_GAIN`,
    не больше трёх. Подсказок по вилке нет никогда.
    """
    need = needs.get_owned(db, employer_id, need_id)
    query = current_query(db, need)
    grades = support.grade_codes()
    sections = sections_for(query, grades)
    if not sections:
        return []
    pool = load_pool(db, employer_id, now, specialization_code=query.specialization_code, grade_codes=list(sections))
    return hints_for(query, pool.visible(), [kind for kind in kinds if kind in ALL_HINT_KINDS], grades)
