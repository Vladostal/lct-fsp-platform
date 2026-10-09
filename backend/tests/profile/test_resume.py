"""Резюме: проверки до разбора, двойной движок, отдельный процесс, поля демо-резюме (Арх. 6.14, 10.7; прил. B, §1.5)."""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiException
from app.modules.profile import service
from app.modules.profile.constants import RESUME_MAX_BYTES, RESUME_PARSE_BUDGET_S, RESUME_RATE_PER_HOUR
from app.modules.profile.models import CandidateDeclaredSkill, CandidateProfile, ResumeUpload
from app.modules.profile.resume import extract, parser
from app.modules.profile.resume.upload import upload_resume
from tests.conftest import TestUser
from tests.profile import pdfgen
from tests.profile.conftest import Candidate, profile_data

URL = "/api/v1/candidate/profile/resume"
DEMO_RESUME = Path(__file__).resolve().parents[3] / "data" / "demo-resume.pdf"
RESUME_LINES = [
    "Смирнова Анна Сергеевна",
    "Python-разработчик",
    "Email: anna@example.com",
    "Желаемая должность",
    "Backend-разработчик",
    "Навыки",
    "Python, FastAPI, PostgreSQL, Docker",
    "О себе",
    "Пишу серверный код на Python и люблю понятные интерфейсы, аккуратные запросы к базе данных и честные тесты. "
    "Хочу расти в сторону проектирования сервисов и работы с нагрузкой, помогать коллегам и делиться опытом.",
    "Опыт работы",
    "Март 2022 — август 2024",
    "Python-разработчик, ООО «Пример»",
]


@pytest.fixture
def me(make_user: Callable[..., TestUser], login_as: Callable[..., TestClient]) -> TestUser:
    user = make_user("candidate")
    login_as(user)
    return user


def post(client: TestClient, data: bytes, name: str = "cv.pdf") -> Any:
    return client.post(URL, files={"file": (name, data, "application/pdf")})


def good_pdf() -> bytes:
    return pdfgen.text_pdf([RESUME_LINES])


# --- проверки до разбора ----------------------------------------------------------------------------------------------


def test_too_large_is_413_before_reading_body(client: TestClient, me: TestUser) -> None:
    response = post(client, b"%PDF-" + b"0" * (RESUME_MAX_BYTES + 100_000))
    assert (response.status_code, response.json()["code"]) == (413, "resume_too_large")


def test_size_is_checked_on_actual_bytes(db: Session, me: TestUser, now: datetime) -> None:
    with pytest.raises(ApiException) as error:
        upload_resume(db, me.id, b"%PDF-" + b"0" * RESUME_MAX_BYTES, now)
    assert (error.value.status, error.value.code) == (413, "resume_too_large")


@pytest.mark.parametrize("data", [b"hello world", b"", b"\x00" * 2000 + b"%PDF-1.4"])
def test_not_pdf_is_415(client: TestClient, me: TestUser, data: bytes) -> None:
    response = post(client, data)
    assert (response.status_code, response.json()["code"]) == (415, "resume_not_pdf")


def test_rate_limit_counts_uploads_of_the_last_hour(
    db: Session, client: TestClient, me: TestUser, now: datetime
) -> None:
    def add(created: datetime) -> None:
        db.add(
            ResumeUpload(
                user_id=me.id, sha256="0" * 64, size_bytes=1, status="parsed", parser_version="t", created_at=created
            )
        )

    for _ in range(RESUME_RATE_PER_HOUR - 1):
        add(now - timedelta(minutes=30))
    add(now - timedelta(minutes=61))  # старше часа в счёт не идёт
    db.commit()
    assert post(client, good_pdf()).status_code == 200  # десятая загрузка в окне
    response = post(client, good_pdf())
    assert (response.status_code, response.json()["code"]) == (429, "resume_rate_limited")


@pytest.mark.parametrize(
    ("data", "status", "code"),
    [
        (pdfgen.encrypted_pdf(), 422, "resume_encrypted"),
        (pdfgen.blank_pdf(11), 422, "resume_too_many_pages"),
        (pdfgen.blank_pdf(1), 422, "resume_no_text"),
        (b"%PDF-1.4\nthis is not a pdf at all, only garbage " * 30, 422, "resume_unreadable"),
    ],
    ids=["encrypted", "pages", "scan", "garbage"],
)
def test_error_codes(client: TestClient, db: Session, me: TestUser, data: bytes, status: int, code: str) -> None:
    response = post(client, data)
    assert (response.status_code, response.json()["code"]) == (status, code)
    # Неудачная попытка остаётся в базе (считается в часовом лимите), результата и страниц у неё нет.
    row = db.scalars(select(ResumeUpload).where(ResumeUpload.user_id == me.id)).one()
    assert (row.status, row.error_code, row.result) == ("failed", code, None)


