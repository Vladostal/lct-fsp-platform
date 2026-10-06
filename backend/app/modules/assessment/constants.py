"""Числа модуля `assessment` для `Catalog.limits` (их собирает `app.wiring`); источник значений — `config.py`."""

from __future__ import annotations

from app.modules.assessment.config import get_config

_cfg = get_config()

PUBLIC_LIMITS: dict[str, int | float] = {
    "assessment_items_min": _cfg.items_min,
    "assessment_items_max": _cfg.items_max,
    "assessment_max_sessions_per_30d": _cfg.max_sessions_per_30d,
    "assessment_retry_same_grade_days": _cfg.retry_same_grade_days,
    "assessment_grade_change_cooldown_days": _cfg.grade_change_cooldown_days,
    "assessment_specialization_change_cooldown_days": _cfg.specialization_change_cooldown_days,
    "assessment_evidence_window_days": _cfg.evidence_window_days,
    "assessment_stale_after_days": _cfg.stale_after_days,
    "blueprint_preview_text_min": 30,
    "blueprint_preview_text_max": 5000,
}

#: Лимиты предпросмотра плана (поправка рецензии R3-data-api-security-9): событий в час.
PREVIEW_LIMIT_ANON_PER_HOUR = 30
PREVIEW_LIMIT_USER_PER_HOUR = 20
