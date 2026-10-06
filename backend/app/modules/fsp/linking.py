"""Привязка ФСП ID: начало потока, возврат (callback), отвязка, привязка для сида (Арх. 7.4; приложение D, §3).

Поток — OIDC authorization code + PKCE (S256), одинаковый для обоих адаптеров. Состояние потока живёт в таблице
`fsp_link_attempt` 10 минут; `state` хранится только хэшем, `code_verifier` затирается после возврата. Токены
ФСП ID нигде не сохраняются. Согласие `fsp_data` пишется через `identity.grant_consent`.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import delete, event, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.core.errors import ApiException
from app.modules.fsp import consent_text, sync
from app.modules.fsp import constants as c
from app.modules.fsp.gateway import factory
from app.modules.fsp.gateway.base import (
    AuthorizationRequest,
    ExportNotModified,
    ExportNotRegistered,
    ExportOk,
    FspAuthError,
    FspContractError,
    FspGateway,
    FspGrantRevoked,
    FspUnavailable,
)
from app.modules.fsp.models import (
    ExternalIdentity,
    FspAchievement,
    FspCredential,
    FspLinkAttempt,
    FspSnapshot,
    FspSyncAttempt,
)
from app.modules.fsp.schemas import FspLinkStartRequest, FspLinkStartView
from app.modules.identity import service as identity_service
from app.shared.enums import ConsentKind

log = logging.getLogger("app.fsp")

UnlinkReasonName = Literal["user", "revoked", "minor", "account_deleted", "demo_reset"]
NOTICE_OUTCOME: dict[str, str] = {"revoked": c.OUTCOME_UNLINKED_REVOKED, "minor": c.OUTCOME_UNLINKED_MINOR}


@dataclass(frozen=True, slots=True)
class LinkOutcome:
    """Итог callback: значение `result` и, для `error`, `reason`; `login` — нет сессии, нужно войти."""

    result: str
    reason: str | None = None

    def query(self) -> str:
        return f"result={self.result}" + (f"&reason={self.reason}" if self.reason else "")


def _error(reason: str) -> LinkOutcome:
    return LinkOutcome("error", reason)


def hash_state(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def redirect_uri() -> str:
    """`redirect_uri` берётся только из настройки, никогда из запроса (Арх. 7.4)."""
    return get_settings().public_base_url.rstrip("/") + c.CALLBACK_PATH


def mask_fsp_id(fsp_id: str) -> str:
    """В журнале и аудите — последние 4 символа `fsp_id` (Арх. 10.7)."""
    return "…" + fsp_id[-4:]


_PENDING_KEY = "fsp_after_commit"


def _after_commit(db: Session, action: Callable[[], None]) -> None:
    """Выполнить `action` после фиксации сессии (best-effort); откат отменяет действие.

    Нужно для `revoke_grant`: сетевой вызов внутри транзакции держал бы блокировки, а при откате снимать
    разрешение было бы незачем (Арх. 7.4; поправка R3-data-api-security-7). Очередь действий лежит в `db.info`,
    слушатели сессии ставятся один раз: снимать их во время рассылки события нельзя.
    """
    if _PENDING_KEY not in db.info:
        db.info[_PENDING_KEY] = []

        def on_commit(session: Session) -> None:
            pending: list[Callable[[], None]] = session.info[_PENDING_KEY]
            actions, pending[:] = list(pending), []
            for item in actions:
                try:
                    item()
                except Exception as exc:
                    log.warning("не удалось снять разрешение в реестре ФСП: %s", type(exc).__name__)

        def on_rollback(session: Session) -> None:
            session.info[_PENDING_KEY][:] = []

        event.listen(db, "after_commit", on_commit)
        event.listen(db, "after_rollback", on_rollback)
    db.info[_PENDING_KEY].append(action)


# ---------------------------------------------------------------------------------------------------------------------
# Начало потока
# ---------------------------------------------------------------------------------------------------------------------


def start_link(db: Session, user_id: UUID, body: FspLinkStartRequest) -> FspLinkStartView:
    """`POST /fsp/link/start`: проверки, погашение прежних попыток, `state`, `nonce`, PKCE (приложение D, §3.2)."""
    settings = get_settings()
    if not body.accept:
        raise ApiException(422, "fsp_consent_required")
    version = consent_text.current_version()
    if body.consent_version != version:
        raise ApiException(409, "fsp_consent_outdated", params={"version": version})
    if db.scalar(select(ExternalIdentity.id).where(ExternalIdentity.user_id == user_id)) is not None:
        raise ApiException(409, "fsp_link_exists")
    now = clock.real_now()
    window = timedelta(minutes=c.LINK_ATTEMPTS_WINDOW_MINUTES)
    recent = list(
        db.scalars(
            select(FspLinkAttempt.created_at)
            .where(FspLinkAttempt.user_id == user_id, FspLinkAttempt.created_at > now - window)
            .order_by(FspLinkAttempt.created_at)
        )
    )
    if len(recent) >= c.LINK_ATTEMPTS_LIMIT:
        retry_after = max(1, int((recent[0] + window - now).total_seconds() + 0.999))
        raise ApiException(
            429, "fsp_too_many_attempts", params={"retry_after": retry_after}, headers={"Retry-After": str(retry_after)}
        )
    try:
        gateway = factory.get_fsp_gateway()
    except FspUnavailable as exc:
        raise ApiException(503, "fsp_unavailable") from exc

    # Прежние неиспользованные попытки гасятся, а не удаляются: иначе не сработал бы лимит выше.
    db.execute(
        update(FspLinkAttempt)
        .where(FspLinkAttempt.user_id == user_id, FspLinkAttempt.used_at.is_(None))
        .values(used_at=now, outcome="superseded", code_verifier="")
    )
    db.execute(
        delete(FspLinkAttempt).where(
            FspLinkAttempt.user_id == user_id,
            FspLinkAttempt.created_at < now - timedelta(hours=c.LINK_ATTEMPT_RETENTION_HOURS),
        )
    )
    db.execute(delete(FspSyncAttempt).where(FspSyncAttempt.user_id == user_id, FspSyncAttempt.identity_id.is_(None)))

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(16)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()
    expires_at = now + timedelta(minutes=c.LINK_ATTEMPT_TTL_MINUTES)
    db.add(
        FspLinkAttempt(
            user_id=user_id,
            state_hash=hash_state(state),
            nonce=nonce,
            code_verifier=verifier,
            redirect_uri=redirect_uri(),
            provider_mode=gateway.mode,
            consent_version=version,
            consent_text_sha256=consent_text.text_sha256(),
            created_at=now,
            expires_at=expires_at,
        )
    )
    db.flush()
    url = gateway.authorization_url(
        AuthorizationRequest(
            state=state,
            nonce=nonce,
            code_challenge=challenge,
            redirect_uri=redirect_uri(),
            scope=settings.fsp_oidc_scope,
        )
    )
    return FspLinkStartView(authorize_url=url, expires_at=expires_at)


# ---------------------------------------------------------------------------------------------------------------------
# Возврат из ФСП ID
# ---------------------------------------------------------------------------------------------------------------------


def _set_outcome(db: Session, attempt_id: UUID, outcome: str) -> None:
    db.execute(update(FspLinkAttempt).where(FspLinkAttempt.id == attempt_id).values(outcome=outcome))


def _is_linked(db: Session, user_id: UUID) -> bool:
    return db.scalar(select(ExternalIdentity.id).where(ExternalIdentity.user_id == user_id)) is not None


def finish_link(
    db: Session, session_user_id: UUID | None, *, code: str | None, state: str | None, error: str | None
) -> LinkOutcome:
    """`GET /fsp/link/callback`: проверка `state`, гашение попытки, обмен кода, конфликт, первая выгрузка, привязка.

    Всегда возвращает исход, а не исключение: ответ — 302 на `/candidate/settings/fsp?result=…`. Исход `login` —
    сессии нет: попытка не гасится, пользователь начнёт заново после входа (приложение D, §3.3).
    """
    if not state:
        return _error("state")
    attempt = db.scalar(select(FspLinkAttempt).where(FspLinkAttempt.state_hash == hash_state(state)))
    if attempt is None:
        return _error("state")
    if session_user_id is None:
        return LinkOutcome("login")
    if attempt.user_id != session_user_id:
        identity_service.audit(
            db, "fsp.link.user_mismatch", actor_user_id=session_user_id, target_user_id=attempt.user_id
        )
        return _error("state")

    user_id = attempt.user_id
    verifier, nonce, uri = attempt.code_verifier, attempt.nonce, attempt.redirect_uri
    consent_version, consent_sha, started_at = attempt.consent_version, attempt.consent_text_sha256, attempt.created_at
    now = clock.real_now()
    claimed = db.execute(
        update(FspLinkAttempt)
        .where(FspLinkAttempt.id == attempt.id, FspLinkAttempt.used_at.is_(None), FspLinkAttempt.expires_at > now)
        .values(used_at=now, code_verifier="")
        .returning(FspLinkAttempt.id)
        .execution_options(synchronize_session=False)
    ).first()
    if claimed is None:
        return LinkOutcome("linked") if _is_linked(db, user_id) else _error("expired")
    attempt_id = attempt.id
    db.commit()  # попытка погашена и видна; сетевые вызовы ниже не держат блокировок

    if error:
        outcome = LinkOutcome("cancelled") if error == "access_denied" else _error("auth")
        _set_outcome(db, attempt_id, "cancelled" if outcome.result == "cancelled" else "auth_error")
        return outcome
    if not code:
        _set_outcome(db, attempt_id, "auth_error")
        return _error("auth")
    try:
        gateway = factory.get_fsp_gateway()
        identity = gateway.exchange_code(code=code, code_verifier=verifier, redirect_uri=uri, nonce=nonce)
    except FspAuthError:
        _set_outcome(db, attempt_id, "auth_error")
        return _error("auth")
    except FspUnavailable:
        _set_outcome(db, attempt_id, "unavailable")
        return _error("unavailable")
    except FspContractError:
        _set_outcome(db, attempt_id, "auth_error")
        return _error("auth")

    if _is_linked(db, user_id):  # двойной щелчок и две вкладки: привязка уже создана
        _set_outcome(db, attempt_id, "linked")
        return LinkOutcome("linked")
    if _conflict(db, user_id, gateway, identity.subject, identity.fsp_id):
        _set_outcome(db, attempt_id, "conflict")
        identity_service.audit(db, "fsp.link.conflict", actor_user_id=user_id, target_user_id=user_id)
        return LinkOutcome("already_linked")

    started = clock.real_now()
    sync_failure: str | None = None
    fetched: ExportOk | ExportNotRegistered | ExportNotModified | None = None
    try:
        fetched = gateway.fetch_export(identity.fsp_id, user_token=identity.user_token)
    except (FspAuthError, FspGrantRevoked):
        _set_outcome(db, attempt_id, "auth_error")
        return _error("auth")
    except FspUnavailable:
        sync_failure = c.OUTCOME_FAILED_UNAVAILABLE
    except FspContractError:
        sync_failure = c.OUTCOME_FAILED_CONTRACT
    if isinstance(fetched, ExportOk) and not fetched.export.athlete.is_adult:
        _best_effort_revoke(gateway, identity.fsp_id)
        _set_outcome(db, attempt_id, "minor")
        _apply_minor_consequences(db, user_id)
        return LinkOutcome("minor")

    now = clock.real_now()
    row = ExternalIdentity(
        user_id=user_id,
        provider=c.PROVIDER,
        issuer=identity.issuer,
        subject=identity.subject,
        fsp_id=identity.fsp_id,
        provider_mode=gateway.mode,
        claims={
            key: value
            for key, value in {"iss": identity.issuer, "sub": identity.subject, "fsp_id": identity.fsp_id}.items()
            if key in c.CLAIMS_WHITELIST
        },
        consent_version=consent_version,
        linked_at=now,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:  # гонка двух аккаунтов за один ФСП ID
        _set_outcome(db, attempt_id, "conflict")
        return LinkOutcome("already_linked")
    identity_service.grant_consent(
        db, user_id, ConsentKind.FSP_DATA, consent_version, consent_sha, c.CONSENT_SOURCE_USER, started_at
    )
    attempt_row = FspSyncAttempt(
        user_id=user_id, identity_id=row.id, trigger="link", started_at=started, finished_at=now
    )
    if fetched is not None:
        attempt_row.outcome = sync.apply_export(db, row, fetched, now)
    else:
        attempt_row.outcome = sync_failure
    db.add(attempt_row)
    _set_outcome(db, attempt_id, "linked")
    identity_service.audit(
        db,
        "fsp.linked",
        actor_user_id=user_id,
        target_user_id=user_id,
        params={"mode": gateway.mode, "fsp_id": mask_fsp_id(identity.fsp_id), "history": fetched is not None},
    )
    db.flush()
    return LinkOutcome("linked")


def _conflict(db: Session, user_id: UUID, gateway: FspGateway, subject: str, fsp_id: str) -> bool:
    """Тот же ФСП ID (по `subject` или по `fsp_id`) уже привязан к другому аккаунту."""
    other = db.scalar(
        select(ExternalIdentity.id).where(
            ExternalIdentity.provider == c.PROVIDER,
            ExternalIdentity.issuer == gateway.issuer,
            ExternalIdentity.user_id != user_id,
            or_(ExternalIdentity.subject == subject, ExternalIdentity.fsp_id == fsp_id),
        )
    )
    return other is not None


def _best_effort_revoke(gateway: FspGateway, fsp_id: str) -> None:
    try:
        gateway.revoke_grant(fsp_id)
    except Exception as exc:
        log.warning("разрешение ФСП %s не снято: %s", mask_fsp_id(fsp_id), type(exc).__name__)


def _apply_minor_consequences(db: Session, user_id: UUID) -> None:
    """Реестр сообщил, что кандидату нет 18 лет (поправка R3-data-api-security-3).

    Платформа — сервис для совершеннолетних: отзывается согласие на публикацию (профиль перестаёт быть виден
    работодателям), в аудит пишется событие без персональных данных. Кандидату интерфейс показывает сообщение
    с предложением удалить аккаунт. Запрет повторной публикации — на стороне `identity` и `profile` (см. запрос).
    """
    now = clock.real_now()
    identity_service.revoke_consent(db, user_id, ConsentKind.PUBLICATION, now)
    identity_service.audit(db, "fsp.minor_detected", actor_user_id=None, target_user_id=user_id)


# ---------------------------------------------------------------------------------------------------------------------
# Отвязка
# ---------------------------------------------------------------------------------------------------------------------


def unlink(db: Session, user_id: UUID, *, reason: UnlinkReasonName) -> None:
    """Отвязка: сведения удаляются в одной транзакции, разрешение снимается после фиксации (приложение D, §3.5).

    Привязки нет — выход (операция идемпотентна). Согласие `fsp_data` получает `revoked_at`, запись остаётся
    как доказательство. Для `revoked` и `minor` остаётся одна строка-уведомление (`fsp_sync_attempt` без
    `identity_id`), которую кандидат увидит один раз; при `minor` дополнительно отзывается согласие на публикацию.
    """
    identity = db.scalar(select(ExternalIdentity).where(ExternalIdentity.user_id == user_id))
    if identity is None:
        return
    now = clock.real_now()
    fsp_id, mode = identity.fsp_id, identity.provider_mode
    _delete_rows(db, user_id, identity)
    if reason != "account_deleted":
        identity_service.revoke_consent(db, user_id, ConsentKind.FSP_DATA, now)
    identity_service.audit(
        db,
        "fsp.unlinked",
        actor_user_id=user_id if reason == "user" else None,
        target_user_id=user_id,
        params={"reason": reason, "mode": mode, "fsp_id": mask_fsp_id(fsp_id)},
    )
    outcome = NOTICE_OUTCOME.get(reason)
    if outcome is not None:
        db.add(
            FspSyncAttempt(
                user_id=user_id, identity_id=None, trigger="auto", started_at=now, finished_at=now, outcome=outcome
            )
        )
    if reason == "minor":
        _apply_minor_consequences(db, user_id)
    _after_commit(db, lambda: _revoke_in_registry(fsp_id))


def _delete_rows(db: Session, user_id: UUID, identity: ExternalIdentity) -> None:
    db.execute(delete(FspAchievement).where(FspAchievement.user_id == user_id))
    db.execute(delete(FspCredential).where(FspCredential.user_id == user_id))
    db.execute(delete(FspSnapshot).where(FspSnapshot.user_id == user_id))
    db.execute(delete(FspSyncAttempt).where(FspSyncAttempt.user_id == user_id))
    db.execute(delete(FspLinkAttempt).where(FspLinkAttempt.user_id == user_id))
    db.delete(identity)
    db.flush()


def _revoke_in_registry(fsp_id: str) -> None:
    """Снять разрешение в реестре: две попытки; недоступность реестра отвязку и удаление аккаунта не блокирует."""
    last: Exception | None = None
    for _ in range(2):
        try:
            factory.get_fsp_gateway().revoke_grant(fsp_id)
            return
        except Exception as exc:
            last = exc
    log.warning("разрешение ФСП %s не снято: %s", mask_fsp_id(fsp_id), type(last).__name__)


def on_user_delete(db: Session, user_id: UUID) -> None:
    """Обработчик `USER_CLEANUP` (Арх. 2.6; поправка R3-data-api-security-7).

    Читает привязку, удаляет строки модуля в транзакции удаления аккаунта, а разрешение в реестре снимает после
    фиксации по best-effort: недоступный реестр удаление не блокирует.
    """
    unlink(db, user_id, reason="account_deleted")


def seed_link(db: Session, user_id: UUID, fsp_id: str) -> None:
    """Привязать синтетического кандидата к спортсмену демо-реестра — тем же кодом, что обычный поток, с шага 7.

    `external_identity` (издатель шлюза, `subject = fsp_id`), согласие `fsp_data` с источником `seed`, разрешение
    в реестре с пометкой `seed`, первая синхронизация через шлюз (Арх. 7.5, триггер `seed`).
    """
    gateway = factory.get_fsp_gateway()
    existing = db.scalar(select(ExternalIdentity).where(ExternalIdentity.user_id == user_id))
    if existing is not None:
        if existing.fsp_id == fsp_id:
            return
        raise ValueError("seed_link: у пользователя уже есть привязка к другому ФСП ID")
    now = clock.real_now()
    version = consent_text.current_version()
    identity = ExternalIdentity(
        user_id=user_id,
        provider=c.PROVIDER,
        issuer=gateway.issuer,
        subject=fsp_id,
        fsp_id=fsp_id,
        provider_mode=gateway.mode,
        claims={"iss": gateway.issuer, "sub": fsp_id, "fsp_id": fsp_id},
        consent_version=version,
        linked_at=now,
    )
    db.add(identity)
    db.flush()
    identity_service.grant_consent(
        db, user_id, ConsentKind.FSP_DATA, version, consent_text.text_sha256(), c.CONSENT_SOURCE_SEED, now
    )
    register = getattr(gateway, "seed_grant", None)
    if register is not None:
        register(fsp_id)
    db.flush()
    started = clock.real_now()
    try:
        fetched = gateway.fetch_export(fsp_id)
    except (FspUnavailable, FspContractError, FspAuthError, FspGrantRevoked) as exc:
        raise RuntimeError(f"seed_link: первая выгрузка не удалась: {type(exc).__name__}") from exc
    if isinstance(fetched, ExportOk) and not fetched.export.athlete.is_adult:
        raise ValueError("seed_link: спортсмен несовершеннолетний, привязка недопустима")
    if isinstance(fetched, ExportNotModified):
        raise RuntimeError("seed_link: реестр ответил 304 на первый запрос")
    finished = clock.real_now()
    outcome = sync.apply_export(db, identity, fetched, finished)
    db.add(
        FspSyncAttempt(
            user_id=user_id,
            identity_id=identity.id,
            trigger="seed",
            started_at=started,
            finished_at=finished,
            outcome=outcome,
        )
    )
    db.flush()


def demo_reset(db: Session, user_ids: list[UUID]) -> None:
    """Сброс демо-данных: отвязка без уведомления (привязки пересоздаёт сид)."""
    for user_id in user_ids:
        unlink(db, user_id, reason="demo_reset")
