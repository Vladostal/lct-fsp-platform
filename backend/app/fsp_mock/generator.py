"""Генератор синтетического реестра ФСП (Арх. 7.1, 7.3; приложение D, §1.3, §8).

Детерминирован: `random.Random(FSP_SEED)`, идентификаторы — `uuid5(NAMESPACE_FSP_MOCK, …)`; один сид — одни и те же
спортсмены, соревнования и места. Все данные синтетические, настоящие протоколы не используются.

Порядок: типовые персонажи → случайные спортсмены → завершённые соревнования плана (по датам: отбор перед финалом,
этапы кубка перед финалом) → служебные соревнования персонажа `edge` → предстоящие соревнования → разряды.
Строки протоколов персонажей закреплены (`personas.PINNED`): случайные команды занимают остальные места.

Судейство, сборные и таблица норм ЕВСК не моделируются (Арх. 15.1, № 47): разряды выдаются по результатам
эвристически и без нормативов, чтобы счётчики анонимности и нижняя граница сигнала имели на чём работать.
"""

from __future__ import annotations

import logging
import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import pairwise
from typing import Final
from uuid import UUID, uuid5

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import session_scope
from app.fsp_mock import reference as ref
from app.fsp_mock import schemas
from app.fsp_mock.models import (
    AccessGrant,
    Athlete,
    AuthCode,
    Competition,
    Control,
    Entry,
    EntryMember,
    RankAssignment,
)
from app.fsp_mock.personas import (
    PENDING_PERSONA,
    PERSONA_BY_KEY,
    PERSONAS,
    PINNED,
    SERVICE_COMPETITIONS,
    PinnedEntry,
    PinnedMember,
    persona_fsp_id,
)

log = logging.getLogger("app.init")

#: Дата сида: «сегодня» синтетического реестра (приложение D, §8.1). Данные не зависят от реальной даты запуска.
SEED_DATE: Final = date(2026, 10, 5)
RANDOM_ATHLETES: Final = 1500
COACH_POOL_SIZE: Final = 80
COACH_SHARE: Final = 0.4
TARGET_RANKS: Final = 60
RANKS_FROM: Final = date(2025, 1, 1)
DOMAIN: Final = "https://fsp-demo.example.com"
MIN_ROWS: Final = 3

MIN_AGE: Final = 14
JUNIOR_MAX_AGE: Final = 26
AGES: Final = tuple(range(14, 31))
AGE_WEIGHTS: Final = (2, 3, 5, 8, 10, 12, 12, 11, 9, 7, 6, 5, 4, 3, 2, 1, 1)
FIRST_YEARS: Final = (2022, 2023, 2024, 2025, 2026)
FIRST_YEAR_WEIGHTS: Final = (2, 3, 4, 5, 4)
DURATIONS: Final = (1, 2, 3, 4, 5)
DURATION_WEIGHTS: Final = (40, 27, 18, 10, 5)
MAIN_DISCIPLINES: Final = ("algo", "product", "infosec", "uav", "robotics")
MAIN_DISCIPLINE_WEIGHTS: Final = (0.45, 0.35, 0.12, 0.04, 0.04)
SECOND_DISCIPLINES: Final = ("algo", "product", "infosec")
SECOND_DISCIPLINE_SHARE: Final = 0.30

#: Скрытая сила персонажей: нужна только жюри и тестам; наружу не отдаётся.
PERSONA_LATENT: Final[dict[str, float]] = {"mikhail": 2.5, "anna": 1.5, "rustam": 1.0, "zarina": 1.0}


@dataclass(frozen=True, slots=True)
class PlanRow:
    """Строка плана соревнований (приложение D, §8.2)."""

    code: str
    discipline: str
    level: str
    kind: str
    stage: str
    team_size: int | None
    field: int
    years: tuple[int, int, int, int, int]
    month: int
    bias: float
    age_group: str = "adults"
    entries_count: int | None = None


