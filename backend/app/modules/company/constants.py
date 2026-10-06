"""Константы модуля `company`: границы длины полей профиля (приложение E, экран E1) и подписи доверия."""

from __future__ import annotations

from app.shared.enums import TrustLevel

NAME_MIN, NAME_MAX = 2, 100
SPHERE_MIN, SPHERE_MAX = 2, 100
DESCRIPTION_MIN, DESCRIPTION_MAX = 50, 2000
SITE_MAX = 200
CITY_MAX = 80

#: Подпись уровня доверия: видна кандидату в приглашении и работодателю в профиле (Арх. 4.9; приложение C, §4).
TRUST_LABELS: dict[TrustLevel, str] = {
    TrustLevel.BASIC: "Компания подтвердила только e-mail",
    TrustLevel.VERIFIED: "Компания проверена",
}