def test_ten_pages_are_fine(client: TestClient, me: TestUser) -> None:
    assert post(client, pdfgen.text_pdf([RESUME_LINES] * 10)).status_code == 200


# --- двойной движок ---------------------------------------------------------------------------------------------------


def test_second_engine_when_first_text_is_unusable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extract, "_with_pypdf", lambda *args: (1, "кракозябры"))
    result = extract.extract(good_pdf())
    assert result["engine"] == "pdfplumber" and "Смирнова" in result["text"]


def test_second_engine_when_first_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: Any) -> tuple[int, str]:
        raise RuntimeError("pypdf сломался")

    monkeypatch.setattr(extract, "_with_pypdf", broken)
    assert extract.extract(good_pdf())["engine"] == "pdfplumber"


def test_both_unusable_is_no_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extract, "_with_pypdf", lambda *args: (1, "мало"))
    monkeypatch.setattr(extract, "_with_pdfplumber", lambda *args: (1, "мало"))
    with pytest.raises(extract.ExtractError) as error:
        extract.extract(good_pdf())
    assert error.value.code == "resume_no_text"


def test_text_criterion_letters_and_share() -> None:
    assert extract.is_usable("а" * 200, 200, 0.5)
    assert not extract.is_usable("а" * 199, 200, 0.5)
    assert not extract.is_usable("а" * 200 + "1" * 400, 200, 0.5)  # цифры и знаки: доля букв меньше половины


def test_short_text_resume_is_not_taken_for_a_scan() -> None:
    """Короткое, но настоящее резюме (сотня букв) пригодно: порог отсекает сканы, а не лаконичных людей."""
    from app.modules.profile.constants import RESUME_MIN_LETTERS

    assert RESUME_MIN_LETTERS == extract.DEFAULTS["min_letters"] == 100
    short = "Иванов И. тел 89001234567. Ищу работу программистом: php, js, mysql, вёрстка. Воронеж, можно удалённо."
    letters, _share = extract.letter_stats(short)
    assert 60 <= letters < 100 and not extract.is_usable(short, 100, 0.5)
    assert extract.is_usable(short + " Делал сайты на битриксе и вордпрессе, интеграции с crm.", 100, 0.5)


# --- поля из неудобной вёрстки ----------------------------------------------------------------------------------------


def test_phone_split_by_line_break_is_joined() -> None:
    from app.modules.profile.resume import fields

    whole = fields.find_phone(["Тел.: +7 (912) 345-67-89"])
    assert whole is not None and (whole.value, whole.confidence) == ("+79123456789", "high")
    wrapped = fields.find_phone(["КОНТАКТЫ", "Тел.: 8 912 345 67", "89", "Почта: a@example.com"])
    assert wrapped is not None and (wrapped.value, wrapped.confidence) == ("+79123456789", "medium")
    assert fields.find_phone(["Опыт 8 лет", "912 задач"]) is None
    # Последняя цифра года — не начало номера: «2018» и числа следующей строки телефоном не становятся.
    assert fields.find_phone(["Работал в 2015 – 2018", "345 123 45 67 задач закрыто"]) is None
    assert fields.find_phone(["Проект 2018 345 123 45 67"]) is None


def test_link_split_after_slash_is_joined() -> None:
    from app.modules.profile.resume import fields

    wrapped = fields.find_link(["почта · t.me/mpetrova · linkedin.com/in/", "mpetrova", "Summary"])
    assert wrapped is not None and wrapped.value == "https://linkedin.com/in/mpetrova"
    # Следующая строка — не продолжение адреса: ссылка остаётся как есть.
    kept = fields.find_link(["github.com/anna-dev", "Опыт работы"])
    assert kept is not None and kept.value == "https://github.com/anna-dev"
    # Адрес с косой чертой в конце и заголовок раздела или слово с заглавной буквы на следующей строке.
    for following in ("Skills", "summary", "Projects"):
        whole = fields.find_link(["https://github.com/anna-dev/", following])
        assert whole is not None and whole.value.rstrip("/") == "https://github.com/anna-dev", following


