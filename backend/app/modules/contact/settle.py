"""Материализация истечения и блокировки строк состояния (Арх. 4.4).

Здесь всё, что касается порядка блокировок модуля `contact`:

1. строка `employer_contact_state` (только в операциях работодателя);
2. строки `candidate_contact_state` — **одним запросом** по возрастанию `candidate_id`;
3. строки `invitation`.

Операция сначала вычисляет всё множество кандидатов, которых затронет, блокирует его целиком (`lock_candidates`)
и передаёт в `settle` как `locked`: повторного захвата строк кандидатов внутри транзакции нет, поэтому
перекрёстные отправки двух работодателей не дают взаимной блокировки. Любой переход статуса приглашения
выполняется под блокировкой строки состояния его кандидата, поэтому статус, прочитанный под этой блокировкой,
до конца транзакции не изменится.

Читающие эндпоинты эти функции не вызывают: они показывают `rules.effective_status` (Арх. 4.4, 10.1).
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.modules.contact import constants as c
from app.modules.contact import rules
from app.modules.contact.models import CandidateContactState, EmployerContactState, Invitation, InvitationEvent
from app.modules.identity import service as identity_service
from app.modules.profile import service as profile_service
from app.shared.enums import EventActor, EventCode, InvitationStatus

Responder = Callable[[dict[UUID, CandidateContactState]], object]


def add_event(
    db: Session,
    inv: Invitation,
    code: EventCode,
    actor: EventActor,
    at: datetime,
    payload: Mapping[str, Any] | None = None,
) -> None:
    """Записать событие истории приглашения (Арх. 8.9): одно на каждый переход и каждую отметку (I5).

    Журнал — только вставка. В `payload` нет персональных данных: только служебные признаки (`fields`, `reason`,
    `revision_id`, `demo`).
    """
    db.add(
        InvitationEvent(
            invitation_id=inv.id,
            employer_id=inv.employer_id,
            code=code.value,
            actor=actor.value,
            at=at,
            payload=dict(payload or {}),
        )
    )


def lock_employer(db: Session, now: datetime, employer_id: UUID) -> EmployerContactState:
    """Создать при отсутствии и заблокировать строку `employer_contact_state` (Арх. 4.4).

    Первая блокировка в порядке блокировок: отправки, отзывы и отметки одного работодателя идут строго по очереди,
    поэтому подсчёт слотов и суточного лимита при записи не гонится с параллельной отправкой (I2).
    """
    db.execute(
        pg_insert(EmployerContactState)
        .values(employer_id=employer_id, updated_at=now)
        .on_conflict_do_nothing(index_elements=["employer_id"])
    )
    return db.scalars(
        select(EmployerContactState)
        .where(EmployerContactState.employer_id == employer_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()


def normalize_pause(db: Session, state: CandidateContactState, now: datetime) -> None:
    """Снять автопаузу, закончившуюся по сроку (Арх. 4.4, 4.10).

    Если `profile.auto_pause_until(candidate) <= now`: `profile.clear_auto_pause` и счётчик молчания становится
    `SILENCE_STRIKES - 1` — остаётся один «страйк», следующее истечение без ответа ставит паузу снова.
    Вызывается только под блокировкой строки состояния кандидата.
    """
    until = profile_service.auto_pause_until(db, state.candidate_id)
    if until is not None and until <= now:
        profile_service.clear_auto_pause(db, state.candidate_id)
        state.consecutive_expired = rules.strikes_after_auto_resume()
        state.updated_at = now


def lock_candidates(
    db: Session,
    now: datetime,
    candidate_ids: Collection[UUID],
    *,
    already: Mapping[UUID, CandidateContactState] | None = None,
) -> dict[UUID, CandidateContactState]:
    """Создать при отсутствии и заблокировать строки `candidate_contact_state` одним запросом (Арх. 4.4).

    Порядок блокировок: строки берутся `ORDER BY candidate_id FOR UPDATE` — единый порядок исключает взаимную
    блокировку операций с пересекающимися множествами кандидатов. Строки из `already` повторно не блокируются.
    Для каждой вновь заблокированной строки выполняется `normalize_pause`. Идентификаторы обязаны быть
    существующими пользователями (внешний ключ на `app_user`): это проверяет вызывающий код до блокировки
    (поправка R3-data-api-security-8).
    """
    states: dict[UUID, CandidateContactState] = dict(already or {})
    missing = sorted(set(candidate_ids) - set(states))
    if not missing:
        return states
    db.execute(
        pg_insert(CandidateContactState)
        .values([{"candidate_id": cid, "consecutive_expired": 0, "updated_at": now} for cid in missing])
        .on_conflict_do_nothing(index_elements=["candidate_id"])
    )
    rows = db.scalars(
        select(CandidateContactState)
        .where(CandidateContactState.candidate_id.in_(missing))
        .order_by(CandidateContactState.candidate_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    for row in rows:
        normalize_pause(db, row, now)
        states[row.candidate_id] = row
    return states


def due_candidates(
    db: Session, now: datetime, *, employer_id: UUID | None = None, candidate_id: UUID | None = None
) -> set[UUID]:
    """Кандидаты области, у которых есть `sent` или `viewed` с `expires_at <= now` (Арх. 4.4, шаг 1).

    Читает без блокировок. Операция работодателя вызывает её, чтобы заранее узнать, чьи строки состояния
    заблокировать вместе со строкой адресата.
    """
    statement = select(Invitation.candidate_id).where(
        Invitation.status.in_(rules.ACTIVE_STATUSES), Invitation.expires_at <= now
    )
    if employer_id is not None:
        statement = statement.where(Invitation.employer_id == employer_id)
    if candidate_id is not None:
        statement = statement.where(Invitation.candidate_id == candidate_id)
    return set(db.scalars(statement.distinct()))


def settle(
    db: Session,
    now: datetime,
    *,
    employer_id: UUID | None = None,
    candidate_id: UUID | None = None,
    everything: bool = False,
    locked: Mapping[UUID, CandidateContactState] | None = None,
    extra_candidate_ids: Collection[UUID] = (),
    responder: Responder | None = None,
) -> int:
    """Материализовать истёкшие приглашения области: переход T6 (Арх. 4.2, 4.4). Возвращает число закрытых.

    Область — приглашения одного работодателя, одного кандидата либо все (`everything`, фоновый цикл).

    Шаги и порядок блокировок:

    1. без блокировок найти кандидатов области с `sent`/`viewed` и `expires_at <= now` (плюс `extra_candidate_ids` —
       демо-кандидаты с назревшим действием ответчика, только в `settle_all`);
    2. строки их состояния, которых нет в `locked`, создать и заблокировать одним запросом по возрастанию
       `candidate_id` (`lock_candidates`, там же `normalize_pause`);
    3. `responder` (демо-ответчик, только из `settle_all` при `DEMO_MODE`) выполняет назревшие действия;
    4. строки `invitation` области в порядке `(expires_at, id)` блокируются и получают `status = expired`,
       `resolved_at = slot_release_at = expires_at`, `pair_block_until = expires_at + PAIR_RETRY_DAYS`;
    5. для каждой: событие `expired` (`actor = system`, `at = expires_at`); `consecutive_expired += 1`; при
       `consecutive_expired >= SILENCE_STRIKES` и отсутствии автопаузы — `profile.set_auto_pause(at = expires_at,
       until = expires_at + AUTO_PAUSE_MAX_DAYS)`.

    Демо-приглашение живому кандидату «страйк» не даёт (`rules.counts_for_candidate`; поправки
    R3-data-api-security-11 и R3-mechanics-recheck-4). Повторный вызов ничего не меняет: строки уже не `sent`
    и не `viewed`, событие `expired` создаётся один раз (I5).
    """
    if sum((employer_id is not None, candidate_id is not None, everything)) != 1:
        raise ValueError("settle: область задаётся ровно одним из employer_id, candidate_id, everything")

    affected = due_candidates(db, now, employer_id=employer_id, candidate_id=candidate_id) | set(extra_candidate_ids)
    if not affected:
        return 0
    states = lock_candidates(db, now, affected, already=locked)

    if responder is not None:
        responder(states)

    statement = (
        select(Invitation)
        .where(Invitation.status.in_(rules.ACTIVE_STATUSES), Invitation.expires_at <= now)
        .order_by(Invitation.expires_at, Invitation.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if employer_id is not None:
        statement = statement.where(Invitation.employer_id == employer_id)
    if candidate_id is not None:
        statement = statement.where(Invitation.candidate_id == candidate_id)
    expired = [inv for inv in db.scalars(statement) if inv.candidate_id in states]
    if not expired:
        return 0

    # Признак аккаунта нужен только для демо-приглашений: живому кандидату они «страйк» не дают.
    demo_addressees = {inv.candidate_id for inv in expired if inv.is_demo}
    accounts = identity_service.users(db, demo_addressees) if demo_addressees else {}

    for inv in expired:
        inv.status = InvitationStatus.EXPIRED.value
        inv.resolved_at = inv.expires_at
        inv.slot_release_at = inv.expires_at
        inv.pair_block_until = inv.expires_at + c.PAIR_RETRY
        inv.updated_at = now
        add_event(db, inv, EventCode.EXPIRED, EventActor.SYSTEM, inv.expires_at)

        account = accounts.get(inv.candidate_id)
        candidate_is_demo = account.is_demo if account is not None else False
        if not rules.counts_for_candidate(invitation_is_demo=inv.is_demo, candidate_is_demo=candidate_is_demo):
            continue
        state = states[inv.candidate_id]
        state.consecutive_expired += 1
        state.updated_at = now
        if (
            rules.strike_triggers_pause(state.consecutive_expired)
            and profile_service.auto_pause_until(db, inv.candidate_id) is None
        ):
            profile_service.set_auto_pause(
                db, inv.candidate_id, at=inv.expires_at, until=inv.expires_at + c.AUTO_PAUSE_MAX
            )
    db.flush()
    return len(expired)
