"""Общий инструмент сценарной проверки: клиенты ролей, синтетические аккаунты, журнал результатов.

Запуск сценариев: `backend/.venv/bin/python qa-audit/tools/<файл>.py` при поднятом стенде (`docker compose up -d`).
Пароли проверочных аккаунтов создаются случайно на время запуска и никуда не пишутся. Адреса — только
`qa.*@example.com`. Ответы заданий берутся из базы стенда (`docker compose exec db psql`): это ключ банка, нужный,
чтобы вести тест по заранее заданной последовательности; независимая проверка самих ключей — отдельные сценарии BANK.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
BASE = os.environ.get("QA_BASE_URL", "http://localhost:8080")
API = "/api/v1"
EVIDENCE = ROOT / "qa-audit" / "evidence"
RESULTS = EVIDENCE / "results.jsonl"
ENTITIES = EVIDENCE / "entities.jsonl"
RUN = datetime.now(UTC).strftime("%m%d%H%M%S")
PASSWORD = os.environ.get("QA_PASSWORD") or "Qa-" + secrets.token_urlsafe(12)  # одна на запуск, в отчёты не попадает
SURVEY = {"direction": "development", "specialization": "backend", "main_language": "python", "experience_band": "2_4"}
_seq = 0


def sql(query: str) -> str:
    out = subprocess.run(
        ["docker", "compose", "-f", str(ROOT / "compose.yml"), "exec", "-T", "db", "psql", "-U", "app", "-d", "app", "-Atc", query],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    return out.stdout.strip()


def admin_headers() -> dict[str, str]:
    token = next(
        line.split("=", 1)[1].strip() for line in (ROOT / ".env").read_text().splitlines() if line.startswith("ADMIN_TOKEN=")
    )
    return {"X-Admin-Token": token, "Origin": BASE}


def rec(case: str, title: str, level: str, expected: str, actual: Any, ok: bool | None, *, status: str | None = None,
        source: str = "", note: str = "") -> bool:  # fmt: skip
    """Записать результат проверки. `ok=None` требует явного `status` (BLOCKED, N/A, SPEC GAP, NOT RUN)."""
    state = status or ("PASS" if ok else "FAIL")
    actual_text = actual if isinstance(actual, str) else json.dumps(actual, ensure_ascii=False, default=str)
    row = {
        "id": case, "title": title, "level": level, "source": source, "expected": expected,
        "actual": actual_text[:700], "status": state, "note": note, "run": RUN, "at": datetime.now(UTC).isoformat(timespec="seconds"),
    }  # fmt: skip
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    with RESULTS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    if state != "PASS" or os.environ.get("QA_VERBOSE"):
        mark = {"PASS": "  ok ", "FAIL": " FAIL"}.get(state, f" {state}")
        print(f"{mark} {case:10} {title}" + ("" if state == "PASS" else f" — {actual_text[:300]}"))
    return state == "PASS"


def entity(kind: str, **fields: Any) -> None:
    with ENTITIES.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"kind": kind, "run": RUN, **fields}, ensure_ascii=False, default=str) + "\n")


class User:
    """Независимый «браузерный контекст» роли на уровне API: своя сессия и cookie."""

    def __init__(self, label: str = "") -> None:
        self.label = label
        self.email = ""
        self.id = ""
        self.c = httpx.Client(base_url=BASE, timeout=60, headers={"Origin": BASE})

    def call(self, method: str, path: str, **kw: Any) -> tuple[int, Any]:
        reply = self.c.request(method, API + path if path.startswith("/") and not path.startswith("/api") else path, **kw)
        try:
            body = reply.json()
        except Exception:
            body = reply.text[:300]
        return reply.status_code, body

    def get(self, path: str, **kw: Any) -> tuple[int, Any]:
        return self.call("GET", path, **kw)

    def post(self, path: str, body: Any = None, **kw: Any) -> tuple[int, Any]:
        return self.call("POST", path, json=body, **kw) if body is not None else self.call("POST", path, **kw)

    def put(self, path: str, body: Any = None, **kw: Any) -> tuple[int, Any]:
        return self.call("PUT", path, json=body, **kw) if body is not None else self.call("PUT", path, **kw)

    def clone(self) -> "User":
        other = User(self.label)
        other.email, other.id = self.email, self.id
        for key, value in self.c.cookies.items():
            other.c.cookies.set(key, value)
        return other


def mails(to: str) -> list[dict[str, str]]:
    found = httpx.get(BASE + "/mail/api/v1/search", params={"query": f"to:{to}"}, timeout=30).json()
    out = []
    for item in found.get("messages", []):
        full = httpx.get(BASE + f"/mail/api/v1/message/{item['ID']}", timeout=30).json()
        out.append({"subject": full["Subject"], "text": full["Text"], "to": ",".join(a["Address"] for a in full["To"])})
    return out


def mail_token(to: str, needle: str = "token=", tries: int = 30) -> str | None:
    for _ in range(tries):
        for message in mails(to):
            match = re.search(r"token=([\w\-.]+)", message["text"])
            if match and needle in message["text"]:
                return match.group(1)
        time.sleep(0.4)
    return None


def new_email(tag: str) -> str:
    global _seq
    _seq += 1
    return f"qa.{tag}.{RUN}{_seq}@example.com"


_FIXTURE = """
import sys
from app.core import clock, db
from app.modules.identity import service as identity
from app.shared.enums import ConsentKind, Role
email, password, role = sys.argv[1:4]
with db.session_scope() as s:
    uid = identity.create_user(s, email, password, Role(role), verified=True, is_demo=False, demo_key=None)
    text = identity.current_consent(ConsentKind.PROCESSING)
    identity.grant_consent(s, uid, ConsentKind.PROCESSING, text.version, text.sha256, "seed", clock.real_now())
    print(uid)