def test_name_in_capitals_and_outside_the_head() -> None:
    from app.modules.profile.resume import fields

    caps = fields.name_candidate(["ДАРЬЯ ОРЛОВА", "Data Scientist"])
    assert caps is not None and caps.words == ("Дарья", "Орлова")
    # Заголовок прописными именем не считается.
    assert fields.name_candidate(["ЯЗЫКИ ПРОГРАММИРОВАНИЯ", "Python"]) is None
    assert fields.name_candidate(["КЛЮЧЕВЫЕ НАВЫКИ"]) is None
    # Латиница прописными не принимается: «CONTACT INFORMATION» от имени по форме не отличить.
    assert fields.name_candidate(["CONTACT INFORMATION", "John Smith"]).words == ("John", "Smith")
    assert fields.name_candidate(["SOFTWARE ENGINEER"]) is None

    two_columns = ["КОНТАКТЫ", "Тел.: 8 912 345 67", "89", "НАВЫКИ", "Python", "ДАРЬЯ ОРЛОВА", "ML-инженер, Middle"]
    located = fields.name_by_dictionary(two_columns)
    assert located is not None
    candidate, next_line = located
    assert candidate.words == ("Дарья", "Орлова") and next_line == "ML-инженер, Middle"
    assert fields.name_by_dictionary(["КОНТАКТЫ", "НАВЫКИ", "Python Django"]) is None


def test_two_column_resume_gets_name_and_grade_from_the_line_under_it() -> None:
    from datetime import date

    left_column = ["КОНТАКТЫ", "Тел.: 8 912 345 67", "89", "Почта:", "d.orlova@example.com", "г. Екатеринбург"]
    skills = ["НАВЫКИ", "Python", "Pandas, NumPy", "SQL"]
    right_column = ["ДАРЬЯ ОРЛОВА", "Data Scientist / ML-инженер, Middle", "ОПЫТ"]
    jobs = ["2023 – н.в. — ML-инженер. Модели ранжирования.", "2021 – 2023 — младший аналитик данных."]
    text = "\n".join([*left_column, *skills, *right_column, *jobs])
    result = parser.build_result(text, today=date(2026, 10, 9), pages=1, engine="pypdf", started=time.monotonic())
    fields_found = result.fields
    assert (fields_found["first_name"].value, fields_found["last_name"].value) == ("Дарья", "Орлова")
    assert fields_found["first_name"].confidence == "medium"  # найдено вне шапки — уверенность ниже
    assert fields_found["phone"].value == "+79123456789"
    assert fields_found["grade_hint"].value == "middle"


# --- отдельный процесс ------------------------------------------------------------------------------------------------


def test_text_is_extracted_in_a_child_process(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[list[str]] = []
    real = parser.subprocess.Popen

    def spy(command: list[str], *args: Any, **kwargs: Any) -> Any:
        started.append(command)
        return real(command, *args, **kwargs)

    monkeypatch.setattr(parser.subprocess, "Popen", spy)
    result = parser.run_extract(good_pdf())
    assert result["engine"] == "pypdf" and "Смирнова Анна Сергеевна" in result["text"]
    assert len(started) == 1 and started[0][0] == sys.executable and started[0][-1].startswith("{")
    assert started[0][1:3] == ["-I", "-B"] and Path(started[0][3]).name == "extract.py"


def heavy_pdf() -> bytes:
    """Одна страница, которую pypdf разбирает десятки секунд при малом расходе памяти: форма из 10 тысяч операторов,
    вызванная 400 раз (разбирается заново при каждом вызове).
    """
    return pdfgen.text_pdf([["Резюме " * 40]], form_ops=10_000, form_calls=400)


def test_heavy_page_times_out_without_blocking_others() -> None:
    heavy = heavy_pdf()
    outcome: dict[str, Any] = {}

    def run() -> None:
        started = time.monotonic()
        try:
            parser.run_extract(heavy, budget_s=1.5)
        except parser.ResumeFailure as failure:
            outcome["code"] = failure.code
        outcome["elapsed"] = time.monotonic() - started

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(0.3)
    quick_started = time.monotonic()
    assert "Смирнова" in parser.run_extract(good_pdf())["text"]  # другой разбор идёт параллельно
    quick = time.monotonic() - quick_started
    thread.join(timeout=10)
    assert outcome["code"] == "resume_timeout"
    assert 1.4 < outcome["elapsed"] < 4
    assert quick < outcome["elapsed"] + 1


@pytest.mark.slow
def test_default_budget_is_five_seconds(client: TestClient, me: TestUser, db: Session) -> None:
    assert RESUME_PARSE_BUDGET_S == 5.0
    started = time.monotonic()
    response = post(client, heavy_pdf())
    elapsed = time.monotonic() - started
    assert (response.status_code, response.json()["code"]) == (422, "resume_timeout")
    assert 4.9 < elapsed < 8
    assert db.scalars(select(ResumeUpload.error_code)).one() == "resume_timeout"


def test_at_most_two_parses_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parser, "RESUME_QUEUE_WAIT_S", 0.3)
    heavy = heavy_pdf()
    results: list[str] = []

    def run() -> None:
        try:
            parser.run_extract(heavy, budget_s=2.0)
        except parser.ResumeFailure as failure:
            results.append(failure.code)

    threads = [threading.Thread(target=run) for _ in range(3)]
    for thread in threads:
        thread.start()
        time.sleep(0.05)
    for thread in threads:
        thread.join(timeout=15)
    # Два разбора заняли места и упёрлись в бюджет; третий не дождался очереди.
    assert sorted(results) == ["resume_rate_limited", "resume_timeout", "resume_timeout"]


