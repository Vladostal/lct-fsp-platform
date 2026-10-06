"""Симулятор git для семейств `git.*` и настоящий git как независимый оракул (приложение A, §2.2, §3.3; Арх. 5.3).

Две модели с общей записью команд — строкой в синтаксисе git, чтобы одна и та же запись шла и в условие, и в
симулятор, и в настоящий `git` во временном каталоге:

* `GitGraph` — граф коммитов: `commit`, `branch`, `checkout`, `merge`, `reset`, `revert`, `cherry-pick`, `rebase`.
  Коммит — целое число; содержимое файлов не моделируется, потому что генераторы строят только истории без
  конфликтов (каждый коммит добавляет свой файл). Это допущение проверяет оракул.
* `ThreeTrees` — три дерева (HEAD, индекс, рабочая копия) для `add`, `commit`, `reset`, `restore`, `stash`.

Ошибочные команды (нечего коммитить, нет такого файла, ссылка за началом истории) — `GitError`: генератор
превращает его в `Reject`. Модели ошибок кандидата задаются флагами симулятора (`flags`).
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path

from app.modules.assessment.families._lib.contract import OracleUnavailable

__all__ = ["GitError", "GitGraph", "GitScript", "RealGit", "ThreeTrees", "status_sets"]


class GitError(Exception):
    """Команда была бы отклонена настоящим git или выходит за поддерживаемое подмножество."""


_SPEC = re.compile(r"^([A-Za-z][\w/.-]*)(?:~(\d+))?$")


# --------------------------------------------------------------------------------------------------------------------
# Граф коммитов
# --------------------------------------------------------------------------------------------------------------------


class GitGraph:
    """Граф коммитов с ветками и HEAD. Начальное состояние — пустой репозиторий, ветка `main` не создана.

    Флаги моделей ошибок: `first_parent` (счёт идёт только по первым родителям), `reset_keeps_history` (reset
    ничего не убирает из истории), `revert_noop` (revert не создаёт коммита), `detached_moves_branch` (коммиты
    при отсоединённом HEAD двигают ветку, с которой ушли), `merge_always_commit` (слияние всегда создаёт коммит,
    даже при перемотке), `cherry_pick_links_original` (cherry-pick делает исходный коммит достижимым),
    `squash_keeps_all` (`merge --squash` переносит все коммиты как обычное слияние).
    """

    def __init__(self, flags: Iterable[str] = ()) -> None:
        self.flags = frozenset(flags)
        self.parents: dict[int, tuple[int, ...]] = {}
        self.branches: dict[str, int] = {}
        self.cur: str | None = "main"
        self.detached: int | None = None
        self.left_branch: str | None = None
        self.replayed: list[tuple[int, int]] = []  # (старый коммит, новый коммит) последнего rebase
        # Файлы: коммит добавляет файл (`adds`) или удаляет его (`deletes`, у revert). Нужны, чтобы отсеять
        # последовательности, на которых настоящий git дал бы конфликт или пустой коммит.
        self.adds: dict[int, int] = {}
        self.deletes: dict[int, int] = {}
        self._next = 1

    # -- ссылки ----------------------------------------------------------------------------------------------------

    def head(self) -> int | None:
        """Коммит, на который указывает HEAD."""
        return self.branches.get(self.cur) if self.cur else self.detached

    def resolve(self, spec: str) -> int:
        """`name`, `name~k`, `HEAD`, `HEAD~k` -> коммит; `GitError`, если ссылки нет."""
        m = _SPEC.match(spec)
        if not m:
            raise GitError(f"неподдерживаемая ссылка {spec}")
        name, steps = m.group(1), int(m.group(2) or 0)
        commit = self.head() if name == "HEAD" else self.branches.get(name)
        if commit is None:
            raise GitError(f"нет ссылки {name}")
        for _ in range(steps):
            if not self.parents[commit]:
                raise GitError(f"{spec}: за началом истории")
            commit = self.parents[commit][0]
        return commit

    def reach(self, commit: int | None) -> set[int]:
        """Все коммиты, достижимые из `commit` (включая его)."""
        seen: set[int] = set()
        stack = [] if commit is None else [commit]
        first_only = "first_parent" in self.flags
        while stack:
            c = stack.pop()
            if c in seen:
                continue
            seen.add(c)
            parents = self.parents[c]
            stack.extend(parents[:1] if first_only else parents)
        return seen

    def count(self, spec: str) -> int:
        """Сколько коммитов покажет `git log --oneline spec`."""
        return len(self.reach(self.resolve(spec)))

    def count_range(self, base: str, tip: str) -> int:
        """Сколько коммитов покажет `git log base..tip`."""
        return len(self.reach(self.resolve(tip)) - self.reach(self.resolve(base)))

    # -- команды ---------------------------------------------------------------------------------------------------

    def run(self, lines: Iterable[str]) -> GitGraph:
        """Выполнить команды по порядку; возвращает себя."""
        for line in lines:
            self.apply(line)
        return self

    def _move(self, commit: int) -> None:
        if self.cur:
            self.branches[self.cur] = commit
        else:
            self.detached = commit
            if "detached_moves_branch" in self.flags and self.left_branch:
                self.branches[self.left_branch] = commit

    def _new(self, parents: tuple[int, ...]) -> int:
        commit = self._next
        self._next += 1
        self.parents[commit] = parents
        return commit

    def apply(self, line: str) -> None:
        """Одна команда; неизвестная или недопустимая — `GitError`."""
        args = shlex.split(line)
        if args[:1] != ["git"] or len(args) < 2:
            raise GitError(f"не команда git: {line}")
        cmd, rest = args[1], args[2:]
        head = self.head()
        if cmd == "commit":
            commit = self._new(() if head is None else (head,))
            self.adds[commit] = commit
            self._move(commit)
        elif cmd == "branch":
            if head is None or rest[0] in self.branches:
                raise GitError("ветку нельзя создать")
            self.branches[rest[0]] = head
        elif cmd == "checkout":
            self._checkout(rest)
        elif cmd == "merge":
            self._merge(rest)
        elif cmd == "reset":
            if rest[0] != "--hard" or head is None:
                raise GitError("поддержан только reset --hard")
            target = self.resolve(rest[1])
            if "reset_keeps_history" not in self.flags:
                self._move(target)
        elif cmd == "revert":
            target = self.resolve(next(a for a in rest if not a.startswith("--")))
            if len(self.parents[target]) != 1 or target not in self.reach(head) or target not in self.adds:
                raise GitError("revert: нужен обычный коммит текущей истории")
            if self.adds[target] in self._deleted_files(head):
                raise GitError("revert: файл уже удалён")
            assert head is not None
            if "revert_noop" not in self.flags:
                commit = self._new((head,))
                self.deletes[commit] = self.adds[target]
                self._move(commit)
        elif cmd == "cherry-pick":
            target = self.resolve(next(a for a in rest if not a.startswith("--")))
            if target in self.reach(head) or len(self.parents[target]) != 1 or target not in self.adds:
                raise GitError("cherry-pick: нужен обычный коммит вне текущей истории")
            present = {self.adds[c] for c in self.reach(head) if c in self.adds}
            if self.adds[target] in present or self.adds[target] in self._deleted_files(head):
                raise GitError("cherry-pick: файл уже есть в истории")
            assert head is not None
            linked = "cherry_pick_links_original" in self.flags
            commit = self._new((head, target) if linked else (head,))
            self.adds[commit] = self.adds[target]
            self._move(commit)
        elif cmd == "rebase":
            self._rebase(rest)
        else:
            raise GitError(f"неподдерживаемая команда {cmd}")

    def _deleted_files(self, head: int | None) -> set[int]:
        return {self.deletes[c] for c in self.reach(head) if c in self.deletes}

    def _checkout(self, rest: list[str]) -> None:
        if rest[0] == "-b":
            head = self.head()
            if head is None or rest[1] in self.branches:
                raise GitError("ветку нельзя создать")
            self.branches[rest[1]] = head
            self.cur, self.detached = rest[1], None
        elif rest[0] in self.branches:
            self.cur, self.detached = rest[0], None
        else:
            commit = self.resolve(rest[0])
            self.left_branch = self.cur or self.left_branch
            self.cur, self.detached = None, commit

    def _merge(self, rest: list[str]) -> None:
        squash, no_ff = "--squash" in rest, "--no-ff" in rest
        name = next(a for a in rest if not a.startswith("--"))
        head, target = self.head(), self.resolve(name)
        if self.cur is None or head is None:
            raise GitError("merge: нужна ветка с коммитами")
        if target in self.reach(head):
            return
        if squash and "squash_keeps_all" not in self.flags:
            return  # изменения попадают в индекс; граф меняет следующий `git commit`
        if head in self.reach(target) and not no_ff and "merge_always_commit" not in self.flags:
            self._move(target)
        else:
            commit = self._new((head, target))
            self._move(commit)

    def _replay(self, commits: Sequence[int], onto: int) -> int:
        tip = onto
        self.replayed = []
        for old in commits:
            tip = self._new((tip,))
            if old in self.adds:
                self.adds[tip] = self.adds[old]
            if old in self.deletes:
                self.deletes[tip] = self.deletes[old]
            self.replayed.append((old, tip))
        return tip

    def _linear_range(self, tip: int, stop: int) -> list[int]:
        """Коммиты `stop..tip` от старых к новым; слияния внутри диапазона не поддерживаются."""
        exclude = self.reach(stop)
        chain: list[int] = []
        commit = tip
        while commit not in exclude:
            if len(self.parents[commit]) != 1:
                raise GitError("rebase: слияния в диапазоне не поддерживаются")
            chain.append(commit)
            commit = self.parents[commit][0]
        if self.reach(tip) - exclude != set(chain):
            raise GitError("rebase: диапазон нелинеен")
        return chain[::-1]

    def _rebase(self, rest: list[str]) -> None:
        if self.cur is None:
            raise GitError("rebase: нужна ветка")
        if rest[0] == "--onto":
            onto, old = self.resolve(rest[1]), self.resolve(rest[2])
            branch = rest[3] if len(rest) > 3 else self.cur
            if branch not in self.branches:
                raise GitError("rebase: нет ветки")
            self.cur, self.detached = branch, None
            chain = self._linear_range(self.branches[branch], old)
            self.branches[branch] = self._replay(chain, onto)
            return
        upstream = self.resolve(rest[0])
        tip = self.branches[self.cur]
        if upstream in self.reach(tip):
            self.replayed = []
            return
        if tip in self.reach(upstream):
            self.replayed = []
            self.branches[self.cur] = upstream
            return
        self.branches[self.cur] = self._replay(self._linear_range(tip, upstream), upstream)


class GitScript:
    """Построитель сценария для генераторов: команды проверяются живым симулятором, `commit` нумеруется."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.sim = GitGraph()
        self._n = 0

    def add(self, line: str) -> bool:
        """Добавить команду, если симулятор её принимает; иначе вернуть False и ничего не менять."""
        try:
            self.sim.apply(line)
        except GitError:
            return False
        self.lines.append(line)
        return True

    def commit(self, times: int = 1) -> None:
        """`times` коммитов подряд с сообщениями c1, c2, …"""
        for _ in range(times):
            self._n += 1
            self.add(f'git commit -m "c{self._n}"')


