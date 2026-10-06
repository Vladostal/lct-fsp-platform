"""Константы модуля `fsp`: веса сигнала, матрица переноса, словари подписей (Арх. 7.6, 7.7; приложение D, §5.11).

Веса заданы экспертно, не подобраны по данным: сигнал ФСП — только добавка к силе профиля с ограниченным весом.
Судейство, сборные и таблица норм ЕВСК в MVP не моделируются (Арх. 15.1, № 47): констант для них здесь нет.

Файл не импортирует SQLAlchemy: его читает чистое ядро `signal.py` (Арх. 2.4, п. 6).
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

#: Версия правил сигнала; входит в `scorer_version` подбора (Арх. 6.10).
FSP_SIGNAL_VERSION: Final = "fsp-signal-1"

PROVIDER: Final = "fsp"
#: Издатель демо-провайдера ФСП ID.
MOCK_ISSUER: Final = "urn:fsp-mock"
MOCK_CLIENT_ID: Final = "talent-platform"
#: Пространство имён детерминированных идентификаторов фактов (`uuid5`): повторная синхронизация их не меняет.
NAMESPACE_FSP: Final = UUID("6f1f6d3a-5d0e-5f0b-9a57-1c0f5a2b7e11")

# --- вес одного результата (приложение D, §5.2) -----------------------------------------------------------------------
W_LEVEL: Final[dict[str, float]] = {
    "international": 1.00,
    "national": 0.80,
    "interregional": 0.45,
    "regional": 0.25,
    "municipal": 0.10,
}
W_KIND: Final[dict[str, float]] = {"championship": 1.00, "cup": 0.90, "youth_championship": 0.75, "other": 0.70}
W_STAGE: Final[dict[str, float]] = {"single": 1.00, "final": 1.00, "stage": 0.60, "qualification": 0.30}
#: Неизвестный вид соревнования считается как `other`, неизвестный этап — как отбор (самый осторожный вес).
KIND_FALLBACK: Final = "other"
STAGE_FALLBACK: Final = "qualification"

PLACE_FLOOR: Final = 0.25
PLACE_SPAN: Final = 0.35
MEDAL: Final[dict[int, float]] = {1: 1.00, 2: 0.85, 3: 0.75}
FIELD_REF: Final = 8
FIELD_MIN: Final = 0.5
FIELD_UNKNOWN: Final = 0.5
TEAM_DILUTION: Final = 0.1
TEAM_UNKNOWN: Final = 0.7

# --- формула сигнала (приложение D, §5.3, §5.5) -----------------------------------------------------------------------
HALF_LIFE_YEARS: Final = 2.0
GAMMA: Final = 0.6
TAU: Final = 0.4
SIGNAL_BAND_MEDIUM: Final = 0.3
SIGNAL_BAND_HIGH: Final = 0.6
#: Сколько вкладов отдаётся подбору для объяснения.
CONTRIBUTIONS_LIMIT: Final = 3

RANK_FLOOR: Final[dict[str, float]] = {
    "msmk": 0.95,
    "ms": 0.90,
    "kms": 0.75,
    "r1": 0.55,
    "r2": 0.40,
    "r3": 0.30,
    "y1": 0.15,
    "y2": 0.12,
    "y3": 0.10,
}
#: Звания бессрочны, но нижняя граница сигнала действует столько лет после присвоения.
TITLE_FLOOR_YEARS: Final = 6
R_DEFAULT: Final = 0.5
#: Перенос разряда, у которого реестр не назвал дисциплину.
R_RANK_UNKNOWN: Final = 0.7

DISCIPLINES: Final = ("algo", "product", "infosec", "uav", "robotics")
DISCIPLINE_OTHER: Final = "other"
SPECIALIZATIONS: Final = (
    "backend",
    "frontend",
    "fullstack",
    "mobile",
    "data_ml",
    "devops",
    "qa",
    "infosec",
    "analyst",
    "embedded",
)

_R_ROWS: Final[dict[str, tuple[float, ...]]] = {
    "algo": (1.0, 0.6, 0.8, 0.6, 0.9, 0.5, 0.5, 0.6, 0.5, 0.7),
    "product": (0.9, 0.9, 1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.8, 0.5),
    "infosec": (0.6, 0.4, 0.5, 0.4, 0.4, 0.8, 0.6, 1.0, 0.4, 0.5),
    "uav": (0.5, 0.4, 0.4, 0.4, 0.6, 0.4, 0.4, 0.4, 0.4, 1.0),
    "robotics": (0.5, 0.4, 0.4, 0.4, 0.6, 0.4, 0.4, 0.4, 0.4, 1.0),
}
#: Матрица переноса «дисциплина → специализация» (Арх. 7.6): экспертная априорная оценка, нижняя граница 0.4.
RELEVANCE: Final[dict[str, dict[str, float]]] = {
    discipline: dict(zip(SPECIALIZATIONS, row, strict=True)) for discipline, row in _R_ROWS.items()
}

# --- подтверждение навыков и лидерство (приложение D, §5.7, §5.8) -----------------------------------------------------
EVIDENCE_MIN_POINTS: Final = 0.10
LEADERSHIP_WINDOW_YEARS: Final = 4
#: Дисциплина подтверждает только родные навыки и никогда — язык или фреймворк.
DISCIPLINE_SKILLS: Final[dict[str, tuple[str, ...]]] = {
    "algo": ("algorithms", "data_structures"),
    "product": ("teamwork", "mvp_delivery"),
    "infosec": ("infosec", "vulnerability_analysis"),
    "uav": ("uav_programming",),
    "robotics": ("robotics", "embedded"),
}
SKILL_TEAMWORK: Final = "teamwork"
SKILL_PUBLIC_SPEAKING: Final = "public_speaking"
SKILL_LEADERSHIP: Final = "leadership"
SKILL_MENTORING: Final = "mentoring"
#: Все коды навыков, которые модуль может подтвердить: архитектурный тест сверяет их со справочником каталога.
EVIDENCE_SKILL_CODES: Final = tuple(
    sorted(
        {code for codes in DISCIPLINE_SKILLS.values() for code in codes}
        | {SKILL_TEAMWORK, SKILL_PUBLIC_SPEAKING, SKILL_LEADERSHIP, SKILL_MENTORING}
    )
)
CAPTAIN_STRONG_COUNT: Final = 3

# --- обобщённая строка (приложение D, §6.2) ---------------------------------------------------------------------------
PERIOD_RECENT_DAYS: Final = 730
PERIOD_MID_DAYS: Final = 1461

# --- привязка и синхронизация (Арх. 7.4, 7.5) -------------------------------------------------------------------------
LINK_ATTEMPT_TTL_MINUTES: Final = 10
LINK_ATTEMPTS_LIMIT: Final = 5
LINK_ATTEMPTS_WINDOW_MINUTES: Final = 10
LINK_ATTEMPT_RETENTION_HOURS: Final = 24
#: Попытка синхронизации без `finished_at` старше этого срока считается зависшей.
SYNC_STUCK_SECONDS: Final = 30
SYNC_ATTEMPTS_KEEP: Final = 20
SNAPSHOTS_KEEP: Final = 2
SNAPSHOT_STALE_DAYS: Final = 30
MAX_EXPORT_BYTES: Final = 2 * 1024 * 1024
SUPPORTED_SCHEMA_MAJOR: Final = "1"
#: Ключи утверждений ID-токена, которые разрешено хранить в `external_identity.claims`.
CLAIMS_WHITELIST: Final = ("iss", "sub", "fsp_id", "aud", "azp", "iat", "auth_time")

# --- календарь (Арх. 7.9) ---------------------------------------------------------------------------------------------
CALENDAR_CACHE_KEY: Final = "calendar"
CALENDAR_TTL_HOURS: Final = 6
CALENDAR_LIMIT_DEFAULT: Final = 3
CALENDAR_LIMIT_MAX: Final = 10
CALENDAR_FETCH_LIMIT: Final = 100
CALENDAR_STATUSES: Final = ("registration_open", "scheduled")
CALENDAR_SKIPPED_AGE_GROUPS: Final = frozenset({"youth", "children"})
#: Релевантность соревнования кандидату без категории.
CALENDAR_RELEVANCE_DEFAULT: Final = 0.7

# --- куда возвращается браузер после привязки -------------------------------------------------------------------------
CALLBACK_PATH: Final = "/api/v1/fsp/link/callback"
SETTINGS_PATH: Final = "/candidate/settings/fsp"
LOGIN_PATH: Final = "/login"

# ---------------------------------------------------------------------------------------------------------------------
# Подписи: формирует сервер, клиент их не собирает (Арх. 9.1)
# ---------------------------------------------------------------------------------------------------------------------
DISCIPLINE_LABEL: Final[dict[str, str]] = {
    "algo": "алгоритмическое программирование",
    "product": "продуктовое программирование",
    "infosec": "информационная безопасность",
    "uav": "программирование БАС",
    "robotics": "робототехника",
    "other": "спортивное программирование",
}
LEVEL_LABEL: Final[dict[str, str]] = {
    "international": "международный",
    "national": "всероссийский",
    "interregional": "окружной",
    "regional": "региональный",
    "municipal": "муниципальный",
}
STAGE_LABEL: Final[dict[str, str]] = {"qualification": "отборочный этап", "stage": "этап", "final": "финал"}
FORMAT_LABEL: Final[dict[str, str]] = {"onsite": "очно", "online": "дистанционно", "hybrid": "смешанный формат"}
AGE_GROUP_LABEL: Final[dict[str, str]] = {
    "adults": "мужчины и женщины",
    "juniors": "юниоры и юниорки",
    "youth": "юноши и девушки",
    "children": "мальчики и девочки",
}
ROLE_LABEL: Final[dict[str, str]] = {
    "athlete": "участник",
    "coach": "тренер",
    "representative": "представитель команды",
}
ROLE_LABEL_CAPTAIN: Final = "капитан команды"
RANK_LABEL: Final[dict[str, str]] = {
    "msmk": "МСМК",
    "ms": "Мастер спорта России",
    "kms": "КМС",
    "r1": "I спортивный разряд",
    "r2": "II спортивный разряд",
    "r3": "III спортивный разряд",
    "y1": "I юношеский разряд",
    "y2": "II юношеский разряд",
    "y3": "III юношеский разряд",
}

TIER_LABEL: Final[dict[str, str]] = {
    "national": "всероссийский уровень и выше",
    "interregional": "уровень федерального округа",
    "regional": "региональный уровень",
}
TIER_SHORT: Final[dict[str, str]] = {
    "national": "всеросс. уровень",
    "interregional": "окружной уровень",
    "regional": "региональный уровень",
}
PERIOD_LABEL: Final[dict[str, str]] = {
    "recent": "за последние 2 года",
    "mid": "2–4 года назад",
    "old": "более 4 лет назад",
}
BUCKET_LABEL: Final[dict[str, str]] = {
    "medal": "призовое место (1–3)",
    "top_half": "верхняя половина протокола",
    "participant": "участие",
}
BUCKET_SHORT: Final[dict[str, str]] = {
    "medal": "призовое место",
    "top_half": "верхняя половина",
    "participant": "участие",
}
SUMMARY_GENERIC_HEADLINE: Final = "Есть подтверждённые достижения ФСП"
SUMMARY_GENERIC_SHORT: Final = "есть достижения"

UNCOUNTED_LABEL: Final[dict[str, str]] = {
    "role_not_athlete": "роль тренера или представителя",
    "annulled": "результат аннулирован",
    "not_finished": "соревнование не завершено или протокол не утверждён",
    "dsq": "дисквалификация",
    "dns": "не стартовал(а)",
    "unknown_level": "уровень соревнования не распознан",
    "no_date": "нет даты проведения",
    "superseded_in_series": "учтён лучший результат серии: этапы и финал не складываются",
}

#: Нейтральная строка блока работодателя: одинакова для «не привязал», «истории нет», «скрыл» и «реестр недоступен».
NEUTRAL_TEXT: Final = "Подтверждённых достижений ФСП в профиле нет. На оценку по тесту это не влияет"
NOTE_BEFORE_DISCLOSURE: Final = "Подробности откроются, когда кандидат примет приглашение"
NOTE_SUMMARY_ONLY: Final = "Кандидат показывает достижения ФСП только в обобщённом виде"
SOURCE_LABEL: Final[dict[str, str]] = {"mock": "Источник: демо-реестр ФСП", "keycloak": "Источник: реестр ФСП"}
EVIDENCE_PUBLIC_PREFIX: Final = "достижение ФСП"
EVIDENCE_ROLE_PUBLIC: Final = "подтверждено данными ФСП"

# --- тексты ошибок API (приложение D, §10.4) --------------------------------------------------------------------------
ERROR_MESSAGES: Final[dict[str, str]] = {
    "fsp_link_exists": "ФСП ID уже привязан. Чтобы привязать другой, сначала отвяжите текущий",
    "fsp_consent_outdated": "Текст согласия обновился. Прочитайте его ещё раз",
    "fsp_consent_required": "Чтобы привязать ФСП ID, нужно согласие на получение сведений",
    "fsp_too_many_attempts": "Слишком много попыток. Повторите позже",
    "fsp_sync_too_frequent": "Данные обновлялись только что. Повторите позже",
    "fsp_not_linked": "ФСП ID не привязан",
    "fsp_unavailable": "Сервис ФСП ID недоступен. Попробуйте позже",
}

#: Машиночитаемый перечень сведений для экрана согласия.
CONSENT_DATA_ITEMS: Final = ("competition", "result", "team", "team_role", "rank")
#: Источник согласия, записанного сидом.
CONSENT_SOURCE_USER: Final = "user"
CONSENT_SOURCE_SEED: Final = "seed"

#: Исходы синхронизации и причины отвязки (приложение D, §3.5, §4.2).
OUTCOME_OK_CHANGED: Final = "ok_changed"
OUTCOME_OK_UNCHANGED: Final = "ok_unchanged"
OUTCOME_IN_PROGRESS: Final = "in_progress"
OUTCOME_FAILED_UNAVAILABLE: Final = "failed_unavailable"
OUTCOME_FAILED_CONTRACT: Final = "failed_contract"
OUTCOME_FAILED_AUTH: Final = "failed_auth"
OUTCOME_FAILED_TIMEOUT: Final = "failed_timeout"
OUTCOME_UNLINKED_REVOKED: Final = "unlinked_revoked"
OUTCOME_UNLINKED_MINOR: Final = "unlinked_minor"
RESYNC_PAUSE_SECONDS: Final = 0.1

#: Тексты возврата из потока привязки видит интерфейс; здесь только подписи уведомлений об отвязке.
NOTICE_TEXT: Final[dict[str, str]] = {
    "unlinked_revoked": "Вы отозвали доступ платформы на стороне ФСП. ФСП ID отвязан, полученные сведения удалены",
    "unlinked_minor": "По данным реестра вам нет 18 лет. ФСП ID отвязан, сведения удалены",
}
