"""Схемы сводок отчётов валидации (Арх. 9.11) — единственный источник правды о составе `summary`.

Пакеты валидации (`app.eval.*`) обязаны писать в `report.json` → `summary` ровно эти ключи; тест сборки сверяет
файлы с моделями. Лишний ключ не допускается (`extra="forbid"`): расхождение видно сразу, а не теряется молча.
Все числа — доли 0..1, кроме помеченных; отсутствующее значение — `null`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SummaryMeta(_Section):
    """Происхождение чисел: когда, при каком начальном значении датчика, на скольких объектах, на каких версиях."""

    generated_at: datetime
    seed: int
    n: int
    versions: dict[str, str]


class ExpertStatus(_Section):
    """Что из экспертной проверки проведено (Арх. 12.2): E1 — сложность заданий, E2 — согласие оценщиков, E3 — пилот."""

    e1: Literal["done", "author_only", "not_done"]
    e2_kappa: float | None = None
    e3: Literal["done", "not_done"]


class TestingSummary(SummaryMeta):
    """Тестирование (Арх. 12.2): планки V1–V6 и утечка подтверждения; `sessions_to_first_repeat` — штук."""

    __test__ = False  # имя начинается с «Test»: pytest не должен принимать модель за тестовый класс

    v1_accuracy: float | None = None
    v2_agreement: float | None = None
    v3_exact: float | None = None
    v3_overgrade: float | None = None
    v4_agreement: float | None = None
    v5_three_attempts: float | None = None
    v6_correlation: float | None = None
    leak_false_confirm_m5: float | None = None
    leak_false_confirm_m5_pessimistic: float | None = None
    sessions_to_first_repeat: float | None = None
    expert: ExpertStatus


class MatchingSummary(SummaryMeta):
    """Подбор (Арх. 12.3): точность первой десятки по сравнению с бейзлайнами; `manual_pairs` — штук."""

    p10_ours: float | None = None
    p10_declared: float | None = None
    p10_random: float | None = None
    p10_diff_declared: float | None = None
    p10_diff_ci_low: float | None = None
    p10_diff_ci_high: float | None = None
    #: Бейзлайн «только сила профиля»: наш порядок не должен ему уступать (Арх. 12.3).
    p10_strength_only: float | None = None
    manual_pairs: int
    manual_kappa: float | None = None


class ContactSummary(SummaryMeta):
    """Контакт (Арх. 12.4): доли доставки, ответа в срок, согласия и заполненных потребностей."""

    delivered_share: float | None = None
    reply_in_time_share: float | None = None
    accept_share: float | None = None
    needs_filled_share: float | None = None
    needs_filled_share_no_limits: float | None = None


class ValidationSummary(BaseModel):
    """Сводки трёх отчётов; секция, чьего отчёта нет или он не соответствует модели, — `null`."""

    testing: TestingSummary | None = None
    matching: MatchingSummary | None = None
    contact: ContactSummary | None = None