# --------------------------------------------------------------------------------------------------------------------
# Три дерева
# --------------------------------------------------------------------------------------------------------------------

Tree = dict[str, str]


class ThreeTrees:
    """Рабочая копия, индекс и коммиты. Содержимое файла — строка из дописанных `echo` строк.

    Поддержаны: `echo TEXT > f`, `echo TEXT >> f`, `git add f|.`, `git commit -m ..`, `git reset
    [--soft|--mixed|--hard] HEAD~k`, `git restore f`, `git restore --staged f`, `git stash [-u]`.

    Флаги моделей ошибок: `soft_resets_index` (`--soft` сбрасывает индекс), `mixed_is_hard` (`--mixed` трогает и
    рабочую копию), `hard_cleans_untracked` (`--hard`
    удаляет и неотслеживаемые файлы), `restore_resets_index` (`restore f` откатывает и индекс), `stash_takes_untracked`
    (`stash` без `-u` прячет и неотслеживаемые файлы).
    """

    def __init__(self, flags: Iterable[str] = ()) -> None:
        self.flags = frozenset(flags)
        self.commits: list[Tree] = []
        self.head = -1  # индекс в `commits`
        self.index: Tree = {}
        self.work: Tree = {}

    def head_tree(self) -> Tree:
        """Снимок HEAD (пустой до первого коммита)."""
        return self.commits[self.head] if self.head >= 0 else {}

    def run(self, lines: Iterable[str]) -> ThreeTrees:
        """Выполнить команды по порядку; возвращает себя."""
        for line in lines:
            self.apply(line)
        return self

    def apply(self, line: str) -> None:
        """Одна команда; недопустимая — `GitError`."""
        args = shlex.split(line)
        if args[0] == "echo":
            self._echo(args)
            return
        if args[:1] != ["git"]:
            raise GitError(f"не команда: {line}")
        cmd, rest = args[1], args[2:]
        if cmd == "add":
            self._add(rest[0])
        elif cmd == "commit":
            snapshot = dict(self.index)
            if snapshot == self.head_tree():
                raise GitError("нечего коммитить")
            self.commits = [*self.commits[: self.head + 1], snapshot]
            self.head += 1
        elif cmd == "reset":
            self._reset(rest)
        elif cmd == "restore":
            self._restore(rest)
        elif cmd == "stash":
            self._stash("-u" in rest)
        else:
            raise GitError(f"неподдерживаемая команда {cmd}")

    def _echo(self, args: list[str]) -> None:
        if len(args) != 4 or args[2] not in (">", ">>"):
            raise GitError("echo: ожидается `echo текст > файл`")
        text, op, name = args[1], args[2], args[3]
        if op == ">":
            if name in self.work:
                raise GitError("echo >: файл уже есть")
            self.work[name] = text
        else:
            if name not in self.work:
                raise GitError("echo >>: нет файла")
            self.work[name] += "\n" + text

    def _add(self, target: str) -> None:
        names = list(self.work) if target == "." else [target]
        for name in names:
            if name not in self.work:
                raise GitError(f"add: нет файла {name}")
            self.index[name] = self.work[name]

    def _reset(self, rest: list[str]) -> None:
        mode = next((a[2:] for a in rest if a.startswith("--")), "mixed")
        spec = next((a for a in rest if not a.startswith("--")), "HEAD")
        m = re.fullmatch(r"HEAD(?:~(\d+))?", spec)
        if not m or self.head < 0:
            raise GitError("reset: поддержан только HEAD~k")
        new_head = self.head - int(m.group(1) or 0)
        if new_head < 0:
            raise GitError("reset: за началом истории")
        self.head = new_head
        target = self.commits[new_head]
        if mode == "soft" and "soft_resets_index" in self.flags:
            mode = "mixed"
        if mode == "mixed" and "mixed_is_hard" in self.flags:
            mode = "hard"
        if mode in ("mixed", "hard"):
            old_index = self.index
            self.index = dict(target)
            if mode == "hard":
                for name in list(self.work):
                    if name in target:
                        self.work[name] = target[name]
                    elif name in old_index or "hard_cleans_untracked" in self.flags:
                        del self.work[name]

    def _restore(self, rest: list[str]) -> None:
        staged = "--staged" in rest
        name = rest[-1]
        head = self.head_tree()
        if staged:
            if name not in self.index:
                raise GitError("restore --staged: файла нет в индексе")
            if name in head:
                self.index[name] = head[name]
            else:
                del self.index[name]
            return
        if name not in self.index:
            raise GitError("restore: файла нет в индексе")
        if "restore_resets_index" in self.flags:
            self.index[name] = head[name] if name in head else self.index[name]
            self.work[name] = self.index[name]
        else:
            self.work[name] = self.index[name]

    def _stash(self, include_untracked: bool) -> None:
        include_untracked = include_untracked or "stash_takes_untracked" in self.flags
        head = self.head_tree()
        clean = self.index == head and all(self.work.get(n) == self.index.get(n) for n in self.index)
        if clean and not (include_untracked and any(n not in self.index for n in self.work)):
            raise GitError("stash: нечего прятать")
        for name in list(self.work):
            tracked = name in self.index
            if name in head:
                self.work[name] = head[name]
            elif tracked or include_untracked:
                del self.work[name]
        self.index = dict(head)

    # -- состояние ---------------------------------------------------------------------------------------------------

    def status(self) -> tuple[set[str], set[str], set[str]]:
        """(в индексе, изменены в рабочей копии, неотслеживаемые) — то, что показывает `git status`."""
        return status_sets(self.head_tree(), self.index, self.work)


