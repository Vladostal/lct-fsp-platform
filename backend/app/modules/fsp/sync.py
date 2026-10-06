"""Синхронизация с реестром ФСП: захват попытки, запрос, нормализация, снимки, факты (Арх. 7.5; приложение D, §4).

Время считается по `clock.real_now()` (механика привязки и синхронизации — реальные секунды, а не демо-часы).
Запрос к реестру идёт вне транзакции: попытка фиксируется до вызова, результат применяется отдельной фиксацией.
Идемпотентность: идентификаторы фактов — `uuid5` от пользователя, строки протокола и роли, поэтому повторная
синхронизация с тем же ответом ничего не меняет и ссылки подбора на факт-доказательство не ломаются.
Токены ФСП ID сюда приходят только на время одного вызова и нигде не сохраняются.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.core.errors import ApiException
from app.modules.fsp import constants as c
from app.modules.fsp import signal as sig
from app.modules.fsp.gateway import factory
from app.modules.fsp.gateway.base import (
    ExportNotModified,
    ExportNotRegistered,
    ExportOk,
    FspAuthError,
    FspContractError,
    FspGateway,
    FspGrantRevoked,
    FspUnavailable,
    ParticipationRecord,
)
from app.modules.fsp.models import (
    ExternalIdentity,
    FspAchievement,
    FspCredential,
    FspSnapshot,
    FspSyncAttempt,
)

log = logging.getLogger("app.fsp")

TRIGGERS = ("link", "manual", "stale", "cli", "seed")


class NotLinked(Exception):
    """У пользователя нет привязки ФСП ID."""


@dataclass(frozen=True, slots=True)
class SyncResult:
    outcome: str
    #: Для `in_progress` и отказов по частоте — через сколько секунд повторить.
    retry_after: int | None = None


# ---------------------------------------------------------------------------------------------------------------------
# Разбор выгрузки
# ---------------------------------------------------------------------------------------------------------------------


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def payload_sha256(raw: dict[str, Any]) -> str:
    """SHA-256 канонического JSON тела без `generated_at` (приложение D, §4.2)."""
    material = {key: value for key, value in raw.items() if key != "generated_at"}
    return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


def minimized_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """Тело выгрузки без региона спортсмена и соревнований (поправка R3-data-api-security-12)."""
    payload = copy.deepcopy(raw)
    athlete = payload.get("athlete")
    if isinstance(athlete, dict):
        athlete.pop("region_code", None)
    for record in payload.get("participations") or []:
        if not isinstance(record, dict):
            continue
        for part in ("entry", "competition"):
            block = record.get(part)
            if isinstance(block, dict):
                block.pop("region_code", None)
    return payload


def fact_id(user_id: UUID, entry_id: str, member_role: str) -> UUID:
    return uuid5(c.NAMESPACE_FSP, f"{user_id}:{entry_id}:{member_role}")


def credential_id(user_id: UUID, kind: str, source_key: str) -> UUID:
    return uuid5(c.NAMESPACE_FSP, f"{user_id}:{kind}:{source_key}")


def to_participation(record: ParticipationRecord) -> sig.Participation:
    competition = record.competition
    return sig.Participation(
        entry_id=record.entry_id,
        member_role=record.member_role,
        is_captain=record.is_captain,
        participation=record.entry.kind or competition.participation,
        team_size=record.entry.team_size,
        discipline_code=competition.discipline_code,
        level=competition.level,
        kind=competition.kind,
        stage=competition.stage,
        series_code=competition.series_code,
        competition_status=competition.status,
        protocol_status=competition.protocol_status,
        date_start=competition.date_start,
        date_end=competition.date_end,
        entries_count=competition.entries_count,
        result_status=record.result.status,
        place=record.result.place,
        place_to=record.result.place_to,
    )


def build_facts(
    user_id: UUID, snapshot_id: UUID, ok: ExportOk, now: datetime
) -> tuple[list[FspAchievement], list[FspCredential]]:
    """Нормализовать выгрузку (приложение D, §5.1) в строки `fsp_achievement` и `fsp_credential`."""
    export = ok.export
    today = clock.to_local_date(now)
    unique: dict[tuple[str, str], ParticipationRecord] = {}
    for record in export.participations:
        unique[(record.entry_id, record.member_role)] = record
    normalized = sig.normalize_all([to_participation(item) for item in unique.values()], today)
    achievements: list[FspAchievement] = []
    for fact in normalized:
        record = unique[(fact.entry_id, fact.member_role)]
        competition, result = record.competition, record.result
        anonymity = record.anonymity
        achievements.append(
            FspAchievement(
                id=fact_id(user_id, record.entry_id, record.member_role),
                user_id=user_id,
                snapshot_id=snapshot_id,
                entry_id=record.entry_id,
                competition_id=competition.competition_id,
                competition_title=competition.title,
                ekp_number=competition.ekp_number,
                discipline_code=competition.discipline_code,
                level=competition.level,
                kind=competition.kind,
                stage=competition.stage,
                series_code=competition.series_code,
                tier=fact.tier,
                age_group=competition.age_group,
                participation=record.entry.kind or competition.participation,
                format=competition.format,
                city=competition.city,
                date_start=competition.date_start,
                event_date=fact.event_date,
                protocol_url=competition.protocol_url,
                field_size=fact.field_size,
                regions_count=competition.regions_count,
                member_role=record.member_role,
                is_captain=record.is_captain,
                team_name=record.entry.team_name,
                team_size=record.entry.team_size,
                result_status=result.status,
                place=result.place,
                place_to=result.place_to,
                place_eff=fact.place_eff,
                score=result.score,
                score_max=result.score_max,
                solved=result.solved,
                problems_total=result.problems_total,
                penalty=result.penalty,
                result_bucket=fact.result_bucket,
                verified=fact.verified,
                counted=fact.counted,
                uncounted_reason=fact.uncounted_reason,
                base_points=fact.base_points,
                anon_period=anonymity.period if anonymity else None,
                anon_k_a=anonymity.k_a if anonymity else None,
                anon_k_b=anonymity.k_b if anonymity else None,
            )
        )
    credentials = [
        FspCredential(
            id=credential_id(user_id, "rank", rank.rank_id),
            user_id=user_id,
            snapshot_id=snapshot_id,
            kind="rank",
            source_key=rank.rank_id,
            code=rank.rank_code,
            discipline_code=rank.discipline_code,
            level=None,
            title=None,
            assigned_on=rank.assigned_on,
            valid_from=rank.assigned_on,
            valid_until=rank.valid_until,
            revoked_on=rank.revoked_on,
            event_date=None,
            season=None,
            order_number=rank.order_number,
            assigned_by=rank.assigned_by,
        )
        for rank in {item.rank_id: item for item in export.ranks}.values()
    ]
    return achievements, credentials


# ---------------------------------------------------------------------------------------------------------------------
# Применение результата
# ---------------------------------------------------------------------------------------------------------------------


def current_snapshot(db: Session, identity_id: UUID) -> FspSnapshot | None:
    return db.scalar(
        select(FspSnapshot).where(FspSnapshot.identity_id == identity_id, FspSnapshot.is_current.is_(True))
    )


def _replace_snapshot(
    db: Session,
    identity: ExternalIdentity,
    snapshot: FspSnapshot,
    facts: tuple[list[FspAchievement], list[FspCredential]],
) -> None:
    """Снять `is_current` со старого снимка, вставить новый и пересоздать факты; оставить два последних снимка."""
    user_id = identity.user_id
    db.execute(delete(FspAchievement).where(FspAchievement.user_id == user_id))
    db.execute(delete(FspCredential).where(FspCredential.user_id == user_id))
    db.execute(
        update(FspSnapshot)
        .where(FspSnapshot.identity_id == identity.id, FspSnapshot.is_current.is_(True))
        .values(is_current=False)
    )
    db.flush()
    db.add(snapshot)
    db.flush()
    db.add_all(facts[0])
    db.add_all(facts[1])
    db.flush()
    keep = list(
        db.scalars(
            select(FspSnapshot.id)
            .where(FspSnapshot.user_id == user_id)
            .order_by(FspSnapshot.fetched_at.desc(), FspSnapshot.id)
            .limit(c.SNAPSHOTS_KEEP)
        )
    )
    db.execute(delete(FspSnapshot).where(FspSnapshot.user_id == user_id, FspSnapshot.id.not_in(keep)))
    db.flush()


def apply_export(
    db: Session, identity: ExternalIdentity, result: ExportOk | ExportNotRegistered | ExportNotModified, now: datetime
) -> str:
    """Применить успешный ответ реестра: вернуть `ok_changed` либо `ok_unchanged`. Несовершеннолетних здесь нет.

    Вызывающий уже проверил `is_adult`: при `false` данные не сохраняются вовсе.
    """
    current = current_snapshot(db, identity.id)
    if isinstance(result, ExportNotModified):
        if current is not None:
            current.checked_at = now
        return c.OUTCOME_OK_UNCHANGED
    gateway_source = identity.provider_mode
    if isinstance(result, ExportNotRegistered):
        if current is not None and not current.athlete_registered:
            current.checked_at = now
            return c.OUTCOME_OK_UNCHANGED
        snapshot = FspSnapshot(
            identity_id=identity.id,
            user_id=identity.user_id,
            is_current=True,
            source=gateway_source,
            registry_url=current.registry_url if current else "",
            api_version=current.api_version if current else "",
            schema_version=current.schema_version if current else "",
            etag=None,
            payload={},
            payload_sha256=hashlib.sha256(b"{}").hexdigest(),
            athlete_registered=False,
            participations_count=0,
            generated_at=None,
            fetched_at=now,
            checked_at=now,
        )
        _replace_snapshot(db, identity, snapshot, ([], []))
        return c.OUTCOME_OK_CHANGED
    sha = payload_sha256(result.raw)
    if current is not None and current.payload_sha256 == sha and current.athlete_registered:
        current.checked_at = now
        if result.etag:
            current.etag = result.etag
        return c.OUTCOME_OK_UNCHANGED
    snapshot = FspSnapshot(
        id=uuid4(),
        identity_id=identity.id,
        user_id=identity.user_id,
        is_current=True,
        source=gateway_source,
        registry_url=_registry_url(),
        api_version=result.api_version,
        schema_version=result.export.schema_version,
        etag=result.etag,
        payload=minimized_payload(result.raw),
        payload_sha256=sha,
        athlete_registered=True,
        participations_count=len(result.export.participations),
        generated_at=result.export.generated_at,
        fetched_at=now,
        checked_at=now,
    )
    # Идентификатор снимка задан заранее: факты ссылаются на него до вставки.
    _replace_snapshot(db, identity, snapshot, build_facts(identity.user_id, snapshot.id, result, now))
    return c.OUTCOME_OK_CHANGED


def _registry_url() -> str:
    try:
        return factory.get_fsp_gateway().registry_url
    except FspUnavailable:
        return get_settings().fsp_registry_url


# ---------------------------------------------------------------------------------------------------------------------
# Синхронизация
# ---------------------------------------------------------------------------------------------------------------------


def _close(
    attempt: FspSyncAttempt, outcome: str, now: datetime, *, error_code: str | None = None, started: float | None = None
) -> None:
    attempt.finished_at = now
    attempt.outcome = outcome
    attempt.error_code = error_code
    if started is not None:
        attempt.duration_ms = int((time.monotonic() - started) * 1000)


def _prune_attempts(db: Session, user_id: UUID) -> None:
    keep = list(
        db.scalars(
            select(FspSyncAttempt.id)
            .where(FspSyncAttempt.user_id == user_id, FspSyncAttempt.identity_id.is_not(None))
            .order_by(FspSyncAttempt.started_at.desc(), FspSyncAttempt.id)
            .limit(c.SYNC_ATTEMPTS_KEEP)
        )
    )
    db.execute(
        delete(FspSyncAttempt).where(
            FspSyncAttempt.user_id == user_id,
            FspSyncAttempt.identity_id.is_not(None),
            FspSyncAttempt.id.not_in(keep),
            FspSyncAttempt.finished_at.is_not(None),
        )
    )


def manual_wait(db: Session, identity_id: UUID, now: datetime) -> int:
    """Сколько секунд осталось до разрешённой ручной синхронизации (0 — можно)."""
    last = db.scalar(
        select(func.max(FspSyncAttempt.finished_at)).where(
            FspSyncAttempt.identity_id == identity_id, FspSyncAttempt.trigger == "manual"
        )
    )
    if last is None:
        return 0
    interval = timedelta(seconds=get_settings().fsp_manual_sync_min_interval_s)
    return max(0, int((last + interval - now).total_seconds() + 0.999))


def run_sync(
    db: Session,
    user_id: UUID,
    trigger: str,
    *,
    user_token: str | None = None,
    gateway: FspGateway | None = None,
) -> SyncResult:
    """Синхронизация одного пользователя (приложение D, §4.2). Данные меняются только при успехе.

    Ручная — не чаще раза в `FSP_MANUAL_SYNC_MIN_INTERVAL_S` секунд (429 `fsp_sync_too_frequent`). Попытка
    захватывается и фиксируется до запроса; пока она не закрыта, вторая не стартует (`in_progress`). Зависшая
    дольше 30 секунд закрывается как `failed_timeout`.
    """
    if trigger not in TRIGGERS:
        raise ValueError(f"неизвестный триггер синхронизации: {trigger}")
    now = clock.real_now()
    identity = db.scalar(select(ExternalIdentity).where(ExternalIdentity.user_id == user_id))
    if identity is None:
        raise NotLinked
    if trigger == "manual":
        wait = manual_wait(db, identity.id, now)
        if wait > 0:
            raise ApiException(429, "fsp_sync_too_frequent", params={"retry_after": wait})
    db.execute(
        update(FspSyncAttempt)
        .where(
            FspSyncAttempt.identity_id == identity.id,
            FspSyncAttempt.finished_at.is_(None),
            FspSyncAttempt.started_at <= now - timedelta(seconds=c.SYNC_STUCK_SECONDS),
        )
        .values(finished_at=now, outcome=c.OUTCOME_FAILED_TIMEOUT)
    )
    attempt = FspSyncAttempt(user_id=user_id, identity_id=identity.id, trigger=trigger, started_at=now)
    try:
        with db.begin_nested():
            db.add(attempt)
            db.flush()
    except IntegrityError:
        return SyncResult(c.OUTCOME_IN_PROGRESS, retry_after=c.SYNC_STUCK_SECONDS)
    attempt_id = attempt.id
    fsp_id = identity.fsp_id
    snapshot = current_snapshot(db, identity.id)
    etag = snapshot.etag if snapshot is not None and trigger != "link" else None
    db.commit()  # попытка видна другим процессам до запроса к реестру; транзакция на время запроса не держится

    started = time.monotonic()
    gateway = gateway or factory.get_fsp_gateway()
    error: str | None = None
    unlink_reason: str | None = None
    outcome = c.OUTCOME_FAILED_UNAVAILABLE
    fetched: ExportOk | ExportNotRegistered | ExportNotModified | None = None
    try:
        fetched = gateway.fetch_export(fsp_id, user_token=user_token, etag=etag)
    except FspGrantRevoked:
        unlink_reason = "revoked"
        outcome = c.OUTCOME_UNLINKED_REVOKED
    except FspUnavailable as exc:
        outcome, error = c.OUTCOME_FAILED_UNAVAILABLE, str(exc)[:200]
    except FspContractError as exc:
        outcome, error = c.OUTCOME_FAILED_CONTRACT, str(exc)[:200]
    except FspAuthError as exc:
        outcome, error = c.OUTCOME_FAILED_AUTH, str(exc)[:200]

    if unlink_reason is not None:
        from app.modules.fsp import linking

        linking.unlink(db, user_id, reason="revoked")
        db.commit()
        return SyncResult(outcome)
    now = clock.real_now()
    if fetched is not None:
        if isinstance(fetched, ExportOk) and not fetched.export.athlete.is_adult:
            from app.modules.fsp import linking

            linking.unlink(db, user_id, reason="minor")
            db.commit()
            return SyncResult(c.OUTCOME_UNLINKED_MINOR)
        identity = db.get(ExternalIdentity, identity.id, populate_existing=True)
        if identity is None:  # отвязали, пока шёл запрос
            return SyncResult(outcome)
        outcome = apply_export(db, identity, fetched, now)
    stored = db.get(FspSyncAttempt, attempt_id, populate_existing=True)
    if stored is not None:
        _close(stored, outcome, now, error_code=error, started=started)
        _prune_attempts(db, user_id)
    db.commit()
    return SyncResult(outcome)


def seconds_since(moment: datetime | None, now: datetime) -> float | None:
    return None if moment is None else (now - moment).total_seconds()
