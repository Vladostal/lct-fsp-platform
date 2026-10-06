"""Семейство `git.log_reach`: сколько коммитов покажет `git log` после серии команд (numeric_input).

Уровень 1 — `commit`, `branch`, `checkout`, `merge`; уровень 2 — `reset --hard` и `revert`; уровень 3 —
`cherry-pick` и отсоединённый HEAD. Ответ считает симулятор графа `GitGraph`; оракул — настоящий git во временном
каталоге: те же команды, затем `git rev-list`. Каждый коммит добавляет свой файл, поэтому конфликтов нет и граф
определяется только командами. Модели ошибок: `merge_first_parent_only`, `reset_keeps_history`, `revert_noop`,
`detached_moves_branch`, `cherry_pick_links_original` — каждая вычисляется тем же симулятором с флагом.
Вариант, в котором ни одна ошибка не меняет ответ, отбрасывается.
"""

from __future__ import annotations

import re
from random import Random

from app.modules.assessment.families._lib import names
from app.modules.assessment.families._lib.contract import AnswerSpec, CodeBlock, InputHint, Reject, Variant
from app.modules.assessment.families._lib.gitsim import GitError, GitGraph, RealGit
from app.modules.assessment.families.registry import family_meta

META = family_meta(
    "git.log_reach",
    version=1,
    feature_bounds={
        1: {"code_lines": (7, 16), "concepts": (3, 4)},
        2: {"code_lines": (4, 18), "concepts": (2, 5)},
        3: {"code_lines": (8, 20), "concepts": (3, 5)},
    },
    misconceptions=(
        "merge_first_parent_only",
        "reset_keeps_history",
        "revert_noop",
        "detached_moves_branch",
        "cherry_pick_links_original",
    ),
)

LEVEL_FLAGS: dict[int, tuple[str, ...]] = {
    1: ("first_parent",),
    2: ("reset_keeps_history", "revert_noop"),
    3: ("detached_moves_branch", "cherry_pick_links_original"),
}
FLAG_CODE = {
    "first_parent": "merge_first_parent_only",
    "reset_keeps_history": "reset_keeps_history",
    "revert_noop": "revert_noop",
    "detached_moves_branch": "detached_moves_branch",
    "cherry_pick_links_original": "cherry_pick_links_original",
}


