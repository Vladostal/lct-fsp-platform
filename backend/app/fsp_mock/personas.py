"""Типовые персонажи демо-реестра (приложение D, §8.3) и их закреплённые строки протоколов.

Персонажи создаются до случайного заполнения: их строки вставляются с заданными местами, случайные команды
занимают остальные места. `fsp_id = uuid5(NAMESPACE_FSP_MOCK, "persona:" + key)` — идентификаторы не зависят от
сида, поэтому сид платформы может привязать `anna` и `olga`, не заглядывая в реестр.

Судейство и сборные не моделируются (Арх. 15.1, № 47): у `elena` остались роли тренера, у `mikhail` — результаты
и звание.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Final
from uuid import UUID, uuid5

from app.fsp_mock.reference import NAMESPACE_FSP_MOCK


def persona_fsp_id(key: str) -> UUID:
    """`fsp_id` персонажа: детерминирован ключом."""
    return uuid5(NAMESPACE_FSP_MOCK, f"persona:{key}")


@dataclass(frozen=True, slots=True)
class PersonaRank:
    """Разряд или звание персонажа."""

    code: str
    assigned_on: date
    discipline: str | None = None
    revoked_on: date | None = None


@dataclass(frozen=True, slots=True)
class Persona:
    """Типовой персонаж: синтетический спортсмен с заранее известной историей."""

    key: str
    first_name: str
    last_name: str
    middle_name: str
    gender: str
    birth_date: date
    region: str
    #: Строка описания на странице входа демо-провайдера.
    description: str
    ranks: tuple[PersonaRank, ...] = ()
    #: Скрыт на странице входа (виден при `?all=1`): персонаж для автотестов.
    hidden: bool = False


@dataclass(frozen=True, slots=True)
class PinnedMember:
    """Персонаж в составе закреплённой строки."""

    persona: str
    role: str = "athlete"
    captain: bool = False


@dataclass(frozen=True, slots=True)
class PinnedEntry:
    """Закреплённая строка протокола: соревнование плана (код, год, дата), команда, место.

    Строки с одинаковыми `(code, year, on)` и одним хозяином попадают в одно соревнование. Команда с одним
    `team_key` в этапе и финале кубка выступает в том же составе.
    """

    code: str
    year: int
    on: date | None
    team_key: str
    region: str
    place: int | None = None
    place_to: int | None = None
    status: str = "ok"
    members: tuple[PinnedMember, ...] = ()
    team_name: str | None = None
    #: Размер поля соревнования в выгрузке неизвестен (`entries_count = null`).
    unknown_field: bool = False


@dataclass(frozen=True, slots=True)
class ServiceCompetition:
    """Служебное соревнование персонажа `edge`: отклонение от контракта, которого нет в плане генерации."""

    key: str
    title: str
    on: date
    level: str
    protocol_status: str
    place: int
    persona: str = "edge"
    region: str = "RU-NVS"
    discipline: str = "algo"
    team: int = 3
    field: int = 6


PERSONAS: Final[tuple[Persona, ...]] = (
    Persona(
        "anna", "Анна", "Соколова", "Игоревна", "f", date(1999, 3, 14), "RU-TA",
        "Сильная командная история: призёр финала Кубка России, капитан команды",
    ),
    Persona(
        "olga", "Ольга", "Миронова", "Сергеевна", "f", date(2001, 7, 2), "RU-LEN",
        "Запись спортсмена есть, результатов соревнований пока нет",
    ),
    Persona(
        "mikhail", "Михаил", "Орлов", "Андреевич", "m", date(1998, 11, 23), "RU-MOW",
        "Чемпион России в личном зачёте, мастер спорта",
        ranks=(PersonaRank("ms", date(2026, 2, 10), "algo"),),
    ),
    Persona(
        "dasha", "Дарья", "Климова", "Павловна", "f", date(2003, 5, 30), "RU-NIZ",
        "Два региональных старта в середине протокола",
    ),
    Persona(
        "oleg", "Олег", "Тарасов", "Николаевич", "m", date(1997, 2, 8), "RU-SVE",
        "Результаты трёхлетней давности, срок разряда истёк",
        ranks=(PersonaRank("r2", date(2023, 6, 1), "algo"),),
    ),
    Persona(
        "rustam", "Рустам", "Галиев", "Маратович", "m", date(2000, 9, 17), "RU-SPE",
        "Информационная безопасность: призёр чемпионата России и округа",
    ),
    Persona(
        "zarina", "Зарина", "Ахметова", "Ринатовна", "f", date(2002, 1, 25), "RU-KDA",
        "Редкая дисциплина: призёр чемпионата России по программированию БАС",
    ),
    Persona(
        "elena", "Елена", "Васильева", "Викторовна", "f", date(1990, 6, 11), "RU-NIZ",
        "Тренер команд: собственных результатов в реестре нет",
    ),
    Persona(
        "pavel", "Павел", "Громов", "Олегович", "m", date(2001, 12, 3), "RU-ROS",
        "Записи об участии есть, зачтённых результатов нет",
    ),
    Persona(
        "timur", "Тимур", "Назаров", "Ильдарович", "m", date(2010, 3, 12), "RU-MOS",
        "Несовершеннолетний участник первенства России",
    ),
    Persona(
        "edge", "Эдуард", "Граничный", "Тестович", "m", date(1999, 8, 19), "RU-NVS",
        "Отклонения от контракта (для автотестов)",
        ranks=(PersonaRank("r3", date(2025, 6, 1), "algo", revoked_on=date(2025, 12, 1)),),
        hidden=True,
    ),
)  # fmt: skip
PERSONA_BY_KEY: Final[dict[str, Persona]] = {persona.key: persona for persona in PERSONAS}


def _one(persona: str, *, captain: bool = False, role: str = "athlete") -> tuple[PinnedMember, ...]:
    return (PinnedMember(persona, role, captain),)


PINNED: Final[tuple[PinnedEntry, ...]] = (
    # anna: финал кубка — 2 из 16; этап той же серии — 3 из 18 (вытесняется финалом); округ — 1 из 10, капитан.
    PinnedEntry("P-CS", 2026, date(2026, 2, 15), "orbita", "RU-TA", 3, members=_one("anna"), team_name="Орбита-5"),
    PinnedEntry("P-CF", 2026, date(2026, 4, 19), "orbita", "RU-TA", 2, members=_one("anna"), team_name="Орбита-5"),
    PinnedEntry("A-IR", 2025, date(2025, 5, 18), "kazan-algo", "RU-TA", 1, members=_one("anna", captain=True)),
    PinnedEntry("P-RG", 2024, date(2024, 11, 24), "kazan-prod", "RU-TA", 2, members=_one("anna", captain=True)),
    # elena: тренер команды в финале кубка (5 место) и на чемпионате округа; в этапе команда выступала без тренера.
    PinnedEntry("P-CS", 2026, date(2026, 2, 15), "volga", "RU-NIZ", 6, team_name="Волга"),
    PinnedEntry("P-CF", 2026, date(2026, 4, 19), "volga", "RU-NIZ", 5, members=_one("elena", role="coach"),
                team_name="Волга"),
    PinnedEntry("A-IR", 2025, date(2025, 5, 18), "niz-algo", "RU-NIZ", 4, members=_one("elena", role="coach")),
    # mikhail
    PinnedEntry("A-NC", 2025, date(2025, 11, 16), "mikhail", "RU-MOW", 1, members=_one("mikhail")),
    PinnedEntry("A-IN", 2026, date(2026, 7, 12), "mikhail", "RU-MOW", 22, members=_one("mikhail")),
    PinnedEntry("A-CF", 2025, date(2025, 4, 20), "msk-algo", "RU-MOW", 3, members=_one("mikhail")),
    PinnedEntry("A-IR", 2024, date(2024, 5, 19), "msk-algo-24", "RU-MOW", 1, members=_one("mikhail")),
    # dasha
    PinnedEntry("P-RG", 2024, date(2024, 10, 13), "niz-prod", "RU-NIZ", 5, members=_one("dasha")),
    PinnedEntry("A-RG", 2024, date(2024, 3, 24), "niz-algo-24", "RU-NIZ", 6, members=_one("dasha")),
    # oleg
    PinnedEntry("A-IR", 2023, date(2023, 4, 23), "ural-algo", "RU-SVE", 3, members=_one("oleg")),
    PinnedEntry("A-RG", 2023, date(2023, 2, 19), "ekb-algo", "RU-SVE", 1, members=_one("oleg")),
    # rustam
    PinnedEntry("I-NC", 2023, date(2023, 12, 10), "spb-sec", "RU-SPE", 3, members=_one("rustam")),
    PinnedEntry("I-IR", 2025, date(2025, 6, 8), "spb-sec-25", "RU-SPE", 2, members=_one("rustam")),
    # zarina
    PinnedEntry("U-NC", 2026, date(2026, 6, 14), "zarina", "RU-KDA", 2, members=_one("zarina")),
    # pavel: дисквалификация и неявка — записи есть, зачтённых нет
    PinnedEntry("A-RG", 2025, None, "rostov-algo", "RU-ROS", status="dsq", members=_one("pavel")),
    PinnedEntry("P-IR", 2024, None, "rostov-prod", "RU-ROS", status="dns", members=_one("pavel")),
    # timur
    PinnedEntry("A-YN", 2026, date(2026, 6, 7), "timur", "RU-MOS", 5, members=_one("timur")),
    # edge: делёжка мест 2–3 и неизвестный размер поля
    PinnedEntry("P-IR", 2025, date(2025, 5, 25), "nsk-prod", "RU-NVS", 2, 3, members=_one("edge")),
    PinnedEntry("A-RG", 2025, date(2025, 3, 9), "nsk-algo", "RU-NVS", 1, members=_one("edge"), unknown_field=True),
)  # fmt: skip

SERVICE_COMPETITIONS: Final[tuple[ServiceCompetition, ...]] = (
    ServiceCompetition(
        "district",
        "Открытый турнир по спортивному программированию (уровень не из словаря)",
        date(2025, 10, 12),
        level="district",
        protocol_status="official",
        place=2,
    ),
    ServiceCompetition(
        "annulled",
        "Чемпионат Новосибирской области 2024 (протокол аннулирован)",
        date(2024, 12, 8),
        level="regional",
        protocol_status="annulled",
        place=1,
    ),
)
#: Персонаж, заявленный в одном из предстоящих региональных соревнований (результата ещё нет).
PENDING_PERSONA: Final = "pavel"
