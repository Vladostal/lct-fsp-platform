"""Демо-компании, их потребности и история приглашений (Арх. 13.5).

Три компании по одной потребности на каждую доступную категорию `backend` и две потребности по специализациям
без теста (Frontend, QA) с версией подборки, но без приглашений; истории принятых приглашений хватает для
показателей и медианы вилок категории (`contact.salary_hint`: не меньше `SALARY_HINT_MIN_N` принятых от
`SALARY_HINT_MIN_EMPLOYERS` работодателей). Дата каждого действия — в прошлом: `now` передаётся в функции записи.
"""

# ruff: noqa: E501 — тексты демо-компаний

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.core.db import session_scope
from app.modules.assessment import service as assessment
from app.modules.company import service as company
from app.modules.company.dto import CompanyData
from app.modules.contact import service as contact
from app.modules.contact.dto import DeclineCondition, InvitationData
from app.modules.identity import service as identity
from app.modules.matching import service as matching
from app.modules.matching.dto import NeedData, NeedRefDTO
from app.modules.profile import service as profile
from app.seed import common as C
from app.shared.enums import ConditionKind, ContactKind, DeclineReason, Role, TrustLevel, WorkFormat
from app.shared.schemas import ContactMethod

HISTORY_OFFSET = 3


@dataclass(frozen=True)
class CompanySpec:
    key: str
    name: str
    sphere: str
    description: str
    city: str
    site: str
    contact: str
    #: грейд → (обязательные, желательные навыки, вилка от, до, форматы)
    needs: dict[str, tuple[list[str], list[str], int, int, list[WorkFormat]]]


H, R = WorkFormat.HYBRID, WorkFormat.REMOTE
COMPANIES: tuple[CompanySpec, ...] = (
    CompanySpec(
        "company_1", "Лазурит Технологии", "Финтех",
        "Платёжные сервисы для малого бизнеса: эквайринг, выплаты, сверки и аналитика. Команда разработки — сорок человек.",
        "Москва", "https://example.com/lazurit", "hr-lazurit@example.com",
        {
            "junior": (["python", "sql"], ["git", "docker"], 90_000, 130_000, [H, R]),
            "middle": (["python", "postgresql"], ["redis", "docker"], 200_000, 260_000, [H, R]),
            "senior": (["python", "system_design", "postgresql"], ["kafka", "microservices"], 330_000, 450_000, [R]),
        },
    ),
    CompanySpec(
        "company_2", "Северный ветер", "Логистика и склад",
        "Платформа управления складами и маршрутами для розничных сетей. Свои сервисы на Java и собственная дежурная смена.",
        "Санкт-Петербург", "https://example.com/severny-veter", "hr-veter@example.com",
        {
            "junior": (["java", "sql"], ["git"], 85_000, 120_000, [H]),
            "middle": (["java", "postgresql"], ["kafka", "docker"], 190_000, 250_000, [H, R]),
            "senior": (["java", "system_design"], ["microservices", "kafka"], 320_000, 430_000, [H, R]),
        },
    ),
    CompanySpec(
        "company_3", "Мост Цифровой", "Государственные сервисы",
        "Разрабатываем цифровые сервисы для обращений граждан и взаимодействия ведомств. Стабильная команда, гибкий график.",
        "Казань", "https://example.com/most-digital", "hr-most@example.com",
        {
            "junior": (["sql"], ["python", "git"], 90_000, 125_000, [H, R]),
            "middle": (["rest_api", "sql"], ["docker", "redis"], 195_000, 255_000, [R]),
            "senior": (["system_design", "microservices"], ["kafka", "postgresql"], 320_000, 440_000, [H, R]),
        },
    ),
)  # fmt: skip

@dataclass(frozen=True)
class DeclaredNeedSpec:
    """Потребность по специализации без теста: в подборке — кандидаты с заявленным грейдом, приглашений нет."""

    company_key: str
    title: str
    team: str
    specialization: str
    grade: str
    must: tuple[str, ...]
    nice: tuple[str, ...]
    salary_from: int
    salary_to: int
    formats: tuple[WorkFormat, ...]