@pytest.mark.skipif(sys.platform != "linux", reason="RLIMIT_AS не действует на macOS: проверяется в контейнере api")
def test_child_memory_is_limited_to_256_mb() -> None:
    answer = parser._run_child(
        b"", parser._params(5.0, 256 * 1024 * 1024), budget_s=5.0, extra_args=["--selftest-memory"]
    )
    assert answer == {"limit": 256 * 1024 * 1024, "allocated": False}


def test_pdfplumber_runs_in_child_process_under_the_memory_limit() -> None:
    """Второй движок тяжелее первого: в дочернем процессе с пределом 256 МБ (на Linux) он должен отработать."""
    params = parser._params(5.0, 256 * 1024 * 1024, engines=["pdfplumber"])
    answer = parser._run_child(good_pdf(), params, budget_s=5.0)
    assert answer is not None and answer["ok"] is True, answer
    assert answer["engine"] == "pdfplumber" and "Смирнова" in answer["text"]


# --- результат --------------------------------------------------------------------------------------------------------


def test_parse_result_and_bytes_are_not_stored(client: TestClient, me: TestUser, db: Session) -> None:
    data = good_pdf()
    response = post(client, data)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "parsed" and body["total"] == 9 and body["meta"]["engine"] == "pypdf"
    assert body["fields"]["email"]["value"] == "anna@example.com"
    row = db.scalars(select(ResumeUpload)).one()
    import hashlib

    assert row.sha256 == hashlib.sha256(data).hexdigest() and row.size_bytes == len(data) and row.pages == 1
    assert row.status == "parsed" and row.result is not None and "%PDF" not in str(row.result)
    columns = {column.name for column in ResumeUpload.__table__.columns}
    assert not {name for name in columns if "byte" in name and name != "size_bytes"} and "file" not in columns


def test_demo_resume_is_recognized_in_at_least_eight_fields(client: TestClient, me: TestUser) -> None:
    assert DEMO_RESUME.exists()
    response = post(client, DEMO_RESUME.read_bytes(), "demo-resume.pdf")
    assert response.status_code == 200, response.text
    body = response.json()
    fields = body["fields"]
    assert body["recognized"] >= 8 and body["total"] == 9, sorted(fields)
    assert (fields["last_name"]["value"], fields["first_name"]["value"], fields["middle_name"]["value"]) == (
        "Смирнова",
        "Анна",
        "Сергеевна",
    )
    assert fields["email"]["value"] == "anna.smirnova@example.com"
    assert fields["phone"]["value"] == "+79171234567"
    assert fields["telegram"]["value"] == "@anna_smirnova_dev"
    assert fields["link"]["value"] == "https://github.com/anna-smirnova-demo"
    assert fields["city"]["value"] == "Казань"
    assert fields["experience_years"]["value"] == 4.0 and fields["experience_years"]["confidence"] == "medium"
    skills = [s["code"] for s in fields["declared_skills"]["value"]]
    assert skills[0] == "python" and {"fastapi", "django", "postgresql", "docker"} <= set(skills)  # чаще всех — Python
    assert {s["code"] for s in fields["soft_skills"]["value"]} >= {"communication", "responsibility", "teamwork"}
    assert fields["grade_hint"]["value"] == "middle"
    assert fields["about"]["value"].startswith("Пишу серверный код")
    assert all(len(f.get("snippet") or "") <= 120 for f in fields.values())


