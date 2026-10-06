"""Учёт показов (Арх. 6.13).

`exposure_event(employer_id, candidate_id, day, source, opened)`: при создании версии — позиции
1..`EXPOSURE_TOP_K`; при выдаче первой страницы банка — первые `EXPOSURE_TOP_K` строк; открытие карточки ставит
`opened = true`. Один работодатель даёт кандидату не больше одного показа в день. Показы считаются до
сегодняшнего дня, поэтому в течение дня порядок выдачи не меняется.

Учёт показов — честный порядок среди равных, а не перераспределение спроса: его эффект мал (Арх. 6.7).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Sequence
from datetime import date, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core import clock
from app.modules.matching import constants as C
from app.modules.matching.dto import ExposureStats
from app.modules.matching.models import ExposureEvent, Need, ShortlistItem, ShortlistSnapshot
from app.shared.enums import EvidenceKind, ExposureSource


def record_shown(
    db: Session, employer_id: UUID, candidate_ids: Sequence[UUID], day: date, source: ExposureSource
) -> None:
    """Отметить показ первых строк выдачи: `INSERT … ON CONFLICT DO NOTHING` (не больше показа в день на пару)."""
    rows = [
        {"employer_id": employer_id, "candidate_id": cid, "day": day, "source": source.value, "opened": False}
        for cid in candidate_ids[: C.EXPOSURE_TOP_K]
    ]
    if rows:
        db.execute(insert(ExposureEvent).values(rows).on_conflict_do_nothing())


def record_opened(db: Session, employer_id: UUID, candidate_id: UUID, day: date, source: ExposureSource) -> None:
    """Отметить открытие карточки: строка создаётся, если её не было, `opened` становится истинным."""
    statement = insert(ExposureEvent).values(
        employer_id=employer_id, candidate_id=candidate_id, day=day, source=source.value, opened=True
    )
    db.execute(
        statement.on_conflict_do_update(
            index_elements=[ExposureEvent.employer_id, ExposureEvent.candidate_id, ExposureEvent.day],
            set_={"opened": True},
        )
    )


def opened_count(db: Session, employer_id: UUID, day: date) -> int:
    """Сколько карточек работодатель открыл за день — для лимита `CARD_OPEN_LIMIT_PER_DAY`."""
    return int(
        db.scalar(
            select(func.count())
            .select_from(ExposureEvent)
            .where(ExposureEvent.employer_id == employer_id, ExposureEvent.day == day, ExposureEvent.opened.is_(True))
        )
        or 0
    )


def is_opened(db: Session, employer_id: UUID, candidate_id: UUID, day: date) -> bool:
    """Открывал ли работодатель карточку этого кандидата сегодня (повторное открытие лимит не расходует)."""
    return bool(
        db.scalar(
            select(ExposureEvent.opened).where(
                ExposureEvent.employer_id == employer_id,
                ExposureEvent.candidate_id == candidate_id,
                ExposureEvent.day == day,
            )
        )
    )


def exposure_7d(db: Session, candidate_ids: Collection[UUID], today: date) -> dict[UUID, int]:
    """Число показов каждого кандидата за `EXPOSURE_WINDOW_DAYS` дней до сегодняшнего — одним запросом на пул."""
    if not candidate_ids:
        return {}
    rows = db.execute(
        select(ExposureEvent.candidate_id, func.count())
        .where(
            ExposureEvent.candidate_id.in_(list(candidate_ids)),
            ExposureEvent.day >= today - timedelta(days=C.EXPOSURE_WINDOW_DAYS),
            ExposureEvent.day < today,
        )
        .group_by(ExposureEvent.candidate_id)
    ).all()
    return {candidate_id: int(count) for candidate_id, count in rows}


def stats(db: Session, candidate_id: UUID, since: datetime, now: datetime) -> ExposureStats:
    """Показы кандидата для воронки (Арх. 4.12, 6.13).

    `needs_shown` — число потребностей, в версиях которых кандидат был с даты `since`; `employers_opened` —
    число работодателей, открывших карточку; `unconfirmed_must` — обязательные навыки, которые в этих
    потребностях были у кандидата `declared` или `none`. Названий компаний и потребностей в ответе нет.
    """
    rows = db.execute(
        select(ShortlistSnapshot.need_id, ShortlistSnapshot.created_at, ShortlistItem.explanation)
        .join(ShortlistItem, ShortlistItem.snapshot_id == ShortlistSnapshot.id)
        .join(Need, Need.id == ShortlistSnapshot.need_id)
        .where(
            ShortlistItem.candidate_id == candidate_id,
            ShortlistSnapshot.created_at >= since,
            ShortlistSnapshot.created_at <= now,
        )
        .order_by(ShortlistSnapshot.created_at)
    ).all()
    # По каждой потребности учитывается последняя версия с кандидатом: навык считается один раз на потребность.
    latest: dict[UUID, dict[str, object]] = {}
    for need_id, _, explanation in rows:
        latest[need_id] = explanation
    counter: Counter[str] = Counter()
    for explanation in latest.values():
        requirements = explanation.get("requirements") if isinstance(explanation, dict) else None
        for item in requirements if isinstance(requirements, list) else []:
            if item.get("priority") == "must" and item.get("kind") in (EvidenceKind.DECLARED, EvidenceKind.NONE):
                counter[str(item.get("skill_code"))] += 1
    unconfirmed: list[str] = []
    for skill, count in sorted(counter.items(), key=lambda pair: (-pair[1], pair[0])):
        unconfirmed.extend([skill] * count)

    since_day = clock.to_local_date(since)
    employers_opened = int(
        db.scalar(
            select(func.count(func.distinct(ExposureEvent.employer_id))).where(
                ExposureEvent.candidate_id == candidate_id,
                ExposureEvent.day >= since_day,
                ExposureEvent.opened.is_(True),
            )
        )
        or 0
    )
    return ExposureStats(needs_shown=len(latest), employers_opened=employers_opened, unconfirmed_must=unconfirmed)