class _Script:
    """Список команд с номерами коммитов в сообщениях."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self._n = 0
        self._live = GitGraph()

    def try_add(self, line: str) -> bool:
        """Добавить команду, только если живой симулятор её принимает (иначе настоящий git дал бы ошибку)."""
        try:
            self._live.apply(line)
        except GitError:
            return False
        self.lines.append(line)
        return True

    def commit(self, times: int = 1) -> None:
        for _ in range(times):
            self._n += 1
            self.try_add(f'git commit -m "c{self._n}"')

    def add(self, line: str) -> None:
        if not self.try_add(line):
            raise Reject("git_error")


Question = tuple[str, str | None]


def _scenario(level: int, rng: Random) -> tuple[list[str], str, list[Question]]:
    """Команды и допустимые вопросы: (строки, побочная ветка, [(ссылка, база)]); база None — `git log ссылка`."""
    side = names.pick(rng, [b for b in names.BRANCH_NAMES if b != "main"])
    s = _Script()
    s.commit(rng.randint(2, 4 if level == 1 else 5))
    if level == 1:
        s.add(f"git checkout -b {side}")
        s.commit(rng.randint(1, 3))
        s.add("git checkout main")
        s.commit(rng.randint(1, 3))
        if rng.random() < 0.3:  # слияние в обратную сторону: main вливается в побочную ветку
            s.add(f"git checkout {side}")
            s.add("git merge main")
            if rng.random() < 0.6:
                s.commit(rng.randint(1, 2))
            return s.lines, side, [(side, None)]
        s.add(f"git merge {side}" + rng.choice(("", "", " --no-ff")))
        if rng.random() < 0.6:
            s.commit(rng.randint(1, 2))
        return s.lines, side, [("main", None)]
    if level == 2:
        for _ in range(rng.randint(2, 4)):
            op = rng.choice(("commit", "reset", "revert", "commit"))
            if op == "commit":
                s.commit(rng.randint(1, 2))
            elif op == "reset":
                s.try_add(f"git reset --hard HEAD~{rng.randint(1, 2)}")
            else:
                s.try_add(f"git revert HEAD~{rng.randint(0, 1)}")
        if rng.random() < 0.5:
            s.add(f"git branch {side}")
            s.try_add(f"git reset --hard HEAD~{rng.randint(1, 2)}")
            s.commit(rng.randint(0, 1))
            return s.lines, side, [("main", side), (side, "main"), ("main", None)]
        return s.lines, side, [("main", None)]
    # уровень 3: cherry-pick и отсоединённый HEAD
    s.add(f"git checkout -b {side}")
    s.commit(rng.randint(2, 3))
    s.add("git checkout main")
    s.commit(rng.randint(1, 2))
    s.add(f"git cherry-pick {side}" + rng.choice(("", "~1")))
    if rng.random() < 0.7:
        s.add(f"git checkout main~{rng.randint(1, 2)}")
        s.commit(rng.randint(1, 2))
        s.add("git checkout main")
    return s.lines, side, [("main", None), (side, "main"), ("main", side)]


def _question(ref: str, base: str | None) -> tuple[str, str]:
    """Текст команды и вопроса."""
    command = f"git log --oneline {ref}" if base is None else f"git log {base}..{ref}"
    return command, f"Сколько коммитов выведет команда «{command}»? Ответ — целое число."


def _count(g: GitGraph, ref: str, base: str | None) -> int:
    return g.count(ref) if base is None else g.count_range(base, ref)


def generate(level: int, seed: int) -> Variant:
    """Вариант: история команд с нуля и вопрос о выводе `git log`.

    Ответ — число достижимых коммитов (или число коммитов диапазона `a..b`), вычисленное симулятором графа.
    Модели ошибок — флаги симулятора (первые родители, «reset не убирает историю», «revert ничего не добавляет»,
    «коммиты на отсоединённом HEAD двигают ветку», «cherry-pick делает исходный коммит достижимым»); в вариант
    попадают только те, что меняют ответ. Ответ однозначен: команды выполняются подряд без конфликтов.
    """
    rng = Random(seed)
    lines, _, candidates = _scenario(level, rng)
    rng.shuffle(candidates)
    try:
        correct = GitGraph().run(lines)
        alternatives = {flag: GitGraph([flag]).run(lines) for flag in LEVEL_FLAGS[level]}
    except GitError as exc:
        raise Reject("git_error") from exc
    # Вопрос выбирается среди тех, где ответ не тривиален и хотя бы одна модель ошибки его меняет.
    for ref, base in candidates:
        answer = _count(correct, ref, base)
        wrong = {FLAG_CODE[f]: _count(g, ref, base) for f, g in alternatives.items() if _count(g, ref, base) != answer}
        if wrong and answer >= 2:
            break
    else:
        raise Reject("no_informative_question")
    command, question = _question(ref, base)
    text = "\n".join(lines)
    concepts = len({line.split()[1] for line in lines})
    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt=f"В пустом репозитории выполнены команды (каждый коммит добавляет файл, конфликтов нет). {question}",
        code=CodeBlock(language="bash", text=text),
        input=InputHint(placeholder="целое число", max_length=3),
        answer=AnswerSpec.numeric(answer),
        misconception_answers=wrong,
        features={"code_lines": len(lines), "concepts": min(concepts, 5)},
        explanation=f"Граф строится по командам; {command} -> {answer}. Модели ошибок: {wrong}.",
    )


_LOG = re.compile(r"«git log (?:--oneline (\S+)|(\S+)\.\.(\S+))»")


def _asked(v: Variant) -> tuple[str, str | None]:
    m = _LOG.search(v.prompt)
    if not m:
        raise GitError("в условии нет команды git log")
    return (m.group(1), None) if m.group(1) else (m.group(3), m.group(2))


def selfcheck(v: Variant) -> list[str]:
    """Пересчёт вторым способом: граф родителей разбирается из текста, коммиты считаются обходом."""
    assert v.code is not None
    ref, base = _asked(v)
    # Независимая реализация: граф как словарь родителей, достижимость обходом в ширину.
    parents: dict[int, list[int]] = {}
    refs: dict[str, int] = {}
    head: str = "main"  # имя ветки или "#<id>"
    nxt = 1

    def tip(name: str) -> int | None:
        return int(name[1:]) if name.startswith("#") else refs.get(name)

    def spec(text: str) -> int:
        name, _, steps = text.partition("~")
        node = tip("main" if False else head) if name == "HEAD" else refs[name]
        assert node is not None
        for _ in range(int(steps or 0)):
            node = parents[node][0]
        return node

    def move(node: int) -> None:
        nonlocal head
        if head.startswith("#"):
            head = f"#{node}"
        else:
            refs[head] = node

    for row in v.code.text.split("\n"):
        w = row.split()
        cur = tip(head)
        if w[1] == "commit":
            parents[nxt] = [] if cur is None else [cur]
            move(nxt)
            nxt += 1
        elif w[1] == "checkout" and w[2] == "-b":
            refs[w[3]] = cur  # type: ignore[assignment]
            head = w[3]
        elif w[1] == "checkout":
            head = w[2] if w[2] in refs else f"#{spec(w[2])}"
        elif w[1] == "merge":
            target = refs[next(a for a in w[2:] if not a.startswith("--"))]
            assert cur is not None
            seen, todo = set(), [cur]
            while todo:
                x = todo.pop()
                if x not in seen:
                    seen.add(x)
                    todo += parents[x]
            if target in seen:
                continue
            ancestors, todo = set(), [target]
            while todo:
                x = todo.pop()
                if x not in ancestors:
                    ancestors.add(x)
                    todo += parents[x]
            if cur in ancestors and "--no-ff" not in w:
                move(target)
            else:
                parents[nxt] = [cur, target]
                move(nxt)
                nxt += 1
        elif w[1] == "reset":
            move(spec(w[3]))
        elif w[1] in ("revert", "cherry-pick"):
            parents[nxt] = [cur]  # type: ignore[list-item]
            move(nxt)
            nxt += 1
        elif w[1] == "branch":
            refs[w[2]] = cur  # type: ignore[assignment]

    def reach(node: int) -> set[int]:
        out, todo = set(), [node]
        while todo:
            x = todo.pop()
            if x not in out:
                out.add(x)
                todo += parents[x]
        return out

    got = len(reach(refs[ref])) if base is None else len(reach(refs[ref]) - reach(refs[base]))
    return [] if got == v.answer.value else [f"пересчёт графа даёт {got}, ключ {v.answer.value}"]


def oracle_check(v: Variant) -> list[str]:
    """Сверка ключа с настоящим git: те же команды в временном репозитории, затем `git rev-list`."""
    assert v.code is not None
    ref, base = _asked(v)
    with RealGit("graph") as git:
        git.run(v.code.text.split("\n"))
        real = git.count(ref) if base is None else git.count_range(base, ref)
    return [] if real == v.answer.value else [f"git насчитал {real}, ключ {v.answer.value}"]