def test_unknown_terms_are_returned_but_never_logged(
    client: TestClient, me: TestUser, world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.catalog import service as catalog

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("резюме не должно писать в skill_miss_log (R3-data-api-security-5)")

    monkeypatch.setattr(catalog, "log_miss", forbidden)
    world.unknown_terms = ["Tarantool"]
    assert post(client, good_pdf()).json()["unknown_terms"] == ["Tarantool"]


def test_facade_failure_does_not_break_upload(
    client: TestClient, me: TestUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.textparse import service as textparse

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("заглушка")

    monkeypatch.setattr(textparse, "link_skills", broken)
    body = post(client, good_pdf()).json()
    assert "declared_skills" not in body["fields"] and body["fields"]["email"]["value"] == "anna@example.com"


# --- сохранение профиля с загрузкой; обнуление результата ------------------------------------------------------------


def test_save_profile_zeroes_result_and_moves_hints(client: TestClient, me: TestUser, db: Session) -> None:
    upload_id = post(client, DEMO_RESUME.read_bytes()).json()["upload_id"]
    payload = {
        "last_name": "Смирнова",
        "first_name": "Анна",
        "declared_skills": [{"code": "python"}, {"custom_label": "Tarantool"}],
        "resume_upload_id": upload_id,
        "resume_accepted_fields": ["last_name", "email"],
    }
    response = client.put("/api/v1/candidate/profile", json=payload)
    assert response.status_code == 200, response.text
    row = db.get(ResumeUpload, upload_id)
    assert row is not None and row.result is None and row.accepted_fields == ["last_name", "email"]
    profile = db.get(CandidateProfile, me.id)
    assert profile is not None and profile.grade_hint == "middle" and profile.specialization_hint == "backend"
    sources = {s.skill_code or s.custom_label: s.source for s in db.scalars(select(CandidateDeclaredSkill))}
    assert sources == {"python": "resume", "Tarantool": "manual"}
    data = client.get("/api/v1/candidate/profile").json()
    assert data["hints"] == {"grade_hint": "middle", "specialization_hint": "backend"}
    assert data["resume"]["upload_id"] == upload_id and data["resume"]["status"] == "parsed"


def test_foreign_upload_is_404(
    client: TestClient, me: TestUser, db: Session, make_candidate: Callable[..., Candidate]
) -> None:
    other = make_candidate()
    row = ResumeUpload(
        id=uuid4(),
        user_id=other.id,
        sha256="0" * 64,
        size_bytes=1,
        status="parsed",
        parser_version="t",
        created_at=datetime.now().astimezone(),
        result={"fields": {}},
    )
    db.add(row)
    db.commit()
    response = client.put(
        "/api/v1/candidate/profile",
        json={"last_name": "Я", "first_name": "Ты", "resume_upload_id": str(row.id)},
    )
    assert response.status_code == 404
    db.refresh(row)
    assert row.result == {"fields": {}}


def test_purge_resume_results_after_24_hours(db: Session, me: TestUser, now: datetime) -> None:
    def add(age_hours: float) -> ResumeUpload:
        row = ResumeUpload(
            user_id=me.id,
            sha256="0" * 64,
            size_bytes=1,
            status="parsed",
            parser_version="t",
            created_at=now - timedelta(hours=age_hours),
            result={"fields": {"email": {"value": "a@example.com"}}},
        )
        db.add(row)
        return row

    old, fresh = add(25), add(23)
    failed_old = ResumeUpload(
        user_id=me.id,
        sha256="0" * 64,
        size_bytes=1,
        status="failed",
        error_code="resume_no_text",
        parser_version="t",
        created_at=now - timedelta(hours=30),
    )
    db.add(failed_old)
    db.flush()
    assert service.purge_resume_results(db, now) == 1
    db.refresh(old)
    db.refresh(fresh)
    assert old.result is None and fresh.result is not None
    assert service.purge_resume_results(db, now) == 0


def test_profile_data_rejects_garbage_resume_fields() -> None:
    with pytest.raises(ValueError):
        profile_data(resume_accepted_fields=["x" * 41])
