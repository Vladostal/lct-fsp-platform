"""Семейство `git.reset_restore`: что покажет `git status` после reset, restore и stash (multi_choice).

Сценарий строится с нуля командами (файлы, два коммита, правки в рабочей копии, часть добавлена в индекс), затем
идут ключевые команды уровня: 1 — `reset --soft/--mixed/--hard HEAD~1`; 2 — `restore`, `restore --staged`, `stash`;
3 — сочетания с неотслеживаемыми файлами. Вопрос — какие файлы git status покажет в одном из трёх разделов
(в индексе, не в индексе, неотслеживаемые). Ответ считает симулятор трёх деревьев `ThreeTrees`; оракул — настоящий
git и `git status --porcelain`. Модели ошибок — флаги симулятора: `reset_soft_resets_index`, `reset_mixed_is_hard`,
`reset_hard_cleans_untracked`, `restore_resets_index`, `stash_takes_untracked`; в вариант попадают те, что меняют
ответ. Ответ однозначен: каждая правка дописывает уникальную строку, поэтому содержимое файлов сравнивается точно.
"""

from __future__ import annotations

from random import Random

from app.modules.assessment.families._lib import names
from app.modules.assessment.families._lib.contract import AnswerSpec, CodeBlock, Option, Reject, Variant
from app.modules.assessment.families._lib.gitsim import GitError, RealGit, ThreeTrees
from app.modules.assessment.families.registry import family_meta

META = family_meta(
    "git.reset_restore",
    version=1,
    feature_bounds={
        1: {"code_lines": (13, 26), "concepts": (2, 4), "options_count": (4, 5)},
        2: {"code_lines": (14, 28), "concepts": (3, 5), "options_count": (5, 5)},
        3: {"code_lines": (14, 30), "concepts": (3, 6), "options_count": (5, 5)},
    },
    misconceptions=(
        "reset_soft_resets_index",
        "reset_mixed_is_hard",
        "reset_hard_cleans_untracked",
        "restore_resets_index",
        "stash_takes_untracked",
    ),
)

FLAG_CODE = {
    "soft_resets_index": "reset_soft_resets_index",
    "mixed_is_hard": "reset_mixed_is_hard",
    "hard_cleans_untracked": "reset_hard_cleans_untracked",
    "restore_resets_index": "restore_resets_index",
    "stash_takes_untracked": "stash_takes_untracked",
}
LEVEL_FLAGS = {
    1: ("soft_resets_index", "mixed_is_hard", "hard_cleans_untracked"),
    2: ("restore_resets_index", "stash_takes_untracked"),
    3: tuple(FLAG_CODE),
}
QUESTIONS = {
    "staged": "подготовленные к коммиту (Changes to be committed)",
    "unstaged": "изменённые, но не добавленные в индекс (Changes not staged for commit)",
    "untracked": "неотслеживаемые (Untracked files)",
}


