"""Раскрытие контактов пары «работодатель — кандидат» и журнал доступа (Арх. 4.14, 10.4, 10.8).

Раскрытие — строка `contact_disclosure`; создаёт её только `disclose`. Каналы связи кандидата выдаёт только
`contacts_for_pair`: карточка, `…/contacts`, PDF и выгрузка берут данные из неё и больше ниоткуда.

Правило маскирования (Арх. 4.14, 10.4). Если работодатель — демо-аккаунт, а кандидат — нет (решает признак аккаунта
`app_user.is_demo`, а не чип показа), раскрытие записывается, но данные не передаются: `contacts_for_pair` отдаёт
заглушки, а `is_disclosed`, `disclosed_map` и `display_names` отвечают как до раскрытия.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ApiException
from app.core.pagination import PageParams, make_page
from app.modules.company import service as company
from app.modules.identity import service as identity
from app.modules.profile import privacy as privacy_store
from app.modules.profile.constants import (
    CONTACTS_VIEWED_INTERVAL_HOURS,
    MASKED_VALUE,
    UNKNOWN_COMPANY_NAME,
)
from app.modules.profile.dto import ContactsDTO
from app.modules.profile.models import AccessLog, CandidateDeclaredSkill, CandidateProfile, ContactDisclosure
from app.modules.profile.privacy import in_ids
from app.modules.profile.schemas import AccessLogItem, AccessLogRef
from app.shared.enums import AccessKind, DiscloseField, DisclosureSource
from app.shared.schemas import Page


def _ordered(fields: Iterable[str]) -> list[DiscloseField]:
    chosen = {DiscloseField(item) for item in fields}
    return [item for item in DiscloseField if item in chosen]


# --- запись раскрытия ------------------------------------------------------------------------------------------------


def _existing(db: Session, source: DisclosureSource, ref_id: UUID) -> ContactDisclosure | None:
    column = (
        ContactDisclosure.invitation_id if source == DisclosureSource.INVITATION else ContactDisclosure.application_id
    )
    return db.scalars(select(ContactDisclosure).where(column == ref_id)).first()


def disclose(
    db: Session,
    employer_id: UUID,
    candidate_id: UUID,
    *,
    source: DisclosureSource,
    ref_id: UUID,
    fields: Collection[DiscloseField],
    now: datetime,
) -> None:
    """Раскрыть пару; необратимо и идемпотентно по ссылке (`ref_id` приглашения или отклика).

    Повторный вызов с той же ссылкой ничего не меняет: строки не обновляются, набор каналов остаётся тем, что
    кандидат выбрал первый раз. E-mail открывается всегда (Арх. 10.4). Запись `contacts_disclosed` в журнале
    доступа пишется один раз — вместе со строкой раскрытия, в том числе для маскируемой пары (Арх. 4.14).
    """
    source = DisclosureSource(source)
    if _existing(db, source, ref_id) is not None:
        return
    chosen = _ordered([*fields, DiscloseField.EMAIL])
    row = ContactDisclosure(
        employer_id=employer_id,
        candidate_id=candidate_id,
        source=source.value,
        invitation_id=ref_id if source == DisclosureSource.INVITATION else None,
        application_id=ref_id if source == DisclosureSource.APPLICATION else None,
        fields=[item.value for item in chosen],
        disclosed_at=now,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        # Параллельный вызов с той же ссылкой успел первым; любая другая причина — не коллизия, а ошибка.
        if _existing(db, source, ref_id) is None:
            raise
        return
    log_access(db, candidate_id, employer_id, AccessKind.CONTACTS_DISCLOSED, ref_id, now)


# --- чтение раскрытия ------------------------------------------------------------------------------------------------


def _pair_rows(db: Session, employer_id: UUID, candidate_ids: Collection[UUID]) -> dict[UUID, list[ContactDisclosure]]:
    ids = list(dict.fromkeys(candidate_ids))
    result: dict[UUID, list[ContactDisclosure]] = {}
    if not ids:
        return result
    query = (
        select(ContactDisclosure)
        .where(ContactDisclosure.employer_id == employer_id, in_ids(ContactDisclosure.candidate_id, ids))
        .order_by(ContactDisclosure.disclosed_at, ContactDisclosure.id)
    )
    for row in db.scalars(query):
        result.setdefault(row.candidate_id, []).append(row)
    return result


def _visible_pairs(
    db: Session, employer_id: UUID, candidate_ids: Collection[UUID]
) -> dict[UUID, list[ContactDisclosure]]:
    """Раскрытые пары без маскируемых: для всех внешних ответов маскируемая пара — «не раскрыта»."""
    rows = _pair_rows(db, employer_id, candidate_ids)
    if not rows:
        return {}
    masked = privacy_store.masked_candidates(db, employer_id, list(rows))
    return {candidate_id: items for candidate_id, items in rows.items() if candidate_id not in masked}


def is_disclosed(db: Session, employer_id: UUID, candidate_id: UUID) -> bool:
    return candidate_id in _visible_pairs(db, employer_id, [candidate_id])


def disclosed_map(db: Session, employer_id: UUID, candidate_ids: Collection[UUID]) -> dict[UUID, frozenset[str]]:
    """Раскрытые пары и объединение выбранных каналов по всем их раскрытиям (приглашения и отклики)."""
    return {
        candidate_id: frozenset(field for row in rows for field in row.fields)
        for candidate_id, rows in _visible_pairs(db, employer_id, candidate_ids).items()
    }


def display_names(db: Session, employer_id: UUID, candidate_ids: Collection[UUID]) -> dict[UUID, str | None]:
    """«Имя Фамилия» — только для раскрытых пар (маскируемые и нераскрытые в ответе отсутствуют)."""
    pairs = _visible_pairs(db, employer_id, candidate_ids)
    if not pairs:
        return {}
    profiles = {
        row.user_id: row
        for row in db.scalars(select(CandidateProfile).where(in_ids(CandidateProfile.user_id, list(pairs))))
    }
    result: dict[UUID, str | None] = {}
    for candidate_id in pairs:
        profile = profiles.get(candidate_id)
        name = " ".join(part for part in (profile.first_name, profile.last_name) if part) if profile else ""
        result[candidate_id] = name or None
    return result


def _custom_tags(db: Session, candidate_id: UUID) -> list[str]:
    query = (
        select(CandidateDeclaredSkill.custom_label)
        .where(CandidateDeclaredSkill.user_id == candidate_id, CandidateDeclaredSkill.custom_label.is_not(None))
        .order_by(CandidateDeclaredSkill.position)
    )
    return [label for label in db.scalars(query) if label]


def contacts_for_pair(db: Session, employer_id: UUID, candidate_id: UUID) -> ContactsDTO | None:
    """Единственный источник каналов связи для работодателя.

    `None` — пара не раскрыта. Иначе: ФИО, «О себе» (если кандидат не скрыл его настройкой), свои теги и только
    каналы, выбранные кандидатом (объединение по всем раскрытиям пары). Для маскируемой пары — `masked = True`
    и заглушки во всех полях.
    """
    rows = _pair_rows(db, employer_id, [candidate_id]).get(candidate_id)
    if not rows:
        return None
    profile = db.get(CandidateProfile, candidate_id)
    if profile is None:  # раскрытие без профиля невозможно (код кандидата создаётся вместе с ним)
        return None
    disclosed_at = rows[0].disclosed_at
    if privacy_store.is_masked_pair(db, employer_id, candidate_id):
        return ContactsDTO(
            candidate_id=candidate_id,
            public_code=profile.public_code,
            first_name=MASKED_VALUE,
            last_name=MASKED_VALUE,
            middle_name=MASKED_VALUE,
            about=MASKED_VALUE,
            email=MASKED_VALUE,
            phone=MASKED_VALUE,
            telegram=MASKED_VALUE,
            link=MASKED_VALUE,
            custom_skills=[],
            disclosed_fields=[],
            disclosed_at=disclosed_at,
            masked=True,
        )
    chosen = {field for row in rows for field in row.fields}
    email = identity.get_user(db, candidate_id).email if DiscloseField.EMAIL.value in chosen else None
    return ContactsDTO(
        candidate_id=candidate_id,
        public_code=profile.public_code,
        first_name=profile.first_name or "",
        last_name=profile.last_name or "",
        middle_name=profile.middle_name,
        about=profile.about if privacy_store.load(db, candidate_id).show_about else None,
        email=email,
        phone=profile.phone if DiscloseField.PHONE.value in chosen else None,
        telegram=profile.telegram if DiscloseField.TELEGRAM.value in chosen else None,
        link=profile.link if DiscloseField.LINK.value in chosen else None,
        custom_skills=_custom_tags(db, candidate_id),
        disclosed_fields=_ordered(chosen),
        disclosed_at=disclosed_at,
    )


def filled_channels(db: Session, candidate_id: UUID) -> frozenset[str]:
    """Каналы, которые кандидат может выбрать при принятии: e-mail всегда, остальные — если заполнены.

    `fsp_details` (подробности достижений ФСП) не канал связи, но входит в тот же набор `disclose`; профиль не знает,
    привязан ли ФСП ID, поэтому предлагает его всегда — пустой блок ничего не раскроет.
    """
    profile = db.get(CandidateProfile, candidate_id)
    channels = {DiscloseField.EMAIL.value, DiscloseField.FSP_DETAILS.value}
    if profile is not None:
        if profile.phone:
            channels.add(DiscloseField.PHONE.value)
        if profile.telegram:
            channels.add(DiscloseField.TELEGRAM.value)
        if profile.link:
            channels.add(DiscloseField.LINK.value)
    return frozenset(channels)


def own_contacts(db: Session, candidate_id: UUID) -> ContactsDTO:
    """Сведения самого кандидата для его PDF: все заполненные каналы. Профиль без имени — 409 `profile_incomplete`."""
    profile = db.get(CandidateProfile, candidate_id)
    if profile is None or not profile.first_name or not profile.last_name:
        raise ApiException(409, "profile_incomplete", "Заполните имя и фамилию в профиле")
    channels = filled_channels(db, candidate_id)
    return ContactsDTO(
        candidate_id=candidate_id,
        public_code=profile.public_code,
        first_name=profile.first_name,
        last_name=profile.last_name,
        middle_name=profile.middle_name,
        about=profile.about,
        email=identity.get_user(db, candidate_id).email,
        phone=profile.phone,
        telegram=profile.telegram,
        link=profile.link,
        custom_skills=_custom_tags(db, candidate_id),
        disclosed_fields=_ordered(channels),
        disclosed_at=None,
    )


# --- журнал доступа --------------------------------------------------------------------------------------------------


def log_access(
    db: Session, candidate_id: UUID, employer_id: UUID, kind: AccessKind, ref_id: UUID | None, now: datetime
) -> None:
    """Записать событие в журнал доступа кандидата.

    Название компании сохраняется копией: запись переживает удаление работодателя (Арх. 10.8). `contacts_viewed`
    пишется не чаще раза в сутки на пару — обновление страницы журнал не засоряет.
    """
    kind = AccessKind(kind)
    if kind == AccessKind.CONTACTS_VIEWED:
        since = now - timedelta(hours=CONTACTS_VIEWED_INTERVAL_HOURS)
        recent = db.scalar(
            select(AccessLog.id)
            .where(
                AccessLog.candidate_id == candidate_id,
                AccessLog.employer_id == employer_id,
                AccessLog.kind == kind.value,
                AccessLog.at > since,
            )
            .limit(1)
        )
        if recent is not None:
            return
    info = company.get_company(db, employer_id)
    db.add(
        AccessLog(
            candidate_id=candidate_id,
            employer_id=employer_id,
            company_name=info.name if info is not None and info.name else UNKNOWN_COMPANY_NAME,
            kind=kind.value,
            ref_id=ref_id,
            at=now,
        )
    )
    db.flush()


KIND_LABELS: dict[AccessKind, str] = {
    AccessKind.CONTACTS_DISCLOSED: "Получила ваши контакты",
    AccessKind.CONTACTS_VIEWED: "Открыла ваши контакты",
    AccessKind.PDF_DOWNLOADED: "Скачала PDF-профиль",
    AccessKind.EXPORT_DOWNLOADED: "Выгрузила профиль",
}


def access_log_page(db: Session, candidate_id: UUID, paging: PageParams) -> Page[AccessLogItem]:
    """Журнал доступа самого кандидата: новые события выше; курсор — пара «момент, номер записи»."""
    query = select(AccessLog).where(AccessLog.candidate_id == candidate_id)
    position = paging.position
    if position is not None:
        try:
            cursor_at = datetime.fromisoformat(str(position["at"]))
            cursor_id = int(position["id"])
        except (KeyError, ValueError, TypeError):
            raise ApiException(422, "cursor_invalid") from None
        query = query.where((AccessLog.at < cursor_at) | ((AccessLog.at == cursor_at) & (AccessLog.id < cursor_id)))
    rows = list(db.scalars(query.order_by(AccessLog.at.desc(), AccessLog.id.desc()).limit(paging.limit + 1)))
    refs = {row.ref_id for row in rows if row.ref_id is not None}
    types: dict[UUID, Literal["invitation", "application"]] = {}
    if refs:
        found = db.execute(
            select(ContactDisclosure.invitation_id, ContactDisclosure.application_id).where(
                (ContactDisclosure.invitation_id.in_(refs)) | (ContactDisclosure.application_id.in_(refs))
            )
        )
        for invitation_id, application_id in found:
            if invitation_id is not None:
                types[invitation_id] = "invitation"
            if application_id is not None:
                types[application_id] = "application"

    def to_item(row: AccessLog) -> AccessLogItem:
        kind = AccessKind(row.kind)
        ref_type = types.get(row.ref_id) if row.ref_id is not None else None
        return AccessLogItem(
            at=row.at,
            company_name=row.company_name,
            kind=kind,
            kind_label=KIND_LABELS[kind],
            ref=AccessLogRef(type=ref_type, id=row.ref_id) if ref_type and row.ref_id else None,
        )

    page = make_page(rows, paging.limit, lambda row: {"at": row.at.isoformat(), "id": row.id})
    shown = {row.id for row in rows[: paging.limit]}
    return Page[AccessLogItem](items=[to_item(row) for row in rows if row.id in shown], next_cursor=page.next_cursor)
