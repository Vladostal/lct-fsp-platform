"""Словари разбора текста: леммы, стоп-слова, грейды, роли, города, голосование за специализацию.

Всё здесь — чистые функции и неизменяемые таблицы; в базу ничего не пишется (Арх. 2.5). Справочники ролей и
городов берутся у `catalog.service` и индексируются при первом обращении.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Collection
from functools import lru_cache

import pymorphy3

from app.modules.catalog import service as catalog

# ---------------------------------------------------------------------------------------------------------------------
# Леммы
# ---------------------------------------------------------------------------------------------------------------------

_CYRILLIC_RE = re.compile(r"[а-я]")


def has_cyrillic(text: str) -> bool:
    return _CYRILLIC_RE.search(text) is not None


@lru_cache(maxsize=1)
def _morph() -> pymorphy3.MorphAnalyzer:
    return pymorphy3.MorphAnalyzer()


@lru_cache(maxsize=100_000)
def lemma_word(word: str) -> str:
    """Начальная форма слова в нижнем регистре (`ё` → `е`); слова без кириллицы возвращаются как есть.

    Составные слова через дефис pymorphy разбирает сам (`python-разработчика` → `python-разработчик`); если он
    слово не знает, лемматизируется каждая часть отдельно. Результат — функция только от слова, поэтому алиасы
    справочника и слова текста сравниваются в одной форме независимо от выбранной леммы.
    """
    if not has_cyrillic(word):
        return word
    parsed = _morph().parse(word)[0]
    if "UNKN" in parsed.tag and "-" in word:
        return "-".join(lemma_word(part) for part in word.split("-") if part)
    return parsed.normal_form.replace("ё", "е")


def lemma_key(words: list[str]) -> str:
    """Ключ окна слов: леммы через пробел."""
    return " ".join(lemma_word(word) for word in words)


_WORD_RE = re.compile(r"[a-zа-я0-9+#]+(?:[-/.][a-zа-я0-9+#]+)*")


def words_of(phrase: str) -> list[str]:
    """Слова фразы в нижнем регистре (`ё` → `е`); дефис, слэш и точка внутри слова не разрывают его."""
    return _WORD_RE.findall(phrase.lower().replace("ё", "е"))


# ---------------------------------------------------------------------------------------------------------------------
# Стоп-слова нераспознанных терминов
# ---------------------------------------------------------------------------------------------------------------------

#: Частые английские слова и названия компаний: в перечислении они не считаются «неизвестными навыками».
STOP_TERMS: frozenset[str] = frozenset(
    [
        "a",
        "about",
        "above",
        "across",
        "after",
        "again",
        "against",
        "all",
        "also",
        "always",
        "am",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "both",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "doing",
        "down",
        "during",
        "each",
        "either",
        "else",
        "etc",
        "every",
        "few",
        "for",
        "from",
        "further",
        "had",
        "has",
        "have",
        "having",
        "he",
        "her",
        "here",
        "hers",
        "him",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "just",
        "like",
        "make",
        "many",
        "may",
        "me",
        "might",
        "more",
        "most",
        "much",
        "must",
        "my",
        "need",
        "needs",
        "no",
        "nor",
        "not",
        "now",
        "of",
        "off",
        "on",
        "once",
        "only",
        "or",
        "other",
        "our",
        "out",
        "over",
        "own",
        "per",
        "same",
        "she",
        "should",
        "so",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "too",
        "under",
        "until",
        "up",
        "us",
        "use",
        "used",
        "using",
        "very",
        "via",
        "want",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "within",
        "without",
        "would",
        "you",
        "your",
        "ability",
        "able",
        "advanced",
        "agile",
        "analysis",
        "analytics",
        "application",
        "applications",
        "architecture",
        "backend",
        "based",
        "basic",
        "basics",
        "best",
        "big",
        "business",
        "candidate",
        "candidates",
        "career",
        "clean",
        "client",
        "clients",
        "cloud",
        "code",
        "coding",
        "collaboration",
        "commercial",
        "communication",
        "company",
        "complex",
        "concept",
        "concepts",
        "continuous",
        "core",
        "creating",
        "culture",
        "customer",
        "data",
        "day",
        "deep",
        "delivery",
        "design",
        "designing",
        "developer",
        "developers",
        "development",
        "devops",
        "digital",
        "documentation",
        "domain",
        "driven",
        "education",
        "engineer",
        "engineering",
        "english",
        "environment",
        "excellent",
        "experience",
        "expert",
        "expertise",
        "familiarity",
        "fast",
        "features",
        "flexible",
        "frameworks",
        "frontend",
        "full",
        "fullstack",
        "good",
        "great",
        "group",
        "hands",
        "high",
        "highly",
        "improvement",
        "independent",
        "infrastructure",
        "integration",
        "interest",
        "interested",
        "internal",
        "junior",
        "knowledge",
        "language",
        "languages",
        "large",
        "lead",
        "leading",
        "learn",
        "learning",
        "level",
        "logic",
        "management",
        "manager",
        "market",
        "mentoring",
        "methodologies",
        "microservices",
        "middle",
        "modern",
        "monitoring",
        "multiple",
        "native",
        "network",
        "new",
        "office",
        "onsite",
        "open",
        "operations",
        "optimization",
        "ownership",
        "participation",
        "performance",
        "pipeline",
        "plus",
        "practices",
        "principles",
        "problem",
        "process",
        "processes",
        "product",
        "production",
        "professional",
        "programming",
        "project",
        "projects",
        "quality",
        "quick",
        "real",
        "relevant",
        "remote",
        "requirements",
        "responsibilities",
        "responsible",
        "result",
        "results",
        "review",
        "reviews",
        "role",
        "scalable",
        "scale",
        "security",
        "senior",
        "service",
        "services",
        "skills",
        "small",
        "software",
        "solid",
        "solutions",
        "solving",
        "strong",
        "structures",
        "support",
        "systems",
        "task",
        "tasks",
        "team",
        "teams",
        "technical",
        "technologies",
        "technology",
        "testing",
        "tests",
        "tools",
        "tooling",
        "understanding",
        "university",
        "usage",
        "user",
        "users",
        "value",
        "version",
        "web",
        "work",
        "working",
        "years",
        "google",
        "yandex",
        "yandex.cloud",
        "sber",
        "sberbank",
        "tinkoff",
        "avito",
        "ozon",
        "wildberries",
        "vk",
        "mail.ru",
        "mailru",
        "kaspersky",
        "jetbrains",
        "microsoft",
        "amazon",
        "apple",
        "meta",
        "facebook",
        "netflix",
        "uber",
        "oracle",
        "sap",
        "ibm",
        "intel",
        "nvidia",
        "huawei",
        "samsung",
        "cisco",
        "epam",
        "luxoft",
        "jira",
        "confluence",
        "slack",
        "zoom",
        "telegram",
        "whatsapp",
        "linkedin",
        "hh.ru",
    ]
)

# ---------------------------------------------------------------------------------------------------------------------
# Грейды
# ---------------------------------------------------------------------------------------------------------------------

#: Словарь грейдов (приложение B, §1.5); в заголовке — целиком, в теле текста — без общих слов («ведущий», «старший»).
_GRADE_FULL: dict[str, re.Pattern[str]] = {
    "junior": re.compile(r"\b(?:junior|джун\w*|джуниор\w*|младш\w*|стажер\w*|intern|trainee)\b"),
    "middle": re.compile(r"\b(?:middle|мидл\w*|миддл\w*)\b"),
    "senior": re.compile(r"\b(?:senior|сеньор\w*|синьор\w*|старш\w*|ведущ\w*|lead|лид|тимлид|principal)\b"),
}
_GRADE_BODY: dict[str, re.Pattern[str]] = {
    "junior": re.compile(r"\b(?:junior|джун\w*|джуниор\w*|стажер\w*|intern|trainee)\b"),
    "middle": _GRADE_FULL["middle"],
    "senior": re.compile(r"\b(?:senior|сеньор\w*|синьор\w*|principal|тимлид)\b"),
}
#: Грейд рядом с этими словами — про других людей («наставлять джунов»), а не про вакансию.
_GRADE_OTHERS_RE = re.compile(r"наставл|наставнич|ментор|обуч|помога|помощ|ревью|руковод|управл|воспитыва")
_GRADE_ORDER = ("junior", "middle", "senior")

#: Пороги стажа (Арх. 6.14, 15.1 № 19): одно правило для резюме, потребности и предпросмотра.
JUNIOR_YEARS_BELOW = 1.5
MIDDLE_YEARS_BELOW = 4.0


def norm_lower(text: str) -> str:
    return text.lower().replace("ё", "е")


def grade_words(text: str, *, strict: bool = False) -> list[str]:
    """Названные в тексте грейды без повторов, от младшего к старшему.

    `strict` — режим тела вакансии: словарь без общих слов и без упоминаний вроде «наставлять джунов».
    """
    lowered = norm_lower(text)
    patterns = _GRADE_BODY if strict else _GRADE_FULL
    found: list[str] = []
    for grade in _GRADE_ORDER:
        for match in patterns[grade].finditer(lowered):
            if strict and _GRADE_OTHERS_RE.search(lowered[max(0, match.start() - 40) : match.start()]):
                continue
            found.append(grade)
            break
    return found


def grade_from_text(text: str) -> tuple[str | None, list[str]]:
    """Грейд из текста и другие названные грейды: несколько грейдов → младший, остальные в списке."""
    found = grade_words(text)
    if not found:
        return None, []
    return found[0], found[1:]


def grade_from_years(years: float) -> str:
    """Грейд по стажу: `< 1.5` — junior, `< 4` — middle, иначе senior."""
    if years < JUNIOR_YEARS_BELOW:
        return "junior"
    if years < MIDDLE_YEARS_BELOW:
        return "middle"
    return "senior"


# ---------------------------------------------------------------------------------------------------------------------
# Роли и голосование
# ---------------------------------------------------------------------------------------------------------------------

MAX_ROLE_WORDS = 5


@lru_cache(maxsize=1)
def _role_index() -> tuple[dict[str, str], dict[str, str | None]]:
    """(ключ-лемма алиаса → код роли, код роли → специализация)."""
    by_key: dict[str, str] = {}
    spec_of: dict[str, str | None] = {}
    for role in catalog.role_entries():
        spec_of[role.code] = role.specialization
        for alias in role.aliases:
            by_key.setdefault(lemma_key(words_of(alias)), role.code)
    return by_key, spec_of


def role_specialization(role_code: str) -> str | None:
    return _role_index()[1].get(role_code)


def find_roles(text: str) -> list[str]:
    """Коды ролей из текста по леммам; порядок — по первому вхождению, без повторов."""
    by_key, _ = _role_index()
    words = words_of(text)
    found: list[str] = []
    i = 0
    while i < len(words):
        for size in range(min(MAX_ROLE_WORDS, len(words) - i), 0, -1):
            code = by_key.get(lemma_key(words[i : i + size]))
            if code is not None:
                if code not in found:
                    found.append(code)
                i += size
                break
        else:
            i += 1
    return found


#: Запас голосов, ниже которого специализация не определена (Арх. 6.14).
SPEC_MIN_MARGIN = 0.2
TITLE_ROLE_VOTE = 3.0
TEXT_ROLE_VOTE = 1.0
PRIMARY_SKILL_VOTE = 1.0
SECONDARY_SKILL_VOTE = 0.5


def vote_table(
    title_roles: Collection[str], text_roles: Collection[str], skill_codes: Collection[str]
) -> dict[str, float]:
    """Голоса за специализации (формула — в `vote_specialization`)."""
    votes: dict[str, float] = defaultdict(float)
    for role in title_roles:
        if spec := role_specialization(role):
            votes[spec] += TITLE_ROLE_VOTE
    for role in text_roles:
        if spec := role_specialization(role):
            votes[spec] += TEXT_ROLE_VOTE
    skills = {s.code: s for s in catalog.skill_entries()}
    for code in set(skill_codes):
        entry = skills.get(code)
        if entry is None:
            continue
        for index, spec in enumerate(entry.specializations):
            votes[spec] += PRIMARY_SKILL_VOTE if index == 0 else SECONDARY_SKILL_VOTE
    return dict(votes)


def vote_specialization(
    title_roles: Collection[str], text_roles: Collection[str], skill_codes: Collection[str]
) -> tuple[str | None, float]:
    """Голосование за специализацию (приложение B, §2.3): код (или `None`) и запас лидера.

    ```
    votes[s] = 3 · (роли со специализацией s в заголовке) + 1 · (роли в остальном тексте)
             + Σ по навыкам: 1.0, если s — основная специализация навыка, 0.5, если дополнительная
    margin   = (top − second) / max(top, 1)
    ```
    Специализация — лидер, если `top > 0` и `margin ≥ SPEC_MIN_MARGIN`. Доступность теста здесь не учитывается:
    текст про недоступную специализацию распознаётся, а черновик получает предупреждение
    `specialization_unavailable` (Арх. 6.14). Возвращаемое число — запас лидера (0..1), он же уверенность.
    """
    votes = vote_table(title_roles, text_roles, skill_codes)
    if not votes:
        return None, 0.0
    order = {code: i for i, code in enumerate(catalog.specialization_codes())}
    ranked = sorted(votes.items(), key=lambda item: (-item[1], order.get(item[0], 99)))
    top = ranked[0][1]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = (top - second) / max(top, 1.0)
    if top > 0 and margin >= SPEC_MIN_MARGIN:
        return ranked[0][0], round(margin, 3)
    return None, round(margin, 3)


# ---------------------------------------------------------------------------------------------------------------------
# Города
# ---------------------------------------------------------------------------------------------------------------------

MAX_CITY_WORDS = 3
_CITY_MARK_RE = re.compile(
    r"(?i:\bпроживает(?:\s+в)?|\bгород\w*|(?<![а-яё])г\.)\s*:?\s*(?i:в\s+)?([А-ЯЁ][а-яё-]+(?:\s[А-ЯЁ][а-яё-]+)?)"
)


@lru_cache(maxsize=1)
def _city_index() -> dict[str, str]:
    """Ключ-лемма названия или сокращения → город в нормальной форме."""
    index: dict[str, str] = {}
    for city in catalog.city_entries():
        for name in (city.name, *city.aliases):
            index.setdefault(lemma_key(words_of(name)), city.name)
    return index


def _city_by_words(words: list[str]) -> str | None:
    return _city_index().get(lemma_key(words))


def find_city(text: str) -> str | None:
    """Город в нормальной форме: сначала после слов «г.», «город», «проживает», затем первый из `cities.txt`."""
    match = _CITY_MARK_RE.search(text)
    if match:
        captured = words_of(match.group(1))
        for size in range(min(2, len(captured)), 0, -1):
            city = _city_by_words(captured[:size])
            if city:
                return city
    words = words_of(text)
    for i in range(len(words)):
        for size in range(min(MAX_CITY_WORDS, len(words) - i), 0, -1):
            city = _city_by_words(words[i : i + size])
            if city:
                return city
    return None
