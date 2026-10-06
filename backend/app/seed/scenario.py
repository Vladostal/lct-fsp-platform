"""Именованные аккаунты сценария показа и работодатель `orbita` (Арх. 13.5).

Кандидаты `anna`, `dmitry`, `ivan`, `gleb`, `boris`, `olga`, `maria`, `petr` — `backend`, пароль из `DEMO_PASSWORD`,
адрес `{key}@demo.test`. Состояния получены вызовами функций записи фасадов с датами в прошлом отсчётом от
текущего времени сервиса. Аккаунт `nina` (клон на вход) в этой сборке не создаётся.

`orbita` и демо-компании при перезапуске сценария не удаляются: пересоздаются только именованные кандидаты,
а `orbita` получает новую версию подборки и заново отправляет приглашения сценария.
"""

# ruff: noqa: E501 — тексты сценария

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.core.db import session_scope
from app.eval.testing.bank import from_db
from app.eval.testing.pathsim import PathResult
from app.modules.company import service as company
from app.modules.company.dto import CompanyData
from app.modules.contact import service as contact
from app.modules.fsp import service as fsp
from app.modules.identity import service as identity
from app.modules.matching import service as matching
from app.modules.matching.dto import NeedData, NeedRefDTO
from app.seed import common as C
from app.seed import companies, people
from app.shared.enums import ContactKind, DeclineReason, Role, TestOutcome, TrustLevel, WorkFormat
from app.shared.schemas import ContactMethod
from app.simulation.population import WorldParams, item_world

H, R, OFF = WorkFormat.HYBRID, WorkFormat.REMOTE, WorkFormat.OFFICE
SCENARIO_OFFSET = 4
ORBITA_EMAIL = "hr-orbita@example.com"
ORBITA_NEED_TITLE = "Backend-разработчик в платёжный сервис"


@dataclass(frozen=True)
class Named:
    key: str
    last_name: str
    first_name: str
    grade: str
    min_salary: int | None
    formats: tuple[WorkFormat, ...]
    city: str
    theta: float | None
    #: Условие на путь теста: `None` — категория того же грейда; иначе имя проверки.
    shape: str | None = None
    fsp_persona: str | None = None
    publish: bool = True
    about: str | None = None


NAMED: tuple[Named, ...] = (
    Named("anna", "Соколова", "Анна", "middle", 160_000, (H, R), "Москва", 0.8, fsp_persona="anna",
          about="Три года пишу сервисы на Python, в школе и университете участвовала в соревнованиях по спортивному программированию."),
    Named("dmitry", "Волков", "Дмитрий", "middle", 260_000, (H, R), "Санкт-Петербург", 0.7),
    Named("ivan", "Морозов", "Иван", "middle", 180_000, (H, R), "Москва", 0.6),
    Named("gleb", "Новиков", "Глеб", "middle", 140_000, (H, R), "Казань", 0.5),
    Named("boris", "Кузнецов", "Борис", "junior", 80_000, (H, R, OFF), "Москва", -0.8),
    Named("olga", "Попова", "Ольга", "middle", 160_000, (R,), "Новосибирск", 0.6, fsp_persona="olga"),
    Named("maria", "Фёдорова", "Мария", "middle", 200_000, (H, R), "Москва", 1.15, shape="margin"),
    Named("petr", "Орлов", "Пётр", "middle", 140_000, (H, R), "Екатеринбург", -0.9, shape="unconfirmed"),
)  # fmt: skip


def _accept(spec: Named) -> Callable[[PathResult], bool]:
    if spec.shape == "margin":
        return lambda path: path.grade == spec.grade and path.sessions[0].outcome == TestOutcome.CONFIRMED_WITH_MARGIN
    if spec.shape == "unconfirmed":
        return lambda path: path.grade is None and path.sessions[0].outcome == TestOutcome.NOT_CONFIRMED
    return lambda path: path.grade == spec.grade


def _expected(grade: str) -> int:
    return 1000 + {"junior": 1, "middle": 2, "senior": 3}[grade]


def seed_named() -> int:
    """Создать недостающих именованных кандидатов; вернуть число созданных."""
    if not C.ensure_ready():
        return 0
    rng = C.rng_for(SCENARIO_OFFSET)
    with session_scope() as db:
        bank = from_db(db)
        now = clock.now(db)
    world = item_world(bank.families, rng, WorldParams())
    created = 0
    for position, spec in enumerate(NAMED, start=1):
        finished_at = now - timedelta(days=45 + position)
        candidate, path, sessions = people.simulate(
            bank, world, rng, 1000 + position, spec.grade if spec.shape != "unconfirmed" else "middle", finished_at,
            theta=spec.theta, max_sessions=1, accept=_accept(spec),
        )  # fmt: skip
        person = people.build_person(
            spec.key, 1000 + position, candidate, path, sessions, rng, finished_at, claimed=candidate.claimed_grade,
            publish=spec.publish,
        )  # fmt: skip
        person.last_name, person.first_name, person.city = spec.last_name, spec.first_name, spec.city
        person.min_salary, person.formats, person.persona = spec.min_salary, list(spec.formats), None
        if spec.about:
            person.about = spec.about
        if spec.fsp_persona:
            person.fsp_id = fsp.demo_persona_id(spec.fsp_persona)
        with session_scope() as db:
            if identity.demo_user_ids(db, [spec.key]):
                continue
            people.create_candidate(db, person)
            created += 1
    return created


def _named_ids(db: Session) -> dict[str, UUID]:
    result: dict[str, UUID] = {}
    for key in C.CANDIDATE_KEYS:
        ids = identity.demo_user_ids(db, [key])
        if ids:
            result[key] = ids[0]
    return result


