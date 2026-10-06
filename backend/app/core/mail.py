"""Почта через очередь транзакции (Арх. 2.4, п. 4).

Сервис не отправляет письмо сам, а ставит его в очередь своей сессии::

    mail.enqueue(db, "verify_email", to=email, context={"link": link, "expires_hours": 24})

Письма копятся в `db.info["outbox"]` и уходят только после успешной фиксации транзакции: в запросе это делает
`core.db.TxRoute` (фоновая задача ответа), вне запроса — `core.db.session_scope` и фоновый цикл. При откате
и при повторе `run_in_tx` очередь сбрасывается, поэтому письмо не может уйти раньше данных или дважды.

Шаблоны — файлы Jinja2 `<имя>.txt` (первая строка — «Тема: …», затем пустая строка и текст) и необязательный
`<имя>.html`. Свои шаблоны модуль кладёт в `app/modules/<модуль>/mail_templates/`; шаблоны ядра
(`verify_email`, `already_registered`, `password_reset`, `reregister_cooldown`) лежат в `app/core/mail_templates/`.
В каждом шаблоне доступны `app_name` и `base_url`. Отправка — стандартной библиотекой (`smtplib`, `email.message`).
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound, select_autoescape
from sqlalchemy.orm import Session

from app.core.config import BACKEND_DIR, get_settings

log = logging.getLogger("app.mail")

OUTBOX_KEY = "outbox"
_SUBJECT_PREFIXES = ("Тема:", "Subject:")
_SMTP_TIMEOUT_S = 10


@dataclass(frozen=True)
class OutgoingMail:
    """Готовое к отправке письмо: шаблон уже отрисован в момент постановки в очередь."""

    template: str
    to: str
    subject: str
    text: str
    html: str | None = None
    context: Mapping[str, Any] = field(default_factory=dict)


Transport = Callable[[Sequence[OutgoingMail]], None]


# --------------------------------------------------------------------------------------------------------------------
# Шаблоны
# --------------------------------------------------------------------------------------------------------------------


def template_dirs() -> list[Path]:
    """Каталоги шаблонов: ядро и `mail_templates` каждого модуля, у которого он есть."""
    app_dir = BACKEND_DIR / "app"
    dirs = [app_dir / "core" / "mail_templates"]
    dirs += sorted(path for path in (app_dir / "modules").glob("*/mail_templates") if path.is_dir())
    return dirs


@lru_cache(maxsize=1)
def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader([str(path) for path in template_dirs()]),
        autoescape=select_autoescape(enabled_extensions=("html",), default_for_string=False),
        undefined=StrictUndefined,  # опечатка в имени переменной — ошибка в запросе, а не пустое место в письме
        keep_trailing_newline=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def reset_templates() -> None:
    """Забыть кэш шаблонов (тесты и появление нового каталога шаблонов без перезапуска)."""
    _environment.cache_clear()


def render(template: str, to: str, context: Mapping[str, Any] | None = None) -> OutgoingMail:
    """Отрисовать шаблон в письмо. Ошибка шаблона поднимается здесь, то есть внутри транзакции запроса."""
    settings = get_settings()
    variables: dict[str, Any] = {"app_name": settings.app_name, "base_url": settings.public_base_url}
    variables.update(context or {})
    env = _environment()
    raw = env.get_template(f"{template}.txt").render(variables).strip()
    first, _, rest = raw.partition("\n")
    subject = settings.app_name
    body = raw
    for prefix in _SUBJECT_PREFIXES:
        if first.startswith(prefix):
            subject = first[len(prefix) :].strip()
            body = rest.strip()
            break
    try:
        html: str | None = env.get_template(f"{template}.html").render(variables)
    except TemplateNotFound:
        html = None
    return OutgoingMail(
        template=template, to=to, subject=subject, text=body + "\n", html=html, context=dict(context or {})
    )


# --------------------------------------------------------------------------------------------------------------------
# Очередь транзакции
# --------------------------------------------------------------------------------------------------------------------


def enqueue(db: Session, template: str, to: str, context: Mapping[str, Any] | None = None) -> None:
    """Поставить письмо в очередь транзакции `db`. Уйдёт только после её успешной фиксации."""
    db.info.setdefault(OUTBOX_KEY, []).append(render(template, to, context))


def pending(db: Session) -> list[OutgoingMail]:
    """Письма, ждущие фиксации (без изъятия из очереди)."""
    return list(db.info.get(OUTBOX_KEY, ()))


def take(db: Session) -> list[OutgoingMail]:
    """Забрать очередь. Вызывается только после успешной фиксации."""
    return list(db.info.pop(OUTBOX_KEY, ()))


def discard(db: Session) -> None:
    """Сбросить очередь: транзакция откатилась или будет повторена."""
    dropped = db.info.pop(OUTBOX_KEY, None)
    if dropped:
        log.debug("очередь писем сброшена: %s", len(dropped))


def flush(db: Session) -> None:
    """Отправить очередь сразу (вне запроса). Вызывается только после успешной фиксации."""
    deliver(take(db))


# --------------------------------------------------------------------------------------------------------------------
# Отправка
# --------------------------------------------------------------------------------------------------------------------


def _mask(address: str) -> str:
    """Адрес для журнала: контакты в журнал приложения не пишутся (Арх. 10.8)."""
    local, _, domain = address.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


def build_message(item: OutgoingMail) -> EmailMessage:
    """Собрать `EmailMessage`: текстовая часть обязательна, HTML — если есть шаблон."""
    settings = get_settings()
    message = EmailMessage()
    message["Subject"] = item.subject
    message["From"] = formataddr((settings.app_name, settings.mail_from))
    message["To"] = item.to
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid(domain=settings.mail_from.rpartition("@")[2] or "localhost")
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(item.text)
    if item.html:
        message.add_alternative(item.html, subtype="html")
    return message


def _smtp_transport(messages: Sequence[OutgoingMail]) -> None:
    settings = get_settings()
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=_SMTP_TIMEOUT_S) as smtp:
        if settings.smtp_tls:
            smtp.starttls(context=ssl.create_default_context())
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        for item in messages:
            smtp.send_message(build_message(item))


_transport: Transport = _smtp_transport


def set_transport(transport: Transport | None) -> Transport:
    """Подменить отправку (тесты кладут письма в список). `None` возвращает SMTP. Отдаёт прежний транспорт."""
    global _transport
    previous = _transport
    _transport = transport or _smtp_transport
    return previous


def deliver(messages: Sequence[OutgoingMail]) -> None:
    """Отправить письма. Сбой почты не роняет ни запрос, ни фоновую задачу: данные уже зафиксированы."""
    if not messages:
        return
    try:
        _transport(messages)
    except Exception as exc:
        log.warning(
            "письма не отправлены (%s шт.: %s): %s: %s",
            len(messages),
            ", ".join(f"{item.template}→{_mask(item.to)}" for item in messages),
            type(exc).__name__,
            exc,
        )
    else:
        for item in messages:
            log.info("письмо отправлено: %s → %s", item.template, _mask(item.to))
