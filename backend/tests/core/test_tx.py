"""Граница транзакции (Арх. 2.4, п. 4): фиксация до ответа, откат при ошибке, письма только после фиксации."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, BackgroundTasks
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core import clock, mail
from app.core.db import TxRoute, run_in_tx, session_scope
from app.core.deps import Db
from app.core.errors import ApiException

LETTER = {"link": "http://localhost:8080/verify-email?token=t", "expires_hours": 24}


def _offset(engine) -> int:
    """Смещение часов, прочитанное отдельным соединением: видит только зафиксированное."""
    with engine.connect() as conn:
        return int(conn.execute(text("SELECT coalesce(max(offset_seconds), 0) FROM service_clock")).scalar())


# --------------------------------------------------------------------------------------------------------------------
# Настоящая фиксация: что видит другое соединение в момент отправки ответа
# --------------------------------------------------------------------------------------------------------------------


@pytest.mark.real_db
def test_response_is_sent_only_after_commit_and_mail_only_after_response(engine, db_factory, build_app, mailbox):
    router = APIRouter(route_class=TxRoute)

    @router.post("/advance")
    def advance(db: Db) -> dict[str, int]:
        value = clock.advance(db, 5)
        mail.enqueue(db, "verify_email", "new@example.com", LETTER)
        return {"offset": value}

    application = build_app(router)
    seen: dict[str, object] = {}

    async def spy(scope, receive, send):
        """Обёртка ASGI: в момент начала ответа смотрим в базу чужим соединением и в почтовый ящик."""

        async def spying_send(message):
            if message["type"] == "http.response.start":
                seen["committed_offset"] = _offset(engine)
                seen["mail_before_response"] = len(mailbox)
            await send(message)

        await application(scope, receive, spying_send)

    response = TestClient(spy).post("/api/v1/advance")
    assert response.status_code == 200
    assert seen["committed_offset"] == 5, "ответ 2xx ушёл раньше фиксации транзакции"
    assert seen["mail_before_response"] == 0, "письмо ушло раньше ответа и фиксации"
    assert [item.to for item in mailbox] == ["new@example.com"]


@pytest.mark.real_db
def test_exception_rolls_back_and_drops_mail(engine, db_factory, build_app, mailbox):
    router = APIRouter(route_class=TxRoute)

    @router.post("/fail")
    def fail(db: Db) -> None:
        clock.advance(db, 7)
        mail.enqueue(db, "verify_email", "lost@example.com", LETTER)
        raise ApiException(409, "session_active")

    @router.post("/fail-but-keep")
    def fail_but_keep(db: Db) -> None:
        clock.advance(db, 3)
        mail.enqueue(db, "verify_email", "kept@example.com", LETTER)
        raise ApiException(401, "invalid_credentials", commit=True)

    @router.post("/crash")
    def crash(db: Db) -> None:
        clock.advance(db, 11)
        mail.enqueue(db, "verify_email", "lost@example.com", LETTER)
        raise RuntimeError("boom")

    client = TestClient(build_app(router), raise_server_exceptions=False)

    assert client.post("/api/v1/fail").status_code == 409
    assert _offset(engine) == 0
    assert client.post("/api/v1/crash").status_code == 500
    assert _offset(engine) == 0
    assert mailbox == []

    # commit=True: записанное до ошибки остаётся (так сохраняется неудачная попытка входа), письмо уходит.
    assert client.post("/api/v1/fail-but-keep").status_code == 401
    assert _offset(engine) == 3
    assert [item.to for item in mailbox] == ["kept@example.com"]


@pytest.mark.real_db
def test_error_status_without_exception_also_rolls_back(engine, db_factory, build_app):
    from fastapi.responses import JSONResponse

    router = APIRouter(route_class=TxRoute)

    @router.post("/soft-fail")
    def soft_fail(db: Db) -> JSONResponse:
        clock.advance(db, 9)
        return JSONResponse({"code": "x", "message": "y"}, status_code=409)

    assert TestClient(build_app(router)).post("/api/v1/soft-fail").status_code == 409
    assert _offset(engine) == 0


@pytest.mark.real_db
def test_failed_commit_is_an_error_not_a_false_success(engine, db_factory, build_app, mailbox, monkeypatch):
    from sqlalchemy.orm import Session

    router = APIRouter(route_class=TxRoute)

    @router.post("/advance")
    def advance(db: Db) -> dict[str, bool]:
        clock.advance(db, 5)
        mail.enqueue(db, "verify_email", "new@example.com", LETTER)
        return {"ok": True}

    def broken_commit(self) -> None:
        raise OperationalError("COMMIT", {}, Exception("connection lost"))

    monkeypatch.setattr(Session, "commit", broken_commit)
    response = TestClient(build_app(router), raise_server_exceptions=False).post("/api/v1/advance")
    monkeypatch.undo()

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    assert _offset(engine) == 0
    assert mailbox == []


# --------------------------------------------------------------------------------------------------------------------
# То же на сессии теста: порядок «данные → письмо», фоновые задачи обработчика сохраняются
# --------------------------------------------------------------------------------------------------------------------


def test_mail_goes_after_commit_and_keeps_handler_background_tasks(probe, tx_router, db, mailbox):
    order: list[str] = []

    @tx_router.post("/signup", status_code=202)
    def signup(db: Db, tasks: BackgroundTasks) -> dict[str, bool]:
        mail.enqueue(db, "verify_email", "new@example.com", LETTER)
        tasks.add_task(order.append, "handler-task")
        assert mailbox == [] and len(mail.pending(db)) == 1  # внутри транзакции письмо только в очереди
        return {"ok": True}

    assert probe(tx_router).post("/api/v1/signup").status_code == 202
    assert order == ["handler-task"]
    assert len(mailbox) == 1
    assert mailbox[0].template == "verify_email"
    assert LETTER["link"] in mailbox[0].text
    assert mail.pending(db) == []


def test_rollback_keeps_data_prepared_before_request(probe, tx_router, db, make_user):
    """Откат запроса не уносит то, что тест создал до запроса (точка сохранения освобождена перед запросом)."""
    user = make_user()

    @tx_router.post("/fail")
    def fail(db: Db) -> None:
        clock.advance(db, 100)
        raise ApiException(409, "session_active")

    assert probe(tx_router).post("/api/v1/fail").status_code == 409
    assert clock.offset_seconds(db) == 0
    assert db.execute(text("SELECT count(*) FROM app_user WHERE id = :id"), {"id": user.id}).scalar() == 1


# --------------------------------------------------------------------------------------------------------------------
# run_in_tx
# --------------------------------------------------------------------------------------------------------------------


def _pg_error(sqlstate: str) -> OperationalError:
    return OperationalError("UPDATE …", {}, SimpleNamespace(sqlstate=sqlstate))  # type: ignore[arg-type]


@pytest.mark.parametrize("sqlstate", ["40001", "40P01"])
def test_run_in_tx_retries_once_and_resets_outbox(db, mailbox, sqlstate):
    calls: list[int] = []

    def operation(session) -> int:
        calls.append(len(calls))
        mail.enqueue(session, "verify_email", "retry@example.com", LETTER)
        clock.advance(session, 10)
        if len(calls) == 1:
            raise _pg_error(sqlstate)
        return 42

    assert run_in_tx(db, operation) == 42
    assert calls == [0, 1]
    assert clock.offset_seconds(db) == 10, "первая попытка должна быть откатана"
    assert len(mail.pending(db)) == 1, "письмо первой попытки должно быть сброшено"
    assert mailbox == [], "run_in_tx сам письма не отправляет: это делает граница запроса после фиксации"


def test_run_in_tx_gives_up_after_second_failure_and_sends_nothing(db, mailbox):
    def operation(session) -> None:
        mail.enqueue(session, "verify_email", "never@example.com", LETTER)
        clock.advance(session, 10)
        raise _pg_error("40001")

    with pytest.raises(OperationalError):
        run_in_tx(db, operation)
    assert clock.offset_seconds(db) == 0
    assert mail.pending(db) == [] and mailbox == []


def test_run_in_tx_does_not_retry_other_errors(db):
    calls: list[int] = []

    def operation(session) -> None:
        calls.append(1)
        mail.enqueue(session, "verify_email", "x@example.com", LETTER)
        raise _pg_error("23505")  # нарушение уникальности — не повод для повтора

    with pytest.raises(OperationalError):
        run_in_tx(db, operation)
    assert calls == [1]
    assert mail.pending(db) == []


def test_run_in_tx_api_exception_rolls_back_unless_commit_requested(db):
    def rejected(session) -> None:
        clock.advance(session, 10)
        raise ApiException(409, "quota_exceeded")

    with pytest.raises(ApiException):
        run_in_tx(db, rejected)
    assert clock.offset_seconds(db) == 0

    def kept(session) -> None:
        clock.advance(session, 10)
        raise ApiException(409, "conditions_mismatch", commit=True)

    with pytest.raises(ApiException):
        run_in_tx(db, kept)
    assert clock.offset_seconds(db) == 10


def test_run_in_tx_inside_request_sends_mail_once(probe, tx_router, mailbox):
    attempts: list[int] = []

    @tx_router.post("/invite", status_code=201)
    def invite(db: Db) -> dict[str, int]:
        def operation(session) -> int:
            attempts.append(1)
            mail.enqueue(session, "verify_email", "candidate@example.com", LETTER)
            if len(attempts) == 1:
                raise _pg_error("40P01")
            return len(attempts)

        return {"attempts": run_in_tx(db, operation)}

    response = probe(tx_router).post("/api/v1/invite")
    assert response.json() == {"attempts": 2}
    assert len(mailbox) == 1, "при повторе письмо не должно уйти дважды"


@pytest.mark.real_db
def test_run_in_tx_survives_real_deadlock(db_factory):
    """Две транзакции берут две блокировки в разном порядке: PostgreSQL обрывает одну с 40P01, повтор проходит."""
    barrier = threading.Barrier(2, timeout=10)
    results: dict[str, int] = {}
    errors: list[BaseException] = []

    def worker(name: str, first: int, second: int) -> None:
        session = db_factory()
        attempts = 0

        def operation(db) -> int:
            nonlocal attempts
            attempts += 1
            db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": first})
            if attempts == 1:
                barrier.wait()  # обе транзакции держат по одной блокировке и идут за второй
            db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": second})
            return attempts

        try:
            results[name] = run_in_tx(session, operation)
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=("a", 910_001, 910_002)),
        threading.Thread(target=worker, args=("b", 910_002, 910_001)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors, errors
    assert sorted(results.values()) == [1, 2], "ровно одна транзакция должна была повториться"


# --------------------------------------------------------------------------------------------------------------------
# session_scope
# --------------------------------------------------------------------------------------------------------------------


def test_session_scope_commits_then_sends_and_drops_on_error(db, mailbox):
    with session_scope() as session:
        clock.advance(session, 4)
        mail.enqueue(session, "verify_email", "scope@example.com", LETTER)
        assert mailbox == []
    assert len(mailbox) == 1
    assert clock.offset_seconds(db) == 4

    with pytest.raises(RuntimeError):
        with session_scope() as session:
            clock.advance(session, 100)
            mail.enqueue(session, "verify_email", "lost@example.com", LETTER)
            raise RuntimeError("boom")
    assert len(mailbox) == 1
    assert clock.offset_seconds(db) == 4
