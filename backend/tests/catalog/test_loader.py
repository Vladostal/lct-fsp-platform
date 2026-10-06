"""Справочники из файлов: правила приложения B, §1.3 и покрытие кодов, которые нужны другим модулям."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from app.modules.catalog import loader, service
from app.modules.catalog.loader import MAX_IMPLIES_DEPTH, SKILL_KINDS, CatalogDataError, normalize_alias
from app.modules.textparse import lexicon

DATA = Path(loader.DATA_DIR)

#: Таблица Арх. 5.4: все `direct` и `related` (SKILL_GROUP_MAP).
SKILL_GROUP_CODES = [
    "code_reading",
    "debugging",
    "algorithms",
    "complexity",
    "graphs",
    "dynamic_programming",
    "data_structures",
    "hashing",
    "trees",
    "sql",
    "sql_joins",
    "sql_aggregation",
    "sql_window_functions",
    "postgresql",
    "mysql",
    "clickhouse",
    "oracle",
    "mssql",
    "orm",
    "http",
    "rest_api",
    "web_caching",
    "web_security_basics",
    "fastapi",
    "django",
    "flask",
    "spring",
    "express",
    "graphql",
    "openapi",
    "git",
    "gitlab",
    "github",
    "code_review",
    "python",
    "asyncio",
    "javascript",
    "async_js",
    "typescript",
    "nodejs",
    "databases",
    "db_indexes",
    "db_transactions",
    "db_design",
    "mongodb",
    "redis",
    "concurrency",
    "async",
    "system_design",
    "multithreading",
    "kafka",
    "rabbitmq",
    "microservices",
    "highload",
    "css",
    "css_layout",
    "html",
    "sass",
    "tailwind",
    "dom",
    "react",
    "frontend_performance",
    "redux",
    "vue",
    "nextjs",
    "angular",
    "statistics",
    "probability",
    "ab_testing",
    "product_analytics",
    "ml_metrics",
    "ml_validation",
    "machine_learning",
    "sklearn",
    "catboost",
    "pytorch",
    "pandas",
    "data_wrangling",
    "numpy",
    "spark",
    "etl",
]

#: `skill_tags` семейств заданий (приложение A, §3).
FAMILY_TAGS = [
    "code_reading",
    "data_structures",
    "algorithms",
    "debugging",
    "complexity",
    "graphs",
    "dynamic_programming",
    "hashing",
    "trees",
    "sql",
    "sql_aggregation",
    "sql_joins",
    "sql_window_functions",
    "http",
    "rest_api",
    "web_caching",
    "web_security_basics",
    "git",
    "python",
    "javascript",
    "async_js",
    "databases",
    "db_indexes",
    "db_design",
    "db_transactions",
    "concurrency",
    "async",
    "system_design",
    "css",
    "css_layout",
    "dom",
    "react",
    "frontend_performance",
    "statistics",
    "probability",
    "ab_testing",
    "ml_metrics",
    "ml_validation",
    "pandas",
    "data_wrangling",
]

#: Коды, которые подтверждает ФСП (Арх. 7.6).
FSP_CODES = [
    "algorithms",
    "data_structures",
    "teamwork",
    "mvp_delivery",
    "public_speaking",
    "infosec",
    "vulnerability_analysis",
    "uav_programming",
    "robotics",
    "embedded",
    "leadership",
    "mentoring",
]


def test_skill_codes_cover_architecture_tables() -> None:
    missing = {code for code in [*SKILL_GROUP_CODES, *FAMILY_TAGS, *FSP_CODES] if not service.is_skill(code)}
    assert not missing


def test_assessment_group_map_is_covered() -> None:
    """Карта «навык → группа» живёт в `assessment`; каждый её код должен быть в каталоге."""
    groups = pytest.importorskip("app.modules.assessment.groups")
    codes = {c for skill_map in groups.SKILL_GROUP_MAP.values() for c in (*skill_map.direct, *skill_map.related)}
    assert not {c for c in codes if not service.is_skill(c)}


def test_catalog_size_and_soft_skills() -> None:
    skills = service.skill_entries()
    assert len(skills) >= 120
    assert sum(skill.kind == "soft" for skill in skills) >= 18
    assert {skill.kind for skill in skills} <= SKILL_KINDS


def test_skill_code_format_and_unique() -> None:
    codes = [skill.code for skill in service.skill_entries()]
    assert len(codes) == len(set(codes))
    assert all(re.fullmatch(r"[a-z0-9_]{2,40}", code) for code in codes)


def test_aliases_are_unique_across_catalog() -> None:
    owner: dict[str, str] = {}
    for skill in service.skill_entries():
        for alias in skill.aliases:
            assert alias == normalize_alias(alias)
            assert owner.setdefault(alias, skill.code) == skill.code, f"алиас «{alias}»: {owner[alias]} и {skill.code}"
    for skill in service.skill_entries():
        for alias in skill.case_aliases:
            assert normalize_alias(alias) not in owner, f"алиас с регистром «{alias}» совпал с обычным"


def test_aliases_are_unique_after_lemmatization() -> None:
    """Две разные формы одного слова не должны вести к разным навыкам: иначе результат зависит от порядка."""
    owner: dict[str, str] = {}
    for skill in service.skill_entries():
        for alias in skill.aliases:
            if not lexicon.has_cyrillic(alias):
                continue
            key = lexicon.lemma_key(alias.split())
            assert owner.setdefault(key, skill.code) == skill.code, f"лемма «{key}»: {owner[key]} и {skill.code}"


def test_alias_length_fits_linker_window() -> None:
    for skill in service.skill_entries():
        assert all(len(alias.split()) <= 4 for alias in (*skill.aliases, *skill.case_aliases)), skill.code


def test_implies_is_acyclic_with_bounded_depth() -> None:
    skills = {skill.code: skill for skill in service.skill_entries()}

    def depth(code: str, path: tuple[str, ...] = ()) -> int:
        assert code not in path, f"цикл через {code}"
        return max((depth(parent, (*path, code)) + 1 for parent in skills[code].implies), default=0)

    assert max(depth(code) for code in skills) <= MAX_IMPLIES_DEPTH
    assert all(parent in skills for skill in skills.values() for parent in skill.implies)


def test_implies_closure_is_transitive_and_excludes_self() -> None:
    assert service.implies_closure("fastapi") == {"python"}
    assert service.implies_closure("nextjs") == {"react", "javascript"}
    assert service.implies_closure("postgresql") == {"sql"}
    assert service.implies_closure("python") == frozenset()
    assert service.implies_closure("no_such_skill") == frozenset()
    for skill in service.skill_entries():
        assert skill.code not in service.implies_closure(skill.code)


def test_specialization_and_grade_tables() -> None:
    catalog = service.get_catalog()
    assert [s.code for s in catalog.specializations] == [
        "backend", "frontend", "fullstack", "data_ml", "mobile", "analyst", "qa", "devops", "infosec", "embedded",
    ]  # fmt: skip
    assert {d.code for d in catalog.directions} == {"development", "data", "quality_infra", "security_embedded"}
    assert {s.direction_code for s in catalog.specializations} <= {d.code for d in catalog.directions}
    assert [(g.code, g.order) for g in catalog.grades] == [("junior", 1), ("middle", 2), ("senior", 3)]
    assert {s.title_short for s in catalog.specializations} >= {"Backend", "Frontend", "Fullstack", "Data/ML"}


def test_roles_and_cities() -> None:
    roles = service.role_entries()
    assert len(roles) >= 18
    assert {"backend_developer", "team_lead", "intern", "architect"} <= {r.code for r in roles}
    assert {r.specialization for r in roles if r.specialization} <= {
        s.code for s in service.get_catalog().specializations
    }
    cities = {c.name for c in service.city_entries()}
    assert len(cities) >= 150 and {"Москва", "Санкт-Петербург", "Казань"} <= cities


def test_skills_version_is_hash_of_file() -> None:
    digest = hashlib.sha256((DATA / "skills.yaml").read_bytes()).hexdigest()[:8]
    assert digest == service.SKILLS_VERSION


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("- {code: a_b, title: A, kind: tool, implies: [a_b]}", "сам себя"),
        (
            "- {code: aa, title: A, kind: tool, implies: [bb]}\n- {code: bb, title: B, kind: tool, implies: [aa]}",
            "цикл",
        ),
        ("- {code: aa, title: A, kind: tool, aliases: [x]}\n- {code: bb, title: B, kind: tool, aliases: [X]}", "алиас"),
        ("- {code: aa, title: A, kind: wizard}", "kind"),
        ("- {code: A, title: A, kind: tool}", "код"),
        (
            "- {code: aa, title: A, kind: tool, implies: [bb]}\n- {code: bb, title: B, kind: tool, implies: [cc]}\n"
            "- {code: cc, title: C, kind: tool, implies: [dd]}\n- {code: dd, title: D, kind: tool, implies: [ee]}\n"
            "- {code: ee, title: E, kind: tool}",
            "глубина",
        ),
    ],
)
def test_loader_rejects_bad_skill_files(
    content: str, message: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Загрузчик не пропускает дубли алиасов, циклы, слишком глубокий `implies` и неверные коды."""
    for name in ("directions.yaml", "specializations.yaml", "grades.yaml", "roles.yaml", "cities.txt"):
        (tmp_path / name).write_bytes((DATA / name).read_bytes())
    (tmp_path / "skills.yaml").write_text(content, encoding="utf-8")
    monkeypatch.setattr(loader, "DATA_DIR", tmp_path)
    loader.load.cache_clear()
    try:
        with pytest.raises(CatalogDataError, match=message):
            loader.load()
    finally:
        loader.load.cache_clear()
