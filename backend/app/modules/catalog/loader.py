"""Загрузка справочников из YAML в память (Арх. 8.1, 15.1 № 20).

Справочники в базе не хранятся: файлы `data/*.yaml` и `data/cities.txt` читаются один раз при первом обращении,
проверяются и становятся неизменяемыми. Нарушение любого правила — `CatalogDataError` при импорте
`catalog.service`: приложение не стартует с битым справочником, а не отвечает странно потом.

Правила (приложение B, §1.3): код навыка — `[a-z0-9_]{2,40}`; алиас уникален во всём справочнике; `implies` —
граф без циклов глубиной не больше 3; транзитивное замыкание считается здесь.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.modules.catalog.dto import CityEntry, RoleEntry, SkillEntry
from app.shared.schemas import Ref

DATA_DIR = Path(__file__).parent / "data"

SKILL_KINDS = frozenset({"language", "framework", "database", "tool", "platform", "concept", "practice", "soft"})
MAX_IMPLIES_DEPTH = 3
_CODE_RE = re.compile(r"^[a-z0-9_]{2,40}$")


class CatalogDataError(ValueError):
    """Файл справочника нарушает правила."""


def normalize_alias(text: str) -> str:
    """Нормальный вид алиаса и текста: NFKC, нижний регистр, `ё` → `е`, пробелы схлопнуты."""
    text = unicodedata.normalize("NFKC", text).lower().replace("ё", "е")
    return " ".join(text.split())


@dataclass(frozen=True)
class SpecializationRow:
    code: str
    title: str
    title_short: str
    direction_code: str


@dataclass(frozen=True)
class GradeRow:
    code: str
    title: str
    order: int
    description: str


@dataclass(frozen=True)
class CatalogData:
    """Всё, что загружено из файлов."""

    directions: tuple[Ref, ...]
    specializations: tuple[SpecializationRow, ...]
    grades: tuple[GradeRow, ...]
    skills: tuple[SkillEntry, ...]
    roles: tuple[RoleEntry, ...]
    cities: tuple[CityEntry, ...]
    #: Замыкание `implies` без самого навыка: `fastapi` → `{python}`.
    closure: dict[str, frozenset[str]]
    #: sha256 файла навыков, первые 8 знаков (`SKILLS_VERSION`).
    skills_version: str


def _read_yaml(name: str) -> list[dict[str, Any]]:
    data = yaml.safe_load((DATA_DIR / name).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise CatalogDataError(f"{name}: ожидается список записей")
    return data


def _strings(raw: Any, where: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(item, str) and item.strip() for item in raw):
        raise CatalogDataError(f"{where}: ожидается список непустых строк")
    return tuple(raw)


def _implies_closure(skills: dict[str, SkillEntry]) -> dict[str, frozenset[str]]:
    """Замыкание `implies`; проверяет ссылки, циклы и глубину."""
    closure: dict[str, frozenset[str]] = {}
    depth: dict[str, int] = {}
    visiting: list[str] = []

    def visit(code: str) -> None:
        if code in closure:
            return
        if code in visiting:
            raise CatalogDataError(f"implies: цикл {' → '.join([*visiting[visiting.index(code) :], code])}")
        visiting.append(code)
        reached: set[str] = set()
        level = 0
        for parent in skills[code].implies:
            if parent not in skills:
                raise CatalogDataError(f"{code}: implies ссылается на неизвестный навык «{parent}»")
            if parent == code:
                raise CatalogDataError(f"{code}: навык не может подразумевать сам себя")
            visit(parent)
            reached.add(parent)
            reached |= closure[parent]
            level = max(level, depth[parent] + 1)
        visiting.pop()
        closure[code] = frozenset(reached)
        depth[code] = level
        if level > MAX_IMPLIES_DEPTH:
            raise CatalogDataError(f"{code}: глубина implies {level} больше {MAX_IMPLIES_DEPTH}")

    for code in skills:
        visit(code)
    return closure


def _load_skills(spec_codes: set[str]) -> tuple[tuple[SkillEntry, ...], str]:
    raw_bytes = (DATA_DIR / "skills.yaml").read_bytes()
    entries: dict[str, SkillEntry] = {}
    owner: dict[str, str] = {}
    case_owner: dict[str, str] = {}
    for row in _read_yaml("skills.yaml"):
        code = row.get("code")
        if not isinstance(code, str) or not _CODE_RE.fullmatch(code):
            raise CatalogDataError(f"навык: недопустимый код {code!r}")
        if code in entries:
            raise CatalogDataError(f"навык {code} описан дважды")
        kind = row.get("kind")
        if kind not in SKILL_KINDS:
            raise CatalogDataError(f"{code}: недопустимый kind {kind!r}")
        title = row.get("title")
        if not isinstance(title, str) or not title:
            raise CatalogDataError(f"{code}: нет названия")
        specs = _strings(row.get("specializations"), f"{code}.specializations")
        unknown_specs = set(specs) - spec_codes
        if unknown_specs:
            raise CatalogDataError(f"{code}: неизвестные специализации {sorted(unknown_specs)}")
        aliases: list[str] = []
        for alias in _strings(row.get("aliases"), f"{code}.aliases"):
            key = normalize_alias(alias)
            if key in owner and owner[key] != code:
                raise CatalogDataError(f"алиас «{key}» у навыков {owner[key]} и {code}")
            owner[key] = code
            if key not in aliases:  # «вёрстка» и «верстка» после `ё → е` — один алиас
                aliases.append(key)
        case_aliases = _strings(row.get("case_aliases"), f"{code}.case_aliases")
        for alias in case_aliases:
            if alias in case_owner:
                raise CatalogDataError(f"алиас с регистром «{alias}» у навыков {case_owner[alias]} и {code}")
            case_owner[alias] = code
        entries[code] = SkillEntry(
            code=code,
            title=title,
            kind=kind,
            specializations=specs,
            aliases=tuple(aliases),
            case_aliases=case_aliases,
            implies=_strings(row.get("implies"), f"{code}.implies"),
        )
    for alias, code in case_owner.items():
        if normalize_alias(alias) in owner:
            raise CatalogDataError(f"алиас с регистром «{alias}» ({code}) совпадает с обычным алиасом")
    _implies_closure(entries)
    return tuple(entries.values()), hashlib.sha256(raw_bytes).hexdigest()[:8]


def _load_roles(spec_codes: set[str]) -> tuple[RoleEntry, ...]:
    roles: dict[str, RoleEntry] = {}
    owner: dict[str, str] = {}
    for row in _read_yaml("roles.yaml"):
        code = row["code"]
        if code in roles:
            raise CatalogDataError(f"роль {code} описана дважды")
        spec = row.get("specialization")
        if spec is not None and spec not in spec_codes:
            raise CatalogDataError(f"роль {code}: неизвестная специализация {spec!r}")
        aliases = []
        for alias in _strings(row.get("aliases"), f"{code}.aliases"):
            key = normalize_alias(alias)
            if key in owner and owner[key] != code:
                raise CatalogDataError(f"алиас роли «{key}» у {owner[key]} и {code}")
            owner[key] = code
            if key not in aliases:
                aliases.append(key)
        roles[code] = RoleEntry(code=code, title=row["title"], specialization=spec, aliases=tuple(aliases))
    return tuple(roles.values())


def _load_cities() -> tuple[CityEntry, ...]:
    cities: dict[str, CityEntry] = {}
    for line in (DATA_DIR / "cities.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, tail = line.partition("|")
        name = name.strip()
        if name in cities:
            raise CatalogDataError(f"город «{name}» указан дважды")
        aliases = tuple(normalize_alias(a) for a in tail.split(",") if a.strip())
        cities[name] = CityEntry(name=name, aliases=aliases)
    return tuple(cities.values())


@lru_cache(maxsize=1)
def load() -> CatalogData:
    """Прочитать и проверить все файлы справочников (один раз за процесс)."""
    directions = tuple(Ref(code=row["code"], title=row["title"]) for row in _read_yaml("directions.yaml"))
    direction_codes = {d.code for d in directions}
    specializations = tuple(
        SpecializationRow(
            code=row["code"], title=row["title"], title_short=row["title_short"], direction_code=row["direction_code"]
        )
        for row in _read_yaml("specializations.yaml")
    )
    for spec in specializations:
        if spec.direction_code not in direction_codes:
            raise CatalogDataError(f"специализация {spec.code}: неизвестное направление {spec.direction_code}")
    grades = tuple(
        sorted(
            (
                GradeRow(
                    code=row["code"],
                    title=row["title"],
                    order=int(row["order"]),
                    description=row.get("description", ""),
                )
                for row in _read_yaml("grades.yaml")
            ),
            key=lambda g: g.order,
        )
    )
    if len({g.order for g in grades}) != len(grades):
        raise CatalogDataError("грейды: повторяется order")
    spec_codes = {s.code for s in specializations}
    skills, version = _load_skills(spec_codes)
    closure = _implies_closure({s.code: s for s in skills})
    return CatalogData(
        directions=directions,
        specializations=specializations,
        grades=grades,
        skills=skills,
        roles=_load_roles(spec_codes),
        cities=_load_cities(),
        closure=closure,
        skills_version=version,
    )
