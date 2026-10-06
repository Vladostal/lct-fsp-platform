"""Грейды, роли, города, голосование за специализацию."""

from __future__ import annotations

import pytest

from app.modules.textparse import service


@pytest.mark.parametrize(
    ("years", "grade"),
    [(0, "junior"), (1.0, "junior"), (1.49, "junior"), (1.5, "middle"), (3.9, "middle"), (4, "senior"), (12, "senior")],
)
def test_grade_from_years_thresholds(years: float, grade: str) -> None:
    assert service.grade_from_years(years) == grade


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Junior Python Developer", ("junior", [])),
        ("Джуниор-разработчик", ("junior", [])),
        ("Стажёр-аналитик", ("junior", [])),
        ("Младший тестировщик", ("junior", [])),
        ("Мидл Java-разработчик", ("middle", [])),
        ("Middle backend", ("middle", [])),
        ("Сеньор по Go", ("senior", [])),
        ("Старший разработчик", ("senior", [])),
        ("Ведущий инженер", ("senior", [])),
        ("Team Lead", ("senior", [])),
        ("Middle/Senior Python", ("middle", ["senior"])),
        ("Junior, middle или senior", ("junior", ["middle", "senior"])),
        ("Python Developer", (None, [])),
    ],
)
def test_grade_from_text(text: str, expected: tuple[str | None, list[str]]) -> None:
    assert service.grade_from_text(text) == expected


def test_find_roles_by_lemmas() -> None:
    assert service.find_roles("Ищем Python-разработчика и тимлида") == ["backend_developer", "team_lead"]
    assert service.find_roles("Требуется аналитик данных") == ["data_scientist"]
    assert service.find_roles("Frontend-разработчики, фронтендеры, QA-инженер") == [
        "frontend_developer", "qa_engineer",
    ]  # fmt: skip
    assert service.find_roles("Опытный кулинар") == []


def test_vote_specialization_weights() -> None:
    # роль в заголовке — 3 голоса, навыки — 1.0 за основную специализацию и 0.5 за дополнительную
    assert service.vote_specialization(["backend_developer"], [], []) == ("backend", 1.0)
    spec, margin = service.vote_specialization([], [], ["python", "fastapi", "react"])
    assert spec == "backend" and 0.2 <= margin <= 1.0
    spec, _ = service.vote_specialization(["frontend_developer"], ["backend_developer"], ["python"])
    assert spec == "frontend"


def test_vote_specialization_requires_margin() -> None:
    # frontend 1 против backend 1 — ничья, запас 0
    assert service.vote_specialization([], [], ["react", "fastapi"]) == (None, 0.0)
    assert service.vote_specialization([], [], []) == (None, 0.0)
    assert service.vote_specialization([], [], ["teamwork", "git"]) == (None, 0.0)  # общие навыки голосов не дают


def test_vote_specialization_does_not_exclude_unavailable_specializations() -> None:
    """Арх. 6.14: специализация без теста распознаётся, предупреждение ставит `parse_need_text`."""
    assert service.vote_specialization(["data_scientist"], [], [])[0] == "data_ml"
    assert service.vote_specialization(["devops_engineer"], [], [])[0] == "devops"


@pytest.mark.parametrize(
    ("text", "city"),
    [
        ("Офис в Москве", "Москва"),
        ("работа в Нижнем Новгороде", "Нижний Новгород"),
        ("г. Санкт-Петербург, гибрид", "Санкт-Петербург"),
        ("Локация: Питер", "Санкт-Петербург"),
        ("проживает в Казани", "Казань"),
        ("Город: Вологда", "Вологда"),
        ("Ростов-на-Дону", "Ростов-на-Дону"),
        ("Полностью удалённо из любой точки", None),
        ("Видное место в рейтинге", None),
    ],
)
def test_find_city(text: str, city: str | None) -> None:
    assert service.find_city(text) == city


def test_find_city_prefers_marker_over_first_mention() -> None:
    assert service.find_city("Офисы в Москве и Казани. Город: Казань") == "Казань"
