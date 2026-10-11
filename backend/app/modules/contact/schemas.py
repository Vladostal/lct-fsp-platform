"""Схемы эндпоинтов модуля `contact` (Арх. 9.9, 9.11; приложение C, §5.3).

Одна модель данных — две проекции. Поля, которых сторона видеть не должна, отсутствуют в схеме физически:

* у схем работодателя нет `below_my_min`, минимума кандидата, счётчика молчания, жалоб, заполненности входящих;
* у схем кандидата нет позиции, полосы совпадения, вкладов и риска; статуса
  `bounced` кандидат не видит никогда.

Типы нижних модулей включаются как поля, без копирования (Арх. 2.4, п. 1): `InvitationWhy` и `RelaxationHint` —
из `matching.dto`, состояние показа — `profile.dto.VisibilityDTO`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.contact import constants as c
from app.modules.contact.dto import DeclineCondition
from app.modules.matching.dto import InvitationWhy, RelaxationHint
from app.modules.profile.dto import VisibilityDTO
from app.shared.enums import (
    ComplaintReason,
    ComplaintStatus,
    DeclineReason,
    DiscloseField,
    EventActor,
    InvitationStatus,
    TrustLevel,
    WorkFormat,
)
from app.shared.schemas import CategoryRef, ContactMethod, Ref

#: Статусы, которые видит кандидат: всё, кроме `bounced`.
CandidateStatus = Literal["sent", "viewed", "accepted", "declined", "expired", "withdrawn"]

# --------------------------------------------------------------------------------------------------------------------
# Условия предложения и запросы
# --------------------------------------------------------------------------------------------------------------------


class OfferTerms(BaseModel):
    """Условия предложения: неизменяемый снимок, который видят обе стороны (ТЗ, п. 2.2)."""

    title: str = Field(min_length=c.TITLE_MIN, max_length=c.TITLE_MAX)
    description: str = Field(min_length=c.DESCRIPTION_MIN, max_length=c.DESCRIPTION_MAX)
    #: Вилка, целые рубли в месяц до вычета налога; правила — `shared.salary.validate_range`.
    salary_from: int
    salary_to: int
    work_format: WorkFormat
    #: Обязателен при `office` и `hybrid`.
    city: str | None = Field(default=None, max_length=c.CITY_MAX)
    contact_method: ContactMethod
    message: str | None = Field(default=None, max_length=c.MESSAGE_MAX)


class InvitationCreate(OfferTerms):
    """Тело `POST /employer/invitations`. При пересмотре (`revises_id`) кандидат, потребность и версия подборки
    берутся из исходного приглашения; `candidate_id` обязан совпадать с его адресатом.
    """

    candidate_id: UUID
    need_id: UUID | None = None
    snapshot_id: UUID | None = None
    revises_id: UUID | None = None


class AcceptRequest(BaseModel):
    """Тело принятия. Без `disclose` раскрываются e-mail и каналы по настройкам приватности `reveal_*`."""

    disclose: list[DiscloseField] | None = Field(default=None, max_length=len(DiscloseField))


class DeclineRequest(BaseModel):
    """Тело отклонения: причина обязательна; условие — только при причинах `salary` и `format`."""

    reason_code: DeclineReason
    condition: DeclineCondition | None = None
    comment: str | None = Field(default=None, max_length=c.DECLINE_COMMENT_MAX)


class CandidateOutcomeRequest(BaseModel):
    """P1: ответ кандидата об исходе контакта. `terms_matched = null` — «пока не обсуждали»."""

    contacted: bool
    terms_matched: bool | None = None


class EmployerOutcomeRequest(BaseModel):
    """P1: отметка работодателя «связались»."""

    contacted: bool


class ComplaintRequest(BaseModel):
    """P1: жалоба кандидата на доставленное приглашение."""

    reason_code: ComplaintReason
    comment: str | None = Field(default=None, max_length=c.COMPLAINT_COMMENT_MAX)


# --------------------------------------------------------------------------------------------------------------------
# Общие части проекций
# --------------------------------------------------------------------------------------------------------------------


class TimelineEvent(BaseModel):
    """Событие таймлайна с готовой подписью."""

    code: str
    label: str
    at: datetime
    actor: EventActor
    note: str | None = None


class InvitationStrikes(BaseModel):
    """Счётчик молчания кандидата: «пропущено {count} из {limit}»."""

    count: int
    limit: int


class InvitationCandidateRef(BaseModel):
    """Кандидат в проекции работодателя: имя — только у раскрытой пары."""

    candidate_id: UUID
    public_code: str
    display_name: str | None = None
    category: CategoryRef


class NeedBrief(BaseModel):
    """Потребность, из которой отправлено приглашение."""

    id: UUID
    title: str


class DeclineEmployerView(BaseModel):
    """Отказ глазами работодателя. Для пары «демо-компания — живой кандидат» условие и комментарий скрыты."""

    reason_code: DeclineReason
    reason_label: str
    condition: DeclineCondition | None = None
    comment: str | None = None


class DeclineCandidateView(BaseModel):
    """Собственный отказ кандидата."""

    reason_code: DeclineReason
    reason_label: str
    condition: DeclineCondition | None = None


class OutcomeEmployerView(BaseModel):
    """P1: отметки об исходе контакта, видимые работодателю."""

    employer_contacted: bool | None = None
    candidate_contacted: bool | None = None


class OutcomeCandidateView(BaseModel):
    """P1: собственные ответы кандидата об исходе."""

    candidate_contacted: bool | None = None
    candidate_terms_matched: bool | None = None


# --------------------------------------------------------------------------------------------------------------------
# Проекция работодателя
# --------------------------------------------------------------------------------------------------------------------


class InvitationEmployerBrief(BaseModel):
    """Строка списка приглашений работодателя: срок, исход."""

    id: UUID
    status: InvitationStatus
    status_label: str
    is_new_for_employer: bool
    is_demo: bool
    candidate: InvitationCandidateRef
    need: NeedBrief | None = None
    title: str
    salary_from: int
    salary_to: int
    work_format: WorkFormat
    city: str | None = None
    sent_at: datetime
    updated_at: datetime
    expires_at: datetime
    pair_block_until: datetime | None = None
    revises_id: UUID | None = None
    can_revise: bool


class InvitationEmployerView(OfferTerms):
    """Приглашение глазами отправителя. Полей `below_my_min`, `fit_band` и минимума кандидата здесь нет."""

    # Снимок уже сохранён: ограничения длины запроса на ответ не действуют.
    title: str
    description: str
    city: str | None = None
    message: str | None = None

    id: UUID
    status: InvitationStatus
    status_label: str
    is_new_for_employer: bool
    is_demo: bool
    candidate: InvitationCandidateRef
    need: NeedBrief | None = None
    sent_at: datetime
    updated_at: datetime
    expires_at: datetime
    pair_block_until: datetime | None = None
    revises_id: UUID | None = None
    revision_id: UUID | None = None
    decline: DeclineEmployerView | None = None
    #: `resolved_at + CONTACT_SLA_HOURS` при `accepted`.
    contact_sla_until: datetime | None = None
    outcome: OutcomeEmployerView | None = None
    timeline: list[TimelineEvent]
    can_withdraw: bool
    #: Истинно и после `bounced`: доступно одно пересмотренное приглашение до `revise_until`.
    can_revise: bool
    revise_until: datetime | None = None
    outcome_prompt: bool


# --------------------------------------------------------------------------------------------------------------------
# Проекция кандидата
# --------------------------------------------------------------------------------------------------------------------


class CompanyMetric(BaseModel):
    """Показатель компании числами «{yes} из {n}» (P1); показывается при `n >= METRIC_MIN_N`."""

    yes: int
    n: int


class CompanyMetrics(BaseModel):
    """P1: «выходит на связь» и «условия совпадают» по ответам кандидатов."""

    contact_confirmed: CompanyMetric | None = None
    terms_matched: CompanyMetric | None = None


class InvitationCompanyView(BaseModel):
    """Компания на момент отправки — целиком из снимка `invitation_terms`, а не из текущего профиля."""

    name: str
    sphere: str
    description: str
    site: str | None = None
    on_platform_since: date
    trust_level: TrustLevel
    trust_label: str
    metrics: CompanyMetrics


class DiscloseOption(BaseModel):
    """Строка диалога принятия: что можно раскрыть работодателю."""

    field: DiscloseField
    label: str
    #: Канал заполнен в профиле.
    available: bool
    #: Начальное значение чекбокса.
    default: bool


class InvitationCandidateBrief(BaseModel):
    """Карточка списка входящих."""

    id: UUID
    status: CandidateStatus
    status_label: str
    is_demo: bool
    #: Ещё не просмотрено (`sent`).
    is_new: bool
    company_name: str
    title: str
    salary_from: int
    salary_to: int
    work_format: WorkFormat
    city: str | None = None
    sent_at: datetime
    updated_at: datetime
    expires_at: datetime
    revision_of: UUID | None = None
    #: «Ниже вашего минимума» (Арх. 4.6); считается при чтении и отдаётся только кандидату.
    below_my_min: bool
    strikes: InvitationStrikes | None = None


class InvitationCandidateView(OfferTerms):
    """Приглашение глазами адресата. Позиции, полосы совпадения, вкладов и риска здесь нет."""

    title: str
    description: str
    city: str | None = None
    message: str | None = None

    id: UUID
    status: CandidateStatus
    status_label: str
    is_demo: bool
    sent_at: datetime
    expires_at: datetime
    revision_of: UUID | None = None
    company: InvitationCompanyView
    why: InvitationWhy
    disclose_options: list[DiscloseOption]
    #: Что раскрыто — после `accepted`.
    disclosed: list[DiscloseField] | None = None
    decline: DeclineCandidateView | None = None
    contact_sla_until: datetime | None = None
    outcome: OutcomeCandidateView | None = None
    #: При `expired`.
    strikes: InvitationStrikes | None = None
    timeline: list[TimelineEvent]
    outcome_prompt: bool
    can_complain: bool
    below_my_min: bool


class InvitationSummaryView(BaseModel):
    """Счётчики вкладок входящих, счётчик молчания и состояние показа — для шапки кабинета кандидата."""

    awaiting: int
    accepted: int
    archived: int
    outcome_prompts: int
    strikes: InvitationStrikes
    visibility: VisibilityDTO


class NotDeliveredItem(BaseModel):
    """Недоставленная попытка в воронке кандидата: вилка, формат, дата — без названия компании."""

    salary_from: int
    salary_to: int
    work_format: WorkFormat
    at: datetime


class MissingSkill(BaseModel):
    """P1: обязательный навык, которого чаще всего не хватало в потребностях, где кандидат был показан."""

    skill: Ref
    needs: int


class FunnelView(BaseModel):
    """Воронка спроса кандидата за `window_days` (Арх. 4.12)."""

    window_days: int
    shown: int
    opened: int
    delivered: int
    not_delivered: int
    stage: Literal["hidden", "ok", "blocked_by_min", "not_shown", "not_opened", "not_invited"]
    not_delivered_items: list[NotDeliveredItem]
    missing_skill: MissingSkill | None = None


# --------------------------------------------------------------------------------------------------------------------
# Квота, предпроверка, состояние пары
# --------------------------------------------------------------------------------------------------------------------


class QuotaView(BaseModel):
    """Суточный лимит работодателя."""

    daily_used: int
    daily_limit: int
    frozen: bool


class SalaryHint(BaseModel):
    """Медиана вилок принятых приглашений категории — «ориентир рынка» (Арх. 4.11)."""

    model_config = ConfigDict(populate_by_name=True)

    from_: int = Field(alias="from")
    to: int


class PrecheckBlocker(BaseModel):
    """Причина, по которой приглашение сейчас отправить нельзя."""

    code: str
    message: str
    params: dict[str, str | int | float] | None = None


class PrecheckPair(BaseModel):
    """Состояние пары для формы отправки: блокировка и право на одно пересмотренное приглашение."""

    block_until: datetime | None = None
    can_revise: bool
    revises_id: UUID | None = None
    condition: DeclineCondition | None = None


class InvitationPrecheckView(BaseModel):
    """Несекретная предпроверка отправки: те же проверки, что при отправке, кроме формата и пересмотра;
    вилка и минимум кандидата в ней не участвуют (Арх. 4.5).
    """

    can_invite: bool
    blockers: list[PrecheckBlocker]
    quota: QuotaView
    pair: PrecheckPair
    #: Пусто, если кандидат сейчас не виден и пара не раскрыта.
    candidate_formats: list[WorkFormat]
    expires_at_preview: datetime
    salary_hint: SalaryHint | None = None


class PairInvitationView(BaseModel):
    """Последнее приглашение пары."""

    id: UUID
    status: InvitationStatus
    expires_at: datetime


class PairBlockView(BaseModel):
    """Блокировка пары."""

    code: Literal["conditions_mismatch", "pair_cooldown"]
    until: datetime


class PairStateItem(BaseModel):
    """Состояние пары «я — кандидат» для строки подборки, банка и карточки."""

    candidate_id: UUID
    invitation: PairInvitationView | None = None
    pair_block: PairBlockView | None = None
    #: P2: активный сигнал интереса кандидата к вакансии работодателя.
    interest: bool = False


class PairStatesView(BaseModel):
    """Ответ `GET /employer/invitations/pair-states`."""

    items: list[PairStateItem]


# --------------------------------------------------------------------------------------------------------------------
# Сводки работодателя и показатели
# --------------------------------------------------------------------------------------------------------------------


class InvitationFunnel(BaseModel):
    """Воронка приглашений работодателя (приложение C, §8.1)."""

    delivered: int = 0
    not_delivered: int = 0
    viewed: int = 0
    accepted: int = 0
    declined: int = 0
    expired: int = 0
    withdrawn: int = 0


class NeedFunnel(BaseModel):
    """Воронка одной потребности и счётчики для списка потребностей."""

    need_id: UUID
    funnel: InvitationFunnel
    awaiting: int
    updates: int


class ReasonCount(BaseModel):
    """Число отказов с одной причиной."""

    reason_code: DeclineReason
    reason_label: str
    count: int


class InvitationStatsView(BaseModel):
    """Собственная воронка работодателя: итог и разбивка по потребностям."""

    total: InvitationFunnel
    by_need: list[NeedFunnel]
    median_response_hours: float | None = None
    reasons: list[ReasonCount]


class StatedSalary(BaseModel):
    """Сумма, которую кандидаты назвали сами в условии отказа."""

    value: int
    count: int


class StatedFormat(BaseModel):
    """Формат, который кандидаты назвали сами в условии отказа."""

    value: WorkFormat
    count: int


class NeedInsightsView(BaseModel):
    """Сводка причин по потребности и подсказки к запросу (Арх. 4.11)."""

    funnel: InvitationFunnel
    reasons: list[ReasonCount]
    stated_salary: list[StatedSalary]
    stated_formats: list[StatedFormat]
    hints: list[RelaxationHint]
    salary_note: str | None = None


class PlatformMetricsView(BaseModel):
    """P1: живые показатели платформы (Арх. 4.12). Доли — 0..1; `null`, когда данных нет."""

    window_days: int
    invitations: int
    delivered_share: float | None = None
    reply_in_time_share: float | None = None
    accept_share: float | None = None
    median_response_hours: float | None = None
    contact_confirmed_share: float | None = None
    coverage_share: float | None = None
    concentration_gini: float | None = None


class ComplaintAdminView(BaseModel):
    """P1: жалоба в служебном списке."""

    id: UUID
    invitation_id: UUID
    candidate_id: UUID
    employer_id: UUID
    company_name: str
    reason_code: ComplaintReason
    reason_label: str
    comment: str | None = None
    status: ComplaintStatus
    created_at: datetime
    resolved_at: datetime | None = None
    employer_frozen: bool


class ComplaintResolveRequest(BaseModel):
    """P1: разбор жалобы. `unfreeze` снимает заморозку отправки работодателя."""

    status: Literal["upheld", "dismissed"]
    unfreeze: bool = False
