"""Константы механики контакта (Арх. 4.3) и публичные лимиты модуля.

Значения по умолчанию — из таблицы Арх. 4.3; каждое переопределяется переменной окружения `CONTACT_<ИМЯ>`
(Арх. 13.3). Константы не калиброваны: это допущения, взятые по аналогам, и документация так их и называет
(Арх. 12.7). Общие для нескольких модулей числа вилки и лестницы минимума лежат в `app/shared/salary.py`.

Файл не импортирует SQLAlchemy: его читают чистые правила (`rules.py`) и симуляция (`app/eval/contact`).
"""

from __future__ import annotations

from datetime import timedelta

from pydantic_settings import BaseSettings

from app.core.config import module_env
from app.shared.enums import DemoPersona, TrustLevel


class ContactConstants(BaseSettings):
    """Числа механики; имена полей в верхнем регистре с префиксом `CONTACT_` — имена переменных окружения."""

    model_config = module_env("CONTACT_")

    invitation_ttl_days: int = 7
    slot_limit_basic: int = 10
    slot_limit_verified: int = 30
    daily_send_limit: int = 20
    candidate_inbox_capacity: int = 5
    bounce_slot_hold_hours: int = 72
    pair_retry_days: int = 30
    revision_window_days: int = 7
    silence_strikes: int = 2
    auto_pause_max_days: int = 14
    contact_sla_hours: int = 72
    reason_hint_min: int = 3
    decline_salary_step: int = 5_000
    funnel_window_days: int = 30
    funnel_skill_min_needs: int = 3
    metric_min_n: int = 5
    metric_window_days: int = 90
    salary_hint_min_n: int = 10
    salary_hint_min_employers: int = 3
    salary_hint_window_days: int = 180
    complaint_freeze_threshold: int = 3
    complaint_window_days: int = 30


_c = ContactConstants()

#: Срок ответа кандидата.
INVITATION_TTL_DAYS: int = _c.invitation_ttl_days
INVITATION_TTL = timedelta(days=INVITATION_TTL_DAYS)
#: Одновременно занятых слотов по уровню доверия компании.
SLOT_LIMIT: dict[TrustLevel, int] = {TrustLevel.BASIC: _c.slot_limit_basic, TrustLevel.VERIFIED: _c.slot_limit_verified}
#: Попыток отправки за скользящие 24 часа, включая `bounced`; к демо-аккаунтам не применяется (Арх. 4.14).
DAILY_SEND_LIMIT: int = _c.daily_send_limit
DAILY_WINDOW = timedelta(hours=24)
#: Что показывает квота демо-аккаунту вместо суточного лимита: «практически без лимита», как и его слоты.
DEMO_DAILY_SEND_LIMIT: int = 10_000
#: Неотвеченных приглашений у кандидата.
CANDIDATE_INBOX_CAPACITY: int = _c.candidate_inbox_capacity
#: Сколько недоставленная попытка держит слот.
BOUNCE_SLOT_HOLD_HOURS: int = _c.bounce_slot_hold_hours
BOUNCE_SLOT_HOLD = timedelta(hours=BOUNCE_SLOT_HOLD_HOURS)
#: Пауза перед новым приглашением той же паре.
PAIR_RETRY_DAYS: int = _c.pair_retry_days
PAIR_RETRY = timedelta(days=PAIR_RETRY_DAYS)
#: Срок на пересмотренное приглашение.
REVISION_WINDOW_DAYS: int = _c.revision_window_days
REVISION_WINDOW = timedelta(days=REVISION_WINDOW_DAYS)
#: Истечений подряд до автопаузы и её длительность.
SILENCE_STRIKES: int = _c.silence_strikes
AUTO_PAUSE_MAX_DAYS: int = _c.auto_pause_max_days
AUTO_PAUSE_MAX = timedelta(days=AUTO_PAUSE_MAX_DAYS)
#: Срок выхода работодателя на связь после согласия.
CONTACT_SLA_HOURS: int = _c.contact_sla_hours
CONTACT_SLA = timedelta(hours=CONTACT_SLA_HOURS)
#: Отказов с одной причиной для подсказки к потребности.
REASON_HINT_MIN: int = _c.reason_hint_min
#: Кратность суммы в условии отказа.
DECLINE_SALARY_STEP: int = _c.decline_salary_step
FUNNEL_WINDOW_DAYS: int = _c.funnel_window_days
FUNNEL_SKILL_MIN_NEEDS: int = _c.funnel_skill_min_needs
#: Сколько последних недоставленных попыток видит кандидат в воронке.
FUNNEL_NOT_DELIVERED_ITEMS: int = 5
METRIC_MIN_N: int = _c.metric_min_n
METRIC_WINDOW_DAYS: int = _c.metric_window_days
SALARY_HINT_MIN_N: int = _c.salary_hint_min_n
SALARY_HINT_MIN_EMPLOYERS: int = _c.salary_hint_min_employers
SALARY_HINT_WINDOW_DAYS: int = _c.salary_hint_window_days
COMPLAINT_FREEZE_THRESHOLD: int = _c.complaint_freeze_threshold
COMPLAINT_WINDOW_DAYS: int = _c.complaint_window_days
#: Медиана времени до ответа показывается работодателю при трёх и более ответах (приложение C, §8.1).
MEDIAN_RESPONSE_MIN_N: int = 3

# --- поля приглашения (Арх. 8.9) ------------------------------------------------------------------------------------
TITLE_MIN, TITLE_MAX = 3, 100
DESCRIPTION_MIN, DESCRIPTION_MAX = 50, 3000
MESSAGE_MAX = 1000
CITY_MAX = 100
DECLINE_COMMENT_MAX = 300
COMPLAINT_COMMENT_MAX = 500
PAIR_STATES_MAX_IDS = 100

# --- демо-ответчик (Арх. 4.14) ---------------------------------------------------------------------------------------
#: Персона → (просмотр через, ответ через), секунды от `created_at` по часам сервиса. `silent` не отвечает.
DEMO_TIMING_S: dict[DemoPersona, tuple[int, int]] = {
    DemoPersona.RESPONSIVE: (20, 60),
    DemoPersona.SELECTIVE: (40, 90),
    DemoPersona.EXPENSIVE: (30, 75),
}
#: Персона `expensive` называет условие `ceil(salary_from × 1,15)` с округлением вверх до этой суммы.
DEMO_EXPENSIVE_FACTOR_PCT: int = 115
DEMO_EXPENSIVE_ROUND_TO: int = 20_000

#: Версия правил контакта: попадает в отчёт валидации (`versions`).
RULES_VERSION = "1.2"

#: Числа для `Catalog.limits` (их собирает `app.wiring.publish_limits`). Первые семь названы планом работ;
#: длительность автопаузы и кратность суммы в условии отказа нужны текстам экранов C8, C9.
PUBLIC_LIMITS: dict[str, int | float] = {
    "invitation_ttl_days": INVITATION_TTL_DAYS,
    "pair_retry_days": PAIR_RETRY_DAYS,
    "bounce_slot_hold_hours": BOUNCE_SLOT_HOLD_HOURS,
    "revision_window_days": REVISION_WINDOW_DAYS,
    "contact_sla_hours": CONTACT_SLA_HOURS,
    "candidate_inbox_capacity": CANDIDATE_INBOX_CAPACITY,
    "silence_strikes": SILENCE_STRIKES,
    "auto_pause_max_days": AUTO_PAUSE_MAX_DAYS,
    "decline_salary_step": DECLINE_SALARY_STEP,
}
