"""Таблицы модуля `identity` (Арх. 8.3): пользователи, сессии, заявки и токены, журнал лимитов, согласия, аудит.

Соглашения Арх. 8.1: первичные ключи — `uuid4` из Python, у журналов — `bigserial`; моменты времени пишет Python
(значений по умолчанию `now()` в DDL нет); внешние ключи на `app_user` — `ON DELETE CASCADE`, поэтому удаление
аккаунта — один `DELETE FROM app_user`.

Слой `core` читает `app_user` и `auth_session` по именам колонок (`core/security.py`), а фоновый цикл чистит
`login_attempt.at`, `auth_session.expires_at`, `email_token.expires_at` (`core/background.py`): эти имена — контракт.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_check
from app.shared.enums import ConsentKind, Role

PURPOSE_VERIFY_EMAIL = "verify_email"
PURPOSE_RESET_PASSWORD = "reset_password"

CONSENT_SOURCE_USER = "user"
CONSENT_SOURCE_SEED = "seed"
CONSENT_SOURCES = (CONSENT_SOURCE_USER, CONSENT_SOURCE_SEED)


class AppUser(Base):
    """Пользователь. `id` — он же `candidate_id` или `employer_id` во всех модулях."""

    __tablename__ = "app_user"
    __table_args__ = (
        enum_check("role", Role),
        CheckConstraint("email = lower(email)", name="email_lower"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    #: Пуст до подтверждения адреса: пароль лежит в заявке (`email_token.pending_password_hash`, Арх. 10.1).
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_adult_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    demo_key: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuthSession(Base):
    """Сессия входа: в базе только SHA-256 токена cookie `sid` (Арх. 10.1, 10.6)."""

    __tablename__ = "auth_session"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)


class EmailToken(Base):
    """Одноразовый токен письма: заявка на регистрацию (`verify_email`) либо сброс пароля (`reset_password`).

    Заявка на регистрацию несёт всё, что аккаунт получит при подтверждении: пароль, роль, а также согласие
    на обработку и отметку 18+ того, кто эту заявку подал. Так чужая регистрация на адрес не может ни подменить
    пароль владельца, ни «дать согласие» за него (Арх. 10.1; поправка R3-data-api-security-2): до подтверждения
    строк `consent` нет вовсе.
    """

    __tablename__ = "email_token"
    __table_args__ = (
        CheckConstraint(f"purpose IN ('{PURPOSE_VERIFY_EMAIL}', '{PURPOSE_RESET_PASSWORD}')", name="purpose"),
        Index(None, "user_id", "purpose", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    #: Хэш cookie `reg` браузера, начавшего регистрацию (Арх. 10.2).
    binding_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    pending_password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    pending_role: Mapped[str | None] = mapped_column(Text, nullable=True)
    pending_consent_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    pending_consent_sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    pending_consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pending_is_adult: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LoginAttempt(Base):
    """Общий журнал лимитов (`identity.throttle`) и попыток входа; строки старше 30 суток удаляет фоновый цикл.

    Набор значений `kind` открыт: счётчиком пользуются и другие модули (страницы банка, демо-режим), поэтому
    ограничение проверяет только вид значения, а не закрытый список. `email_sha256` — HMAC-SHA256 канонической
    формы адреса с ключом сервера (`emails.email_hash`): простой SHA-256 адреса подбирается по словарю и оставался бы
    идентификатором человека после удаления аккаунта (поправка R3-tz-compliance-7). Имя колонки — из Арх. 8.3.
    """

    __tablename__ = "login_attempt"
    __table_args__ = (
        CheckConstraint("kind ~ '^[a-z][a-z0-9_]{1,39}$'", name="kind_format"),
        Index(None, "email_sha256", "kind", "at"),
        Index(None, "ip", "kind", "at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    email_sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(Text, nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Consent(Base):
    """Согласие пользователя: версия и SHA-256 текста, момент, источник; отзыв ставит `revoked_at` (Арх. 10.5)."""

    __tablename__ = "consent"
    __table_args__ = (
        enum_check("kind", ConsentKind),
        CheckConstraint("source IN ('user', 'seed')", name="source"),
        # Действующее согласие каждого вида — одно; отозванные остаются как доказательство.
        Index(
            "uq_consent_user_id_kind_active",
            "user_id",
            "kind",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index(None, "user_id", "kind", "granted_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    text_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    """Событие безопасности (Арх. 10.8). Только идентификаторы; внешних ключей нет — запись переживает аккаунт."""

    __tablename__ = "audit_event"
    __table_args__ = (
        Index(None, "code", "at"),
        Index(None, "target_user_id", "at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    target_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