#: Включить потребности по специализациям без теста. Если версия подборки для заявленных категорий падает
#: внутри `matching`, интегратор выключает их здесь одной строкой — остальной сид от них не зависит.
DECLARED_NEEDS_ENABLED = True
DECLARED_NEEDS: tuple[DeclaredNeedSpec, ...] = (
    DeclaredNeedSpec(
        "company_1", "Frontend-разработчик (React)",
        "Лазурит Технологии: личный кабинет клиента на React, команда из пяти человек, дизайн-система и ревью.",
        "frontend", "middle", ("react", "typescript"), ("javascript", "html", "css"), 180_000, 240_000, (H, R),
    ),
    DeclaredNeedSpec(
        "company_2", "QA-инженер (автотесты)",
        "Северный ветер: автотесты складских сервисов, команда качества из четырёх человек.",
        "qa", "middle", ("test_automation", "pytest"), ("playwright", "selenium"), 150_000, 200_000, (H, R),
    ),
)  # fmt: skip

#: Ход истории по грейду: (исход, ...). Принятых в `middle` по четыре у каждой компании: на медиану вилок хватает.
HISTORY_PLAN: dict[str, tuple[str, ...]] = {
    "middle": ("accepted", "expired", "accepted", "declined", "accepted", "withdrawn", "accepted"),
    "junior": ("accepted", "declined", "accepted"),
    "senior": ("accepted", "declined", "accepted"),
}


def employer_name(db: Session, employer_id: UUID) -> str:
    dto = company.get_company(db, employer_id)
    return dto.name if dto else "Компания"


def invitation_data(
    need: NeedRefDTO, candidate_id: UUID, work_format: WorkFormat, contact_email: str, *, title: str | None = None
) -> InvitationData:
    return InvitationData(
        candidate_id=candidate_id,
        title=title or need.title,
        description=(
            f"{need.title}: развивать рабочие сервисы, участвовать в код-ревью и проектировании. "
            f"{need.team_description}"
        )[:900],
        salary_from=need.salary_from,
        salary_to=need.salary_to,
        work_format=work_format,
        city=need.city,
        contact_method=ContactMethod(kind=ContactKind.EMAIL, value=contact_email),
        message="Здравствуйте! Ваш профиль подошёл под нашу задачу, будем рады познакомиться.",
        need_id=need.need_id,
        snapshot_id=need.snapshot_id,
    )


def pick_format(need: NeedRefDTO, candidate_formats: list[WorkFormat]) -> WorkFormat | None:
    common = [item for item in need.work_formats if item in candidate_formats]
    return common[0] if common else None


def run_outcome(
    db: Session,
    employer_id: UUID,
    need: NeedRefDTO,
    candidate_id: UUID,
    outcome: str,
    sent_at: datetime,
    contact_email: str,
    key: str,
    *,
    work_format: WorkFormat,
    decline: tuple[DeclineReason, str | None] = (DeclineReason.STACK, None),
) -> str:
    """Отправить приглашение в `sent_at` и довести до исхода; вернуть итоговый статус (`bounced` — обычный результат)."""
    inv = contact.send_invitation(
        db, sent_at, employer_id, invitation_data(need, candidate_id, work_format, contact_email), key
    )
    if inv.status.value != "sent":
        return inv.status.value
    if outcome == "accepted":
        contact.view_invitation(db, sent_at + timedelta(hours=3), candidate_id, inv.id)
        return contact.accept_invitation(db, sent_at + timedelta(hours=20), candidate_id, inv.id).status.value
    if outcome == "declined":
        reason, condition_format = decline
        condition = (
            DeclineCondition(kind=ConditionKind.WORK_FORMAT, value=WorkFormat(condition_format))
            if condition_format
            else None
        )
        contact.view_invitation(db, sent_at + timedelta(hours=3), candidate_id, inv.id)
        return contact.decline_invitation(
            db, sent_at + timedelta(hours=20), candidate_id, inv.id, reason, condition
        ).status.value
    if outcome == "withdrawn":
        return contact.withdraw_invitation(db, sent_at + timedelta(hours=20), employer_id, inv.id).status.value
    return inv.status.value  # expired: ответа нет, срок истечёт сам


def candidates_by_category(
    db: Session, exclude: set[UUID]
) -> dict[str, list[tuple[UUID, int | None, list[WorkFormat]]]]:
    """Опубликованные демо-кандидаты по категориям: (id, скрытый минимум, форматы) — только для подбора исторических пар."""
    ids = [uid for uid in identity.demo_user_ids(db) if uid not in exclude]
    users = identity.users(db, ids)
    candidates = [uid for uid, user in users.items() if user.role == Role.CANDIDATE]
    categories = assessment.get_categories(db, candidates)
    pool = profile.pool_view(db, list(categories), clock.now(db))
    result: dict[str, list[tuple[UUID, int | None, list[WorkFormat]]]] = {}
    for uid, category in categories.items():
        view = pool.get(uid)
        # История приглашений — только по категориям `backend`: у остальных специализаций грейд заявленный,
        # приглашений им сид не рассылает (иначе QA-кандидат получил бы приглашение на backend-потребность).
        if view is None or not view.visible or category.specialization_code != "backend":
            continue
        result.setdefault(category.grade_code, []).append((uid, profile.min_salary(db, uid), list(view.work_formats)))
    for items in result.values():
        items.sort(key=lambda item: pool[item[0]].public_code)
    return result


