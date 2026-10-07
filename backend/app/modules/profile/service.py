"""Фасад модуля `profile` (Арх. 2.5).

Сигнатуры нормативны. Здесь только тонкие обёртки: логика лежит во внутренних файлах модуля (`profiles.py`,
`privacy.py`, `visibility.py`, `disclosure.py`, `resume/`, `pdf/`), другие модули вызывают только этот файл.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import ApiException
from app.modules.assessment import service as assessment
from app.modules.identity import service as identity
from app.modules.profile import disclosure, profiles
from app.modules.profile import privacy as privacy_store
from app.modules.profile import visibility as visibility_rules
from app.modules.profile.constants import RESUME_RESULT_TTL_HOURS
from app.modules.profile.dto import (
    ConditionsData,
    ContactsDTO,
    PoolProfile,
    PrivacyData,
    PrivacySettingsDTO,
    ProfileData,
    ProfilePdfModel,
    VisibilityDTO,
)
from app.modules.profile.models import CandidateProfile, ResumeUpload
from app.shared.enums import AccessKind, ConsentKind, DemoPersona, DiscloseField, DisclosureSource

# --- чтение ---------------------------------------------------------------------------------------------------------


def pool_view(db: Session, candidate_ids: Collection[UUID], now: datetime) -> dict[UUID, PoolProfile]:
    """Профили пачкой для подбора: только то, что можно показывать до раскрытия (Арх. 6.1)."""
    return profiles.pool_view(db, candidate_ids, now)


def visibility(db: Session, candidate_id: UUID, now: datetime) -> VisibilityDTO:
    return visibility_rules.for_candidate(db, candidate_id, now)


def privacy(db: Session, candidate_id: UUID) -> PrivacySettingsDTO:
    return privacy_store.load(db, candidate_id)


def contacts_for_pair(db: Session, employer_id: UUID, candidate_id: UUID) -> ContactsDTO | None:
    """`None`, если пара не раскрыта; иначе ФИО, «О себе», свои теги и только каналы из `contact_disclosure.fields`.
    Для маскируемой пары (работодатель — демо-аккаунт, кандидат — нет; Арх. 10.4) — `masked = True` и заглушки.
    """
    return disclosure.contacts_for_pair(db, employer_id, candidate_id)


def own_contacts(db: Session, candidate_id: UUID) -> ContactsDTO:
    """Только для PDF-профиля самого кандидата."""
    return disclosure.own_contacts(db, candidate_id)


def filled_channels(db: Session, candidate_id: UUID) -> frozenset[str]:
    """Какие каналы заполнены — для проверки набора `disclose`."""
    return disclosure.filled_channels(db, candidate_id)


def hidden_from_employer(db: Session, employer_id: UUID, candidate_ids: Collection[UUID]) -> set[UUID]:
    """P1: список «не показывать компаниям» (Арх. 10.4)."""
    return privacy_store.hidden_from_employer(db, employer_id, candidate_ids)


def min_salary(db: Session, candidate_id: UUID) -> int | None:
    """Скрытый минимум. Вызывают только `contact` (сверка 4.6, метка кандидату), сид и валидация."""
    return profiles.min_salary(db, candidate_id)


def is_disclosed(db: Session, employer_id: UUID, candidate_id: UUID) -> bool:
    return disclosure.is_disclosed(db, employer_id, candidate_id)


def disclosed_map(db: Session, employer_id: UUID, candidate_ids: Collection[UUID]) -> dict[UUID, frozenset[str]]:
    return disclosure.disclosed_map(db, employer_id, candidate_ids)


def display_names(db: Session, employer_id: UUID, candidate_ids: Collection[UUID]) -> dict[UUID, str | None]:
    """Имена — только для раскрытых пар."""
    return disclosure.display_names(db, employer_id, candidate_ids)


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
    """Единственное место, где создаётся раскрытие пары; оно необратимо и идемпотентно по ссылке (Арх. 10.4)."""
    profiles.ensure_profile(db, candidate_id, now)
    disclosure.disclose(db, employer_id, candidate_id, source=source, ref_id=ref_id, fields=fields, now=now)


def log_access(
    db: Session, candidate_id: UUID, employer_id: UUID, kind: AccessKind, ref_id: UUID | None, now: datetime
) -> None:
    disclosure.log_access(db, candidate_id, employer_id, kind, ref_id, now)


# --- автопауза (ставит и снимает модуль contact) ---------------------------------------------------------------------


def set_auto_pause(db: Session, candidate_id: UUID, at: datetime, until: datetime) -> None:
    row = profiles.ensure_profile(db, candidate_id, at)
    row.auto_paused_at = at
    row.auto_paused_until = until
    db.flush()


def clear_auto_pause(db: Session, candidate_id: UUID) -> None:
    row = db.get(CandidateProfile, candidate_id)
    if row is not None and (row.auto_paused_at is not None or row.auto_paused_until is not None):
        row.auto_paused_at = None
        row.auto_paused_until = None
        db.flush()


def auto_pause_until(db: Session, candidate_id: UUID) -> datetime | None:
    """Срок автопаузы как он записан: действует ли она сейчас, решает вызывающий (`now < срок`)."""
    row = db.get(CandidateProfile, candidate_id)
    return row.auto_paused_until if row is not None else None


def render_profile_pdf(model: ProfilePdfModel) -> bytes:
    """PDF-профиль из готовой модели. WeasyPrint подгружается при первом вызове."""
    from app.modules.profile.pdf.render import render_profile_pdf as render

    return render(model)


def demo_persona(db: Session, candidate_id: UUID) -> str | None:
    return profiles.demo_persona(db, candidate_id)


def purge_resume_results(db: Session, now: datetime) -> int:
    """Фоновая задача (раз в час): обнулить результаты разбора резюме старше 24 часов (Арх. 6.14, 10.5)."""
    cutoff = now - timedelta(hours=RESUME_RESULT_TTL_HOURS)
    result = db.execute(
        update(ResumeUpload)
        .where(ResumeUpload.result.is_not(None), ResumeUpload.created_at < cutoff)
        .values(result=None)
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


# --- функции записи: их вызывают роутер модуля, сид и demo; другие модули — нет -------------------------------------


def save_profile(db: Session, candidate_id: UUID, data: ProfileData, now: datetime) -> None:
    """Сохранить профиль, включая заявленные навыки."""
    profiles.save_profile(db, candidate_id, data, now)


def save_conditions(db: Session, candidate_id: UUID, data: ConditionsData, now: datetime) -> None:
    profiles.save_conditions(db, candidate_id, data, now)


def save_privacy(db: Session, candidate_id: UUID, data: PrivacyData, now: datetime) -> None:
    privacy_store.save(db, candidate_id, data, now)


def set_publication(
    db: Session, candidate_id: UUID, *, granted: bool, version: str | None, now: datetime, source: str = "user"
) -> VisibilityDTO:
    """Дать или отозвать согласие на публикацию и вернуть состояние показа.

    Выдача: 409 `no_category` (нет категории), 409 `profile_incomplete` (нет имени и фамилии), 409
    `consent_version_outdated` (версия не равна действующей). Отзыв версии не требует. `source` — `user` либо
    `seed`: сид не засоряет журнал аудита тысячами записей (необязательный параметр сверх Арх. 2.5).
    """
    if granted:
        if assessment.get_category(db, candidate_id) is None:
            raise ApiException(409, "no_category", "Сначала пройдите тест и получите категорию")
        if not profiles.is_complete(profiles.get_profile(db, candidate_id)):
            raise ApiException(409, "profile_incomplete", "Заполните имя и фамилию в профиле")
        current = identity.current_consent(ConsentKind.PUBLICATION)
        if version != current.version:
            raise ApiException(
                409, "consent_version_outdated", "Текст согласия обновился. Прочитайте новую версию и подтвердите её"
            )
        identity.grant_consent(db, candidate_id, ConsentKind.PUBLICATION, current.version, current.sha256, source, now)
    else:
        identity.revoke_consent(db, candidate_id, ConsentKind.PUBLICATION, now)
    return visibility_rules.for_candidate(db, candidate_id, now)


def set_demo_persona(db: Session, candidate_id: UUID, persona: DemoPersona | None) -> None:
    profiles.set_demo_persona(db, candidate_id, persona, clock.now(db))
