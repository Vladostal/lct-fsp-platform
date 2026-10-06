"""Разделы резюме по словарю заголовков (приложение B, §1.5)."""

from __future__ import annotations

SECTION_HEADINGS: dict[str, tuple[str, ...]] = {
    "skills": (
        "навыки",
        "ключевые навыки",
        "профессиональные навыки",
        "стек",
        "технологии",
        "hard skills",
        "skills",
        "tech stack",
    ),
    "experience": ("опыт работы", "опыт", "места работы", "experience", "work experience"),
    "about": ("обо мне", "о себе", "дополнительная информация", "about", "summary"),
    "position": ("желаемая должность и зарплата", "желаемая должность", "позиция", "objective"),
    "education": ("образование", "education", "курсы", "повышение квалификации"),
    "soft": ("личные качества", "soft skills"),
}
HEADING_MAX_LEN = 40

# Длинные заголовки проверяются первыми: «желаемая должность и зарплата» раньше «желаемая должность».
_ORDERED: list[tuple[str, str]] = sorted(
    ((heading, name) for name, headings in SECTION_HEADINGS.items() for heading in headings),
    key=lambda item: -len(item[0]),
)


def heading_of(line: str) -> tuple[str, str] | None:
    """Раздел и остаток строки после заголовка, если строка — заголовок; иначе `None`.

    Строка (в нижнем регистре, без `:`) совпадает с заголовком целиком либо начинается с него и короче 40 знаков;
    после заголовка должен идти разделитель, а не продолжение слова («стекло» — не «стек»). Остаток — то, что
    стоит после заголовка и двоеточия («Стек: Python, Django» → «Python, Django»): он остаётся строкой раздела.
    """
    stripped = line.strip()
    low = stripped.lower().replace(":", " ")
    if not low.strip() or len(stripped) >= HEADING_MAX_LEN:
        return None
    low = low.strip()
    for heading, name in _ORDERED:
        if low == heading:
            return name, ""
        if low.startswith(heading) and not low[len(heading)].isalnum():
            return name, stripped[len(heading) :].lstrip(" :—–-").strip()
    return None


def split_sections(lines: list[str]) -> dict[str, list[tuple[int, str]]]:
    """Строки по разделам: `{раздел: [(номер строки, строка)]}`; всё до первого заголовка — `head`.

    Сама строка-заголовок в раздел не входит (кроме остатка после двоеточия). Раздел, встретившийся дважды,
    накапливает строки обоих мест.
    """
    result: dict[str, list[tuple[int, str]]] = {"head": []}
    current = "head"
    for index, line in enumerate(lines):
        found = heading_of(line) if line.strip() else None
        if found is not None:
            current, rest = found
            result.setdefault(current, [])
            if rest:
                result[current].append((index, rest))
            continue
        result[current].append((index, line))
    return result
