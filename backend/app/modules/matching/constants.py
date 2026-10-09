"""Константы подбора (Арх. 6.15). Переопределяются переменными окружения `MATCHING_*`.

Значения заданы из смысла, а не подобраны по данным; чувствительность к ним печатает отчёт `make eval-matching`
(Арх. 12.3). Любое изменение констант после первого отчёта меняет `SCORER_VERSION`.

Файл не импортирует SQLAlchemy: его читают чистые ядра `scoring.py` и `ranking.py` (Арх. 2.4, п. 6).
"""

from __future__ import annotations

from pydantic_settings import BaseSettings

from app.core.config import module_env


class MatchingConstants(BaseSettings):
    """Значения по умолчанию — таблица Арх. 6.15; имя переменной окружения — `MATCHING_<ИМЯ>`."""

    model_config = module_env("MATCHING_")

    scorer_version: str = "match-2"
    # Вес доказательства `e` (Арх. 6.2). Заявленное в подтверждённое покрытие не входит.
    e_test: float = 1.0
    e_test_single: float = 0.7
    e_pulse: float = 0.7
    e_fsp: float = 0.7
    e_declared: float = 0.3
    # Вес требования.
    w_must: int = 2
    w_nice: int = 1
    # Потолок полосы покрытия при пробеле в обязательных и границы подписи совпадения, %.
    gap_cap_band: int = 6
    fit_strong_min: int = 70
    fit_good_min: int = 40
    # Сила профиля (Арх. 6.6): доли теста и ФСП, нижняя граница, запас ниже порога.
    w_test: float = 0.7
    w_fsp: float = 0.3
    z_lower: float = 1.0
    under: float = 0.5
    strength_high_min: int = 55
    strength_medium_min: int = 30
    # Размер разделов версии подборки.
    section_limit_exact: int = 30
    section_limit_lower: int = 10
    section_limit_higher: int = 10
    # Учёт показов.
    exposure_window_days: int = 7
    exposure_top_k: int = 10
    # Подсказки-контрфакты.
    hint_min_items: int = 10
    hint_min_gain: int = 3
    # Версии подборки.
    snapshot_dedup_minutes: int = 10
    snapshot_rate_per_hour: int = 30
    # Лимиты.
    pin_limit: int = 50
    card_open_limit_per_day: int = 300
    bank_page_max: int = 50
    bank_pages_limit_per_day: int = 60
    # Поправка рецензии R3-data-api-security-9: PDF-профиль (WeasyPrint) — тяжёлый вызов, лимит на пользователя в час.
    pdf_rate_per_hour: int = 20


_c = MatchingConstants()

SCORER_VERSION: str = _c.scorer_version
E_TEST: float = _c.e_test
E_TEST_SINGLE: float = _c.e_test_single
E_PULSE: float = _c.e_pulse
E_FSP: float = _c.e_fsp
E_DECLARED: float = _c.e_declared
W_MUST: int = _c.w_must
W_NICE: int = _c.w_nice
GAP_CAP_BAND: int = _c.gap_cap_band
FIT_STRONG_MIN: int = _c.fit_strong_min
FIT_GOOD_MIN: int = _c.fit_good_min
W_TEST: float = _c.w_test
W_FSP: float = _c.w_fsp
Z_LOWER: float = _c.z_lower
UNDER: float = _c.under
STRENGTH_HIGH_MIN: int = _c.strength_high_min
STRENGTH_MEDIUM_MIN: int = _c.strength_medium_min
SECTION_LIMITS: dict[str, int] = {
    "exact": _c.section_limit_exact,
    "lower_with_margin": _c.section_limit_lower,
    "higher": _c.section_limit_higher,
}
EXPOSURE_WINDOW_DAYS: int = _c.exposure_window_days
EXPOSURE_TOP_K: int = _c.exposure_top_k
HINT_MIN_ITEMS: int = _c.hint_min_items
HINT_MIN_GAIN: int = _c.hint_min_gain
SNAPSHOT_DEDUP_MINUTES: int = _c.snapshot_dedup_minutes
SNAPSHOT_RATE_PER_HOUR: int = _c.snapshot_rate_per_hour
PIN_LIMIT: int = _c.pin_limit
CARD_OPEN_LIMIT_PER_DAY: int = _c.card_open_limit_per_day
BANK_PAGE_MAX: int = _c.bank_page_max
BANK_PAGES_LIMIT_PER_DAY: int = _c.bank_pages_limit_per_day
PDF_RATE_PER_HOUR: int = _c.pdf_rate_per_hour

# --- ограничения полей потребности и запроса (Арх. 6.14) ------------------------------------------------------------
NEED_TITLE_MIN = 3
NEED_TITLE_MAX = 100
NEED_TEXT_MIN = 20
NEED_TEXT_MAX = 5000
TEAM_DESCRIPTION_MIN = 10
TEAM_DESCRIPTION_MAX = 1000
MUST_SKILLS_MAX = 8
NICE_SKILLS_MAX = 12
BANK_SKILLS_MAX = 8

#: Сколько строк доказательств показывает строка подборки и строка банка; сколько навыков уходит в «Почему вас
#: пригласили» при приглашении из банка (Арх. 15.1, № 18).
TOP_EVIDENCE_LIMIT = 4
BANK_CONFIRMED_LIMIT = 6
WHY_BANK_SKILLS_LIMIT = 6
REASONS_LIMIT = 3
HINTS_LIMIT = 3

#: Запасная версия правил сигнала ФСП для строки `scorer_version`, когда пул пуст и спросить версию не у кого.
FSP_SIGNAL_VERSION_FALLBACK = "fsp-signal-1"

#: Именованные аккаунты работодателей сценария: демо-приглашение живому кандидату отправляет не `orbita`,
#: а одна из демо-компаний сида (Арх. 4.14), поэтому их потребности `demo_need_for` не возвращает.
DEMO_SCENARIO_EMPLOYER_KEYS: tuple[str, ...] = ("orbita",)

#: Счётчик `identity.throttle` для страниц банка (Арх. 6.9, 8.3 `login_attempt.kind`).
BANK_PAGE_THROTTLE_KIND = "bank_page"

#: Числа для `Catalog.limits` (их собирает `app.wiring.publish_limits`).
PUBLIC_LIMITS: dict[str, int | float] = {
    "pin_limit": PIN_LIMIT,
    "section_limit_exact": SECTION_LIMITS["exact"],
    "card_open_limit_per_day": CARD_OPEN_LIMIT_PER_DAY,
}
