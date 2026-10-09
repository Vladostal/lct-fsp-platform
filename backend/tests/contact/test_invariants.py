"""Инварианты I1–I7 на случайных последовательностях действий и гонки с настоящей фиксацией (Арх. 4.4, 4.16)."""

from __future__ import annotations

import threading
from collections import Counter
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st
from sqlalchemy import insert, select

from app.core import clock
from app.core import db as core_db
from app.core.db import run_in_tx
from app.core.errors import ApiException
from app.modules.contact import constants as c
from app.modules.contact import rules, service
from app.modules.contact.dto import DeclineCondition, InvitationData
from app.modules.contact.models import CandidateContactState, Invitation, InvitationEvent
from app.shared.enums import ConditionKind, DeclineReason, InvitationStatus, TrustLevel
from tests.contact.conftest import T0, offer

# --------------------------------------------------------------------------------------------------------------------
# Property-тест
# --------------------------------------------------------------------------------------------------------------------

_ACTIONS = st.sampled_from(
    ["send", "send_high", "revise", "view", "accept", "decline", "decline_cond", "withdraw", "settle", "min_up"]
)
_SEEN: set[str] = set()
_STEP = st.tuples(
    _ACTIONS, st.integers(0, 1), st.integers(0, 2), st.sampled_from([0, 0, 0, 1, 1, 30, 80, 170, 24 * 31])
)


def _check_invariants(db, now, limit):
    db.flush()
    db.expire_all()
    invitations = db.scalars(select(Invitation)).all()
    events = Counter(db.execute(select(InvitationEvent.invitation_id, InvitationEvent.code)).all())
    active = Counter((i.employer_id, i.candidate_id) for i in invitations if rules.is_active(i.status))
    assert all(count == 1 for count in active.values()), "I1"
    by_employer: dict[UUID, list[Invitation]] = {}
    for inv in invitations:
        by_employer.setdefault(inv.employer_id, []).append(inv)
        assert (inv.resolved_at is None) == rules.is_active(inv.status), "I6"
        # I5: каждому достигнутому статусу — ровно одно событие с тем же кодом.
        expected = {inv.status}
        if inv.status != InvitationStatus.BOUNCED.value:
            expected.add("sent")
        if inv.viewed_at is not None:
            expected.add("viewed")
        status_events = {code for (inv_id, code) in events if inv_id == inv.id and code != "revised"}
        assert status_events == expected, f"I5: {status_events} != {expected}"
        assert all(events[(inv.id, code)] == 1 for code in expected), "I5"
    revisions = Counter(i.revises_id for i in invitations if i.revises_id is not None)
    assert all(count == 1 for count in revisions.values()), "I7"
    originals = {i.id: i for i in invitations}
    assert all(originals[i.revises_id].revises_id is None for i in invitations if i.revises_id), "I7"
    for rows in by_employer.values():
        assert rules.slots_used(rows, now)[0] <= limit, "I2"
    assert all(s.consecutive_expired >= 0 for s in db.scalars(select(CandidateContactState)))


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(steps=st.lists(_STEP, min_size=4, max_size=30))
@example(
    steps=[
        ("send", 0, 0, 0),
        ("view", 0, 0, 1),
        ("withdraw", 0, 0, 1),
        ("min_up", 0, 1, 0),
        ("send", 0, 1, 0),
        ("revise", 0, 1, 1),
        ("send", 1, 2, 0),
        ("decline_cond", 1, 2, 1),
        ("revise", 1, 2, 30),
        ("settle", 0, 0, 170),
    ]
)
# Явный путь до `accepted`: без него страховочный тест ниже зависел от того, дойдут ли до этого статуса случайные
# последовательности, и изредка падал (в примере выше принятия нет).
@example(
    steps=[
        ("send", 0, 0, 0),
        ("view", 0, 0, 1),
        ("accept", 0, 0, 2),
        ("send", 1, 1, 0),
        ("decline", 1, 1, 3),
    ]
)
def test_random_sequences_keep_invariants(db, actors, world, monkeypatch, steps):
    monkeypatch.setattr(c, "SLOT_LIMIT", {TrustLevel.BASIC: 2, TrustLevel.VERIFIED: 2})
    employers = [actors.employer().id for _ in range(2)]
    candidates = [actors.candidate().id for _ in range(3)]
    outer = db.begin_nested()
    now = T0
    try:
        for action, e_index, c_index, hours in steps:
            now += timedelta(hours=hours)
            employer_id, candidate_id = employers[e_index], candidates[c_index]
            pair = db.scalars(
                select(Invitation)
                .where(Invitation.employer_id == employer_id, Invitation.candidate_id == candidate_id)
                .order_by(Invitation.created_at.desc(), Invitation.id)
            ).all()
            last = pair[0] if pair else None
            visible_last = next((i for i in pair if i.status != "bounced"), None)
            point = db.begin_nested()
            try:
                if action in ("send", "send_high", "revise"):
                    salary_from = 150_000 if action == "send" else 300_000
                    body = offer(candidate_id, salary_from=salary_from, salary_to=salary_from + 50_000)
                    if action == "revise" and last is not None:
                        body["revises_id"] = str(last.id)
                    before = rules.slots_used(
                        db.scalars(select(Invitation).where(Invitation.employer_id == employer_id)).all(), now
                    )[0]
                    _, created = service.send(
                        db, now, employer_id, InvitationData.model_validate(body), uuid4(), is_demo=False
                    )
                    assert created and before < 2, "I2: отправка при занятых слотах"
                elif action == "settle":
                    service.settle_all(db, now)
                elif action == "min_up":
                    world.candidates[candidate_id].min_salary = 200_000
                elif action == "withdraw" and last is not None:
                    service.withdraw_invitation(db, now, employer_id, last.id)
                elif visible_last is not None:
                    if action == "view":
                        service.view_invitation(db, now, candidate_id, visible_last.id)
                    elif action == "accept":
                        service.accept_invitation(db, now, candidate_id, visible_last.id)
                    elif action == "decline":
                        service.decline_invitation(db, now, candidate_id, visible_last.id, DeclineReason.STACK)
                    elif action == "decline_cond":
                        service.decline_invitation(
                            db,
                            now,
                            candidate_id,
                            visible_last.id,
                            DeclineReason.SALARY,
                            DeclineCondition(kind=ConditionKind.SALARY_FROM, value=400_000),
                        )
                point.commit()
            except ApiException as exc:
                # Договор транзакции: ошибка откатывает действие, кроме случая commit=True (материализация expired).
                if exc.commit:
                    point.commit()
                else:
                    point.rollback()
            _check_invariants(db, now, limit=2)
            _SEEN.update(db.scalars(select(Invitation.status)).all())
    finally:
        outer.rollback()
        db.expire_all()
        for fake in world.candidates.values():
            fake.min_salary = None
            fake.auto_paused_until = None
        world.disclosures.clear()
        world.access_log.clear()


