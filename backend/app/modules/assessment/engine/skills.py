"""Вердикты по группам и правило «навык подтверждён тестом» (Арх. 5.6, 5.9)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from app.modules.assessment.blueprints import MAIN_RANGE
from app.shared.enums import SkillVerdict

__all__ = ["GroupVerdict", "SkillAnswer", "SkillProof", "group_verdicts", "pulse_gives_evidence", "skill_proofs"]


@dataclass(frozen=True)
class SkillAnswer:
    """Учтённый ответ глазами правила навыков: группа семейства, сложность, балл и теги навыков семейства."""

    group: str
    b: float
    score: int
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class GroupVerdict:
    """Вердикт по группе: число учтённых ответов уровня грейда, число верных и теги верно решённых семейств."""

    group: str
    items: int
    correct: int
    verdict: SkillVerdict
    tags_correct: tuple[str, ...]


@dataclass(frozen=True)
class SkillProof:
    """Доказательство навыка: `full` — группа подтверждена (вес 1.0); иначе решено одно задание (вес 0.7)."""

    skill: str
    group: str
    full: bool


def group_verdicts(answers: Iterable[SkillAnswer], ref_grade: str) -> dict[str, GroupVerdict]:
    """Вердикты по группам (Арх. 5.6).

    Считаются ответы с `b ≥ main_range(G_ref).low`: задания ниже уровня грейда навык на этом грейде не подтверждают.
    `confirmed` — `n ≥ 2`, `c ≥ 2`, `c/n ≥ 2/3`; `partial` — `c ≥ 1`; `not_confirmed` — `n ≥ 1`, `c = 0`; при `n = 0`
    строки нет. `tags_correct` — объединение `skill_tags` верно решённых семейств из тех же ответов.
    """
    low = MAIN_RANGE[ref_grade][0]
    counts: dict[str, list[int]] = {}
    tags: dict[str, set[str]] = {}
    for answer in answers:
        if answer.b < low:
            continue
        row = counts.setdefault(answer.group, [0, 0])
        row[0] += 1
        if answer.score:
            row[1] += 1
            tags.setdefault(answer.group, set()).update(answer.tags)
    result = {}
    for group, (n, c) in counts.items():
        if n >= 2 and c >= 2 and c * 3 >= n * 2:
            verdict = SkillVerdict.CONFIRMED
        elif c >= 1:
            verdict = SkillVerdict.PARTIAL
        else:
            verdict = SkillVerdict.NOT_CONFIRMED
        result[group] = GroupVerdict(group, n, c, verdict, tuple(sorted(tags.get(group, ()))))
    return result


def skill_proofs(verdicts: Iterable[GroupVerdict], direct: Mapping[str, Iterable[str]]) -> list[SkillProof]:
    """Правило «навык подтверждён тестом» (Арх. 5.6, 15.1 № 36 и № 54).

    Навык `s` получает доказательство, если есть группа `g`, для которой `s ∈ direct(g)` и `s ∈ tags_correct(g)`:
    кандидат верно решил задание уровня грейда, помеченное именно этим навыком. Вес зависит от вердикта группы:
    `confirmed` → `full = True` (1.0), `partial` → `full = False` (0.7), `not_confirmed` доказательства не даёт.
    Связь `related` и подтверждённая группа без решённого задания с тегом доказательства не дают.
    Если навык доказан в двух группах, остаётся более сильное доказательство.
    """
    best: dict[str, SkillProof] = {}
    for item in verdicts:
        if item.verdict is SkillVerdict.NOT_CONFIRMED:
            continue
        allowed = set(direct.get(item.group, ()))
        for skill in item.tags_correct:
            if skill not in allowed:
                continue
            proof = SkillProof(skill, item.group, item.verdict is SkillVerdict.CONFIRMED)
            if skill not in best or (proof.full and not best[skill].full):
                best[skill] = proof
    return [best[skill] for skill in sorted(best)]


def pulse_gives_evidence(test_verdict: SkillVerdict | str | None) -> bool:
    """Создаёт ли верное короткое задание строку доказательства `pulse` (Арх. 5.9).

    Нет, если вердикт этой группы по тесту в окне — `not_confirmed`: одно короткое задание не перевешивает
    группу, проваленную тестом (свежесть при этом засчитывается).
    """
    return test_verdict is None or SkillVerdict(test_verdict) is not SkillVerdict.NOT_CONFIRMED