PLAN: Final[tuple[PlanRow, ...]] = (
    PlanRow("A-NC", "algo", "national", "championship", "final", None, 40, (1, 1, 1, 1, 0), 11, 1.8),
    PlanRow("A-NQ", "algo", "national", "championship", "qualification", None, 80, (0, 1, 1, 1, 1), 9, 0.6),
    PlanRow("A-CS", "algo", "national", "cup", "stage", 3, 18, (0, 1, 2, 2, 2), 2, 1.2),
    PlanRow("A-CF", "algo", "national", "cup", "final", 3, 14, (0, 1, 1, 1, 1), 4, 1.8),
    PlanRow("A-IR", "algo", "interregional", "championship", "single", 3, 10, (1, 2, 3, 3, 3), 5, 0.8),
    PlanRow("A-RG", "algo", "regional", "championship", "single", 3, 8, (3, 5, 7, 8, 7), 3, 0.0),
    PlanRow("A-MU", "algo", "municipal", "championship", "single", 3, 8, (0, 2, 3, 4, 3), 2, -0.3),
    PlanRow("A-YN", "algo", "national", "youth_championship", "single", None, 24, (0, 1, 1, 1, 1), 6, 1.2, "juniors"),
    PlanRow(
        "A-IN", "algo", "international", "championship", "single", None, 4, (0, 0, 1, 1, 1), 7, 3.0, entries_count=60
    ),
    PlanRow("P-NC", "product", "national", "championship", "single", 5, 12, (1, 1, 1, 1, 0), 11, 1.8),
    PlanRow("P-CS", "product", "national", "cup", "stage", 5, 18, (0, 1, 1, 1, 1), 2, 1.2),
    PlanRow("P-CF", "product", "national", "cup", "final", 5, 16, (0, 1, 1, 1, 1), 4, 1.8),
    PlanRow("P-IR", "product", "interregional", "championship", "single", 4, 10, (1, 2, 3, 3, 3), 5, 0.8),
    PlanRow("P-RG", "product", "regional", "championship", "single", 4, 8, (2, 4, 6, 7, 6), 3, 0.0),
    PlanRow("P-YN", "product", "national", "youth_championship", "single", 4, 10, (0, 1, 1, 1, 1), 6, 1.2, "juniors"),
    PlanRow("P-OT", "product", "national", "other", "single", 5, 14, (0, 0, 1, 1, 1), 8, 1.0),
    PlanRow("I-NC", "infosec", "national", "championship", "single", 4, 10, (0, 1, 1, 1, 0), 12, 1.5),
    PlanRow("I-IR", "infosec", "interregional", "championship", "single", 4, 6, (0, 1, 1, 2, 1), 6, 0.5),
    PlanRow("I-RG", "infosec", "regional", "championship", "single", 4, 6, (1, 1, 2, 3, 2), 4, 0.0),
    PlanRow("U-NC", "uav", "national", "championship", "single", None, 9, (0, 0, 0, 1, 1), 6, 0.8),
    PlanRow("U-RG", "uav", "regional", "championship", "single", None, 6, (0, 1, 1, 1, 1), 4, 0.0),
    PlanRow("R-NC", "robotics", "national", "championship", "single", 3, 6, (0, 0, 1, 1, 1), 7, 0.8),
    PlanRow("R-RG", "robotics", "regional", "championship", "single", 3, 4, (0, 1, 1, 1, 1), 4, 0.0),
)  # fmt: skip
PLAN_BY_CODE: Final[dict[str, PlanRow]] = {row.code: row for row in PLAN}
PLAN_YEARS: Final = (2022, 2023, 2024, 2025, 2026)
#: Самый ранний день года для первого соревнования серии и шаг между следующими — три недели.
FIRST_DAY: Final = 12
STEP_DAYS: Final = 21
JURY_DISCIPLINE: Final = "product"
SHARED_PLACE_SHARE: Final = 0.10
DNS_SHARE: Final = 0.02
DSQ_SHARE: Final = 0.01
INTERNATIONAL_PLACES: Final = (1, 3, 7, 15, 22, 30)

TITLE_KIND: Final[dict[str, str]] = {
    "championship": "Чемпионат",
    "cup": "Кубок",
    "youth_championship": "Первенство",
    "other": "Открытые соревнования",
}
TITLE_DISCIPLINE: Final[dict[str, str]] = {
    "algo": "алгоритмическому программированию",
    "product": "продуктовому программированию",
    "infosec": "программированию систем информационной безопасности",
    "uav": "программированию беспилотных авиационных систем",
    "robotics": "программированию робототехники",
}
FORMATS: Final = ("onsite", "online", "hybrid")
FORMAT_WEIGHTS: Final = (0.5, 0.3, 0.2)


# ---------------------------------------------------------------------------------------------------------------------
# Внутренние структуры
# ---------------------------------------------------------------------------------------------------------------------


@dataclass(slots=True)
class Person:
    """Спортсмен в памяти генератора."""

    fsp_id: UUID
    region: str
    birth: date
    disciplines: tuple[str, ...]
    first_year: int
    last_year: int
    latent: float
    persona: str | None = None


@dataclass(slots=True)
class Team:
    key: str
    name: str | None
    members: list[UUID]
    captain: UUID | None


@dataclass(slots=True)
class Slot:
    """Одно соревнование плана до того, как набраны его участники."""

    row: PlanRow
    competition_id: str
    title: str
    year: int
    start: date
    stage: str
    series_code: str | None
    host: ref.Region
    level: str
    protocol_status: str = "official"
    pinned: list[PinnedEntry] = field(default_factory=list)
    entries_count_unknown: bool = False
    #: Участники пришли из отбора/этапов, а не из общего пула.
    fixed_field: bool = False
    persona_key: str | None = None


@dataclass(slots=True)
class Row:
    """Строка протокола до присвоения места."""

    members: list[tuple[UUID, str, bool]]
    region: str
    team_name: str | None
    performance: float
    pinned: PinnedEntry | None = None
    status: str = "ok"
    place: int | None = None
    place_to: int | None = None
    #: Ключ состава (для финала кубка: тот же состав, что на этапе).
    team_key: str | None = None


@dataclass(slots=True)
class Registry:
    """Результат генерации — списки ORM-объектов, ещё не записанных в базу."""

    athletes: list[Athlete] = field(default_factory=list)
    competitions: list[Competition] = field(default_factory=list)
    entries: list[Entry] = field(default_factory=list)
    members: list[EntryMember] = field(default_factory=list)
    ranks: list[RankAssignment] = field(default_factory=list)


# ---------------------------------------------------------------------------------------------------------------------
# Генератор
# ---------------------------------------------------------------------------------------------------------------------


def _weighted_sample(rng: random.Random, items: list[Person], weights: list[float], k: int) -> list[Person]:
    """Отбор без возвращения с весами (Эфраимидис — Спирикис): меньший ключ — раньше в жеребьёвке."""
    keyed = sorted((-math.log(1.0 - rng.random()) / max(weight, 1e-12), index) for index, weight in enumerate(weights))
    return [items[index] for _, index in keyed[:k]]


def _add_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 29 февраля
        return day.replace(year=day.year + years, day=28)


