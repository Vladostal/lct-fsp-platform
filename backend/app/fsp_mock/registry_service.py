"""Логика демо-реестра: выгрузка спортсмена, словари, календарь, разрешения, режим отказа (Арх. 7.2; приложение D, §2).

Один код обслуживает и HTTP-роутер (`app.py`), и вызовы платформы в процессе (`MockFspGateway`): шлюз получает
те же Pydantic-модели, что и HTTP-клиент. Ошибки контракта — `RegistryError` с кодом из Арх. 7.2; роутер превращает
их в `application/problem+json`, шлюз — в исключения платформы.

Счётчики анонимности считает реестр: только он видит всех спортсменов (приложение D, §6.2).
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core import clock
from app.core.db import new_session
from app.fsp_mock import reference as ref
from app.fsp_mock import schemas
from app.fsp_mock.models import (
    AccessGrant,
    Athlete,
    AuthCode,
    Competition,
    Control,
    Entry,
    EntryMember,
    RankAssignment,
)

FAILURE_KEY = "failure_mode"
SLOW_SECONDS = 10.0
GRANT_SOURCE_OIDC = "oidc"
GRANT_SOURCE_SEED = "seed"


class RegistryError(Exception):
    """Ошибка контракта реестра: статус, код (Арх. 7.2), пояснение."""

    def __init__(self, status: int, code: str, detail: str | None = None, retry_after: int | None = None) -> None:
        super().__init__(f"{status} {code}")
        self.status = status
        self.code = code
        self.detail = detail
        self.retry_after = retry_after


class RegistryMalformed(Exception):
    """Режим отказа `malformed`: ответ намеренно не по контракту."""


@dataclass(frozen=True, slots=True)
class Caller:
    """Кто вызывает реестр: пользователь (токен authorization code, только свой `fsp_id`) или сервис платформы."""

    kind: Literal["user", "service"]
    #: Для пользователя — его `fsp_id`.
    fsp_id: UUID | None = None
    client_id: str = ref.CLIENT_ID


@contextmanager
def registry_session() -> Iterator[Session]:
    """Собственная короткая сессия реестра: мок ведёт себя как внешняя система и не участвует в транзакции платформы.

    Фиксация при выходе, в том числе при `RegistryError`: ошибка контракта не отменяет записанного до неё
    (первый запрос пользователя регистрирует разрешение, даже если записи спортсмена нет). Прочие исключения
    откатывают сессию.
    """
    db = new_session()
    try:
        try:
            yield db
        except RegistryError:
            db.commit()
            raise
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------------------------------------------------
# Режим отказа
# ---------------------------------------------------------------------------------------------------------------------


def get_failure_mode(db: Session) -> str:
    row = db.get(Control, FAILURE_KEY)
    value = row.value if row is not None else "none"
    return value if value in ref.FAILURE_MODES else "none"


def set_failure_mode(db: Session, mode: str) -> None:
    if mode not in ref.FAILURE_MODES:
        raise ValueError(f"неизвестный режим отказа: {mode}")
    row = db.get(Control, FAILURE_KEY)
    if row is None:
        db.add(Control(key=FAILURE_KEY, value=mode))
    else:
        row.value = mode
    db.flush()


def check_failure_mode(db: Session, *, in_process: bool) -> None:
    """Применить режим отказа в начале запроса к реестру.

    `unavailable` — 503; `slow` — задержка 10 с (в процессе сразу 503: иначе тест и демонстрация зависли бы);
    `malformed` — `RegistryMalformed`.
    """
    mode = get_failure_mode(db)
    if mode == "unavailable":
        raise RegistryError(503, "registry_unavailable", "демо-реестр в режиме отказа", retry_after=30)
    if mode == "slow":
        if in_process:
            raise RegistryError(503, "registry_unavailable", "демо-реестр отвечает слишком медленно", retry_after=30)
        time.sleep(SLOW_SECONDS)
    if mode == "malformed":
        raise RegistryMalformed


# ---------------------------------------------------------------------------------------------------------------------
# Словари и календарь
# ---------------------------------------------------------------------------------------------------------------------


def dictionaries() -> schemas.Dictionaries:
    disciplines = []
    for code, item in ref.DISCIPLINES.items():
        size: Any = item["team_size"]
        disciplines.append(
            schemas.DisciplineItem(
                code=code,
                title=str(item["title"]),
                participation=list(item["participation"]),  # type: ignore[call-overload]
                team_size_min=size[0] if size else None,
                team_size_max=size[1] if size else None,
                result_model=str(item["result_model"]),
            )
        )

    def items(mapping: dict[str, str]) -> list[schemas.DictionaryItem]:
        return [schemas.DictionaryItem(code=code, title=title) for code, title in mapping.items()]

    return schemas.Dictionaries(
        schema_version=ref.SCHEMA_VERSION,
        disciplines=disciplines,
        levels=items(ref.LEVELS),
        kinds=items(ref.KINDS),
        stages=items(ref.STAGES),
        age_groups=items(ref.AGE_GROUPS),
        ranks=[
            schemas.RankItem(code=code, title=title, validity_years=ref.RANK_VALIDITY_YEARS.get(code))
            for code, title in ref.RANKS.items()
        ],
    )


def to_competition(row: Competition) -> schemas.Competition:
    return schemas.Competition(
        competition_id=row.competition_id,
        title=row.title,
        ekp_number=row.ekp_number,
        discipline_code=row.discipline_code,
        level=row.level,
        kind=row.kind,
        stage=row.stage,
        series_code=row.series_code,
        age_group=row.age_group,
        participation=row.participation,
        team_size_min=row.team_size_min,
        team_size_max=row.team_size_max,
        format=row.format,
        status=row.status,
        protocol_status=row.protocol_status,
        date_start=row.date_start,
        date_end=row.date_end,
        registration_deadline=row.registration_deadline,
        city=row.city,
        region_code=row.region_code,
        organizer=row.organizer,
        entries_count=row.entries_count,
        athletes_count=row.athletes_count,
        regions_count=row.regions_count,
        registration_url=row.registration_url,
        protocol_url=row.protocol_url,
    )


def list_competitions(
    db: Session,
    *,
    statuses: list[str] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    discipline: str | None = None,
    level: str | None = None,
    age_group: str | None = None,
    region: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> schemas.CompetitionPage:
    """Календарь с фильтрами и курсором (R5). Порядок — по `date_start`, затем `competition_id`."""
    statement = select(Competition)
    if statuses:
        statement = statement.where(Competition.status.in_(statuses))
    if date_from is not None:
        statement = statement.where(Competition.date_start >= date_from)
    if date_to is not None:
        statement = statement.where(Competition.date_start <= date_to)
    if discipline:
        statement = statement.where(Competition.discipline_code == discipline)
    if level:
        statement = statement.where(Competition.level == level)
    if age_group:
        statement = statement.where(Competition.age_group == age_group)
    if region:
        statement = statement.where(Competition.region_code == region)
    if cursor:
        try:
            raw_date, last_id = cursor.split("|", 1)
            after = (date.fromisoformat(raw_date), last_id)
        except ValueError as exc:
            raise RegistryError(422, "validation_error", "курсор не распознан") from exc
        statement = statement.where(
            (Competition.date_start > after[0])
            | ((Competition.date_start == after[0]) & (Competition.competition_id > after[1]))
        )
    statement = statement.order_by(Competition.date_start, Competition.competition_id).limit(limit + 1)
    rows = list(db.scalars(statement))
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = f"{rows[-1].date_start.isoformat()}|{rows[-1].competition_id}"
    return schemas.CompetitionPage(items=[to_competition(row) for row in rows], next_cursor=next_cursor)


def get_competition(db: Session, competition_id: str) -> schemas.Competition:
    row = db.get(Competition, competition_id)
    if row is None:
        raise RegistryError(404, "competition_not_found")
    return to_competition(row)


# ---------------------------------------------------------------------------------------------------------------------
# Разрешения «спортсмен → клиент»
# ---------------------------------------------------------------------------------------------------------------------


def register_grant(db: Session, fsp_id: UUID, client_id: str, source: str, now: datetime) -> None:
    """Зарегистрировать (или возобновить) разрешение. Идемпотентно: гонка двух запросов не даёт ошибки."""
    statement = pg_insert(AccessGrant).values(
        fsp_id=fsp_id, client_id=client_id, scope=ref.SCOPE, source=source, granted_at=now, revoked_at=None
    )
    statement = statement.on_conflict_do_update(
        index_elements=[AccessGrant.fsp_id, AccessGrant.client_id],
        set_={"revoked_at": None, "source": source, "granted_at": now},
        where=AccessGrant.revoked_at.is_not(None),
    )
    db.execute(statement)
    db.flush()


def revoke_grant(db: Session, fsp_id: UUID, client_id: str, now: datetime) -> bool:
    """Снять разрешение (R4 и «отзыв со стороны спортсмена»). Идемпотентно; `True`, если оно было действующим."""
    grant = db.get(AccessGrant, (fsp_id, client_id), populate_existing=True)
    if grant is None or grant.revoked_at is not None:
        return False
    grant.revoked_at = now
    db.flush()
    return True


def has_active_grant(db: Session, fsp_id: UUID, client_id: str = ref.CLIENT_ID) -> bool:
    grant = db.get(AccessGrant, (fsp_id, client_id))
    return grant is not None and grant.revoked_at is None


# ---------------------------------------------------------------------------------------------------------------------
# Выгрузка спортсмена
# ---------------------------------------------------------------------------------------------------------------------


def _period(day: date, today: date) -> str:
    days = (today - day).days
    if days <= ref.PERIOD_RECENT_DAYS:
        return "recent"
    return "mid" if days <= ref.PERIOD_MID_DAYS else "old"


def _bucket(place: int | None, place_to: int | None, field: int | None) -> str:
    """Корзина результата — то же правило, что у платформы (приложение D, §5.1): контракт общий, код — свой."""
    if place is None:
        return "participant"
    place_eff = (place + (place_to if place_to is not None else place)) / 2
    top_half = field is not None and place_eff <= field / 2
    if math.ceil(place_eff) <= 3 and (field is None or top_half):
        return "medal"
    return "top_half" if top_half else "participant"


def _anonymity_counters(
    db: Session, disciplines: set[str], today: date
) -> dict[tuple[str, str], tuple[dict[tuple[str, str], set[UUID]], set[UUID]]]:
    """Для каждой пары `(дисциплина, tier)`: множества спортсменов по `(период, корзина)` и все вместе (`k_b`)."""
    if not disciplines:
        return {}
    rows = db.execute(
        select(
            EntryMember.fsp_id,
            Competition.discipline_code,
            Competition.level,
            Competition.date_end,
            Entry.place,
            Entry.place_to,
            Competition.entries_count,
        )
        .join(Entry, Entry.entry_id == EntryMember.entry_id)
        .join(Competition, Competition.competition_id == Entry.competition_id)
        .where(
            EntryMember.role == "athlete",
            Entry.result_status == "ok",
            Competition.status == "finished",
            Competition.protocol_status == "official",
            Competition.discipline_code.in_(disciplines),
        )
    )
    cells: dict[tuple[str, str], tuple[dict[tuple[str, str], set[UUID]], set[UUID]]] = defaultdict(
        lambda: (defaultdict(set), set())
    )
    for fsp_id, discipline, level, date_end, place, place_to, field in rows:
        tier = ref.TIER.get(level)
        if tier is None:
            continue
        by_cell, everyone = cells[(discipline, tier)]
        by_cell[(_period(date_end, today), _bucket(place, place_to, field))].add(fsp_id)
        everyone.add(fsp_id)
    return cells


def _cohorts_for(
    db: Session, records: list[schemas.ParticipationRecord], today: date
) -> list[schemas.ParticipationRecord]:
    cells = _anonymity_counters(db, {record.competition.discipline_code for record in records}, today)
    for record in records:
        competition = record.competition
        tier = ref.TIER.get(competition.level)
        counted = (
            tier is not None
            and record.result.status == "ok"
            and competition.status == "finished"
            and competition.protocol_status == "official"
        )
        if not counted:
            continue
        assert tier is not None
        by_cell, everyone = cells[(competition.discipline_code, tier)]
        period = _period(competition.date_end, today)
        bucket = _bucket(record.result.place, record.result.place_to, competition.entries_count)
        record.anonymity = schemas.Anonymity(
            period=period,
            k_a=len(by_cell.get((period, bucket), ())),
            k_b=len(everyone),
        )
    return records


def etag_of(body: dict[str, Any]) -> str:
    """`ETag`: первые 16 знаков SHA-256 канонического JSON тела без `generated_at` (приложение D, §2.1)."""
    material = {key: value for key, value in body.items() if key != "generated_at"}
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class ExportResponse:
    export: schemas.AthleteExport
    body: dict[str, Any]
    etag: str


@dataclass(frozen=True, slots=True)
class ExportNotModified:
    etag: str


def _age_years(birth: date, today: date) -> int:
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def build_export(db: Session, athlete: Athlete, now: datetime) -> schemas.AthleteExport:
    """Единая выгрузка по одному спортсмену: только его участия; ФИО, дата рождения и пол не отдаются."""
    today = clock.to_local_date(now)
    rows = db.execute(
        select(EntryMember, Entry, Competition)
        .join(Entry, Entry.entry_id == EntryMember.entry_id)
        .join(Competition, Competition.competition_id == Entry.competition_id)
        .where(EntryMember.fsp_id == athlete.fsp_id)
        .order_by(Competition.date_end.desc(), Entry.entry_id, EntryMember.role)
    ).all()
    sizes: dict[str, int] = {}
    entry_ids = {entry.entry_id for _, entry, _ in rows}
    if entry_ids:
        counted = db.execute(
            select(EntryMember.entry_id, func.count())
            .where(EntryMember.entry_id.in_(entry_ids), EntryMember.role == "athlete")
            .group_by(EntryMember.entry_id)
        )
        sizes = {row[0]: int(row[1]) for row in counted}
    records: list[schemas.ParticipationRecord] = []
    for member, entry, competition in rows:
        records.append(
            schemas.ParticipationRecord(
                entry_id=entry.entry_id,
                member_role=member.role,
                is_captain=member.is_captain,
                entry=schemas.EntryInfo(
                    kind=entry.kind,
                    team_name=entry.team_name,
                    team_size=sizes.get(entry.entry_id) if entry.kind == "team" else None,
                    region_code=entry.region_code,
                ),
                competition=to_competition(competition),
                result=schemas.ResultInfo(
                    status=entry.result_status,
                    place=entry.place,
                    place_to=entry.place_to,
                    score=float(entry.score) if entry.score is not None else None,
                    score_max=float(entry.score_max) if entry.score_max is not None else None,
                    solved=entry.solved,
                    problems_total=entry.problems_total,
                    penalty=entry.penalty,
                ),
            )
        )
    ranks = db.scalars(
        select(RankAssignment).where(RankAssignment.fsp_id == athlete.fsp_id).order_by(RankAssignment.rank_id)
    ).all()
    return schemas.AthleteExport(
        schema_version=ref.SCHEMA_VERSION,
        generated_at=now,
        source=schemas.SourceInfo(registry="fsp", environment="mock"),
        athlete=schemas.AthleteInfo(
            fsp_id=str(athlete.fsp_id),
            is_adult=_age_years(athlete.birth_date, today) >= ref.ADULT_AGE,
            region_code=athlete.region_code,
            status=athlete.status,
        ),
        participations=_cohorts_for(db, records, today),
        ranks=[
            schemas.RankRecord(
                rank_id=rank.rank_id,
                rank_code=rank.rank_code,
                assigned_on=rank.assigned_on,
                valid_until=rank.valid_until,
                order_number=rank.order_number,
                assigned_by=rank.assigned_by,
                discipline_code=rank.discipline_code,
                revoked_on=rank.revoked_on,
            )
            for rank in ranks
        ],
    )


def export(
    db: Session, fsp_id: UUID, caller: Caller, *, if_none_match: str | None = None, in_process: bool = False
) -> ExportResponse | ExportNotModified:
    """R3: единая выгрузка. Проверка доступа, разрешение, 404, ETag.

    Пользовательский токен действует только для своего `fsp_id`; первый запрос с ним регистрирует разрешение
    (в том числе для `fsp_id` без записи спортсмена: иначе следующая синхронизация сервисным токеном получила бы
    `grant_required` и отвязала бы только что привязанного человека). Сервисный токен проходит при действующем
    разрешении.
    """
    check_failure_mode(db, in_process=in_process)
    now = clock.real_now()
    if caller.kind == "user":
        if caller.fsp_id != fsp_id:
            raise RegistryError(403, "insufficient_scope", "пользовательский токен выдан для другого ФСП ID")
        register_grant(db, fsp_id, caller.client_id, GRANT_SOURCE_OIDC, now)
    else:
        grant = db.get(AccessGrant, (fsp_id, caller.client_id))
        if grant is None:
            raise RegistryError(403, "grant_required", "спортсмен не разрешил доступ")
        if grant.revoked_at is not None:
            raise RegistryError(403, "grant_revoked", "спортсмен отозвал доступ")
    athlete = db.get(Athlete, fsp_id)
    if athlete is None:
        raise RegistryError(404, "athlete_not_found", "у ФСП ID нет записи спортсмена")
    built = build_export(db, athlete, now)
    body = built.model_dump(mode="json")
    etag = etag_of(body)
    if if_none_match is not None and if_none_match.strip('"') == etag:
        return ExportNotModified(etag)
    return ExportResponse(export=built, body=body, etag=etag)


# ---------------------------------------------------------------------------------------------------------------------
# Служебные действия ведущего
# ---------------------------------------------------------------------------------------------------------------------


def purge_expired_codes(db: Session, now: datetime) -> None:
    """Коды авторизации живут 60 секунд; просроченные удаляются при выдаче нового."""
    db.query(AuthCode).filter(AuthCode.expires_at < now).delete(synchronize_session=False)


def free_adult_athletes(db: Session, *, with_history: bool) -> list[tuple[UUID, float]]:
    """Свободные взрослые спортсмены (без действующего разрешения, не персонажи): `(fsp_id, latent_skill)`.

    `with_history` — с зачтённым результатом (завершённое соревнование, официальный протокол, статус `ok`) либо
    без единого участия. Нужны сиду платформы: он раздаёт спортсменов синтетическим кандидатам (приложение D, §8.4).
    """
    today = clock.to_local_date(clock.real_now())
    granted = select(AccessGrant.fsp_id).where(AccessGrant.revoked_at.is_(None))
    participates = select(EntryMember.fsp_id).where(EntryMember.role == "athlete")
    counted = (
        select(EntryMember.fsp_id)
        .join(Entry, Entry.entry_id == EntryMember.entry_id)
        .join(Competition, Competition.competition_id == Entry.competition_id)
        .where(
            EntryMember.role == "athlete",
            Entry.result_status == "ok",
            Competition.status == "finished",
            Competition.protocol_status == "official",
        )
    )
    statement = select(Athlete.fsp_id, Athlete.birth_date, Athlete.latent_skill).where(
        Athlete.persona_key.is_(None), Athlete.fsp_id.not_in(granted)
    )
    statement = statement.where(Athlete.fsp_id.in_(counted) if with_history else Athlete.fsp_id.not_in(participates))
    return [
        (fsp_id, float(latent))
        for fsp_id, birth, latent in db.execute(statement.order_by(Athlete.fsp_id))
        if _age_years(birth, today) >= ref.ADULT_AGE
    ]
