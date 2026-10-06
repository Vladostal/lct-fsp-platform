"""Фасад модуля `textparse` (Арх. 2.5): чистые функции разбора текста.

Ничего не пишут в базу и не читают время: один вход — один результат. Справочники берутся из памяти
(`catalog.service`). Нераспознанные термины возвращаются в результате; в `skill_miss_log` их пишет вызывающий
через `catalog.service.log_miss`.
"""

from __future__ import annotations

from collections.abc import Collection

from app.modules.textparse import lexicon, linker, need_parser
from app.modules.textparse.dto import NeedDraft, SkillMention

#: Версия правил разбора текста потребности; хранится в черновике (`NeedDraft.parser_version`).
PARSER_VERSION = need_parser.PARSER_VERSION


def link_skills(text: str, *, enumeration_lines: set[int] | None = None) -> tuple[list[SkillMention], list[str]]:
    """Упоминания навыков и нераспознанные термины (`SkillLinker`, приложение B, §1.4).

    `enumeration_lines` — номера строк (с нуля), которые считаются перечислением навыков: только там срабатывают
    алиасы с учётом регистра (`Go`, `C`, `R`) и собираются неизвестные термины.
    """
    return linker.link(text, enumeration_lines=enumeration_lines)


def parse_need_text(text: str) -> NeedDraft:
    """Черновик потребности из текста вакансии (правила — приложение B, §2.2; Арх. 6.14). В базу не пишет."""
    return need_parser.parse(text)


def vote_specialization(
    title_roles: Collection[str], text_roles: Collection[str], skill_codes: Collection[str]
) -> tuple[str | None, float]:
    """Код специализации (или `None`) и уверенность (запас лидера, 0..1)."""
    return lexicon.vote_specialization(title_roles, text_roles, skill_codes)


def grade_from_text(text: str) -> tuple[str | None, list[str]]:
    """Грейд из текста и другие названные грейды (несколько грейдов → младший, остальные в списке)."""
    return lexicon.grade_from_text(text)


def grade_from_years(years: float) -> str:
    """Грейд по стажу: `< 1.5` года — junior, `< 4` — middle, иначе senior."""
    return lexicon.grade_from_years(years)


def find_roles(text: str) -> list[str]:
    """Коды ролей (`roles.yaml`) из текста по леммам, в порядке появления."""
    return lexicon.find_roles(text)


def find_city(text: str) -> str | None:
    """Город из текста в нормальной форме (`cities.txt`) или `None`."""
    return lexicon.find_city(text)