def status_sets(head: Tree, index: Tree, work: Tree) -> tuple[set[str], set[str], set[str]]:
    """Три множества `git status`: staged (индекс != HEAD), unstaged (рабочая != индекс), untracked."""
    staged = {n for n in set(head) | set(index) if index.get(n) != head.get(n)}
    unstaged = {n for n in index if n in work and work[n] != index[n]}
    untracked = {n for n in work if n not in index}
    return staged, unstaged, untracked


# --------------------------------------------------------------------------------------------------------------------
# Настоящий git
# --------------------------------------------------------------------------------------------------------------------


class RealGit:
    """Настоящий git во временном каталоге: оракул для `GitGraph` и `ThreeTrees`.

    Использование: `with RealGit("graph") as g: g.run(lines); g.count("main")`. Режим `graph` — `git commit`
    предварительно создаёт новый файл (история без конфликтов); режим `files` — команды исполняются как написаны,
    `echo` выполняется самим классом. Окружение изолировано от настроек пользователя; время коммитов растёт с
    каждой командой, чтобы cherry-pick не создал побайтно тот же коммит.
    """

    def __init__(self, mode: str = "graph") -> None:
        if mode not in ("graph", "files"):
            raise ValueError(mode)
        self.mode = mode
        self._tmp = tempfile.TemporaryDirectory(prefix="fsp-git-")
        self.path = Path(self._tmp.name)
        self._clock = 1_700_000_000
        self._files = 0
        self._git(["init", "-q", "-b", "main"])

    def __enter__(self) -> RealGit:
        return self

    def __exit__(self, *exc: object) -> None:
        self._tmp.cleanup()

    def _git(self, args: Sequence[str], *, check: bool = True) -> str:
        self._clock += 1
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(self.path),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_EDITOR": "true",
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
            "GIT_AUTHOR_DATE": f"{self._clock} +0000",
            "GIT_COMMITTER_DATE": f"{self._clock} +0000",
        }
        try:
            done = subprocess.run(
                ["git", "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
                cwd=self.path, env=env, capture_output=True, text=True, timeout=20, check=False,
            )  # fmt: skip
        except FileNotFoundError as exc:
            raise OracleUnavailable("нет git") from exc
        if check and done.returncode != 0:
            raise GitError(f"git {' '.join(args)}: {done.stderr.strip()}")
        return done.stdout

    def run(self, lines: Iterable[str]) -> RealGit:
        """Выполнить команды; ошибка git — `GitError`."""
        for line in lines:
            self.apply(line)
        return self

    def apply(self, line: str) -> None:
        """Одна команда в том виде, в каком она записана в условии."""
        args = shlex.split(line)
        if args[0] == "echo":
            text, op, name = args[1], args[2], args[3]
            with (self.path / name).open("a" if op == ">>" else "x", encoding="utf-8") as fh:
                fh.write(text + "\n")
            return
        rest = args[1:]
        if self.mode == "graph" and rest[0] == "commit":
            self._files += 1
            (self.path / f"f{self._files}.txt").write_text(f"{self._files}\n", encoding="utf-8")
            self._git(["add", "-A"])
            self._git(["commit", "-q", "-m", f"c{self._files}"])
        elif rest[0] == "merge" and "--squash" not in rest:
            self._git(["merge", "--no-edit", *rest[1:]])
        elif rest[0] == "revert":
            self._git(["revert", "--no-edit", *rest[1:]])
        else:
            self._git(rest)

    def rev_list(self, *specs: str) -> list[str]:
        """`git rev-list spec...` — список хэшей."""
        return self._git(["rev-list", *specs]).split()

    def count(self, spec: str) -> int:
        """Число коммитов `git log --oneline spec`."""
        return len(self.rev_list(spec))

    def count_range(self, base: str, tip: str) -> int:
        """Число коммитов `git log base..tip`."""
        return len(self.rev_list(f"{base}..{tip}"))

    def rev(self, spec: str) -> str:
        """Хэш коммита по ссылке."""
        return self._git(["rev-parse", spec]).strip()

    def is_ancestor(self, old: str, new: str) -> bool:
        """Достижим ли `old` из `new`."""
        self._clock += 1
        done = subprocess.run(
            ["git", "merge-base", "--is-ancestor", old, new], cwd=self.path, capture_output=True, check=False
        )
        return done.returncode == 0

    def porcelain_sets(self) -> tuple[set[str], set[str], set[str]]:
        """(в индексе, изменены в рабочей копии, неотслеживаемые) по `git status --porcelain`."""
        staged, unstaged, untracked = set(), set(), set()
        for row in self._git(["status", "--porcelain", "-uall"]).splitlines():
            x, y, name = row[0], row[1], row[3:]
            if row.startswith("??"):
                untracked.add(name)
                continue
            if x != " ":
                staged.add(name)
            if y != " ":
                unstaged.add(name)
        return staged, unstaged, untracked
