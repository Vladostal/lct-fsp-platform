"""Экран кандидата C13: состояние привязки, свои достижения, календарь ближайших соревнований (Арх. 7.4, 7.8, 7.9).

Кандидат видит всё, что о нём хранится: каждую запись, источник, дату получения, версию согласия (право на доступ
к своим данным). Календарь не требует привязки и берёт данные из кэша `fsp_cache` на 6 часов.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.fsp import constants as c
from app.modules.fsp import signal as sig
from app.modules.fsp import sync, views
from app.modules.fsp.dto import FspPublicSummary
from app.modules.fsp.gateway import factory
from app.modules.fsp.gateway.base import Competition, FspContractError, FspUnavailable
from app.modules.fsp.models import FspCache, FspSnapshot, FspSyncAttempt
from app.modules.fsp.schemas import (
    FspCalendarItem,
    FspCalendarView,
    FspConsentBrief,
    FspLinkView,
    FspRefresh,
    FspSignalBrief,
)
from app.modules.identity import service as identity_service
from app.shared.enums import ConsentKind


def _notice(db: Session, user_id: UUID) -> str | None:
    outcome = db.scalar(
        select(FspSyncAttempt.outcome)
        .where(
            FspSyncAttempt.user_id == user_id,
            FspSyncAttempt.identity_id.is_(None),
            FspSyncAttempt.outcome.in_(tuple(c.NOTICE_TEXT)),
        )
        .order_by(FspSyncAttempt.started_at.desc())
        .limit(1)
    )
    return outcome


def needs_refresh(
    data: views.UserData, snapshot: FspSnapshot | None, attempt: FspSyncAttempt | None, now: datetime
) -> bool:
    """Нужно ли ленивое обновление (`stale`): снимка нет либо он старше `FSP_REFRESH_AFTER_HOURS`; прошлая попытка
    завершилась больше `FSP_RETRY_MIN_INTERVAL_MIN` минут назад и ничего не идёт сейчас (приложение D, §4.1).
    """
    if not data.linked:
        return False
    settings = get_settings()
    if snapshot is not None and now - snapshot.checked_at < timedelta(hours=settings.fsp_refresh_after_hours):
        return False
    if attempt is None:
        return True
    if attempt.finished_at is None:
        return now - attempt.started_at >= timedelta(seconds=c.SYNC_STUCK_SECONDS)
    return now - attempt.finished_at >= timedelta(minutes=settings.fsp_retry_min_interval_min)


def build_link_view(
    db: Session, user_id: UUID, *, now: datetime, as_of: date, specialization: str | None
) -> tuple[FspLinkView, bool]:
    """`FspLinkView` и признак «нужно фоновое обновление» (приложение D, §10.2)."""
    settings = get_settings()
    data = views.load(db, [user_id], only_evidence=False)[user_id]
    if not data.linked or data.identity is None:
        return FspLinkView(status="not_linked", provider_mode=settings.fsp_mode, notice=_notice(db, user_id)), False
    identity = data.identity
    snapshot = sync.current_snapshot(db, identity.id)
    attempt = views.last_attempt(db, user_id)
    history = views.history_of(data, snapshot, attempt, now)
    facts, ranks = data.facts(), data.ranks()
    consent = identity_service.consents(db, user_id).get(ConsentKind.FSP_DATA)
    last_manual_wait = sync.manual_wait(db, identity.id, now)
    refresh = FspRefresh(
        checked_at=snapshot.checked_at if snapshot else None,
        fetched_at=snapshot.fetched_at if snapshot else None,
        source_label=c.SOURCE_LABEL.get(identity.provider_mode, c.SOURCE_LABEL["keycloak"]) if snapshot else None,
        stale=snapshot is not None and now - snapshot.checked_at > timedelta(days=c.SNAPSHOT_STALE_DAYS),
        last_outcome=attempt.outcome if attempt is not None else None,
        last_attempt_at=(attempt.finished_at or attempt.started_at) if attempt is not None else None,
        can_sync_at=now + timedelta(seconds=last_manual_wait) if last_manual_wait > 0 else None,
    )
    result = sig.compute_signal(facts, ranks, specialization, as_of)
    summary = sig.public_summary(facts, ranks, specialization, as_of, settings.fsp_k_anon)
    preview = (
        FspPublicSummary(
            level=summary.level,
            headline=summary.headline,
            short=summary.short,
            more=summary.more,
            shortened=summary.shortened,
        )
        if summary is not None
        else None
    )
    view = FspLinkView(
        status="linked",
        provider_mode=identity.provider_mode,
        linked_at=identity.linked_at,
        subject_hint="…" + identity.fsp_id[-4:],
        history_status=history.status if history else None,
        no_history_reason=history.reason if history else None,
        notice=None,
        consent=FspConsentBrief(version=consent.version, granted_at=consent.granted_at) if consent else None,
        refresh=refresh,
        last_sync_at=refresh.checked_at,
        signal=FspSignalBrief(
            band=result.band, counted=result.counted, leadership_level=sig.leadership_level(facts, as_of)
        ),
        achievements=views.detailed_achievements(data, as_of, for_candidate=True),
        credentials=[views.credential_view(row, as_of) for row in views._visible_ranks(data)],
        employer_preview=preview,
    )
    return view, needs_refresh(data, snapshot, attempt, now)


# ---------------------------------------------------------------------------------------------------------------------
# Календарь
# ---------------------------------------------------------------------------------------------------------------------


def _load_calendar(db: Session, now: datetime, today: date) -> tuple[list[Competition], datetime | None, bool]:
    """Календарь из кэша либо из реестра: (соревнования, момент получения, устарел ли кэш)."""
    cache = db.get(FspCache, c.CALENDAR_CACHE_KEY)
    fresh = cache is not None and now - cache.fetched_at < timedelta(hours=c.CALENDAR_TTL_HOURS)
    stale = False
    if not fresh:
        try:
            items = factory.get_fsp_gateway().list_competitions(
                statuses=c.CALENDAR_STATUSES, date_from=today, limit=c.CALENDAR_FETCH_LIMIT
            )
        except (FspUnavailable, FspContractError):
            stale = True
        else:
            payload = [item.model_dump(mode="json") for item in items]
            if cache is None:
                cache = FspCache(key=c.CALENDAR_CACHE_KEY, payload=payload, fetched_at=now)
                db.add(cache)
            else:
                cache.payload, cache.fetched_at = payload, now
            db.flush()
    if cache is None:
        return [], None, True
    return [Competition.model_validate(item) for item in cache.payload], cache.fetched_at, stale


def build_calendar(
    db: Session, *, now: datetime, today: date, specialization: str | None, limit: int
) -> FspCalendarView:
    """Ближайшие соревнования (приложение D, §7.4): без юношеских групп и прошедших сроков, открытые — первыми."""
    competitions, fetched_at, stale = _load_calendar(db, now, today)
    mode = get_settings().fsp_mode
    candidates = []
    for item in competitions:
        if (
            item.status not in c.CALENDAR_STATUSES
            or item.age_group in c.CALENDAR_SKIPPED_AGE_GROUPS
            or item.date_start is None
            or item.date_start < today
            or (item.registration_deadline is not None and item.registration_deadline < today)
        ):
            continue
        relevance = (
            sig.relevance(item.discipline_code, specialization) if specialization else c.CALENDAR_RELEVANCE_DEFAULT
        )
        open_entry = item.level in ("municipal", "regional") or item.stage == "qualification" or item.kind == "other"
        key = (not open_entry, -relevance, item.status != "registration_open", item.date_start, item.competition_id)
        candidates.append((key, item))
    candidates.sort(key=lambda row: row[0])
    items = [
        FspCalendarItem(
            competition_id=item.competition_id,
            title=item.title,
            discipline_label=c.DISCIPLINE_LABEL.get(item.discipline_code, c.DISCIPLINE_LABEL[c.DISCIPLINE_OTHER]),
            level_label=c.LEVEL_LABEL.get(item.level, "уровень не распознан"),
            age_group_label=c.AGE_GROUP_LABEL.get(item.age_group, item.age_group),
            date_start=item.date_start,
            date_end=item.date_end or item.date_start,
            format_label=c.FORMAT_LABEL.get(item.format, item.format),
            city=item.city,
            status=item.status,
            registration_deadline=item.registration_deadline,
            registration_url=item.registration_url,
        )
        for _, item in candidates[:limit]
    ]
    return FspCalendarView(
        items=items,
        fetched_at=fetched_at,
        stale=stale,
        source_label=c.SOURCE_LABEL.get(mode, c.SOURCE_LABEL["keycloak"]),
    )
