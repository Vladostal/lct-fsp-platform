"""Семейство `git.merge_rebase`: перемотка, слияние, rebase, squash (numeric_input).

Уровень 1 — сколько коммитов добавит `git merge` (перемотка или коммит слияния). Уровень 2 — сколько коммитов
получат новые идентификаторы после `git rebase main`. Уровень 3 — `rebase --onto` или `merge --squash`: сколько
коммитов выведет `git log --oneline` после команд. Ответ считает симулятор графа `GitGraph`: переписанный коммит
получает новый идентификатор. Оракул — настоящий git во временном каталоге (каждый коммит добавляет свой файл, поэтому
конфликтов нет). Модели ошибок: `merge_always_commit` и `merge_adds_one` (уровень 1), `rebase_keeps_hashes`
(уровень 2), `onto_takes_upstream` и `squash_keeps_all` (уровень 3). Ответ однозначен: граф строится только командами
из условия, диапазоны линейны.
"""

from __future__ import annotations

import re
from random import Random

from app.modules.assessment.families._lib import names
from app.modules.assessment.families._lib.contract import AnswerSpec, CodeBlock, InputHint, Reject, Variant
from app.modules.assessment.families._lib.gitsim import GitError, GitGraph, GitScript, RealGit
from app.modules.assessment.families.registry import family_meta

META = family_meta(
    "git.merge_rebase",
    version=1,
    feature_bounds={
        1: {"code_lines": (6, 18), "concepts": (3, 3)},
        2: {"code_lines": (8, 26), "concepts": (3, 4)},
        3: {"code_lines": (7, 24), "concepts": (3, 5)},
    },
    misconceptions=(
        "rebase_keeps_hashes",
        "merge_always_commit",
        "merge_adds_one",
        "onto_takes_upstream",
        "squash_keeps_all",
    ),
)

HEAD_NOTE = "В пустом репозитории выполнены команды (каждый git commit добавляет свой файл, конфликтов нет). "


def _level_1(rng: Random) -> tuple[GitScript, str, dict[str, int]]:
    side = names.pick(rng, [b for b in names.BRANCH_NAMES if b != "main"])
    s = GitScript()
    s.commit(rng.randint(1, 3))
    s.add(f"git checkout -b {side}")
    s.commit(rng.randint(2, 6))
    s.add("git checkout main")
    diverged = rng.random() < 0.45
    if diverged:
        s.commit(rng.randint(1, 3))
    s.add(f"git merge {side}" + (" --no-ff" if rng.random() < 0.25 else ""))
    return s, side, {}


def _level_2(rng: Random) -> tuple[GitScript, str, dict[str, int]]:
    s = GitScript()
    s.commit(rng.randint(1, 3))
    sides = names.pick_many(rng, [b for b in names.BRANCH_NAMES if b != "main"], rng.choice((1, 1, 2)))
    for side in sides:
        s.add(f"git checkout -b {side}")
        s.commit(rng.randint(1, 5))
        s.add("git checkout main")
    s.commit(rng.randint(1, 4))
    for side in sides:
        s.add(f"git checkout {side}")
        s.add("git rebase main")
    return s, sides[0], {}


def _level_3(rng: Random) -> tuple[GitScript, str, dict[str, int]]:
    s = GitScript()
    s.commit(rng.randint(1, 5))
    if rng.random() < 0.5:  # rebase --onto: topic2 растёт из topic1, переносится на main без коммитов topic1
        first, second = names.pick_many(rng, [b for b in names.BRANCH_NAMES if b != "main"], 2)
        s.add(f"git checkout -b {first}")
        s.commit(rng.randint(1, 3))
        s.add(f"git checkout -b {second}")
        s.commit(rng.randint(1, 4))
        s.add("git checkout main")
        s.commit(rng.randint(1, 3))
        s.add(f"git rebase --onto main {first} {second}")
        return s, second, {"kind": 1}
    side = names.pick(rng, [b for b in names.BRANCH_NAMES if b != "main"])
    s.add(f"git checkout -b {side}")
    s.commit(rng.randint(2, 5))
    s.add("git checkout main")
    s.commit(rng.randint(0, 4))
    s.add(f"git merge --squash {side}")
    s.add('git commit -m "squash"')
    return s, "main", {"kind": 2}


def _replayed_total(lines: list[str]) -> int:
    g = GitGraph()
    total = 0
    for line in lines:
        g.apply(line)
        if line.startswith("git rebase"):
            total += len(g.replayed)
    return total


