"""`parse_need_text`: разделы, корзины навыков, специализация, грейд, форматы, вилка, предупреждения."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy.orm import Session

from app.core import db as core_db
from app.modules.textparse import service


def test_sections_and_buckets() -> None:
    draft = service.parse_need_text(
        """Backend-разработчик
Требования
- Python
- PostgreSQL, Docker
Будет плюсом
- Redis
- Kafka
"""
    )
    assert draft.must_skills == ["python", "postgresql", "docker"]
    assert draft.nice_skills == ["redis", "kafka"]
    assert draft.confidence["must_skills"] == "high"


def test_nice_marker_in_sentence_moves_skills_to_nice() -> None:
    draft = service.parse_need_text(
        "Python-разработчик\nТребования: Python; Django; знание Kafka будет плюсом; Redis приветствуется."
    )
    assert draft.must_skills == ["python", "django"]
    assert draft.nice_skills == ["kafka", "redis"]


def test_skill_in_both_buckets_stays_in_must() -> None:
    draft = service.parse_need_text("Разработчик\nТребования: Python, Git\nБудет плюсом: Git, Docker")
    assert draft.must_skills == ["python", "git"]
    assert draft.nice_skills == ["docker"]


def test_soft_skills_always_nice() -> None:
    draft = service.parse_need_text("Разработчик\nТребования: Python, умение работать в команде, коммуникабельность")
    assert draft.must_skills == ["python"]
    assert draft.nice_skills == ["teamwork", "communication"]


def test_other_sections_are_nice_and_title_is_must() -> None:
    draft = service.parse_need_text(
        "Java-разработчик\nО команде\nМы пишем на Kotlin и используем Docker.\n"
        "Задачи\nПоддерживать сервисы на Spring Boot"
    )
    assert "java" in draft.must_skills
    assert set(draft.nice_skills) == {"kotlin", "docker", "spring"}


def test_no_required_section_moves_first_three_to_must() -> None:
    draft = service.parse_need_text(
        "Мы ищем разработчика. Стек: Python, FastAPI, PostgreSQL, Redis, Docker, Kafka. Опыт с Python приветствуется."
    )
    assert len(draft.must_skills) == 3 and draft.must_skills[0] == "python"
    assert draft.confidence["must_skills"] == "low"
    assert set(draft.must_skills) | set(draft.nice_skills) >= {"python", "fastapi", "postgresql"}


def test_overflow_and_limits() -> None:
    must = ["python", "django", "fastapi", "flask", "postgresql", "mysql", "redis", "kafka", "rabbitmq", "docker"]
    nice = [
        "git", "linux", "nginx", "celery", "sqlalchemy", "pytest", "graphql", "grpc", "mongodb", "aws", "terraform",
        "ansible", "jira", "postman",
    ]  # fmt: skip
    draft = service.parse_need_text("Разработчик\nТребования: " + ", ".join(must) + "\nЖелательно: " + ", ".join(nice))
    assert draft.must_skills == must[:8]
    assert len(draft.nice_skills) == 12
    assert draft.nice_skills[:2] == ["rabbitmq", "docker"]  # лишнее из must идёт в начало nice
    assert not set(draft.must_skills) & set(draft.nice_skills)


def test_no_skills_warning() -> None:
    draft = service.parse_need_text("Менеджер по продажам\nОбщительность не нужна")
    assert draft.must_skills == [] and "no_skills" in draft.warnings
    assert "no_skills" in service.parse_need_text("").warnings


def test_specialization_from_title_role_and_skills() -> None:
    draft = service.parse_need_text("Frontend-разработчик\nТребования: React, TypeScript, CSS")
    assert draft.specialization_code == "frontend"
    assert draft.confidence["specialization_code"] in ("high", "medium")


def test_ambiguous_specialization_gives_warning_and_none() -> None:
    draft = service.parse_need_text("Разработчик\nТребования: React, FastAPI")
    assert draft.specialization_code is None
    assert "spec_ambiguous" in draft.warnings
    assert "spec_ambiguous" not in service.parse_need_text("Менеджер\nОпыт продаж").warnings


def test_unavailable_specialization_warns(publish: Callable[[set[tuple[str, str]]], None]) -> None:
    text = "Data Scientist\nТребования: Python, pandas, sklearn, статистика"
    draft = service.parse_need_text(text)
    assert draft.specialization_code == "data_ml" and "specialization_unavailable" in draft.warnings
    publish({("data_ml", "middle")})
    assert "specialization_unavailable" not in service.parse_need_text("Middle " + text).warnings
    # специализация доступна, а пара — нет
    assert "specialization_unavailable" in service.parse_need_text("Junior " + text).warnings


def test_grade_priority_title_then_text_then_years() -> None:
    assert service.parse_need_text("Senior Python Developer\nТребования: Python").grade_code == "senior"
    body_only = service.parse_need_text("Python Developer\nИщем middle-разработчика.\nТребования: Python")
    assert (body_only.grade_code, body_only.confidence["grade_code"]) == ("middle", "medium")
    by_years = service.parse_need_text("Python Developer\nТребования: Python, опыт работы от 5 лет")
    assert (by_years.grade_code, by_years.confidence["grade_code"]) == ("senior", "low")
    assert service.parse_need_text("Python Developer\nТребования: Python").grade_code is None


@pytest.mark.parametrize(
    ("experience", "grade"),
    [
        ("опыт работы 1 год", "junior"),
        ("опыт от 1,4 года", "junior"),
        ("опыт от 1.5 лет", "middle"),
        ("коммерческий опыт разработки на Python от 2 лет", "middle"),
        ("опыт 3+ года", "middle"),
        ("стаж от 4 лет", "senior"),
        ("опыт 1-2 года", "junior"),
        ("опыт работы от 7 лет", "senior"),
    ],
)
def test_grade_by_years_thresholds_are_1_5_and_4(experience: str, grade: str) -> None:
    draft = service.parse_need_text(f"Разработчик\nТребования: Python; {experience}")
    assert draft.grade_code == grade


def test_years_outside_experience_context_are_ignored() -> None:
    draft = service.parse_need_text("Разработчик\nО компании: мы на рынке 10 лет.\nТребования: Python")
    assert draft.grade_code is None


def test_several_grades_give_youngest_and_alternatives() -> None:
    draft = service.parse_need_text("Middle/Senior Python-разработчик\nТребования: Python")
    assert (draft.grade_code, draft.grade_alternatives) == ("middle", ["senior"])


def test_mentoring_junior_in_body_is_not_the_vacancy_grade() -> None:
    draft = service.parse_need_text(
        "Python-разработчик\nТребования: Python; готовность наставлять джунов; опыт от 5 лет"
    )
    assert draft.grade_code == "senior"


@pytest.mark.parametrize(
    ("text", "formats"),
    [
        ("Удалённая работа", ["remote"]),
        ("Формат: гибрид, 2 дня в офисе", ["hybrid"]),
        ("Работа в офисе или удалённо", ["office", "remote"]),
        ("Remote, офис в Москве", ["office", "remote"]),
        ("Дистанционный формат", ["remote"]),
        ("Нет данных о формате", []),
    ],
)
def test_work_formats(text: str, formats: list[str]) -> None:
    assert service.parse_need_text(f"Разработчик\nУсловия\n{text}").work_formats == formats


@pytest.mark.parametrize(
    ("text", "bounds", "warnings"),
    [
        ("Зарплата от 150 000 до 220 000 ₽", (150_000, 220_000), []),
        ("Вилка: 150000-220000 руб. на руки", (150_000, 220_000), []),
        ("Оклад 150-220 тыс. руб.", (150_000, 220_000), []),
        ("з/п от 150к до 200к", (150_000, 200_000), []),
        ("Доход 1,2 млн - 1,5 млн рублей", (1_200_000, 1_500_000), []),
        ("Зарплата от 150 000 рублей", (150_000, None), ["salary_single_bound"]),
        ("Зарплата до 300 тыс", (None, 300_000), ["salary_single_bound"]),
        ("Зарплата от 3000 до 4000 $", (None, None), ["salary_currency"]),
        ("Оплата 5k USD", (None, None), ["salary_currency"]),
        ("Зарплата 300 € в день", (None, None), ["salary_currency"]),
        ("Зарплата по результатам собеседования", (None, None), []),
        ("Опыт от 2 до 3 лет", (None, None), []),
    ],
)
def test_salary_in_rubles(text: str, bounds: tuple[int | None, int | None], warnings: list[str]) -> None:
    draft = service.parse_need_text(f"Разработчик\nУсловия\n{text}")
    assert (draft.salary_from, draft.salary_to) == bounds
    assert [w for w in draft.warnings if w.startswith("salary")] == warnings


def test_ruble_wins_over_foreign_mark_in_same_sentence() -> None:
    draft = service.parse_need_text("Разработчик\nЗарплата от 200 000 до 300 000 рублей (около $3000)")
    assert (draft.salary_from, draft.salary_to) == (200_000, 300_000)


def test_title_rules() -> None:
    assert service.parse_need_text("Python-разработчик\nТребования: Python").title == "Python-разработчик"
    assert service.parse_need_text("Требования: Python").title is None
    assert service.parse_need_text("Требования\nPython").title is None
    assert service.parse_need_text("x" * 101 + "\nТребования: Python").title is None


def test_team_description_prefers_about_then_tasks() -> None:
    draft = service.parse_need_text("Разработчик\nО команде\nМы делаем платёжный сервис.\nЗадачи\nПисать код")
    assert draft.team_description == "Мы делаем платёжный сервис."
    draft = service.parse_need_text("Разработчик\nЗадачи\nПисать код")
    assert draft.team_description == "Писать код"


def test_team_description_is_cut_by_sentence_within_1000_chars() -> None:
    sentence = "Мы пишем сервисы для логистики. "
    draft = service.parse_need_text("Разработчик\nО команде\n" + sentence * 60)
    assert draft.team_description is not None
    assert len(draft.team_description) <= 1000 and draft.team_description.endswith(".")


def test_city_from_text() -> None:
    assert service.parse_need_text("Разработчик\nУсловия: офис в Новосибирске").city == "Новосибирск"


def test_unknown_terms_are_returned_for_logging() -> None:
    draft = service.parse_need_text("Разработчик\nТребования: Python, FastAPI, Tarantool, Neo4j")
    assert draft.unknown_terms == ["Tarantool", "Neo4j"]
    assert draft.must_skills == ["python", "fastapi"]


def test_parser_metadata() -> None:
    draft = service.parse_need_text("Разработчик\nТребования: Python")
    assert (draft.parser, draft.parser_version) == ("rules", "need-rules-1")


def test_parse_is_deterministic_and_never_touches_the_database(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("parse_need_text обратился к базе")

    for name in ("execute", "scalars", "scalar", "get", "add", "flush", "commit", "connection"):
        monkeypatch.setattr(Session, name, forbidden)
    monkeypatch.setattr(core_db, "new_session", forbidden)
    monkeypatch.setattr(core_db, "get_engine", forbidden)
    text = (
        "Senior Python-разработчик\nТребования: Python, FastAPI, Tarantool\nБудет плюсом: Kafka\nЗарплата от 300 000 ₽"
    )
    first = service.parse_need_text(text)
    assert [service.parse_need_text(text) for _ in range(3)] == [first] * 3