def _find_need(db: Session, employer_id: UUID) -> NeedRefDTO | None:
    """Потребность `orbita` по первому событию её приглашений (отдельного перечня потребностей в фасадах нет)."""
    events = contact.events_since(db, employer_id, 0, 1)
    if not events:
        return None
    need_id = contact.invitation_for_export(db, employer_id, events[0].invitation_id).need_id
    return matching.need_ref(db, employer_id, need_id) if need_id else None


def _create_need(db: Session, employer_id: UUID, now: datetime) -> NeedRefDTO:
    need_id = matching.create_need(
        db, employer_id,
        NeedData(
            title=ORBITA_NEED_TITLE,
            team_description="Платёжное ядро: шесть разработчиков, ревью обязательно, дежурства по очереди.",
            specialization_code="backend", grade_code="middle",
            must_skills=["python", "postgresql", "kafka"], nice_skills=["redis", "docker"],
            work_formats=[H], city="Москва", salary_from=180_000, salary_to=240_000,
        ),
        now - timedelta(days=30), is_demo=True,
    )  # fmt: skip
    matching.create_snapshot(db, employer_id, need_id, now - timedelta(hours=1))
    return matching.need_ref(db, employer_id, need_id)


def _history(db: Session, employer_id: UUID, need: NeedRefDTO, now: datetime) -> None:
    """История `orbita` с синтетическими кандидатами: принятые, два отказа по формату, отказ по стеку, отзыв, истечение."""
    rng = C.rng_for(SCENARIO_OFFSET + 1)
    named = set(_named_ids(db).values())
    pool = companies.candidates_by_category(db, named)
    options = [item for item in pool.get("middle", []) if item[1] is None or item[1] <= need.salary_from]
    rng.shuffle(options)
    plan = (
        (28, "accepted", None), (25, "accepted", None), (22, "declined", "format"), (19, "declined", "format"),
        (16, "declined", "stack"), (13, "withdrawn", None), (10, "expired", None),
    )  # fmt: skip
    used: set[UUID] = set()
    for days_ago, outcome, reason in plan:
        wants_other = reason == "format"
        for candidate_id, _, formats in options:
            if candidate_id in used or H not in formats or (wants_other and len(formats) < 2):
                continue
            used.add(candidate_id)
            other = next((item for item in formats if item != H), None)
            decline = (DeclineReason.FORMAT, other.value) if wants_other and other else (DeclineReason.STACK, None)
            companies.run_outcome(
                db, employer_id, need, candidate_id, outcome, now - timedelta(days=days_ago), ORBITA_EMAIL,
                C.invitation_key(C.EMPLOYER_KEY, "history", days_ago), work_format=H, decline=decline,
            )  # fmt: skip
            break


def _scenario_invitations(db: Session, employer_id: UUID, need: NeedRefDTO, now: datetime) -> None:
    """Приглашения сценария пересозданным именованным кандидатам: ключ идемпотентности — от идентификатора."""
    ids = _named_ids(db)
    plan = (("dmitry", 9), ("gleb", 6), ("ivan", 2), ("anna", 1))
    for key, days_ago in plan:
        candidate_id = ids.get(key)
        if candidate_id is None:
            continue
        if key == "gleb":
            _first_silence(db, candidate_id, now)
        contact.send_invitation(
            db, now - timedelta(days=days_ago), employer_id,
            companies.invitation_data(need, candidate_id, H, ORBITA_EMAIL),
            C.invitation_key(C.EMPLOYER_KEY, "scenario", candidate_id),
        )  # fmt: skip


def _first_silence(db: Session, candidate_id: UUID, now: datetime) -> None:
    """Первое молчание `gleb`: приглашение демо-компании двадцатидневной давности, истёкшее без ответа."""
    need = matching.demo_need_for(db, "backend:middle")
    if need is None:
        return
    contact.send_invitation(
        db, now - timedelta(days=20), need.employer_id,
        companies.invitation_data(need, candidate_id, H, "hr-lazurit@example.com"),
        C.invitation_key(C.EMPLOYER_KEY, "silence", candidate_id),
    )  # fmt: skip


def seed_orbita() -> bool:
    """Создать `orbita` с потребностью, историей и приглашениями сценария; вернуть «создан сейчас»."""
    if not C.ensure_ready():
        return False
    created = False
    with session_scope() as db:
        now = clock.now(db)
        existing = identity.demo_user_ids(db, [C.EMPLOYER_KEY])
        if existing:
            employer_id = existing[0]
            need = _find_need(db, employer_id)
            if need is None:
                need = _create_need(db, employer_id, now)
            else:
                matching.create_snapshot(db, employer_id, need.need_id, now)  # новая версия: пересозданные в ней
                need = matching.need_ref(db, employer_id, need.need_id)
        else:
            employer_id = identity.create_user(
                db, C.email_for(C.EMPLOYER_KEY), get_settings().demo_password, Role.EMPLOYER,
                verified=True, is_demo=True, demo_key=C.EMPLOYER_KEY,
            )  # fmt: skip
            company.save_company(
                db,
                employer_id,
                CompanyData(
                    name="Орбита", sphere="Финтех: платёжные сервисы",
                    description=(
                        "Платёжный сервис для интернет-магазинов: приём платежей, возвраты, выплаты продавцам "
                        "и антифрод. Команда разработки — двадцать пять человек."
                    ),
                    site="https://example.com/orbita", city="Москва",
                    contact_method=ContactMethod(kind=ContactKind.EMAIL, value=ORBITA_EMAIL),
                ),
                now - timedelta(days=120),
                trust_level=TrustLevel.BASIC,
            )  # fmt: skip
            need = _create_need(db, employer_id, now)
            created = True
            _history(db, employer_id, need, now)
        _scenario_invitations(db, employer_id, need, now)
    return created
