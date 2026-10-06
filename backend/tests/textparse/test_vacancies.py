"""Тексты-примеры `data/vacancies/*.md`: специализация, грейд, корзины навыков, форматы и вилка (приёмка B10)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from app.modules.textparse import service

VACANCIES = Path(__file__).resolve().parents[3] / "data" / "vacancies"

#: Ожидание по каждому тексту: обязательные навыки (все названные), желательные (все названные), форматы, вилка, город.
EXPECTED: dict[str, dict[str, object]] = {
    "backend-junior": {
        "must": {"python", "sql", "databases", "git", "http", "rest_api"},
        "nice": {"fastapi", "postgresql", "pytest", "docker", "redis", "code_review", "teamwork"},
        "formats": ["hybrid"], "salary": (90_000, 130_000), "city": "Казань",
    },
    "backend-middle": {
        "must": {"python", "fastapi", "django", "postgresql", "db_indexes", "db_design", "rest_api"},
        "nice": {"http", "asyncio", "docker", "git", "kafka", "rabbitmq", "redis", "clickhouse"},
        "formats": ["hybrid", "remote"], "salary": (200_000, 280_000), "city": "Москва",
    },
    "backend-senior": {
        "must": {"python", "asyncio", "fastapi", "django", "postgresql", "db_indexes", "db_transactions"},
        "nice": {
            "system_design", "microservices", "kafka", "rabbitmq", "docker", "kubernetes", "mentoring", "clickhouse",
        },
        "formats": ["office", "remote"], "salary": (350_000, 450_000), "city": "Санкт-Петербург",
    },
    "frontend-senior": {
        "must": {"react", "javascript", "typescript", "redux", "html", "css", "css_layout", "frontend_performance"},
        "nice": {"rest_api", "git", "nextjs", "webpack", "vite", "jest", "testing_library", "code_review"},
        "formats": ["hybrid"], "salary": (250_000, 350_000), "city": "Новосибирск",
    },
    "data_ml-junior": {
        "must": {"sql", "sql_window_functions", "python", "pandas", "numpy", "statistics", "probability"},
        "nice": {
            "ab_testing", "tableau", "power_bi", "datalens", "clickhouse", "airflow", "machine_learning", "sklearn",
        },
        "formats": ["remote"], "salary": (80_000, 110_000), "city": None,
    },
}  # fmt: skip


def _load(name: str) -> tuple[dict[str, str], str]:
    raw = (VACANCIES / f"{name}.md").read_text(encoding="utf-8")
    _, header, body = raw.split("---\n", 2)
    return yaml.safe_load(header), body


def test_every_vacancy_file_has_an_expectation() -> None:
    assert {p.stem for p in VACANCIES.glob("*.md")} == set(EXPECTED)
    backend = {p.stem for p in VACANCIES.glob("backend-*.md")}
    assert backend == {"backend-junior", "backend-middle", "backend-senior"}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_vacancy_text_is_parsed_as_expected(name: str, publish: Callable[[set[tuple[str, str]]], None]) -> None:
    header, body = _load(name)
    expected = EXPECTED[name]
    # все четыре специализации доступны: предупреждение недоступности проверяется отдельно
    publish({(s, g) for s in ("backend", "frontend", "data_ml") for g in ("junior", "middle", "senior")})
    draft = service.parse_need_text(body)
    assert draft.specialization_code == header["specialization"]
    assert draft.grade_code == header["grade"]
    assert draft.title == header["title"]
    assert expected["must"] <= set(draft.must_skills)  # type: ignore[operator]
    assert expected["nice"] <= set(draft.nice_skills)  # type: ignore[operator]
    assert not set(draft.must_skills) & set(draft.nice_skills)
    assert draft.work_formats == expected["formats"]
    assert (draft.salary_from, draft.salary_to) == expected["salary"]
    assert draft.city == expected["city"]
    assert draft.warnings == [] and draft.unknown_terms == []
    assert 1 <= len(draft.must_skills) <= 8 and len(draft.nice_skills) <= 12


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_vacancy_salary_passes_platform_rules(name: str) -> None:
    from app.shared import salary

    _, body = _load(name)
    draft = service.parse_need_text(body)
    assert draft.salary_from is not None and draft.salary_to is not None
    assert salary.range_error(draft.salary_from, draft.salary_to) is None


def test_unavailable_specialization_gives_warning() -> None:
    """Стенд без теста `frontend` и `data_ml`: текст предупреждает, а не отказывает."""
    for name in ("frontend-senior", "data_ml-junior"):
        draft = service.parse_need_text(_load(name)[1])
        assert draft.warnings == ["specialization_unavailable"], name
    assert service.parse_need_text(_load("backend-middle")[1]).warnings == []


def test_available_backend_texts_have_all_three_grades() -> None:
    grades = {_load(f"backend-{g}")[0]["grade"] for g in ("junior", "middle", "senior")}
    assert grades == {"junior", "middle", "senior"}