def _declared_needs(db: Session, employer_id: UUID, spec: CompanySpec, now: datetime) -> None:
    """Потребности компании по специализациям без теста с первой версией подборки; приглашения не рассылаются."""
    if not DECLARED_NEEDS_ENABLED:
        return
    for item in DECLARED_NEEDS:
        if item.company_key != spec.key:
            continue
        need_id = matching.create_need(
            db, employer_id,
            NeedData(
                title=item.title, team_description=item.team, specialization_code=item.specialization,
                grade_code=item.grade, must_skills=list(item.must), nice_skills=list(item.nice),
                work_formats=list(item.formats), city=spec.city, salary_from=item.salary_from,
                salary_to=item.salary_to,
            ),
            now, is_demo=True,
        )  # fmt: skip
        matching.create_snapshot(db, employer_id, need_id, now)


def seed_companies() -> int:
    """Создать демо-компании с потребностями, версиями подборки и историей; вернуть число созданных компаний."""
    if not C.ensure_ready():
        return 0
    grades = C.available_grades()
    rng = C.rng_for(HISTORY_OFFSET)
    used: set[UUID] = set()
    created = 0
    for index, spec in enumerate(COMPANIES):
        with session_scope() as db:
            if identity.demo_user_ids(db, [spec.key]):
                continue
            now = clock.now(db)
            named = set(identity.demo_user_ids(db, C.CANDIDATE_KEYS))
            pool = candidates_by_category(db, named | used)
            employer_id = identity.create_user(
                db, C.email_for(spec.key), get_settings().demo_password, Role.EMPLOYER,
                verified=True, is_demo=True, demo_key=spec.key,
            )  # fmt: skip
            company.save_company(
                db,
                employer_id,
                CompanyData(
                    name=spec.name, sphere=spec.sphere, description=spec.description, site=spec.site, city=spec.city,
                    contact_method=ContactMethod(kind=ContactKind.EMAIL, value=spec.contact),
                ),
                now - timedelta(days=100),
                trust_level=TrustLevel.VERIFIED,
            )  # fmt: skip
            needs: dict[str, NeedRefDTO] = {}
            for grade in grades:
                must, nice, low, high, formats = spec.needs[grade]
                title = {
                    "junior": "Junior backend-разработчик",
                    "middle": "Backend-разработчик",
                    "senior": "Senior backend-разработчик",
                }[grade]
                need_id = matching.create_need(
                    db, employer_id,
                    NeedData(
                        title=title, team_description=f"{spec.name}: команда из шести человек, ревью и дежурства по очереди.",
                        specialization_code="backend", grade_code=grade, must_skills=must, nice_skills=nice,
                        work_formats=formats, city=spec.city, salary_from=low, salary_to=high,
                    ),
                    now, is_demo=True,
                )  # fmt: skip
                matching.create_snapshot(db, employer_id, need_id, now)
                needs[grade] = matching.need_ref(db, employer_id, need_id)
            _declared_needs(db, employer_id, spec, now)
            step = 0
            for grade in grades:
                for outcome in HISTORY_PLAN[grade]:
                    need = needs[grade]
                    options = [
                        item for item in pool.get(grade, []) if item[0] not in used
                        and (item[1] is None or item[1] <= need.salary_from) and pick_format(need, item[2]) is not None
                    ]  # fmt: skip
                    if not options:
                        continue
                    candidate_id, _, formats = rng.choice(options)
                    used.add(candidate_id)
                    sent_at = now - timedelta(days=30 - 1.6 * step) - timedelta(hours=index * 3)
                    step += 1
                    work_format = pick_format(need, formats)
                    assert work_format is not None
                    run_outcome(
                        db, employer_id, need, candidate_id, outcome, sent_at, spec.contact,
                        C.invitation_key(spec.key, grade, candidate_id), work_format=work_format,
                        decline=(DeclineReason.STACK, None),
                    )  # fmt: skip
            created += 1
        C.log.info("сид: компания %s готова", spec.name)
    return created