def generate(level: int, seed: int) -> Variant:
    """Вариант: история команд и вопрос о результате merge, rebase, rebase --onto или merge --squash.

    Что вычисляется: уровень 1 — прирост числа коммитов ветки main от последнего merge; уровень 2 — число коммитов,
    переписанных всеми rebase (новые идентификаторы); уровень 3 — вывод `git log --oneline` после `rebase --onto`
    или squash. Симулятор `GitGraph` даёт верное число; модели ошибок считаются флагом симулятора или формулой
    («перемотка тоже создаёт коммит», «merge добавляет один коммит», «rebase сохраняет идентификаторы», «onto
    переносит и чужие коммиты», «squash переносит все коммиты»). Вариант без отличия ответа ошибки отбрасывается.
    """
    rng = Random(seed)
    builder = (_level_1, _level_2, _level_3)[level - 1]
    s, ref, info = builder(rng)
    lines = s.lines
    try:
        if level == 1:
            before_lines, merge = lines[:-1], lines[-1]
            before = GitGraph().run(before_lines).count("main")
            g = GitGraph().run(lines)
            answer = g.count("main") - before
            always = GitGraph(["merge_always_commit"]).run(lines).count("main") - before
            wrong = {"merge_always_commit": always, "merge_adds_one": 1}
            question = (
                f"Сколько коммитов добавит в историю ветки main последняя команда «{merge}»? Ответ — целое число."
            )
        elif level == 2:
            answer = _replayed_total(lines)
            wrong = {"rebase_keeps_hashes": 0}
            question = (
                "Сколько коммитов в сумме получат новые идентификаторы из-за всех команд rebase? Ответ — целое число."
            )
        elif info["kind"] == 1:
            g = GitGraph().run(lines)
            answer = g.count(ref)
            # ошибка: `rebase --onto main A B` переносит и коммиты A; считаем как обычный `rebase main`
            plain = [*lines[:-1], "git rebase main"]
            alt = GitGraph().run(plain[:-1])
            alt.apply(f"git checkout {ref}")
            alt.apply("git rebase main")
            wrong = {"onto_takes_upstream": alt.count(ref)}
            question = f"Сколько коммитов выведет «git log --oneline {ref}» после всех команд? Ответ — целое число."
        else:
            g = GitGraph().run(lines)
            answer = g.count("main")
            side_commits = len(g.reach(g.resolve(lines[-2].split()[-1])) - g.reach(g.resolve("main")))
            wrong = {"squash_keeps_all": answer - 1 + side_commits}
            question = "Сколько коммитов выведет «git log --oneline main» после всех команд? Ответ — целое число."
    except GitError as exc:
        raise Reject("git_error") from exc
    wrong = {code: value for code, value in wrong.items() if value != answer}
    if not wrong:
        raise Reject("misconception_equals_answer")
    if answer < 2:
        raise Reject("trivial_answer")
    concepts = len({line.split()[1] for line in lines})
    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt=HEAD_NOTE + question,
        code=CodeBlock(language="bash", text="\n".join(lines)),
        input=InputHint(placeholder="целое число", max_length=3),
        answer=AnswerSpec.numeric(answer),
        misconception_answers=wrong,
        features={"code_lines": len(lines), "concepts": min(concepts, 5)},
        explanation=f"Граф строится по командам; ответ {answer}; модели ошибок: {wrong}.",
    )


_LOG = re.compile(r"«git log --oneline (\S+)»")


def selfcheck(v: Variant) -> list[str]:
    """Пересчёт: команды из текста исполняются заново, ответ вычисляется по правилу вопроса своего уровня."""
    assert v.code is not None
    lines = v.code.text.split("\n")
    try:
        if v.level == 1:
            got = GitGraph().run(lines).count("main") - GitGraph().run(lines[:-1]).count("main")
        elif v.level == 2:
            got = _replayed_total(lines)
        else:
            m = _LOG.search(v.prompt)
            if not m:
                return ["в условии нет команды git log"]
            got = GitGraph().run(lines).count(m.group(1))
    except GitError as exc:
        return [f"команды не исполняются: {exc}"]
    return [] if got == v.answer.value else [f"пересчёт даёт {got}, ключ {v.answer.value}"]


def oracle_check(v: Variant) -> list[str]:
    """Сверка с настоящим git: уровень 1 — прирост `rev-list`, 2 — потеря старых коммитов, 3 — `rev-list`."""
    assert v.code is not None
    lines = v.code.text.split("\n")
    with RealGit("graph") as git:
        if v.level == 1:
            git.run(lines[:-1])
            before = git.count("main")
            git.run(lines[-1:])
            real = git.count("main") - before
        elif v.level == 2:
            real = 0
            for line in lines:
                if line.startswith("git rebase"):
                    old = git.rev_list("HEAD", "^main")
                    git.run([line])
                    real += sum(1 for c in old if not git.is_ancestor(c, "HEAD"))
                else:
                    git.run([line])
        else:
            git.run(lines)
            m = _LOG.search(v.prompt)
            real = git.count(m.group(1)) if m else -1
    return [] if real == v.answer.value else [f"git насчитал {real}, ключ {v.answer.value}"]