def test_random_sequences_reached_every_status():
    """Страховка от пустого property-теста: случайные последовательности дошли до всех статусов."""
    assert {status.value for status in InvitationStatus} <= _SEEN, _SEEN


# --------------------------------------------------------------------------------------------------------------------
# Гонки: настоящие сессии и настоящая фиксация
# --------------------------------------------------------------------------------------------------------------------


def _user(session, role, world):
    table = core_db.Base.metadata.tables["app_user"]
    user_id = uuid4()
    values = {
        "id": user_id,
        "email": f"{role}-{user_id.hex[:10]}@example.com",
        "password_hash": None,
        "role": role,
        "email_verified_at": clock.real_now(),
        "is_adult_confirmed": True,
        "is_demo": False,
        "demo_key": None,
        "created_at": clock.real_now(),
        "last_login_at": None,
    }
    session.execute(insert(table).values({k: v for k, v in values.items() if k in table.c}))
    if role == "employer":
        world.add_company(user_id)
    else:
        world.add_candidate(user_id)
    return user_id


def _send_now(session, now, employer_id, candidate_id, key=None):
    data = InvitationData.model_validate(offer(candidate_id))
    inv, created = service.send(session, now, employer_id, data, key or uuid4(), is_demo=False)
    session.commit()
    return inv, created


def _parallel(db_factory, jobs):
    """Запустить задания одновременно, каждое в своей сессии; вернуть результаты или исключения по порядку."""
    barrier = threading.Barrier(len(jobs))
    results: list[object] = [None] * len(jobs)

    def run(index, job):
        session = db_factory()
        try:
            barrier.wait(timeout=10)
            results[index] = job(session)
        except Exception as exc:
            session.rollback()
            results[index] = exc
        finally:
            session.close()

    threads = [threading.Thread(target=run, args=(index, job)) for index, job in enumerate(jobs)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads), "взаимная блокировка: поток не завершился"
    return results


