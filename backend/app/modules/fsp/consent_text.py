"""Текст согласия на получение сведений из реестра ФСП (Арх. 7.4, 10.5; приложение D, §3.4).

Версия — `FSP_CONSENT_VERSION` (по умолчанию `fsp-data-1`); SHA-256 текста записывается вместе с согласием
`fsp_data` (`identity.grant_consent`). Судейство и членство в сборной в MVP не запрашиваются (Арх. 15.1, № 47),
поэтому текст про них не говорит: согласие должно описывать ровно то, что платформа получает.
"""

from __future__ import annotations

import hashlib

from app.core.config import get_settings
from app.modules.fsp.constants import CONSENT_DATA_ITEMS
from app.modules.fsp.schemas import FspConsentView

CONSENT_TEXT = (
    "Я даю согласие на получение из реестра Федерации спортивного программирования и обработку сведений обо мне: "
    "участие в соревнованиях (название, дисциплина, уровень, даты, формат), результат (место, число участников, "
    "баллы), название команды и моя роль в ней, спортивные разряды и звания.\n"
    "Цель — подтверждение квалификации в моём профиле и учёт при подборе. Работодатели видят эти сведения "
    "в обобщённом виде; подробно — только работодатель, чьё приглашение я принял(а) или на чью вакансию я "
    "откликнулся(лась), в пределах моих настроек приватности.\n"
    "Не запрашиваются: дата рождения, документы, контакты, сведения о здоровье, данные других участников команд.\n"
    "Согласие действует до отвязки ФСП ID. Отвязка удаляет полученные сведения."
)


def text_sha256() -> str:
    return hashlib.sha256(CONSENT_TEXT.encode("utf-8")).hexdigest()


def current_version() -> str:
    return get_settings().fsp_consent_version


def consent_view() -> FspConsentView:
    """Ответ `GET /fsp/consent`."""
    return FspConsentView(
        version=current_version(), text=CONSENT_TEXT, text_sha256=text_sha256(), data_items=list(CONSENT_DATA_ITEMS)
    )