"""


def fixture_user(tag: str, role: str = "candidate") -> User:
    """ФИКСТУРА: подтверждённый аккаунт создаётся сервисом identity в контейнере api, минуя форму регистрации.

    Нужна, когда исчерпан лимит регистраций с одного адреса (50 в час). Регистрацию и подтверждение почты такие
    аккаунты не проверяют — это делают сценарии AUTH и E2E-01; вход выполняется обычным запросом `/auth/login`.
    """
    user = User(tag)
    user.email = new_email(tag)
    out = subprocess.run(
        ["docker", "compose", "-f", str(ROOT / "compose.yml"), "exec", "-T", "api", "python", "-c", _FIXTURE, user.email, PASSWORD, role],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert out.returncode == 0, out.stderr[-600:]
    user.id = out.stdout.strip().splitlines()[-1]
    status, reply = user.post("/auth/login", {"email": user.email, "password": PASSWORD})
    assert status == 200, (status, reply)
    entity(role, label=tag, email=user.email, id=user.id, created_via="FIXTURE")
    return user


FIXTURE_ONLY = bool(os.environ.get("QA_FIXTURE_USERS"))


def signup(tag: str, role: str = "candidate", *, verify: bool = True) -> User:
    if FIXTURE_ONLY and verify:
        return fixture_user(tag, role)
    user = User(tag)
    user.email = new_email(tag)
    body = {"email": user.email, "password": PASSWORD, "role": role, "consent_processing": True,
            "consent_version": "processing-1", "is_adult": True}  # fmt: skip
    status, reply = user.post("/auth/signup", body)
    if status == 429 and verify:  # лимит регистраций с адреса — продолжаем на фикстуре
        return fixture_user(tag, role)
    assert status == 202, (status, reply)
    if verify:
        token = mail_token(user.email)
        assert token, f"нет письма подтверждения для {user.email}"
        status, reply = user.post("/auth/verify-email", {"token": token})
        assert status == 200, (status, reply)
        user.id = sql(f"select id from app_user where email='{user.email}'")
    entity(role, label=tag, email=user.email, id=user.id, created_via="API")
    return user


PROFILE = {"last_name": "Проверкин", "first_name": "Тест", "city": "Казань", "phone": "+79120000000",
           "telegram": "@qa_marker_tg", "experience_years": 3, "about": "Пишу бэкенд на Python.",
           "declared_skills": [{"code": "python"}, {"code": "postgresql"}]}  # fmt: skip


def candidate(tag: str, grade: str = "middle", *, min_salary: int | None = 200_000,
              formats: tuple[str, ...] = ("remote", "hybrid"), profile: dict[str, Any] | None = None) -> User:  # fmt: skip
    """Кандидат после мастера: профиль, условия, опрос, заявленный грейд. Теста ещё нет."""
    user = signup(tag)
    status, reply = user.put("/candidate/profile", {**PROFILE, **(profile or {})})
    assert status == 200, reply
    status, reply = user.put("/candidate/conditions", {"min_salary": min_salary, "work_formats": list(formats)})
    assert status == 200, reply
    status, reply = user.put("/assessment/survey", {"version": "2026.10", "answers": SURVEY})
    assert status == 200, reply
    status, reply = user.put("/assessment/claim", {"grade_code": grade})
    assert status == 200, reply
    return user


def employer(tag: str) -> User:
    user = signup(tag, "employer")
    body = {"name": f"ООО Проверка {tag}", "sphere": "Финтех",
            "description": "Платёжные сервисы для малого бизнеса, команда 40 человек, работаем удалённо.",
            "contact_method": {"kind": "email", "value": user.email}}  # fmt: skip
    status, reply = user.put("/employer/company", body)
    assert status == 200, reply
    return user


# --- тест -------------------------------------------------------------------------------------------------------------


def item_row(item_id: str) -> dict[str, Any]:
    raw = sql(
        "select json_build_object('kind', v.payload->>'kind', 'answer', v.answer, 'options', v.payload->'options', "
        "'b', i.b_used, 'family', i.family_id, 'level', i.level, 'position', i.position, 'variant', i.variant_id) "
        f"from assessment_session_item i join assessment_variant v on v.id = i.variant_id where i.id = '{item_id}'"
    )
    return json.loads(raw)


def right(row: dict[str, Any]) -> dict[str, Any]:
    kind, key = row["kind"], row["answer"]
    if kind in ("numeric_input", "text_input"):
        return {"value": str(key["value"]) if kind == "numeric_input" else key["value"]}
    if kind == "single_choice":
        return {"option_id": key["option_id"]}
    if kind == "multi_choice":
        return {"option_ids": key["option_ids"]}
    return {"line": key["lines"][0]}


def wrong(row: dict[str, Any]) -> dict[str, Any]:
    """Ответ верного формата, но заведомо неверный."""
    kind, key = row["kind"], row["answer"]
    if kind == "numeric_input":
        return {"value": str(int(float(key["value"])) + 7)}
    if kind == "text_input":
        return {"value": "нет такого ответа"}
    ids = [option["id"] for option in (row["options"] or [])]
    if kind == "single_choice":
        return {"option_id": next(i for i in ids if i != key["option_id"])}
    if kind == "multi_choice":
        other = [i for i in ids if i not in key["option_ids"]]
        return {"option_ids": other[:1] or ids[:1]}
    return {"line": key["lines"][0] + 1 if key["lines"][0] < 3 else key["lines"][0] - 1}


def start(user: User, grade: str, *, quick: bool = False) -> tuple[str, dict[str, Any] | None]:
    if quick:
        status, reply = user.post("/demo/assessment/quick-session", {"grade_code": grade})
        assert status == 200, (status, reply)
        session_id = reply["session_id"]
        return session_id, user.get(f"/assessment/sessions/{session_id}")[1]["item"]
    status, reply = user.post("/assessment/sessions", {"grade_code": grade})
    assert status == 201, (status, reply)
    return reply["id"], reply["item"]


def run_test(user: User, session_id: str, item: dict[str, Any] | None, plan: Any) -> list[dict[str, Any]]:
    """Пройти тест. `plan(n, row)` возвращает 'right' | 'wrong' | 'skip' для n-го задания (с единицы)."""
    trail: list[dict[str, Any]] = []
    number = 0
    while item:
        number += 1
        row = item_row(item["id"])
        move = plan(number, row)
        body: dict[str, Any] = {"item_id": item["id"]}
        if move == "skip":
            body["skipped"] = True
        else:
            body["answer"] = right(row) if move == "right" else wrong(row)
        status, reply = user.post(f"/assessment/sessions/{session_id}/answers", body)
        trail.append({"n": number, "item": item["id"], "move": move, "status": status, "family": row["family"],
                      "variant": row["variant"], "b": row["b"], "kind": row["kind"]})  # fmt: skip
        assert status == 200, (number, status, reply)
        item = reply.get("next_item")
    return trail


def session_db(session_id: str) -> dict[str, Any]:
    raw = sql(
        "select json_build_object('status', status, 'outcome', outcome, 'theta', theta, 'answered', items_answered, "
        "'pooled', pooled_items, 'stage', stage, 'flags', flags, "
        "'items', (select json_agg(json_build_object('p', position, 's', status, 'score', score) order by position) "
        f"from assessment_session_item where session_id = s.id)) from assessment_session s where id = '{session_id}'"
    )
    return json.loads(raw)


def finish_and_publish(user: User, grade: str = "middle", *, quick: bool = True) -> dict[str, Any]:
    session_id, item = start(user, grade, quick=quick)
    run_test(user, session_id, item, lambda n, row: "right")
    status, reply = user.post("/candidate/consents/publication", {"action": "grant", "version": "publication-1"})
    assert status == 200 and reply["state"] == "visible", reply
    profile = user.get("/candidate/profile")[1]
    entity("published", label=user.label, email=user.email, id=user.id, public_code=profile["public_code"], grade=grade,
           demo_result=quick)  # fmt: skip
    return profile


def idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


def invitation(candidate_id: str, contact_email: str, *, low: int = 220_000, high: int = 300_000,
               work_format: str = "remote", **extra: Any) -> dict[str, Any]:  # fmt: skip
    return {"title": "Backend-разработчик в платежи",
            "description": "Команда платежей ищет бэкенд-разработчика: сервисы приёма платежей, Python, PostgreSQL.",
            "work_format": work_format, "city": "Казань", "salary_from": low, "salary_to": high,
            "contact_method": {"kind": "email", "value": contact_email}, "candidate_id": candidate_id, **extra}  # fmt: skip


NEED = {"title": "Backend-разработчик", "team_description": "Команда платежей, 8 человек, сервисы приёма платежей.",
        "specialization_code": "backend", "grade_code": "middle", "must_skills": ["python", "postgresql"],
        "nice_skills": ["docker"], "work_formats": ["remote", "hybrid"], "city": "Казань", "salary_from": 220_000,
        "salary_to": 300_000}  # fmt: skip


# --- сохранение сессий между запусками (вне репозитория: cookie — секрет) -----------------------------------------------

STATE = Path(os.environ.get("QA_STATE_DIR", "/tmp/qa-audit-state"))


def save(user: User, name: str) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / f"{name}.json").write_text(json.dumps({"email": user.email, "id": user.id, "cookies": dict(user.c.cookies)}))
    os.chmod(STATE / f"{name}.json", 0o600)


def load(name: str) -> User:
    data = json.loads((STATE / f"{name}.json").read_text())
    user = User(name)
    user.email, user.id = data["email"], data["id"]
    for key, value in data["cookies"].items():
        user.c.cookies.set(key, value)
    return user