@pytest.mark.real_db
def test_parallel_sends_to_same_pair_give_one_sent_i1(db_factory, world):
    setup = db_factory()
    employer, candidate = _user(setup, "employer", world), _user(setup, "candidate", world)
    setup.commit()

    def job(key):
        def run(session):
            data = InvitationData.model_validate(offer(candidate))
            return run_in_tx(session, lambda s: service.send(s, T0, employer, data, key, is_demo=False)[0].id)

        return run

    # Разные ключи: ровно одна отправка проходит, вторая получает 409.
    results = _parallel(db_factory, [job(uuid4()), job(uuid4())])
    errors = [r for r in results if isinstance(r, ApiException)]
    assert len(errors) == 1 and errors[0].code == "active_invitation_exists", results
    check = db_factory()
    assert check.scalars(select(Invitation.status)).all() == ["sent"]
    # Один ключ: обе получают один и тот же объект.
    check.execute(Invitation.__table__.delete())
    check.commit()
    key = uuid4()
    same = _parallel(db_factory, [job(key), job(key)])
    assert isinstance(same[0], UUID) and same[0] == same[1], same
    assert len(check.scalars(select(Invitation.id)).all()) == 1


@pytest.mark.real_db
def test_nine_slots_two_parallel_sends_one_succeeds_i2(db_factory, world):
    setup = db_factory()
    employer = _user(setup, "employer", world)
    targets = [_user(setup, "candidate", world) for _ in range(11)]
    setup.commit()
    for candidate in targets[:9]:
        _send_now(setup, T0, employer, candidate)

    def job(candidate):
        def run(session):
            data = InvitationData.model_validate(offer(candidate))
            return run_in_tx(session, lambda s: service.send(s, T0, employer, data, uuid4(), is_demo=False)[0].status)

        return run

    results = _parallel(db_factory, [job(targets[9]), job(targets[10])])
    ok = [r for r in results if r == "sent"]
    errors = [r for r in results if isinstance(r, ApiException)]
    assert len(ok) == 1 and len(errors) == 1 and errors[0].code == "quota_exceeded", results
    assert errors[0].params["used"] == 10
    check = db_factory()
    assert len(check.scalars(select(Invitation.id)).all()) == 10


@pytest.mark.real_db
def test_cross_sends_with_expired_invitations_do_not_deadlock(db_factory, world):
    """E1 → C5 при истёкшем E1 → C2 и E2 → C2 при истёкшем E2 → C5: без взаимной блокировки и без повторов."""
    later = T0 + c.INVITATION_TTL + timedelta(hours=1)
    for _ in range(12):
        setup = db_factory()
        e1, e2 = _user(setup, "employer", world), _user(setup, "employer", world)
        c2, c5 = _user(setup, "candidate", world), _user(setup, "candidate", world)
        setup.commit()
        _send_now(setup, T0, e1, c2)
        _send_now(setup, T0, e2, c5)
        setup.close()

        results = _parallel(
            db_factory,
            [
                lambda s, e=e1, cand=c5: _send_now(s, later, e, cand)[0].status,  # без run_in_tx: повторов нет
                lambda s, e=e2, cand=c2: _send_now(s, later, e, cand)[0].status,
            ],
        )
        assert results == ["sent", "sent"], results
        check = db_factory()
        statuses = Counter(check.scalars(select(Invitation.status).where(Invitation.employer_id.in_([e1, e2]))).all())
        assert statuses == {"expired": 2, "sent": 2}
        expired_events = check.scalars(
            select(InvitationEvent.id).where(
                InvitationEvent.employer_id.in_([e1, e2]), InvitationEvent.code == "expired"
            )
        ).all()
        assert len(expired_events) == 2
        strikes = check.scalars(
            select(CandidateContactState.consecutive_expired).where(CandidateContactState.candidate_id.in_([c2, c5]))
        ).all()
        assert strikes == [1, 1]
        check.close()


@pytest.mark.real_db
def test_mail_goes_only_after_commit_and_accept_races_with_settle(db_factory, world, mailbox):
    from app.core import mail

    setup = db_factory()
    employer, candidate = _user(setup, "employer", world), _user(setup, "candidate", world)
    setup.commit()
    data = InvitationData.model_validate(offer(candidate))
    inv, _ = service.send(setup, T0, employer, data, uuid4(), is_demo=False)
    assert mailbox == [] and len(mail.pending(setup)) == 1
    setup.rollback()
    mail.discard(setup)
    inv, _ = _send_now(setup, T0, employer, candidate)
    invitation_id, deadline = inv.id, inv.expires_at
    setup.close()

    # Принятие и фоновая материализация в момент срока: ровно один исход и одно событие.
    results = _parallel(
        db_factory,
        [
            lambda s: run_in_tx(s, lambda x: service.accept_invitation(x, deadline, candidate, invitation_id).status),
            lambda s: run_in_tx(s, lambda x: service.settle_all(x, deadline)),
        ],
    )
    check = db_factory()
    assert check.get(Invitation, invitation_id).status == "expired"
    assert isinstance(results[0], ApiException) and results[0].code == "invitation_not_actionable"
    codes = check.scalars(select(InvitationEvent.code).where(InvitationEvent.invitation_id == invitation_id)).all()
    assert sorted(codes) == ["expired", "sent"]