class _Script:
    """Команды с уникальными строками правок; каждая команда проверяется живым симулятором."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.sim = ThreeTrees()
        self._k = 0

    def run(self, line: str) -> None:
        try:
            self.sim.apply(line)
        except GitError as exc:
            raise Reject("git_error") from exc
        self.lines.append(line)

    def edit(self, name: str, *, new: bool = False) -> None:
        self._k += 1
        self.run(f"echo v{self._k} {'>' if new else '>>'} {name}")


def _scenario(level: int, rng: Random) -> tuple[list[str], list[str], list[str]]:
    """(команды, имена файлов, ключевые команды)."""
    tracked = names.pick_many(rng, names.FILE_NAMES, 5)
    base, extra = tracked[:4], tracked[4]
    s = _Script()
    for name in base:
        s.edit(name, new=True)
    s.run("git add .")
    s.run('git commit -m "first"')
    for name in rng.sample(base, rng.randint(1, 2)):
        s.edit(name)
        s.run(f"git add {name}")
    s.run('git commit -m "second"')
    edited = rng.sample(base, rng.randint(2, 3))
    for name in edited:
        s.edit(name)
    staged = rng.sample(edited, rng.randint(1, len(edited) - 1))
    for name in staged:
        s.run(f"git add {name}")
    if rng.random() < 0.4:
        s.edit(staged[0])
    new_file = level >= 2 or rng.random() < 0.7
    if new_file:
        s.edit(extra, new=True)
        if level == 3 and rng.random() < 0.35:
            s.run(f"git add {extra}")
    key: list[str] = []
    if level == 1:
        key = [f"git reset --{rng.choice(('soft', 'mixed', 'hard'))} HEAD~1"]
    elif level == 2:
        pool = [f"git restore {name}" for name in base if name in s.sim.index]
        pool += [f"git restore --staged {name}" for name in staged]
        key = [rng.choice(pool)] if rng.random() < 0.5 else [rng.choice(pool), "git stash"]
        if key[-1] != "git stash" and rng.random() < 0.3:
            key.append("git stash")
    else:
        mode = rng.choice(("reset --hard HEAD~1", "reset --mixed HEAD~1", "reset --soft HEAD~1", "stash", "stash -u"))
        key = [f"git {mode}"]
        if rng.random() < 0.5:
            key.append(rng.choice((f"git restore --staged {rng.choice(staged)}", f"git restore {rng.choice(base)}")))
    for line in key:
        s.run(line)
    files = sorted({*base, extra} if new_file else set(base))
    return s.lines, files, key


def generate(level: int, seed: int) -> Variant:
    """Вариант: сценарий команд git и вопрос «какие файлы окажутся в разделе X git status».

    Ответ — множество файлов раздела (индекс против HEAD, рабочая копия против индекса, неотслеживаемые) после
    всех команд, по симулятору трёх деревьев. Модели ошибок — флаги симулятора; вариант без отличия ответа
    хотя бы одной модели отбрасывается, как и вариант с пустым или полным ответом. Ответ однозначен:
    каждая правка уникальна, неотслеживаемый файл создаётся один раз.
    """
    rng = Random(seed)
    lines, files, key = _scenario(level, rng)

    def answer_of(flags: tuple[str, ...], question: str) -> set[str] | None:
        sim = ThreeTrees(flags)
        try:
            sim.run(lines)
        except GitError:
            return None
        sets = dict(zip(("staged", "unstaged", "untracked"), sim.status(), strict=True))
        return sets[question]

    # Вопрос выбирается среди тех, где ответ не пуст и не равен всем файлам и хотя бы одна модель ошибки его меняет.
    candidates = list(QUESTIONS)
    rng.shuffle(candidates)
    for question in candidates:
        correct = answer_of((), question)
        if correct is None or not correct or len(correct) >= len(files):
            continue
        wrong: dict[str, set[str]] = {}
        for flag in LEVEL_FLAGS[level]:
            value = answer_of((flag,), question)
            if value is not None and value != correct:
                wrong[FLAG_CODE[flag]] = value
        if wrong:
            break
    else:
        raise Reject("no_informative_question")
    order = files[:]
    rng.shuffle(order)
    ids = {name: f"o{i}" for i, name in enumerate(order, start=1)}
    options = tuple(Option(id=ids[name], text=name) for name in order)
    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt=(
            "В пустом репозитории выполнены команды (каждая правка дописывает новую строку). "
            f"Какие файлы git status покажет как {QUESTIONS[question]}? Отметьте все подходящие."
        ),
        code=CodeBlock(language="bash", text="\n".join(lines)),
        options=options,
        answer=AnswerSpec.multi(ids[n] for n in correct),
        misconception_answers={
            code: sorted((ids[n] for n in value), key=lambda x: int(x[1:])) for code, value in wrong.items()
        },
        features={
            "code_lines": len(lines),
            "concepts": len(
                {line.split()[1] for line in lines if line.startswith("git")} | {k.split()[1] for k in key}
            ),
            "options_count": len(options),
        },
        explanation=(
            f"Раздел {question}: {sorted(correct)}; ключевые команды: {key}; "
            f"модели ошибок: { {c: sorted(v) for c, v in wrong.items()} }."
        ),
    )


def _asked(v: Variant) -> str:
    for key, text in QUESTIONS.items():
        if f"как {text}?" in v.prompt:
            return key
    raise GitError("в условии нет вопроса")


def _answer_names(v: Variant) -> set[str]:
    assert v.options is not None
    by_id = {o.id: o.text for o in v.options}
    return {by_id[i] for i in v.answer.option_ids}


def selfcheck(v: Variant) -> list[str]:
    """Пересчёт: команды из текста заново исполняются симулятором, ответ сверяется с отмеченными файлами."""
    assert v.code is not None
    problems = []
    sim = ThreeTrees()
    try:
        sim.run(v.code.text.split("\n"))
    except GitError as exc:
        return [f"команды не исполняются: {exc}"]
    sets = dict(zip(("staged", "unstaged", "untracked"), sim.status(), strict=True))
    if sets[_asked(v)] != _answer_names(v):
        problems.append(f"пересчёт даёт {sorted(sets[_asked(v)])}, ключ {sorted(_answer_names(v))}")
    shown = {o.text for o in v.options or ()}
    if not set(sim.work) <= shown:
        problems.append("в рабочей копии есть файлы, которых нет среди вариантов")
    return problems


def oracle_check(v: Variant) -> list[str]:
    """Сверка с настоящим git: команды в временном репозитории, затем `git status --porcelain`."""
    assert v.code is not None
    with RealGit("files") as git:
        git.run(v.code.text.split("\n"))
        staged, unstaged, untracked = git.porcelain_sets()
    real = {"staged": staged, "unstaged": unstaged, "untracked": untracked}[_asked(v)]
    return [] if real == _answer_names(v) else [f"git показал {sorted(real)}, ключ {sorted(_answer_names(v))}"]
