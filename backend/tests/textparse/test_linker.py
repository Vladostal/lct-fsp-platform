"""`SkillLinker`: нормализация, окна, регистр, леммы кириллицы, опечатки, неизвестные термины."""

from __future__ import annotations

from itertools import pairwise

import pytest

from app.modules.textparse import service


def codes(text: str, **kwargs: set[int] | None) -> list[str]:
    mentions, _ = service.link_skills(text, **kwargs)
    return [m.skill_code for m in mentions]


def test_special_names_in_enumeration() -> None:
    """`C++`, `C#`, `Node.js`, `.NET`, `Go` в перечислении распознаются."""
    mentions, unknown = service.link_skills("Знаю C++, C#, Node.js, .NET, Go, Python")
    assert [m.skill_code for m in mentions] == ["cpp", "csharp", "nodejs", "dotnet", "go", "python"]
    assert [m.surface for m in mentions] == ["C++", "C#", "Node.js", ".NET", "Go", "Python"]
    assert unknown == []


def test_case_sensitive_aliases_only_in_enumeration() -> None:
    assert codes("Let's Go home and read about R") == []
    assert codes("Навыки: Go", enumeration_lines={0}) == ["go"]
    assert codes("go go go, Python, Java") == ["python", "java"]
    assert codes("Python, Java, Go") == ["python", "java", "go"]  # строка с запятой и двумя найденными навыками
    assert codes("язык C и R", enumeration_lines={0}) == ["c_lang", "r_lang"]


def test_offsets_point_to_original_text() -> None:
    text = "Опыт:​  Pyth​on,\r\n  PostgreSQL — и ёлочка, Kubernetes"
    mentions, _ = service.link_skills(text)
    for mention in mentions:
        assert text[mention.start : mention.end] == mention.surface
    assert [m.skill_code for m in mentions] == ["python", "postgresql", "kubernetes"]
    assert mentions[0].surface == "Pyth​on"


def test_longest_match_wins_and_mentions_do_not_overlap() -> None:
    mentions, _ = service.link_skills("Spring Boot, Node.js, REST API, React Native")
    assert [m.skill_code for m in mentions] == ["spring", "nodejs", "rest_api", "react_native"]
    spans = [(m.start, m.end) for m in mentions]
    assert all(a[1] <= b[0] for a, b in pairwise(spans))


def test_window_is_broken_by_punctuation() -> None:
    assert codes("машинное обучение") == ["machine_learning"]
    assert codes("машинное, обучение") == []
    assert codes("машинное\nобучение") == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("работал с базами данных", ["databases"]),
        ("глубокое знание структур данных и алгоритмов", ["data_structures", "algorithms"]),
        ("опыт построения моделей машинного обучения", ["machine_learning"]),
        ("умею использовать оконные функции", ["sql_window_functions"]),
        ("проектирование схем и составные индексы", ["db_design", "db_indexes"]),
        ("основы теории вероятностей", ["probability"]),
        ("на Python-разработчика", ["python"]),
        ("написание юнит-тестов", ["testing"]),
        ("многопоточностью занимался", ["multithreading"]),
    ],
)
def test_cyrillic_lemmas(text: str, expected: list[str]) -> None:
    assert codes(text) == expected


def test_lemma_method_is_reported() -> None:
    mentions, _ = service.link_skills("работа с базами данных")
    assert [(m.skill_code, m.method) for m in mentions] == [("databases", "lemma")]


def test_typo_threshold_is_90() -> None:
    mentions, _ = service.link_skills("Dockr, Kubernets, Postgresq")
    assert [(m.skill_code, m.method) for m in mentions] == [
        ("docker", "fuzzy"), ("kubernetes", "fuzzy"), ("postgresql", "fuzzy"),
    ]  # fmt: skip
    # ratio('redus', 'redux') = 80 < 90; короткие токены (< 5) не сравниваются вовсе
    assert codes("Redus, Dokr") == []


def test_typo_match_is_not_triggered_by_ordinary_words() -> None:
    assert codes("Please remote design experience, monitoring and delivery") == []
    assert codes("Javascrip") == ["javascript"]


def test_compound_tokens_are_split() -> None:
    assert codes("HTML/CSS, C++/C#, Python+Django") == ["html", "css", "cpp", "csharp", "python", "django"]
    assert codes("CI/CD") == ["ci_cd"]  # целиком — алиас, на части не делится


def test_unknown_terms_in_enumeration_only() -> None:
    _, unknown = service.link_skills("Python, FastAPI, Tarantool, Neo4j, TypeDB, junior, ivan@example.com")
    assert unknown == ["Tarantool", "Neo4j", "TypeDB"]
    _, unknown = service.link_skills("We use Tarantool at work")  # не перечисление
    assert unknown == []
    _, unknown = service.link_skills("Tarantool", enumeration_lines={0})
    assert unknown == ["Tarantool"]


def test_unknown_terms_are_limited_and_unique() -> None:
    line = ", ".join(f"Tool{i}x" for i in range(30)) + ", Tool1x"
    _, unknown = service.link_skills(line, enumeration_lines={0})
    assert len(unknown) == 10 and len(set(unknown)) == 10


def test_unknown_terms_skip_urls_and_company_names() -> None:
    _, unknown = service.link_skills("Python, Git, https://github.com/ivan/repo, Google, Yandex, Sber")
    assert unknown == []


def test_empty_and_symbols() -> None:
    assert service.link_skills("") == ([], [])
    assert service.link_skills("!!! ... ---") == ([], [])


def test_linker_is_deterministic() -> None:
    text = "Python, Kafka или RabbitMQ, Redis, Tarantool; Dockr"
    assert service.link_skills(text) == service.link_skills(text)