class _Generator:
    def __init__(self, seed: int, today: date) -> None:
        self.rng = random.Random(seed)
        self.today = today
        self.registry = Registry()
        self.people: list[Person] = []
        self.by_id: dict[UUID, Person] = {}
        self.coach_pool: list[Person] = []
        self.teams: dict[str, Team] = {}
        self.team_counter = 0
        self.entry_counter = 0
        self.ekp_counter = 0
        #: Результаты по соревнованиям: `competition_id` → строки (нужны финалам и разрядам).
        self.rows_by_competition: dict[str, list[Row]] = {}
        self.competition_by_id: dict[str, Competition] = {}

    # --- спортсмены ------------------------------------------------------------------------------------------------

    def make_personas(self) -> None:
        for persona in PERSONAS:
            fsp_id = persona_fsp_id(persona.key)
            person = Person(
                fsp_id=fsp_id,
                region=persona.region,
                birth=persona.birth_date,
                disciplines=(),
                first_year=0,
                last_year=0,
                latent=PERSONA_LATENT.get(persona.key, 0.0),
                persona=persona.key,
            )
            self.by_id[fsp_id] = person
            self.registry.athletes.append(
                Athlete(
                    fsp_id=fsp_id,
                    last_name=persona.last_name,
                    first_name=persona.first_name,
                    middle_name=persona.middle_name,
                    birth_date=persona.birth_date,
                    gender=persona.gender,
                    region_code=persona.region,
                    status="active",
                    persona_key=persona.key,
                    latent_skill=person.latent,
                )
            )

    def make_athletes(self, count: int) -> None:
        rng = self.rng
        regions = list(ref.REGIONS)
        weights = [region.weight for region in regions]
        for index in range(count):
            region = rng.choices(regions, weights)[0]
            main = rng.choices(MAIN_DISCIPLINES, MAIN_DISCIPLINE_WEIGHTS)[0]
            disciplines = [main]
            if rng.random() < SECOND_DISCIPLINE_SHARE:
                other = rng.choice([item for item in SECOND_DISCIPLINES if item != main])
                disciplines.append(other)
            first_year = rng.choices(FIRST_YEARS, FIRST_YEAR_WEIGHTS)[0]
            duration = rng.choices(DURATIONS, DURATION_WEIGHTS)[0]
            age = rng.choices(AGES, AGE_WEIGHTS)[0]
            birth = self.today - timedelta(days=int(age * 365.25) + rng.randrange(365))
            latent = rng.gauss(0.0, 1.0)
            gender = rng.choice(("m", "f"))
            fsp_id = uuid5(ref.NAMESPACE_FSP_MOCK, f"athlete:{index}")
            person = Person(
                fsp_id, region.code, birth, tuple(disciplines), first_year, first_year + duration - 1, latent
            )
            self.people.append(person)
            self.by_id[fsp_id] = person
            first_names = ref.MALE_NAMES if gender == "m" else ref.FEMALE_NAMES
            surname = rng.choice(ref.SURNAMES)
            root = rng.choice(ref.PATRONYMIC_ROOTS)
            self.registry.athletes.append(
                Athlete(
                    fsp_id=fsp_id,
                    last_name=surname if gender == "m" else surname + "а",
                    first_name=rng.choice(first_names),
                    middle_name=root + ("ич" if gender == "m" else "на"),
                    birth_date=birth,
                    gender=gender,
                    region_code=region.code,
                    status="active",
                    persona_key=None,
                    latent_skill=latent,
                )
            )
        older = [person for person in self.people if self.age_on(person, self.today) > 23]
        self.coach_pool = rng.sample(older, min(COACH_POOL_SIZE, len(older)))

    @staticmethod
    def age_on(person: Person, day: date) -> int:
        return day.year - person.birth.year - ((day.month, day.day) < (person.birth.month, person.birth.day))

    # --- план ------------------------------------------------------------------------------------------------------

    def build_slots(self) -> list[Slot]:
        """Развернуть план в соревнования: закреплённые даты персонажей занимают места плана."""
        pinned_by_slot: dict[tuple[str, int, date | None], list[PinnedEntry]] = defaultdict(list)
        for entry in PINNED:
            pinned_by_slot[(entry.code, entry.year, entry.on)].append(entry)
        slots: list[Slot] = []
        host_cursor: dict[tuple[str, int], int] = defaultdict(int)
        for row in PLAN:
            for year, count in zip(PLAN_YEARS, row.years, strict=True):
                dated = sorted({on for (code, y, on) in pinned_by_slot if code == row.code and y == year and on})
                undated = [entry for (code, y, on), items in pinned_by_slot.items()
                           if code == row.code and y == year and on is None for entry in items]  # fmt: skip
                total = max(count, len(dated))
                plan_dates: list[date] = list(dated)
                first = date(year, row.month, FIRST_DAY)
                step = 0
                while len(plan_dates) < total:
                    candidate = first + timedelta(days=STEP_DAYS * step)
                    step += 1
                    if candidate not in plan_dates:
                        plan_dates.append(candidate)
                plan_dates = sorted(day for day in plan_dates if day < self.today)
                for position, start in enumerate(plan_dates, start=1):
                    pinned = list(pinned_by_slot.get((row.code, year, start), []))
                    if not pinned and undated:
                        pinned = [undated.pop(0)]
                    slots.append(self._slot(row, year, position, start, pinned, host_cursor))
        slots.sort(key=lambda slot: (slot.start, slot.competition_id))
        return slots

    def _slot(
        self,
        row: PlanRow,
        year: int,
        position: int,
        start: date,
        pinned: list[PinnedEntry],
        host_cursor: dict[tuple[str, int], int],
    ) -> Slot:
        stage = row.stage
        series: str | None = None
        if row.code in ("A-NQ", "A-NC") and year >= 2023:
            series = f"{year}-ru-championship-algo"
        elif row.code == "A-NC":
            stage = "single"  # в 2022 году отбора нет: финал набирается обычным отбором
        elif row.kind == "cup":
            series = f"{year}-ru-cup-{row.discipline}"
        host = self._host_for(row, year, pinned, host_cursor)
        competition_id = f"{row.code}-{year}-{position}"
        return Slot(
            row=row,
            competition_id=competition_id,
            title=self._title(row, year, stage, host),
            year=year,
            start=start,
            stage=stage,
            series_code=series,
            host=host,
            level=row.level,
            pinned=pinned,
            entries_count_unknown=any(entry.unknown_field for entry in pinned),
        )

    def _host_for(
        self, row: PlanRow, year: int, pinned: list[PinnedEntry], host_cursor: dict[tuple[str, int], int]
    ) -> ref.Region:
        """Регион проведения: у закреплённых — регион их строки; у региональных — по кругу из восьми крупнейших."""
        if pinned:
            return ref.REGION_BY_CODE[pinned[0].region]
        if row.level in ("national", "international"):
            host_cursor[(row.code, 0)] += 1
            return ref.REGIONS[(0, 2, 4)[host_cursor[(row.code, 0)] % 3]]
        eligible: dict[str, int] = defaultdict(int)
        for person in self.people:
            if self._person_fits(person, row, year):
                eligible[person.region] += 1
        top = [code for code, _ in sorted(eligible.items(), key=lambda item: (-item[1], item[0]))[:8]]
        if row.level == "interregional":
            okrugs = sorted({ref.REGION_BY_CODE[code].okrug for code in top})
            pool = [region for region in ref.REGIONS if region.okrug in okrugs and region.code in top] or [
                ref.REGIONS[0]
            ]
        else:
            pool = [ref.REGION_BY_CODE[code] for code in top] or [ref.REGIONS[0]]
        key = (row.level, year)
        host_cursor[key] += 1
        return pool[(host_cursor[key] - 1) % len(pool)]

    @staticmethod
    def _title(row: PlanRow, year: int, stage: str, host: ref.Region) -> str:
        kind = TITLE_KIND[row.kind]
        subject = TITLE_DISCIPLINE[row.discipline]
        if row.level in ("international",):
            base = f"Международные соревнования по {subject}, российская сборная заявок, {year}"
        elif row.level == "national":
            if row.kind == "youth_championship":
                base = f"Первенство России по {subject} {year}"
            elif row.kind == "other":
                base = f"Всероссийские соревнования по {subject} {year}"
            else:
                base = f"{kind} России по {subject} {year}"
        elif row.level == "interregional":
            base = f"{kind} {ref.OKRUGS[host.okrug].genitive} по {subject} {year}"
        elif row.level == "regional":
            base = f"{kind} {host.genitive} по {subject} {year}"
        else:
            base = f"{kind} города {host.city} по {subject} {year}"
        suffix = {"final": ", финал", "stage": ", этап", "qualification": ", отборочный этап"}.get(stage, "")
        return base + suffix

    def _person_fits(self, person: Person, row: PlanRow, year: int) -> bool:
        if not (person.first_year <= year <= person.last_year) or row.discipline not in person.disciplines:
            return False
        age = year - person.birth.year
        return age >= MIN_AGE and (row.age_group != "juniors" or age < JUNIOR_MAX_AGE)

    # --- участники ------------------------------------------------------------------------------------------------

    def eligible(self, slot: Slot, used: set[UUID], *, relax: bool = False) -> list[Person]:
        """Допущенные к соревнованию; `relax` снимает привязку к региону проведения (открытый турнир)."""
        row = slot.row
        result = []
        for person in self.people:
            if person.fsp_id in used or not self._person_fits(person, row, slot.year):
                continue
            if not relax and row.level in ("regional", "municipal") and person.region != slot.host.code:
                continue
            if (
                not relax
                and row.level == "interregional"
                and ref.REGION_BY_CODE[person.region].okrug != slot.host.okrug
            ):
                continue
            result.append(person)
        return result

    def _team_name(self) -> str:
        self.team_counter += 1
        return f"{self.rng.choice(ref.TEAM_NAMES)}-{self.team_counter}"

    def _pinned_team(self, entry: PinnedEntry, slot: Slot, used: set[UUID]) -> Team:
        """Состав закреплённой команды: персонажи + случайные участники; один `team_key` — один состав."""
        known = self.teams.get(entry.team_key)
        if known is not None:
            return known
        size = slot.row.team_size or 1
        members: list[UUID] = []
        captain: UUID | None = None
        for member in entry.members:
            if member.role != "athlete":
                continue
            fsp_id = persona_fsp_id(member.persona)
            members.append(fsp_id)
            if member.captain:
                captain = fsp_id
        if size > len(members):
            pool = [person for person in self.eligible(slot, used | set(members)) if person.region == entry.region]
            if len(pool) < size - len(members):
                pool = self.eligible(slot, used | set(members))
            picked = self.rng.sample(pool, min(size - len(members), len(pool)))
            members.extend(person.fsp_id for person in picked)
        if captain is None and size > 1:
            captain = next((m for m in members if self.by_id[m].persona is None), members[0])
        team = Team(entry.team_key, entry.team_name or (self._team_name() if size > 1 else None), members, captain)
        self.teams[entry.team_key] = team
        return team

    def _pinned_rows(self, slot: Slot, used: set[UUID]) -> list[Row]:
        rows: list[Row] = []
        for entry in slot.pinned:
            personal = (slot.row.team_size or 1) == 1
            members: list[tuple[UUID, str, bool]] = []
            if personal:
                for member in entry.members:
                    members.append((persona_fsp_id(member.persona), member.role, False))
                team_name = None
            else:
                team = self._pinned_team(entry, slot, used)
                members.extend((m, "athlete", m == team.captain) for m in team.members)
                for member in entry.members:
                    if member.role != "athlete":
                        members.append((persona_fsp_id(member.persona), member.role, False))
                team_name = team.name
            for fsp_id, role, _ in members:
                if role == "athlete":
                    used.add(fsp_id)
            rows.append(
                Row(
                    members=members,
                    region=entry.region,
                    team_name=team_name,
                    performance=0.0,
                    pinned=entry,
                    status=entry.status,
                    place=entry.place,
                    place_to=entry.place_to,
                    team_key=entry.team_key,
                )
            )
        return rows

    def _random_rows(
        self, slot: Slot, used: set[UUID], count: int, *, relax: bool = False, minimum: int = 0
    ) -> list[Row]:
        """Случайные команды по плану: отбор с весом `exp(bias · latent)`, команды — внутри региона.

        Если в регионе проведения допущенных не хватило, чтобы места закреплённых строк персонажей уложились
        в протокол (`minimum` строк), недостающие команды берутся из других регионов: турнир остаётся «открытым».
        """
        rows = self._select_rows(slot, used, count, relax=relax)
        if len(rows) < minimum and not relax:
            taken = used | {member for item in rows for member, _, _ in item.members}
            rows += self._select_rows(slot, taken, minimum - len(rows), relax=True)
        return rows

    def _select_rows(self, slot: Slot, used: set[UUID], count: int, *, relax: bool) -> list[Row]:
        row = slot.row
        size = row.team_size or 1
        pool = self.eligible(slot, used, relax=relax)
        if count <= 0 or not pool:
            return []
        weights = [math.exp(row.bias * person.latent) for person in pool]
        picked = _weighted_sample(self.rng, pool, weights, count * size)
        chosen = {person.fsp_id for person in picked}
        by_region: dict[str, list[Person]] = defaultdict(list)
        for person in picked:
            by_region[person.region].append(person)
        spare: dict[str, list[Person]] = defaultdict(list)
        if size > 1:
            for person in pool:
                if person.fsp_id not in chosen:
                    spare[person.region].append(person)
        teams: list[list[Person]] = []
        for region in sorted(by_region):
            group = by_region[region]
            for start in range(0, len(group), size):
                chunk = group[start : start + size]
                while len(chunk) < size and spare[region]:
                    chunk.append(spare[region].pop(0))
                if len(chunk) == size:
                    teams.append(chunk)
        if len(teams) > count:
            teams = self.rng.sample(teams, count)
        rows = []
        for chunk in teams:
            perf = sum(person.latent for person in chunk) / len(chunk) + self.rng.gauss(0.0, 0.5)
            captain = self.rng.choice(chunk).fsp_id if size > 1 else None
            members = [(person.fsp_id, "athlete", person.fsp_id == captain) for person in chunk]
            rows.append(
                Row(
                    members=members,
                    region=chunk[0].region,
                    team_name=self._team_name() if size > 1 else None,
                    performance=perf,
                )
            )
        return rows

    def _derived_rows(self, slot: Slot, used: set[UUID], need: int) -> list[Row]:
        """Финал, набираемый по итогам отбора или этапов: лучшие строки с тем же составом."""
        row = slot.row
        sources: list[Row] = []
        if row.code == "A-NC" and slot.series_code:
            for other in self.competition_by_id.values():
                if other.series_code == slot.series_code and other.stage == "qualification":
                    sources = list(self.rows_by_competition[other.competition_id])
        elif row.kind == "cup" and row.stage == "final":
            best: dict[tuple[UUID, ...], Row] = {}
            for other in self.competition_by_id.values():
                if other.series_code == slot.series_code and other.stage == "stage":
                    for source in self.rows_by_competition[other.competition_id]:
                        if source.status != "ok" or source.pinned is not None:
                            continue
                        key = tuple(sorted(member[0] for member in source.members))
                        current = best.get(key)
                        if current is None or (source.place or 10**6) < (current.place or 10**6):
                            best[key] = source
            sources = list(best.values())
        ranked = sorted(
            (source for source in sources if source.status == "ok" and source.pinned is None),
            key=lambda source: (source.place or 10**6, source.team_name or ""),
        )
        derived: list[Row] = []
        for source in ranked:
            if len(derived) >= need:
                break
            ids = {member[0] for member in source.members if member[1] == "athlete"}
            if ids & used:
                continue
            used.update(ids)
            derived.append(
                Row(
                    members=[m for m in source.members if m[1] == "athlete"],
                    region=source.region,
                    team_name=source.team_name,
                    performance=source.performance + self.rng.gauss(0.0, 0.5),
                )
            )
        return derived

    # --- соревнование ----------------------------------------------------------------------------------------------

    def build_competition(self, slot: Slot) -> bool:
        """Набрать участников, расставить места, создать записи. `False` — набралось меньше трёх строк."""
        row = slot.row
        used: set[UUID] = set()
        rows = self._pinned_rows(slot, used)
        need = row.field - len(rows)
        derived = (row.code == "A-NC" and slot.series_code is not None) or (row.kind == "cup" and row.stage == "final")
        if derived:
            fresh = self._derived_rows(slot, used, need)
            if len(fresh) < need:  # этапов не хватило — добираем обычным отбором
                for item in fresh:
                    used.update(member[0] for member in item.members)
                fresh += self._random_rows(slot, used | {m for r in rows for m, _, _ in r.members}, need - len(fresh))
        else:
            if row.entries_count is not None:  # международные: поле задано числом российских участников
                minimum = 0
            elif slot.pinned:  # соревнования персонажей набираются до полного поля плана: их места и поле сходятся
                minimum = need
            else:
                minimum = self._min_random(rows)
            fresh = self._random_rows(slot, used, need, minimum=minimum)
        rows.extend(fresh)
        if len(rows) < MIN_ROWS:
            return False
        self._assign_results(slot, rows)
        self._persist_competition(slot, rows)
        return True

    @staticmethod
    def _min_random(pinned: list[Row]) -> int:
        """Сколько случайных строк нужно, чтобы наибольшее закреплённое место не вышло за пределы протокола."""
        top = max((item.place_to or item.place or 0 for item in pinned if item.status == "ok"), default=0)
        return max(0, top - len([item for item in pinned if item.status == "ok"]))

    def _assign_results(self, slot: Slot, rows: list[Row]) -> None:
        rng = self.rng
        pinned_rows = [item for item in rows if item.pinned is not None]
        free = [item for item in rows if item.pinned is None]
        if not pinned_rows:  # в соревнованиях с закреплёнными строками отказов нет: места персонажей должны сойтись
            for item in free:
                draw = rng.random()
                if draw < DNS_SHARE:
                    item.status = "dns"
                elif draw < DNS_SHARE + DSQ_SHARE:
                    item.status = "dsq"
        free_ok = sorted((item for item in free if item.status == "ok"), key=lambda item: -item.performance)
        if slot.row.entries_count is not None:  # международные: места российских участников — из заданного набора
            fixed = [item.place for item in pinned_rows if item.place is not None]
            others = [p for p in INTERNATIONAL_PLACES if p not in fixed]
            places = sorted(rng.sample(others, min(len(free_ok), len(others))))
            for item, place in zip(free_ok, places, strict=False):
                item.place = place
            return
        occupied: set[int] = set()
        partners: dict[tuple[int, int], int] = {}
        for item in pinned_rows:
            if item.place is None:
                continue
            high = item.place_to or item.place
            occupied.update(range(item.place, high + 1))
            if high > item.place:
                partners[(item.place, high)] = high - item.place
        ok_total = len([item for item in rows if item.status == "ok"])
        available = [place for place in range(1, ok_total + 1) if place not in occupied]
        queue = list(free_ok)
        for (low, high), amount in partners.items():
            for _ in range(min(amount, len(queue))):
                partner = queue.pop(0)
                partner.place, partner.place_to = low, high
        for item, place in zip(queue, available, strict=False):
            item.place = place
        if slot.row.discipline == JURY_DISCIPLINE and rng.random() < SHARED_PLACE_SHARE:
            ordered = sorted((item for item in queue if item.place is not None), key=lambda item: item.place or 0)
            for first, second in pairwise(ordered):
                if first.place_to is None and second.place_to is None and second.place == (first.place or 0) + 1:
                    first.place_to = second.place_to = second.place
                    second.place = first.place
                    break

    def _persist_competition(self, slot: Slot, rows: list[Row]) -> None:
        rng = self.rng
        row = slot.row
        self.ekp_counter += 1
        athletes_count = len({m for item in rows for m, role, _ in item.members if role == "athlete"})
        regions = {item.region for item in rows}
        entries_count: int | None = len(rows)
        if row.entries_count is not None:
            entries_count = row.entries_count
        if slot.entries_count_unknown:
            entries_count = None
        team = (row.team_size or 1) > 1
        competition = Competition(
            competition_id=slot.competition_id,
            ekp_number=f"DEMO-{slot.year}-{self.ekp_counter:04d}",
            title=slot.title,
            discipline_code=row.discipline,
            level=slot.level,
            kind=row.kind,
            stage=slot.stage,
            series_code=slot.series_code,
            age_group=row.age_group,
            participation="team" if team else "individual",
            team_size_min=row.team_size if team else None,
            team_size_max=row.team_size if team else None,
            format=rng.choices(FORMATS, FORMAT_WEIGHTS)[0],
            status="finished",
            protocol_status=slot.protocol_status,
            date_start=slot.start,
            date_end=slot.start + timedelta(days=1 if row.level in ("national", "international") else 0),
            registration_deadline=slot.start - timedelta(days=14),
            city=slot.host.city,
            region_code=slot.host.code,
            organizer=ref.ORGANIZER,
            entries_count=entries_count,
            athletes_count=athletes_count,
            regions_count=max(len(regions), 1),
            registration_url=f"{DOMAIN}/competitions/{slot.competition_id}",
            protocol_url=(f"{DOMAIN}/protocols/{slot.competition_id}" if slot.protocol_status == "official" else None),
        )
        self.registry.competitions.append(competition)
        self.competition_by_id[slot.competition_id] = competition
        self.rows_by_competition[slot.competition_id] = rows
        ok_rows = sorted((item for item in rows if item.status == "ok"), key=lambda item: item.place or 0)
        total_ok = max(len(ok_rows), 1)
        for item in rows:
            self.entry_counter += 1
            entry_id = f"E-{slot.competition_id}-{self.entry_counter:05d}"
            rank = (item.place or 1) - 1
            fields = self._score_fields(row.discipline, item, rank, total_ok)
            self.registry.entries.append(
                Entry(
                    entry_id=entry_id,
                    competition_id=slot.competition_id,
                    kind="team" if team else "individual",
                    team_name=item.team_name,
                    region_code=item.region,
                    result_status=item.status,
                    place=item.place if item.status == "ok" else None,
                    place_to=item.place_to if item.status == "ok" else None,
                    **fields,
                )
            )
            members = list(item.members)
            if team and item.pinned is None and rng.random() < COACH_SHARE:
                coach = self._pick_coach(item, rows)
                if coach is not None:
                    members.append((coach, "coach", False))
            for fsp_id, role, captain in members:
                self.registry.members.append(
                    EntryMember(entry_id=entry_id, fsp_id=fsp_id, role=role, is_captain=captain and role == "athlete")
                )

    def _pick_coach(self, item: Row, rows: list[Row]) -> UUID | None:
        in_competition = {m for other in rows for m, role, _ in other.members if role == "athlete"}
        same_region = [p for p in self.coach_pool if p.region == item.region and p.fsp_id not in in_competition]
        pool = same_region or [p for p in self.coach_pool if p.fsp_id not in in_competition]
        return self.rng.choice(pool).fsp_id if pool else None

    def _score_fields(self, discipline: str, item: Row, rank: int, total: int) -> dict[str, object]:
        rng = self.rng
        if item.status != "ok":
            return {}
        share = 1.0 - rank / max(total, 1)
        if discipline == "algo":
            return {
                "problems_total": 12,
                "solved": max(1, round(1 + 10 * share)),
                "penalty": 300 + rank * 85 + rng.randrange(60),
            }
        if discipline == JURY_DISCIPLINE:
            score = round(55 + 40 * share + rng.uniform(-0.4, 0.4), 1)
            parts = [round(score * weight, 1) for weight in (0.3, 0.3, 0.2)]
            parts.append(round(score - sum(parts), 1))
            names = ("Решение задачи", "Качество кода", "Прототип", "Презентация")
            return {
                "score": score,
                "score_max": 100,
                "criteria": [{"name": name, "score": value} for name, value in zip(names, parts, strict=True)],
            }
        return {
            "score": round(40 + 55 * share + rng.uniform(-0.4, 0.4), 1),
            "score_max": 100,
            "penalty": 600 + rank * 40,
        }

    # --- служебные и предстоящие соревнования ------------------------------------------------------------------------

    def service_competitions(self) -> None:
        """Отклонения от контракта для автотестов: неизвестный уровень и аннулированный протокол (персонаж `edge`)."""
        for item in SERVICE_COMPETITIONS:
            # Отбор ведётся как для регионального соревнования (в регионе проведения), а в записи стоит `item.level`.
            row = PlanRow(
                code=f"S-{item.key}",
                discipline=item.discipline,
                level="regional",
                kind="championship",
                stage="single",
                team_size=item.team,
                field=item.field,
                years=(0, 0, 0, 0, 0),
                month=item.on.month,
                bias=0.0,
            )
            pinned = PinnedEntry(
                code=row.code,
                year=item.on.year,
                on=item.on,
                team_key=f"service-{item.key}",
                region=item.region,
                place=item.place,
                members=(PinnedMember(item.persona),),
            )
            slot = Slot(
                row=row,
                competition_id=f"S-{item.key}-{item.on.year}",
                title=item.title,
                year=item.on.year,
                start=item.on,
                stage="single",
                series_code=None,
                host=ref.REGION_BY_CODE[item.region],
                level=item.level,
                protocol_status=item.protocol_status,
                pinned=[pinned],
            )
            used: set[UUID] = set()
            rows = self._pinned_rows(slot, used)
            rows.extend(self._random_rows(slot, used, row.field - len(rows)))
            self._assign_results(slot, rows)
            self._persist_competition(slot, rows)

    def upcoming(self) -> None:
        """16 предстоящих соревнований календаря (приложение D, §8.2, правило 10)."""
        rng = self.rng
        specs: list[tuple[str, str, str, str, str, str, str, str]] = []
        # (discipline, level, kind, stage, age_group, status, region, participation)
        for discipline in ("algo", "product", "infosec"):
            specs.append((discipline, "national", "championship", "final", "adults", "scheduled", "RU-MOW", "team"))
        regional = [
            ("algo", "RU-TA"), ("product", "RU-NIZ"), ("algo", "RU-ROS"), ("infosec", "RU-NVS"),
            ("product", "RU-SVE"), ("algo", "RU-SPE"),
        ]  # fmt: skip
        for index, (discipline, region) in enumerate(regional):
            specs.append(
                (
                    discipline,
                    "regional",
                    "championship",
                    "qualification" if index % 3 == 2 else "single",
                    "adults",
                    "registration_open",
                    region,
                    "team",
                )
            )
        for discipline, region in (("algo", "RU-TA"), ("product", "RU-NVS"), ("infosec", "RU-MOW")):
            specs.append(
                (discipline, "interregional", "championship", "single", "adults", "registration_open", region, "team")
            )
        for discipline, region in (("algo", "RU-MOW"), ("product", "RU-SPE")):
            specs.append((discipline, "national", "other", "single", "adults", "registration_open", region, "team"))
        specs.append(
            ("algo", "national", "youth_championship", "single", "youth", "registration_open", "RU-KDA", "team")
        )
        specs.append(
            ("product", "national", "youth_championship", "single", "children", "registration_open", "RU-TOM", "team")
        )
        offsets = sorted(rng.sample(range(7, 201), len(specs)))
        for index, (
            (discipline, level, kind, stage, age_group, status, region_code, participation),
            offset,
        ) in enumerate(zip(specs, offsets, strict=True), start=1):
            host = ref.REGION_BY_CODE[region_code]
            start = self.today + timedelta(days=offset)
            slot_row = PlanRow("U", discipline, level, kind, stage, 3, 0, (0,) * 5, start.month, 0.0, age_group)
            title = self._title(slot_row, start.year, stage, host)
            self.ekp_counter += 1
            deadline = None if status == "scheduled" else start - timedelta(days=min(14, max(offset - 3, 1)))
            self.registry.competitions.append(
                Competition(
                    competition_id=f"UP-{index:02d}",
                    ekp_number=f"DEMO-{start.year}-{self.ekp_counter:04d}",
                    title=title,
                    discipline_code=discipline,
                    level=level,
                    kind=kind,
                    stage=stage,
                    series_code=None,
                    age_group=age_group,
                    participation=participation,
                    team_size_min=2,
                    team_size_max=5,
                    format=rng.choices(FORMATS, FORMAT_WEIGHTS)[0],
                    status=status,
                    protocol_status="none",
                    date_start=start,
                    date_end=start + timedelta(days=1),
                    registration_deadline=deadline,
                    city=host.city,
                    region_code=host.code,
                    organizer=ref.ORGANIZER,
                    entries_count=None,
                    athletes_count=None,
                    regions_count=None,
                    registration_url=f"{DOMAIN}/competitions/UP-{index:02d}/register",
                    protocol_url=None,
                )
            )
        pending_region = ref.REGION_BY_CODE[PERSONA_BY_KEY[PENDING_PERSONA].region]
        target = next(
            (
                c
                for c in self.registry.competitions
                if c.status == "registration_open" and c.region_code == pending_region.code
            ),
            None,
        )
        if target is not None:
            entry_id = f"E-{target.competition_id}-pending"
            self.registry.entries.append(
                Entry(
                    entry_id=entry_id,
                    competition_id=target.competition_id,
                    kind="team",
                    team_name="Ростовские алгоритмисты",
                    region_code=pending_region.code,
                    result_status="pending",
                )
            )
            self.registry.members.append(
                EntryMember(entry_id=entry_id, fsp_id=persona_fsp_id(PENDING_PERSONA), role="athlete", is_captain=True)
            )

    # --- разряды ------------------------------------------------------------------------------------------------------

    def ranks(self) -> None:
        """Разряды: персонажам — по таблице, остальным — по лучшему результату с 01.01.2025 (без нормативов)."""
        rng = self.rng
        rank_order = {code: index for index, code in enumerate(ref.RANK_ORDER)}
        best: dict[UUID, tuple[int, str, str, date]] = {}
        competitions = self.competition_by_id
        entry_by_id = {entry.entry_id: entry for entry in self.registry.entries}
        for member in self.registry.members:
            if member.role != "athlete" or self.by_id[member.fsp_id].persona is not None:
                continue
            entry = entry_by_id[member.entry_id]
            competition = competitions.get(entry.competition_id)
            if (
                competition is None
                or entry.result_status != "ok"
                or competition.date_end < RANKS_FROM
                or competition.protocol_status != "official"
            ):
                continue
            tier = ref.TIER.get(competition.level)
            if tier is None:
                continue
            place = entry.place or 10**6
            medal = place <= 3 and (competition.entries_count is None or place <= competition.entries_count / 2)
            half = competition.entries_count is not None and place <= competition.entries_count / 2
            code = {
                ("national", True): "kms",
                ("national", False): "r1",
                ("interregional", True): "r1",
                ("interregional", False): "r2",
                ("regional", True): "r2",
                ("regional", False): "r3",
            }[(tier, medal)]
            if not (medal or half):
                continue
            current = best.get(member.fsp_id)
            candidate = (rank_order[code], code, competition.discipline_code, competition.date_end)
            if current is None or candidate[0] < current[0]:
                best[member.fsp_id] = candidate
        eligible = sorted(best)
        share = min(1.0, TARGET_RANKS / max(len(eligible), 1))
        number = 0
        for fsp_id in eligible:
            if rng.random() >= share:
                continue
            _, code, discipline, date_end = best[fsp_id]
            assigned = date_end + timedelta(days=60)
            if assigned > self.today:
                continue
            number += 1
            self._add_rank(fsp_id, code, assigned, discipline, f"DEMO-{assigned.year}-{number:04d}", None)
        for persona in PERSONAS:
            for rank in persona.ranks:
                number += 1
                self._add_rank(
                    persona_fsp_id(persona.key),
                    rank.code,
                    rank.assigned_on,
                    rank.discipline,
                    f"DEMO-{rank.assigned_on.year}-{number:04d}",
                    rank.revoked_on,
                )

    def _add_rank(
        self, fsp_id: UUID, code: str, assigned: date, discipline: str | None, order: str, revoked: date | None
    ) -> None:
        years = ref.RANK_VALIDITY_YEARS.get(code)
        self.registry.ranks.append(
            RankAssignment(
                rank_id=f"R-{fsp_id.hex[:8]}-{code}",
                fsp_id=fsp_id,
                rank_code=code,
                assigned_on=assigned,
                valid_until=_add_years(assigned, years) if years else None,
                order_number=order,
                assigned_by=ref.ASSIGNED_BY,
                discipline_code=discipline,
                basis_entry_id=None,
                revoked_on=revoked,
            )
        )


