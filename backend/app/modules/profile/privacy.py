"""Настройки приватности и правило маскирования для демо-компаний (Арх. 4.14, 8.4, 10.3, 10.4).

Строка `privacy_settings` создаётся при первом сохранении; пока её нет, действуют значения по умолчанию
(`PrivacySettingsDTO`): показ обобщённых сведений включён, раскрытие каналов сверх e-mail выключено.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, any_, literal, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import InstrumentedAttribute, Session
from sqlalchemy.types import Text, Uuid

from app.modules.identity import service as identity
from app.modules.profile.dto import PrivacyData, PrivacySettingsDTO
from app.modules.profile.models import PrivacySettings

_BOOL_FIELDS = (
    "show_city",
    "show_experience",
    "show_declared_stack",
    "show_about",
    "show_fsp_summary",
    "reveal_phone",
    "reveal_telegram",
    "reveal_link",
    "reveal_fsp_details",
)


def in_ids(column: InstrumentedAttribute[UUID], ids: Iterable[UUID]) -> ColumnElement[bool]:
    """`column = ANY(:ids)` одним параметром-массивом: пул подбора — тысячи идентификаторов, а число параметров
    запроса ограничено.
    """
    return column == any_(literal(list(ids), ARRAY(Uuid(as_uuid=True))))


def _to_dto(row: PrivacySettings) -> PrivacySettingsDTO:
    values = {name: getattr(row, name) for name in _BOOL_FIELDS}
    return PrivacySettingsDTO(**values, hidden_domains=list(row.hidden_domains or []))


def load(db: Session, candidate_id: UUID) -> PrivacySettingsDTO:
    row = db.get(PrivacySettings, candidate_id)
    return _to_dto(row) if row is not None else PrivacySettingsDTO()


def load_many(db: Session, candidate_ids: Collection[UUID]) -> dict[UUID, PrivacySettingsDTO]:
    """Настройки пачкой; у кандидата без строки — значения по умолчанию."""
    result = {candidate_id: PrivacySettingsDTO() for candidate_id in candidate_ids}
    if result:
        for row in db.scalars(select(PrivacySettings).where(in_ids(PrivacySettings.user_id, result))):
            result[row.user_id] = _to_dto(row)
    return result


def save(db: Session, candidate_id: UUID, data: PrivacyData, now: datetime) -> PrivacySettingsDTO:
    """Полная замена переключателей; список доменов (P1) меняется, только если он передан явно."""
    row = db.get(PrivacySettings, candidate_id)
    if row is None:
        row = PrivacySettings(user_id=candidate_id, hidden_domains=[], updated_at=now)
        db.add(row)
    for name in _BOOL_FIELDS:
        setattr(row, name, getattr(data, name))
    if "hidden_domains" in data.model_fields_set:
        row.hidden_domains = list(data.hidden_domains)
    row.updated_at = now
    db.flush()
    return _to_dto(row)


# --- маскирование ----------------------------------------------------------------------------------------------------


def masked_candidates(db: Session, employer_id: UUID, candidate_ids: Collection[UUID]) -> set[UUID]:
    """Кандидаты, пара с которыми маскируется: работодатель — демо-аккаунт, кандидат — нет (Арх. 4.14, 10.4).

    Решает только признак аккаунта `app_user.is_demo` обеих сторон. Чип «демо» (`PoolProfile.is_demo`, он же
    ставится живому кандидату после быстрого демо-теста) в решении не участвует. Кандидат, которого `identity`
    не вернул, считается живым: ошибка в сторону маски безопаснее, чем в сторону данных.
    """
    ids = list(dict.fromkeys(candidate_ids))
    if not ids:
        return set()
    employer = identity.users(db, [employer_id]).get(employer_id)
    if employer is None or not employer.is_demo:
        return set()
    candidates = identity.users(db, ids)
    return {
        candidate_id for candidate_id in ids if not (candidates.get(candidate_id) and candidates[candidate_id].is_demo)
    }


def is_masked_pair(db: Session, employer_id: UUID, candidate_id: UUID) -> bool:
    return candidate_id in masked_candidates(db, employer_id, [candidate_id])


# --- «не показывать компаниям» (P1) ----------------------------------------------------------------------------------


def hidden_from_employer(db: Session, employer_id: UUID, candidate_ids: Collection[UUID]) -> set[UUID]:
    """Кандидаты, скрывшие профиль от домена почты этого работодателя (Арх. 10.4).

    Сравнивается домен адреса аккаунта работодателя, а не введённое им название компании.
    """
    ids = list(dict.fromkeys(candidate_ids))
    if not ids:
        return set()
    employer = identity.users(db, [employer_id]).get(employer_id)
    if employer is None or "@" not in employer.email:
        return set()
    domain = employer.email.rsplit("@", 1)[1].strip().lower()
    if not domain:
        return set()
    query = select(PrivacySettings.user_id).where(
        in_ids(PrivacySettings.user_id, ids),
        PrivacySettings.hidden_domains.contains(literal([domain], ARRAY(Text))),
    )
    return set(db.scalars(query))
