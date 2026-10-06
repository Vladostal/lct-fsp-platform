"""Константы механики тестирования — единственный источник (Арх. 5.10).

Каждая константа переопределяется переменной окружения с префиксом `ASSESSMENT_` (например,
`ASSESSMENT_VARIANTS_PER_LEVEL=30`); словари задаются как JSON. Секрет `ASSESSMENT_SECRET` сюда не входит: он лежит
в общих настройках (`core.config.Settings.assessment_secret`).

Читать через `get_config()`: значение кэшируется на процесс; тест, меняющий окружение, вызывает
`get_config.cache_clear()`.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

from app.core.config import module_env

#: Грейды по возрастанию (Арх. 5.2). Порядок используется правилами грейда и планами теста.
GRADES: tuple[str, ...] = ("junior", "middle", "senior")


class AssessmentConfig(BaseSettings):
    """Таблица Арх. 5.10 целиком; имена полей — имена констант в нижнем регистре."""

    model_config = module_env("ASSESSMENT_")

    # --- шкала и решение --------------------------------------------------------------------------------------------
    theta_cut: dict[str, float] = Field(default_factory=lambda: {"junior": -1.5, "middle": 0.0, "senior": 1.5})
    grade_width: float = 1.5
    margin_delta: float = 0.75
    theta_grid_min: float = -4.0
    theta_grid_max: float = 4.0
    theta_grid_step: float = 0.05
    prior_mean: float = 0.0
    prior_sd: float = 2.0
    a_assumed: float = 1.0
    p_confirm: float = 0.80
    p_reject: float = 0.20
    p_margin: float = 0.80

    # --- форма теста ------------------------------------------------------------------------------------------------
    #: Слоты базовой части, привязанные к группам, и свободные слоты растяжки: 12 + 2 = 14 заданий.
    base_main: int = 12
    base_stretch: int = 2
    #: Добавочный блок и их наибольшее число: 14 + 2 · 6 = 26 заданий.
    ext_block: int = 6
    max_ext_blocks: int = 2
    time_limit_base_min: dict[str, int] = Field(default_factory=lambda: {"junior": 30, "middle": 40, "senior": 50})
    time_limit_ext_min: dict[str, int] = Field(default_factory=lambda: {"junior": 10, "middle": 15, "senior": 20})
    answer_grace_s: int = 5

    # --- правила грейда ---------------------------------------------------------------------------------------------
    evidence_window_days: int = 180
    grade_change_cooldown_days: int = 90
    retry_same_grade_days: int = 14
    max_sessions_per_30d: int = 3
    specialization_change_cooldown_days: int = 90
    stale_after_days: int = 180
    drift_sd_per_180d: float = 0.75
    se_eff_max: float = 1.5

    # --- банк -------------------------------------------------------------------------------------------------------
    #: Вариантов на пару «семейство, уровень».
    variants_per_level: int = 60
    #: Вариантов со статусом `demo` на уровень: только для предпросмотра плана, в сессии не попадают.
    demo_variants_per_level: int = 3
    #: Наименьший пул семейств группы в диапазоне грейда. Для демо-стенда 2; целевое значение для продуктива — 3
    #: (тогда ядро P0 — `CORE_P0` реестра, 31 семейство; при 2 — `DEMO_CORE`).
    min_pool: int = 2
    flex_slots: int = 4
    fast_factor: float = 0.15

    # --- короткие задания -------------------------------------------------------------------------------------------
    pulse_min_interval_days: int = 14
    pulse_offer_ttl_days: int = 7
    pulse_time_limit_min: int = 10
    pulse_credit_days: int = 30
    pulse_credit_cap_days: int = 90

    # --- версии -----------------------------------------------------------------------------------------------------
    bank_version: str = "2026.10.0"
    engine_version: str = "1.0"
    survey_version: str = "2026.10"

    @model_validator(mode="after")
    def _grades_complete(self) -> AssessmentConfig:
        for name in ("theta_cut", "time_limit_base_min", "time_limit_ext_min"):
            missing = [grade for grade in GRADES if grade not in getattr(self, name)]
            if missing:
                raise ValueError(f"ASSESSMENT_{name.upper()}: нет значений для грейдов {missing}")
        return self

    @property
    def items_min(self) -> int:
        """Длина теста без добавочных блоков: 14."""
        return self.base_main + self.base_stretch

    @property
    def items_max(self) -> int:
        """Наибольшая длина теста: 26."""
        return self.items_min + self.ext_block * self.max_ext_blocks


@lru_cache(maxsize=1)
def get_config() -> AssessmentConfig:
    """Константы механики для этого процесса."""
    return AssessmentConfig()