def generate(seed: int | None = None, today: date = SEED_DATE, athletes: int = RANDOM_ATHLETES) -> Registry:
    """Собрать реестр целиком в памяти (без записи в базу). Тот же сид и дата — те же идентификаторы и места."""
    gen = _Generator(get_settings().fsp_seed if seed is None else seed, today)
    gen.make_personas()
    gen.make_athletes(athletes)
    for slot in gen.build_slots():
        if not gen.build_competition(slot):
            log.debug("соревнование %s не создано: меньше %s строк", slot.competition_id, MIN_ROWS)
    gen.service_competitions()
    gen.upcoming()
    gen.ranks()
    return gen.registry


# ---------------------------------------------------------------------------------------------------------------------
# Запись в базу, сброс, шаг инициализации
# ---------------------------------------------------------------------------------------------------------------------


def persist(db: Session, registry: Registry) -> None:
    """Записать реестр в базу (порядок — по внешним ключам)."""
    db.add_all(registry.athletes)
    db.add_all(registry.competitions)
    db.flush()
    db.add_all(registry.entries)
    db.flush()
    db.add_all(registry.members)
    db.add_all(registry.ranks)
    db.flush()


def is_empty(db: Session) -> bool:
    return not db.scalar(select(func.count()).select_from(Athlete))


