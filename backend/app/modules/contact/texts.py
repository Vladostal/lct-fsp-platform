"""Готовые подписи и тексты модуля `contact` (Арх. 9.1: подписи формирует сервер; приложение C, §9.5; E, §6.2, §6.4).

Тексты ошибок здесь — запасные: клиент берёт текст по коду из своего словаря и подставляет `params`. Сервер
отдаёт их в `ApiError.message` и в `blockers[].message` предпроверки. В текстах для работодателя нет ни цифр
минимума кандидата, ни названия несовпавшего условия, ни счётчика попыток (Арх. 4.6).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from app.modules.contact import constants as c
from app.shared.enums import (
    ComplaintReason,
    DeclineReason,
    DiscloseField,
    EventCode,
    InvitationStatus,
    TrustLevel,
    WorkFormat,
)
from app.shared.text import count_phrase, fmt_date, fmt_money

STATUS_LABELS_EMPLOYER: dict[InvitationStatus, str] = {
    InvitationStatus.SENT: "Отправлено",
    InvitationStatus.VIEWED: "Просмотрено",
    InvitationStatus.ACCEPTED: "Принято",
    InvitationStatus.DECLINED: "Отклонено",
    InvitationStatus.EXPIRED: "Срок истёк",
    InvitationStatus.WITHDRAWN: "Отозвано",
    InvitationStatus.BOUNCED: "Не доставлено",
}

STATUS_LABELS_CANDIDATE: dict[InvitationStatus, str] = {
    InvitationStatus.SENT: "Новое",
    InvitationStatus.VIEWED: "Ждёт ответа",
    InvitationStatus.ACCEPTED: "Принято",
    InvitationStatus.DECLINED: "Отклонено вами",
    InvitationStatus.EXPIRED: "Срок истёк",
    InvitationStatus.WITHDRAWN: "Отозвано работодателем",
}

DECLINE_REASON_LABELS: dict[DeclineReason, str] = {
    DeclineReason.SALARY: "Зарплата",
    DeclineReason.STACK: "Задачи или стек",
    DeclineReason.FORMAT: "Формат работы",
    DeclineReason.COMPANY: "Компания",
    DeclineReason.NOT_LOOKING: "Сейчас не ищу",
    DeclineReason.OTHER: "Другое",
}

WORK_FORMAT_LABELS: dict[WorkFormat, str] = {
    WorkFormat.OFFICE: "офис",
    WorkFormat.HYBRID: "гибрид",
    WorkFormat.REMOTE: "удалённо",
}

TRUST_LABELS: dict[TrustLevel, str] = {
    TrustLevel.BASIC: "Компания подтвердила только e-mail",
    TrustLevel.VERIFIED: "Компания проверена",
}

DISCLOSE_LABELS: dict[DiscloseField, str] = {
    DiscloseField.EMAIL: "E-mail",
    DiscloseField.PHONE: "Телефон",
    DiscloseField.TELEGRAM: "Telegram",
    DiscloseField.LINK: "Ссылка",
    DiscloseField.FSP_DETAILS: "Достижения ФСП подробно",
}

COMPLAINT_REASON_LABELS: dict[ComplaintReason, str] = {
    ComplaintReason.FAKE_OFFER: "Предложение не настоящее",
    ComplaintReason.TERMS_MISMATCH: "Условия не совпали с приглашением",
    ComplaintReason.SPAM: "Спам",
    ComplaintReason.RUDE: "Грубость",
    ComplaintReason.OTHER: "Другое",
}

#: Подписи событий таймлайна: (для работодателя, для кандидата).
EVENT_LABELS: dict[EventCode, tuple[str, str]] = {
    EventCode.SENT: ("Приглашение отправлено", "Приглашение получено"),
    EventCode.BOUNCED: ("Не доставлено: условия не совпали", ""),
    EventCode.VIEWED: ("Кандидат открыл приглашение", "Вы открыли приглашение"),
    EventCode.ACCEPTED: ("Кандидат принял приглашение", "Вы приняли приглашение"),
    EventCode.DECLINED: ("Кандидат отклонил приглашение", "Вы отклонили приглашение"),
    EventCode.EXPIRED: ("Срок ответа истёк", "Срок ответа истёк"),
    EventCode.WITHDRAWN: ("Вы отозвали приглашение", "Работодатель отозвал приглашение"),
    EventCode.REVISED: ("Отправлено пересмотренное приглашение", "Работодатель прислал пересмотренное приглашение"),
    EventCode.CONTACT_MARKED: ("Вы отметили: связались", "Работодатель отметил: связались"),
    EventCode.CONTACT_CONFIRMED: ("Кандидат подтвердил контакт", "Вы подтвердили контакт"),
    EventCode.CONTACT_DENIED: ("Кандидат сообщил: связи не было", "Вы сообщили: связи не было"),
}

#: Что работодатель видел до согласия — запасной список для приглашения без сохранённого объяснения (Арх. 4.9).
DEFAULT_EMPLOYER_SAW: tuple[str, ...] = ("категорию и интервал уровня", "подтверждённые навыки")
#: То же для кандидата с заявленным грейдом (уровня по тесту нет): «категории» и «интервала уровня» он не имеет.
DECLARED_EMPLOYER_SAW: tuple[str, ...] = ("профиль и заявленный грейд",)

#: Заглушка вместо свободного текста живого кандидата для демо-компании (Арх. 4.14).
MASKED_TEXT = "Скрыто в демо-режиме"

DEMO_INVITATION_NOTE = "Это демонстрационное приглашение: так выглядит выход работодателя на контакт."

MESSAGES: dict[str, str] = {
    "company_profile_incomplete": "Сначала заполните профиль компании",
    "sending_frozen": "Отправка приглашений приостановлена до разбора жалоб",
    "candidate_unavailable": "Кандидат сейчас недоступен для приглашений",
    "format_not_accepted": "Кандидат не рассматривает этот формат работы",
    "revision_not_allowed": "Пересмотренное приглашение этому кандидату уже отправлено или срок вышел",
    "revision_below_condition": "Условия должны быть не хуже названных кандидатом",
    "revision_below_bounced": "Нижняя граница вилки должна быть выше, чем в недоставленном приглашении",
    "active_invitation_exists": "Этому кандидату уже отправлено приглашение, он ещё не ответил",
    "conditions_mismatch": "Условия не совпали с ожиданиями кандидата. Повторить попытку можно с {until}",
    "pair_cooldown": "Новое приглашение этому кандидату можно отправить с {until}",
    "daily_limit_exceeded": "Достигнут суточный лимит приглашений. Следующее можно отправить через {retry_after}",
    "demo_sender_restricted": "Демо-компания не приглашает настоящих пользователей. Зарегистрируйте свою компанию",
    "invitation_not_actionable": "Действие недоступно: приглашение в статусе «{status_label}»",
    "disclose_invalid": "Выберите хотя бы один способ связи, указанный в профиле",
    "condition_invalid": (
        "Проверьте условие: сумма должна быть выше нижней границы вилки, формат — отличаться от предложенного"
    ),
    "complaint_exists": "Жалоба на это приглашение уже отправлена",
}

_FIELD_MESSAGES: dict[str, str] = {
    "title": f"Заголовок — от {c.TITLE_MIN} до {c.TITLE_MAX} знаков",
    "description": f"Описание предложения — от {c.DESCRIPTION_MIN} до {c.DESCRIPTION_MAX} знаков",
    "message": f"Сообщение — не длиннее {c.MESSAGE_MAX} знаков",
    "city": "Укажите город: он обязателен для офиса и гибрида",
    "city_long": f"Название города — не длиннее {c.CITY_MAX} знаков",
    "comment": f"Комментарий — не длиннее {c.DECLINE_COMMENT_MAX} знаков",
    "complaint_comment": f"Комментарий — не длиннее {c.COMPLAINT_COMMENT_MAX} знаков",
    "idempotency_key": "Ключ идемпотентности должен быть UUID",
    "category": "Укажите категорию в виде «специализация:грейд»",
    "candidate_ids": f"Передайте от 1 до {c.PAIR_STATES_MAX_IDS} идентификаторов кандидатов через запятую",
    "need_id": "Неверный идентификатор потребности",
}


def field_message(key: str) -> str:
    """Текст ошибки поля по ключу словаря этого файла."""
    return _FIELD_MESSAGES[key]


def _duration(seconds: int) -> str:
    """«3 ч 20 мин» — для суточного лимита."""
    hours, minutes = divmod(max(0, seconds) // 60, 60)
    if hours and minutes:
        return f"{hours} ч {minutes} мин"
    if hours:
        return f"{hours} ч"
    return f"{max(1, minutes)} мин"


def message(code: str, params: Mapping[str, Any] | None = None) -> str:
    """Текст ошибки или блокера по коду с подстановкой параметров; дат — в формате `ДД.ММ.ГГГГ`."""
    template = MESSAGES.get(code, code)
    values: dict[str, Any] = {}
    for key, value in (params or {}).items():
        if key == "retry_after" and isinstance(value, int):
            values[key] = _duration(value)
        elif isinstance(value, datetime):
            values[key] = fmt_date(value)
        elif isinstance(value, str) and key == "until":
            try:
                values[key] = fmt_date(datetime.fromisoformat(value))
            except ValueError:
                values[key] = value
        else:
            values[key] = value
    return template.format_map(_Missing(values))


class _Missing(dict[str, Any]):
    """Параметр, которого нет в `params`, подставляется прочерком: текст остаётся читаемым."""

    def __missing__(self, key: str) -> str:
        return "—"


def salary_note(stated: list[tuple[int, int]], hint: tuple[int, int] | None) -> str:
    """Подсказка по зарплате в сводке причин (Арх. 4.11): только суммы, которые кандидаты назвали сами.

    Текст без кнопки и без счётчика прироста; медиана вилок категории добавляется, когда она есть.
    """
    parts: list[str] = []
    if stated:
        lowest = min(value for value, _ in stated)
        total = sum(count for _, count in stated)
        parts.append(
            "Возможно, вилка ниже ожиданий: "
            + count_phrase(total, "кандидат назвал", "кандидата назвали", "кандидатов назвали")
            + f" сумму от {fmt_money(lowest)}"
        )
    else:
        parts.append("Возможно, вилка ниже ожиданий: кандидаты отклоняли приглашения из-за зарплаты")
    if hint is not None:
        parts.append(f"Ориентир рынка по принятым приглашениям категории: {fmt_money(hint[0])} – {fmt_money(hint[1])}")
    return ". ".join(parts) + "."
