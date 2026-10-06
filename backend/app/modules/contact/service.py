"""Фасад модуля `contact` (Арх. 2.5) и операции записи механики «Приглашение с возвратом» (Арх. 4).

Функции записи не фиксируют транзакцию: роутер модуля оборачивает их в `core.db.run_in_tx` (повтор при `40001`
и `40P01`), сид и модуль `demo` фиксируют сами. Время идёт первым параметром после `db`: сид передаёт `now`
в прошлом, чтобы построить историю.

Порядок блокировок един (Арх. 4.4, реализация — `settle.py`): строка работодателя → строки кандидатов одним
запросом → строки приглашений. Каждая операция сначала блокирует, затем вызывает `settle` для текущего участника
и только потом читает состояние.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import ApiException, field_error, not_found, validation_error
from app.modules.contact import checks, notify, rules, texts
from app.modules.contact import constants as c
from app.modules.contact import settle as settle_mod
from app.modules.contact.dto import (
    DeclineCondition,
    InvitationData,
    InvitationDTO,
    InvitationEventDTO,
    InvitationExportDTO,
)
from app.modules.contact.models import (
    CandidateContactState,
    Complaint,
    EmployerContactState,
    Invitation,
    InvitationEvent,
    InvitationTerms,
)
from app.modules.identity import service as identity_service
from app.modules.matching import service as matching_service
from app.modules.profile import service as profile_service
from app.shared import salary
from app.shared.contact_method import validate_contact_method
from app.shared.enums import (
    ComplaintReason,
    ComplaintStatus,
    ConditionKind,
    DeclineReason,
    DiscloseField,
    DisclosureSource,
    EventActor,
    EventCode,
    InvitationStatus,
    Role,
    WorkFormat,
)

# --------------------------------------------------------------------------------------------------------------------
# Чтение для верхних модулей
# --------------------------------------------------------------------------------------------------------------------


def has_active_invitation(db: Session, employer_id: UUID, candidate_id: UUID) -> bool:
    """Есть ли у пары приглашение в `sent` или `viewed` (по записанному статусу)."""
    return (
        db.scalar(
            select(Invitation.id)
            .where(
                Invitation.employer_id == employer_id,
                Invitation.candidate_id == candidate_id,
                Invitation.status.in_(rules.ACTIVE_STATUSES),
            )
            .limit(1)
        )
        is not None
    )


def events_since(db: Session, employer_id: UUID, after_event_id: int, limit: int) -> list[InvitationEventDTO]:
    """События приглашений работодателя с `id > after_event_id` по возрастанию — для исходящих вебхуков (P2).

    Событие `complaint_filed` работодателю не показывается и сюда не попадает (Арх. 4.2, T11).
    """
    rows = db.scalars(
        select(InvitationEvent)
        .where(
            InvitationEvent.employer_id == employer_id,
            InvitationEvent.id > after_event_id,
            InvitationEvent.code != EventCode.COMPLAINT_FILED.value,
        )
        .order_by(InvitationEvent.id)
        .limit(max(1, min(limit, 500)))
    )
    return [InvitationEventDTO.model_validate(row) for row in rows]


def invitation_for_export(db: Session, employer_id: UUID, invitation_id: UUID) -> InvitationExportDTO:
    """Приглашение работодателя со снимком условий — для выгрузки (P2); чужое или отсутствующее — 404."""
    inv = db.get(Invitation, invitation_id)
    if inv is None or inv.employer_id != employer_id:
        raise not_found()
    terms = _terms(db, inv.id)
    return InvitationExportDTO(
        id=inv.id,
        employer_id=inv.employer_id,
        candidate_id=inv.candidate_id,
        need_id=inv.need_id,
        status=rules.effective_status(inv, clock.now(db)),
        created_at=inv.created_at,
        resolved_at=inv.resolved_at,
        title=terms.title,
        salary_from=terms.salary_from,
        salary_to=terms.salary_to,
        work_format=WorkFormat(terms.work_format),
        city=terms.city,
    )


# --------------------------------------------------------------------------------------------------------------------
# Фоновый цикл
# --------------------------------------------------------------------------------------------------------------------


def settle_all(db: Session, now: datetime) -> None:
    """Фоновая задача (раз в 30 секунд): материализовать истёкшие приглашения всех участников (Арх. 4.4).

    Только здесь и только при `DEMO_MODE` работает демо-ответчик (Арх. 4.14).
    """
    from app.core.config import get_settings
    from app.modules.contact import demo_responder

    if get_settings().demo:
        plan = demo_responder.plan(db, now)
        settle_mod.settle(
            db,
            now,
            everything=True,
            extra_candidate_ids=plan.candidate_ids,
            responder=lambda states: demo_responder.run(db, now, plan, states),
        )
    else:
        settle_mod.settle(db, now, everything=True)


# --------------------------------------------------------------------------------------------------------------------
# Внутренние помощники
# --------------------------------------------------------------------------------------------------------------------


def _terms(db: Session, invitation_id: UUID) -> InvitationTerms:
    terms = db.get(InvitationTerms, invitation_id)
    if terms is None:  # строки создаются одной транзакцией; отсутствие — нарушение целостности
        raise not_found()
    return terms


def _dto(inv: Invitation) -> InvitationDTO:
    return InvitationDTO.model_validate(inv)


def _not_actionable(inv: Invitation) -> ApiException:
    """409 `invitation_not_actionable`. Фиксация сохраняется: перед отказом `settle` мог записать `expired`
    (Арх. 4.2: действие при `now >= expires_at` сначала материализует истечение, затем отвечает 409).
    """
    status = InvitationStatus(inv.status)
    label = texts.STATUS_LABELS_EMPLOYER[status]
    return ApiException(
        409,
        "invitation_not_actionable",
        texts.message("invitation_not_actionable", {"status_label": label}),
        params={"status": status.value},
        commit=True,
    )


def _find_by_key(db: Session, employer_id: UUID, key: UUID) -> Invitation | None:
    return db.scalar(select(Invitation).where(Invitation.employer_id == employer_id, Invitation.idempotency_key == key))


def _locked_invitation(db: Session, invitation_id: UUID) -> Invitation | None:
    return db.scalar(
        select(Invitation)
        .where(Invitation.id == invitation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _candidate_begin(
    db: Session, now: datetime, candidate_id: UUID, invitation_id: UUID, *, lock_employer_first: bool = False
) -> tuple[Invitation, CandidateContactState]:
    """Начало изменяющего действия кандидата: найти приглашение, заблокировать, выполнить `settle`.

    Чужое, отсутствующее и `bounced` приглашение — 404: о недоставленном кандидат не знает (Арх. 4.2).
    Блокировки: (строка работодателя, если действие может её изменить) → строка кандидата → строка приглашения.
    """
    probe = db.get(Invitation, invitation_id)
    if probe is None or probe.candidate_id != candidate_id or probe.status == InvitationStatus.BOUNCED.value:
        raise not_found()
    if lock_employer_first:
        settle_mod.lock_employer(db, now, probe.employer_id)
    states = settle_mod.lock_candidates(db, now, [candidate_id])
    settle_mod.settle(db, now, candidate_id=candidate_id, locked=states)
    inv = _locked_invitation(db, invitation_id)
    if inv is None:
        raise not_found()
    return inv, states[candidate_id]


def _employer_begin(
    db: Session, now: datetime, employer_id: UUID, candidate_ids: Collection[UUID]
) -> tuple[EmployerContactState, dict[UUID, CandidateContactState]]:
    """Начало изменяющего действия работодателя (Арх. 4.4, 4.5, шаги 3–4).

    Блокирует строку работодателя, вычисляет всё множество кандидатов (переданные и кандидаты с истёкшими `sent`
    и `viewed` этого работодателя), блокирует его одним запросом и выполняет `settle` для работодателя.
    """
    state = settle_mod.lock_employer(db, now, employer_id)
    affected = set(candidate_ids) | settle_mod.due_candidates(db, now, employer_id=employer_id)
    states = settle_mod.lock_candidates(db, now, affected)
    settle_mod.settle(db, now, employer_id=employer_id, locked=states)
    return state, states


# --------------------------------------------------------------------------------------------------------------------
# Отправка (Арх. 4.5)
# --------------------------------------------------------------------------------------------------------------------


def _parse_key(idempotency_key: str | UUID) -> UUID:
    if isinstance(idempotency_key, UUID):
        return idempotency_key
    try:
        return UUID(str(idempotency_key))
    except ValueError:
        raise validation_error(
            field_error("Idempotency-Key", "idempotency_key_invalid", texts.field_message("idempotency_key"))
        ) from None


def _validate_fields(data: InvitationData) -> InvitationData:
    """Шаг 2: длины, вилка, город, способ связи. Возвращает данные с нормализованными строками."""
    errors = []
    title = " ".join(data.title.split())
    description = data.description.strip()
    message = (data.message or "").strip() or None
    city = " ".join((data.city or "").split()) or None
    if not c.TITLE_MIN <= len(title) <= c.TITLE_MAX:
        errors.append(field_error("title", "length", texts.field_message("title")))
    if not c.DESCRIPTION_MIN <= len(description) <= c.DESCRIPTION_MAX:
        errors.append(field_error("description", "length", texts.field_message("description")))
    if message is not None and len(message) > c.MESSAGE_MAX:
        errors.append(field_error("message", "length", texts.field_message("message")))
    if city is not None and len(city) > c.CITY_MAX:
        errors.append(field_error("city", "length", texts.field_message("city_long")))
    if city is None and data.work_format in (WorkFormat.OFFICE, WorkFormat.HYBRID):
        errors.append(field_error("city", "required", texts.field_message("city")))
    if errors:
        raise validation_error(*errors)
    salary.validate_range(data.salary_from, data.salary_to)
    method = validate_contact_method(data.contact_method.kind, data.contact_method.value)
    return data.model_copy(
        update={"title": title, "description": description, "message": message, "city": city, "contact_method": method}
    )


def _revision_denied() -> ApiException:
    """409 без подробностей: чужое, отсутствующее и уже использованное исходное приглашение неразличимы."""
    return ApiException(409, "revision_not_allowed", texts.message("revision_not_allowed"))


def send(
    db: Session, now: datetime, employer_id: UUID, data: InvitationData, idempotency_key: str | UUID, *, is_demo: bool
) -> tuple[Invitation, bool]:
    """Отправить приглашение; возвращает строку и признак «создано сейчас» (ложь — повтор ключа идемпотентности).

    Шаги Арх. 4.5 с поправками R3-data-api-security-1 (пересмотр — только своей же паре) и R3-data-api-security-8
    (адресат проверяется до создания и блокировки строк состояния).
    """
    key = _parse_key(idempotency_key)
    # Шаг 1: повтор ключа возвращает уже созданное.
    found = _find_by_key(db, employer_id, key)
    if found is not None:
        return found, False

    # Шаг 2: поля, адресат, потребность.
    data = _validate_fields(data)
    original: Invitation | None = None
    candidate_id = data.candidate_id
    need_id, snapshot_id = data.need_id, data.snapshot_id
    if data.revises_id is not None:
        original = db.get(Invitation, data.revises_id)
        if original is None or not rules.same_pair(original, employer_id, data.candidate_id):
            raise _revision_denied()
        # Кандидат, потребность и версия подборки пересмотра берутся только из исходного приглашения.
        candidate_id, need_id, snapshot_id = original.candidate_id, original.need_id, original.snapshot_id
    elif need_id is not None:
        need = matching_service.need_ref(db, employer_id, need_id, snapshot_id)  # чужое — 404
        snapshot_id = snapshot_id or need.snapshot_id
    elif snapshot_id is not None:
        raise not_found()

    accounts = identity_service.users(db, [employer_id, candidate_id])
    addressee = accounts.get(candidate_id)
    if addressee is None or addressee.role != Role.CANDIDATE:
        # Несуществующий адресат неотличим от скрытого; таблицы состояния не трогаются.
        raise checks.Violation("5.3", 409, "candidate_unavailable").to_exception()

    # Шаги 3–4: блокировки и материализация истёкшего у обеих сторон.
    _, states = _employer_begin(db, now, employer_id, [candidate_id])
    found = _find_by_key(db, employer_id, key)
    if found is not None:
        return found, False
    settle_mod.settle(db, now, candidate_id=candidate_id, locked=states)

    # Шаг 5: проверки; срабатывает первая невыполненная.
    ctx = checks.gather(db, now, employer_id, candidate_id)
    revision_violation: checks.Violation | None = None
    original_terms: InvitationTerms | None = None
    if original is not None:
        original = _locked_invitation(db, original.id)
        if original is None:
            raise _revision_denied()
        original_terms = _terms(db, original.id)
        has_revision = db.scalar(select(Invitation.id).where(Invitation.revises_id == original.id).limit(1)) is not None
        if not rules.can_revise(original, now, has_revision=has_revision):
            revision_violation = checks.Violation("5.5", 409, "revision_not_allowed")
        elif not rules.revision_terms_ok(
            original, original_terms.salary_from, salary_from=data.salary_from, work_format=data.work_format
        ):
            revision_violation = checks.Violation("5.5", 422, "revision_below_condition")
    failed = checks.violations(
        ctx,
        work_format=data.work_format,
        revision=revision_violation,
        is_revision=original is not None,
        demo_call=is_demo,
    )
    if failed:
        raise failed[0].to_exception()
    company = ctx.company
    assert company is not None  # проверка 5.1 пройдена

    # Шаг 6: сверка вилки — последней и только здесь.
    if rules.skips_salary_check(
        demo_call=is_demo, employer_is_demo=ctx.employer_is_demo, candidate_is_demo=ctx.candidate_is_demo
    ):
        delivered = True
    else:
        delivered = rules.salary_ok(data.salary_from, profile_service.min_salary(db, candidate_id))

    # Шаг 7: объяснение для кандидата и полоса совпадения на момент отправки.
    explain = matching_service.explain_for_invitation(db, employer_id, candidate_id, need_id, snapshot_id, now)

    # Шаг 8: строки приглашения, снимка и событий.
    inv = Invitation(
        employer_id=employer_id,
        candidate_id=candidate_id,
        need_id=need_id,
        snapshot_id=snapshot_id,
        revises_id=original.id if original is not None else None,
        idempotency_key=key,
        status=(InvitationStatus.SENT if delivered else InvitationStatus.BOUNCED).value,
        is_demo=bool(is_demo or ctx.employer_is_demo),
        fit_band_at_send=explain.fit_band.value if explain.fit_band is not None else None,
        created_at=now,
        expires_at=now + c.INVITATION_TTL,
        updated_at=now,
    )
    if not delivered:  # переход T2
        inv.resolved_at = now
        inv.slot_release_at = now + c.BOUNCE_SLOT_HOLD
        inv.pair_block_until = now + c.PAIR_RETRY
    db.add(inv)
    db.flush()
    terms = InvitationTerms(
        invitation_id=inv.id,
        company_name=company.name,
        company_sphere=company.sphere,
        company_description=company.description,
        company_site=company.site,
        company_since=clock.to_local_date(company.created_at),
        company_trust_level=company.trust_level.value,
        title=data.title,
        description=data.description,
        salary_from=data.salary_from,
        salary_to=data.salary_to,
        work_format=data.work_format.value,
        city=data.city,
        contact_kind=data.contact_method.kind.value,
        contact_value=data.contact_method.value,
        message=data.message,
        match_snapshot=explain.why.model_dump(mode="json"),
        scorer_version=explain.scorer_version,
    )
    db.add(terms)
    payload = {"demo": True} if is_demo else {}
    settle_mod.add_event(db, inv, EventCode.SENT if delivered else EventCode.BOUNCED, EventActor.EMPLOYER, now, payload)
    if original is not None:
        original.updated_at = now
        settle_mod.add_event(db, original, EventCode.REVISED, EventActor.EMPLOYER, now, {"revision_id": str(inv.id)})
    db.flush()

    # Шаг 9: письмо кандидату — только при `sent`; уходит после фиксации.
    notify.invitation_sent(db, inv, terms, addressee)
    return inv, True


def send_invitation(
    db: Session, now: datetime, employer_id: UUID, data: InvitationData, idempotency_key: str, *, is_demo: bool = False
) -> InvitationDTO:
    """Отправить приглашение (Арх. 4.5). `bounced` — обычный результат, строка сохраняется.

    `is_demo=True` передают только сид и модуль `demo`: для пары «демо-компания → не демо-аккаунт» это
    демо-приглашение без сверки вилки (Арх. 4.14); вызов из роутера для такой пары отклоняется проверкой 5.11.
    """
    inv, _ = send(db, now, employer_id, data, idempotency_key, is_demo=is_demo)
    return _dto(inv)


# --------------------------------------------------------------------------------------------------------------------
# Действия кандидата (Арх. 4.2, T3–T5; 4.8)
# --------------------------------------------------------------------------------------------------------------------


def do_view(db: Session, now: datetime, inv: Invitation, *, demo: bool = False) -> None:
    """Переход T3 под блокировкой кандидата: `sent → viewed`. Для остальных статусов ничего не меняет."""
    if inv.status != InvitationStatus.SENT.value or now >= inv.expires_at:
        return
    inv.status = InvitationStatus.VIEWED.value
    inv.viewed_at = now
    inv.updated_at = now
    settle_mod.add_event(db, inv, EventCode.VIEWED, EventActor.CANDIDATE, now, {"demo": True} if demo else {})


def _default_disclose(db: Session, candidate_id: UUID, filled: Collection[str]) -> list[DiscloseField]:
    privacy = profile_service.privacy(db, candidate_id)
    return rules.default_disclose(
        reveal_phone=privacy.reveal_phone,
        reveal_telegram=privacy.reveal_telegram,
        reveal_link=privacy.reveal_link,
        reveal_fsp_details=privacy.reveal_fsp_details,
        filled=filled,
    )


def do_accept(
    db: Session,
    now: datetime,
    inv: Invitation,
    state: CandidateContactState,
    disclose: Collection[DiscloseField] | None,
    *,
    demo: bool = False,
) -> None:
    """Переход T4 под блокировкой кандидата: раскрытие контактов, слот свободен сразу, счётчик молчания обнулён."""
    filled = profile_service.filled_channels(db, inv.candidate_id)
    chosen = list(dict.fromkeys(disclose)) if disclose is not None else _default_disclose(db, inv.candidate_id, filled)
    if not rules.disclose_ok(chosen, filled):
        raise ApiException(422, "disclose_invalid", texts.message("disclose_invalid"))
    inv.status = InvitationStatus.ACCEPTED.value
    inv.resolved_at = now
    inv.slot_release_at = now
    inv.pair_block_until = now + c.PAIR_RETRY
    inv.updated_at = now
    state.consecutive_expired = 0
    state.updated_at = now
    profile_service.disclose(
        db, inv.employer_id, inv.candidate_id, source=DisclosureSource.INVITATION, ref_id=inv.id, fields=chosen, now=now
    )
    # Запись журнала доступа `contacts_disclosed` делает сам `profile.disclose` — один раз, вместе со строкой
    # раскрытия; отдельный вызов `profile.log_access` здесь дал бы вторую запись о том же событии.
    payload: dict[str, object] = {"fields": [DiscloseField(item).value for item in chosen]}
    if demo:
        payload["demo"] = True
    settle_mod.add_event(db, inv, EventCode.ACCEPTED, EventActor.CANDIDATE, now, payload)
    db.flush()
    notify.invitation_answered(db, inv, _terms(db, inv.id), now)


def do_decline(
    db: Session,
    now: datetime,
    inv: Invitation,
    state: CandidateContactState,
    reason_code: DeclineReason,
    condition: DeclineCondition | None,
    comment: str | None,
    *,
    demo: bool = False,
) -> None:
    """Переход T5 под блокировкой кандидата: причина, необязательное условие, слот свободен сразу."""
    comment = (comment or "").strip() or None
    if comment is not None and len(comment) > c.DECLINE_COMMENT_MAX:
        raise validation_error(field_error("comment", "length", texts.field_message("comment")))
    terms = _terms(db, inv.id)
    if condition is not None:
        profile = profile_service.pool_view(db, [inv.candidate_id], now).get(inv.candidate_id)
        formats = [item.value for item in profile.work_formats] if profile is not None else []
        value = condition.value.value if isinstance(condition.value, WorkFormat) else condition.value
        if not rules.decline_condition_ok(
            reason_code,
            condition.kind,
            value,
            offer_salary_from=terms.salary_from,
            offer_work_format=terms.work_format,
            candidate_formats=formats,
        ):
            raise ApiException(422, "condition_invalid", texts.message("condition_invalid"))
        inv.decline_condition_kind = condition.kind.value
        if condition.kind is ConditionKind.SALARY_FROM:
            inv.decline_condition_salary_from = int(value)
        else:
            inv.decline_condition_work_format = str(value)
    inv.status = InvitationStatus.DECLINED.value
    inv.resolved_at = now
    inv.slot_release_at = now
    inv.pair_block_until = now + c.PAIR_RETRY
    inv.decline_reason = DeclineReason(reason_code).value
    inv.decline_comment = comment
    inv.updated_at = now
    state.consecutive_expired = 0
    state.updated_at = now
    payload: dict[str, object] = {"reason": inv.decline_reason}
    if demo:
        payload["demo"] = True
    settle_mod.add_event(db, inv, EventCode.DECLINED, EventActor.CANDIDATE, now, payload)
    db.flush()
    notify.invitation_answered(db, inv, terms, now)


def view_invitation(db: Session, now: datetime, candidate_id: UUID, invitation_id: UUID) -> InvitationDTO:
    """Отметка о просмотре (T3). Повтор и просмотр уже закрытого приглашения ничего не меняют и отвечают 200."""
    inv, _ = _candidate_begin(db, now, candidate_id, invitation_id)
    do_view(db, now, inv)
    db.flush()
    return _dto(inv)


def accept_invitation(
    db: Session,
    now: datetime,
    candidate_id: UUID,
    invitation_id: UUID,
    disclose: Collection[DiscloseField] | None = None,
) -> InvitationDTO:
    """Принять приглашение (T4). Без `disclose` — e-mail и каналы по настройкам приватности `reveal_*`.

    Повтор для уже принятого — 200 с текущим состоянием; для другого терминального статуса — 409
    `invitation_not_actionable`; недопустимый набор раскрытия — 422 `disclose_invalid`.
    """
    inv, state = _candidate_begin(db, now, candidate_id, invitation_id)
    if inv.status == InvitationStatus.ACCEPTED.value:
        return _dto(inv)
    if not rules.is_active(inv.status):
        raise _not_actionable(inv)
    do_accept(db, now, inv, state, disclose)
    return _dto(inv)


def decline_invitation(
    db: Session,
    now: datetime,
    candidate_id: UUID,
    invitation_id: UUID,
    reason_code: DeclineReason,
    condition: DeclineCondition | None = None,
    comment: str | None = None,
) -> InvitationDTO:
    """Отклонить приглашение (T5). Условие допустимо при причинах `salary` и `format` (422 `condition_invalid`)."""
    inv, state = _candidate_begin(db, now, candidate_id, invitation_id)
    if inv.status == InvitationStatus.DECLINED.value:
        return _dto(inv)
    if not rules.is_active(inv.status):
        raise _not_actionable(inv)
    do_decline(db, now, inv, state, reason_code, condition, comment)
    return _dto(inv)


def resume(db: Session, now: datetime, candidate_id: UUID) -> None:
    """«Я на связи» (Арх. 4.10): снять автопаузу и обнулить счётчик молчания."""
    states = settle_mod.lock_candidates(db, now, [candidate_id])
    settle_mod.settle(db, now, candidate_id=candidate_id, locked=states)
    profile_service.clear_auto_pause(db, candidate_id)
    state = states[candidate_id]
    state.consecutive_expired = 0
    state.updated_at = now
    db.flush()


# --------------------------------------------------------------------------------------------------------------------
# Действия работодателя
# --------------------------------------------------------------------------------------------------------------------


def _employer_invitation(db: Session, employer_id: UUID, invitation_id: UUID) -> Invitation:
    inv = db.get(Invitation, invitation_id)
    if inv is None or inv.employer_id != employer_id:
        raise not_found()
    return inv


def withdraw_invitation(db: Session, now: datetime, employer_id: UUID, invitation_id: UUID) -> InvitationDTO:
    """Отозвать приглашение (T7): слот занят до исходного срока — отзыв не ускоряет оборот слотов."""
    probe = _employer_invitation(db, employer_id, invitation_id)
    _employer_begin(db, now, employer_id, [probe.candidate_id])
    inv = _locked_invitation(db, invitation_id)
    if inv is None:
        raise not_found()
    if inv.status == InvitationStatus.WITHDRAWN.value:
        return _dto(inv)
    if not rules.is_active(inv.status):
        raise _not_actionable(inv)
    inv.status = InvitationStatus.WITHDRAWN.value
    inv.resolved_at = now
    inv.slot_release_at = inv.expires_at
    inv.pair_block_until = now + c.PAIR_RETRY
    inv.updated_at = now
    settle_mod.add_event(db, inv, EventCode.WITHDRAWN, EventActor.EMPLOYER, now)
    db.flush()
    return _dto(inv)


def set_slot_override(db: Session, employer_id: UUID, limit: int | None) -> None:
    """Задать или снять (`None`) собственный лимит слотов работодателя; демо-компаниям сид ставит 10000."""
    now = clock.now(db)
    state = settle_mod.lock_employer(db, now, employer_id)
    state.slot_limit_override = limit
    state.updated_at = now
    db.flush()


# --------------------------------------------------------------------------------------------------------------------
# Исход и жалоба (P1, Арх. 4.13)
# --------------------------------------------------------------------------------------------------------------------


def _check_freeze(db: Session, now: datetime, state: EmployerContactState) -> None:
    """Выставить заморозку отправки при достижении порога (Арх. 4.13). Вызывается под блокировкой работодателя.

    Считаются разные кандидаты за `COMPLAINT_WINDOW_DAYS`: авторы жалоб (кроме `dismissed`) и ответившие
    «условия не совпали».
    """
    if state.sending_frozen_at is not None:
        return
    since = now - timedelta(days=c.COMPLAINT_WINDOW_DAYS)
    complainers = set(
        db.scalars(
            select(Complaint.candidate_id).where(
                Complaint.employer_id == state.employer_id,
                Complaint.created_at > since,
                Complaint.status != ComplaintStatus.DISMISSED.value,
            )
        )
    )
    mismatched = set(
        db.scalars(
            select(Invitation.candidate_id).where(
                Invitation.employer_id == state.employer_id,
                Invitation.candidate_terms_matched.is_(False),
                Invitation.candidate_outcome_at > since,
            )
        )
    )
    if rules.freeze_due(len(complainers | mismatched)):
        state.sending_frozen_at = now
        state.sending_frozen_reason = "Порог жалоб и ответов «условия не совпали» от разных кандидатов"
        state.updated_at = now


def mark_outcome(
    db: Session,
    now: datetime,
    actor_id: UUID,
    invitation_id: UUID,
    *,
    contacted: bool,
    terms_matched: bool | None = None,
) -> InvitationDTO:
    """Отметка об исходе контакта после согласия (P1; T9 — работодатель, T10 — кандидат).

    Сторона определяется по `actor_id`. Статус не меняется; не `accepted` — 409 `invitation_not_actionable`.
    Ответ кандидата «условия не совпали» (`terms_matched = False`) входит в порог заморозки отправки.
    """
    probe = db.get(Invitation, invitation_id)
    if probe is None or actor_id not in (probe.employer_id, probe.candidate_id):
        raise not_found()
    if actor_id == probe.employer_id:
        _employer_begin(db, now, actor_id, [probe.candidate_id])
        inv = _locked_invitation(db, invitation_id)
        if inv is None:
            raise not_found()
        if inv.status != InvitationStatus.ACCEPTED.value:
            raise _not_actionable(inv)
        inv.employer_contacted = contacted
        inv.employer_outcome_at = now
        inv.updated_at = now
        settle_mod.add_event(db, inv, EventCode.CONTACT_MARKED, EventActor.EMPLOYER, now, {"contacted": contacted})
    else:
        inv, _ = _candidate_begin(db, now, actor_id, invitation_id, lock_employer_first=True)
        if inv.status != InvitationStatus.ACCEPTED.value:
            raise _not_actionable(inv)
        inv.candidate_contacted = contacted
        inv.candidate_terms_matched = terms_matched if contacted else None
        inv.candidate_outcome_at = now
        inv.updated_at = now
        code = EventCode.CONTACT_CONFIRMED if contacted else EventCode.CONTACT_DENIED
        settle_mod.add_event(db, inv, code, EventActor.CANDIDATE, now)
        db.flush()
        employer_state = db.get(EmployerContactState, inv.employer_id)
        if employer_state is not None:
            _check_freeze(db, now, employer_state)
    db.flush()
    return _dto(inv)


def file_complaint(
    db: Session,
    now: datetime,
    candidate_id: UUID,
    invitation_id: UUID,
    reason_code: ComplaintReason,
    comment: str | None = None,
) -> InvitationDTO:
    """Жалоба кандидата на доставленное приглашение (P1, T11): одна на приглашение, иначе 409 `complaint_exists`.

    Событие `complaint_filed` работодателю не показывается. После записи проверяется порог заморозки.
    """
    comment = (comment or "").strip() or None
    if comment is not None and len(comment) > c.COMPLAINT_COMMENT_MAX:
        raise validation_error(field_error("comment", "length", texts.field_message("complaint_comment")))
    inv, _ = _candidate_begin(db, now, candidate_id, invitation_id, lock_employer_first=True)
    exists = db.scalar(select(Complaint.id).where(Complaint.invitation_id == inv.id))
    if exists is not None:
        raise ApiException(409, "complaint_exists", texts.message("complaint_exists"), commit=True)
    db.add(
        Complaint(
            invitation_id=inv.id,
            candidate_id=candidate_id,
            employer_id=inv.employer_id,
            reason_code=ComplaintReason(reason_code).value,
            comment=comment,
            status=ComplaintStatus.OPEN.value,
            created_at=now,
        )
    )
    settle_mod.add_event(db, inv, EventCode.COMPLAINT_FILED, EventActor.CANDIDATE, now)
    db.flush()
    employer_state = db.get(EmployerContactState, inv.employer_id)
    if employer_state is not None:
        _check_freeze(db, now, employer_state)
    db.flush()
    return _dto(inv)


def resolve_complaint(
    db: Session, now: datetime, complaint_id: UUID, status: ComplaintStatus, unfreeze: bool
) -> Complaint:
    """Разбор жалобы администратором (P1): `upheld` или `dismissed`; `unfreeze` снимает заморозку отправки."""
    probe = db.get(Complaint, complaint_id)
    if probe is None:
        raise not_found()
    state = settle_mod.lock_employer(db, now, probe.employer_id)
    complaint = db.scalars(
        select(Complaint)
        .where(Complaint.id == complaint_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    complaint.status = ComplaintStatus(status).value
    complaint.resolved_at = now
    if unfreeze:
        state.sending_frozen_at = None
        state.sending_frozen_reason = None
        state.updated_at = now
    db.flush()
    return complaint