def reset(db: Session, seed: int | None = None) -> schemas.ResetView:
    """Вернуть реестр к состоянию сида: данные, коды, режим отказа и разрешения потока входа.

    Разрешения, созданные сидом платформы (`source = 'seed'`), сохраняются: они часть состояния сида, и без них
    привязанные демо-кандидаты при следующей синхронизации получили бы `grant_required` и были бы отвязаны.
    """
    db.execute(delete(AuthCode))
    db.execute(delete(AccessGrant).where(AccessGrant.source != "seed"))
    for grant in db.scalars(select(AccessGrant)):
        grant.revoked_at = None
    db.execute(delete(RankAssignment))
    db.execute(delete(EntryMember))
    db.execute(delete(Entry))
    db.execute(delete(Competition))
    db.execute(delete(Athlete))
    db.execute(delete(Control))
    db.flush()
    registry = generate(seed)
    persist(db, registry)
    return schemas.ResetView(
        athletes=len(registry.athletes), competitions=len(registry.competitions), entries=len(registry.entries)
    )


def seed_if_empty() -> None:
    """Шаг инициализации: заполнить демо-реестр, если он пуст (идемпотентно, `INIT_STEPS` в `app.wiring`)."""
    with session_scope() as db:
        if not is_empty(db):
            log.info("демо-реестр ФСП уже заполнен")
            return
        view = reset(db)
    log.info(
        "демо-реестр ФСП создан: спортсменов %s, соревнований %s, строк протоколов %s",
        view.athletes,
        view.competitions,
        view.entries,
    )
