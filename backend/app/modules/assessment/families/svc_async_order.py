"""Семейство `svc.async_order`: порядок вывода в программе на asyncio (text_input, режим tokens).

Уровень 1 — `create_task` запускает задачу только когда главная корутина уступает управление, `await` корутины идёт
без передачи управления. Уровень 2 — `asyncio.gather` запускает задачи параллельно. Уровень 3 — `asyncio.Semaphore`
ограничивает число одновременных задач. Ответ — вывод программы по дискретному симулятору событийного цикла
(`_Loop`: очередь готовых задач, таймеры с виртуальным временем, замок-семафор); моменты пробуждения всех таймеров
различны (иначе `Reject`), поэтому порядок не зависит от устройства кучи таймеров. Оракул — настоящий asyncio:
`oracle_check` исполняет текст программы на реальных часах с масштабом 10 мс на единицу задержки, `selfcheck` — на
цикле с виртуальным временем. Модели ошибок: `task_starts_immediately` (create_task запускает задачу сразу),
`gather_is_sequential` (gather ждёт задачи по очереди), `semaphore_ignored` (семафор не ограничивает).
"""

from __future__ import annotations

import asyncio
import contextlib
import heapq
import io
import types
from collections import deque
from collections.abc import Callable, Generator
from random import Random

from app.modules.assessment.families._lib import names
from app.modules.assessment.families._lib.contract import (
    AnswerSpec,
    CodeBlock,
    InputHint,
    OracleUnavailable,
    Reject,
    Variant,
)
from app.modules.assessment.families.registry import family_meta

META = family_meta(
    "svc.async_order",
    version=1,
    feature_bounds={
        1: {"code_lines": (12, 16), "concepts": (3, 3)},
        2: {"code_lines": (13, 16), "concepts": (3, 4)},
        3: {"code_lines": (17, 20), "concepts": (3, 4)},
    },
    misconceptions=("task_starts_immediately", "gather_is_sequential", "semaphore_ignored"),
)

SCALE = 0.01  # секунд реального времени на единицу задержки в оракуле


# --------------------------------------------------------------------------------------------------------------------
# Симулятор событийного цикла
# --------------------------------------------------------------------------------------------------------------------


class _Task:
    def __init__(self, gen: Generator) -> None:
        self.gen = gen
        self.done = False
        self.remaining = 0
        self.waiters: list[_Task] = []


class _Sem:
    def __init__(self, value: int) -> None:
        self.value = value
        self.waiters: deque[_Task] = deque()


class _Tie(Exception):
    """Два таймера просыпаются в один момент: порядок неоднозначен."""


class _Loop:
    """Дискретный цикл: задачи — генераторы, команды `("sleep", d)`, `("wait", [задачи])`, `("acquire", sem)`."""

    def __init__(self, *, eager_tasks: bool = False) -> None:
        self.now = 0
        self.ready: deque[_Task] = deque()
        self.timers: list[tuple[int, int, _Task]] = []
        self.eager = eager_tasks
        self._seq = 0
        self.out: list[str] = []

    def spawn(self, gen: Generator) -> _Task:
        """`create_task`: задача встаёт в очередь (в ошибочной модели запускается немедленно)."""
        task = _Task(gen)
        if self.eager:
            self._step(task)
        else:
            self.ready.append(task)
        return task

    def release(self, sem: _Sem) -> None:
        """Освобождение семафора: первый ожидающий просыпается в следующей итерации цикла."""
        if sem.waiters:
            self.ready.append(sem.waiters.popleft())
        else:
            sem.value += 1

    def _finish(self, task: _Task) -> None:
        task.done = True
        for waiter in task.waiters:
            waiter.remaining -= 1
            if waiter.remaining == 0:
                self.ready.append(waiter)

    def _step(self, task: _Task) -> None:
        try:
            cmd = next(task.gen)
        except StopIteration:
            self._finish(task)
            return
        kind = cmd[0]
        if kind == "sleep":
            when = self.now + cmd[1]
            if any(t[0] == when for t in self.timers):
                raise _Tie
            self._seq += 1
            heapq.heappush(self.timers, (when, self._seq, task))
        elif kind == "wait":
            pending = [t for t in cmd[1] if not t.done]
            if not pending:
                self.ready.append(task)
                return
            task.remaining = len(pending)  # gather/await: просыпаемся, когда завершится последняя из задач
            for t in pending:
                t.waiters.append(task)
        elif kind == "acquire":
            sem: _Sem = cmd[1]
            if sem.value > 0:
                sem.value -= 1
                self.ready.append(task)
            else:
                sem.waiters.append(task)

    def run(self, main: Generator) -> list[str]:
        """Выполнить главную корутину до конца, вернуть вывод по строкам-токенам."""
        self.spawn(main)
        while self.ready or self.timers:
            if self.ready:
                self._step(self.ready.popleft())
            else:
                self.now, _, task = heapq.heappop(self.timers)
                self.ready.append(task)
        return self.out


def _simulate(build: Callable[[_Loop], Generator], *, eager: bool = False) -> str:
    loop = _Loop(eager_tasks=eager)
    return " ".join(loop.run(build(loop)))


# --------------------------------------------------------------------------------------------------------------------
# Сценарии: текст программы + модель (общая спецификация)
# --------------------------------------------------------------------------------------------------------------------

JOB = 'async def job(name, d):\n    print("start", name)\n    await asyncio.sleep(d)\n    print("end", name)\n'
JOB_SEM = (
    "async def job(name, d, sem):\n"
    "    async with sem:\n"
    '        print("start", name)\n'
    "        await asyncio.sleep(d)\n"
    '        print("end", name)\n'
)


def _job_model(loop: _Loop, name: str, d: int, sem: _Sem | None = None) -> Generator:
    if sem is not None:
        yield ("acquire", sem)
    loop.out += ["start", name]
    yield ("sleep", d)
    loop.out += ["end", name]
    if sem is not None:
        loop.release(sem)


def _scenario_1(rng: Random) -> tuple[str, Callable, dict[str, Callable]]:
    a, b = rng.sample(names.LABELS, 2)
    da, db = rng.sample(range(1, 10), 2)
    use_sleep = rng.random() < 0.5
    middle = f"    await asyncio.sleep({db})\n" if use_sleep else f'    await job("{b}", {db})\n'
    text = (
        "import asyncio\n\n"
        + JOB
        + "\nasync def main():\n"
        + f'    t = asyncio.create_task(job("{a}", {da}))\n'
        + '    print("main 1")\n'
        + middle
        + '    print("main 2")\n'
        + "    await t\n"
        + '    print("main 3")\n\nasyncio.run(main())'
    )

    def model(loop: _Loop) -> Generator:
        t = loop.spawn(_job_model(loop, a, da))
        loop.out += ["main", "1"]
        if use_sleep:
            yield ("sleep", db)
        else:
            yield from _job_model(loop, b, db)
        loop.out += ["main", "2"]
        yield ("wait", [t])
        loop.out += ["main", "3"]

    return text, model, {"task_starts_immediately": lambda: _simulate(model, eager=True)}


def _scenario_2(rng: Random) -> tuple[str, Callable, dict[str, Callable]]:
    labels = rng.sample(names.LABELS, rng.randint(3, 4))
    delays = rng.sample(range(1, 10), len(labels))
    calls = ", ".join(f'job("{n}", {d})' for n, d in zip(labels, delays, strict=True))
    text = (
        "import asyncio\n\n"
        + JOB
        + "\nasync def main():\n"
        + '    print("main 1")\n'
        + f"    await asyncio.gather({calls})\n"
        + '    print("main 2")\n\nasyncio.run(main())'
    )

    def model(loop: _Loop) -> Generator:
        loop.out += ["main", "1"]
        tasks = [loop.spawn(_job_model(loop, n, d)) for n, d in zip(labels, delays, strict=True)]
        yield ("wait", tasks)
        loop.out += ["main", "2"]

    def sequential(loop: _Loop) -> Generator:
        loop.out += ["main", "1"]
        for n, d in zip(labels, delays, strict=True):
            yield from _job_model(loop, n, d)
        loop.out += ["main", "2"]

    return text, model, {"gather_is_sequential": lambda: _simulate(sequential)}


def _scenario_3(rng: Random) -> tuple[str, Callable, dict[str, Callable]]:
    labels = rng.sample(names.LABELS, rng.randint(4, 5))
    delays = rng.sample(range(1, 12), len(labels))
    limit = rng.choice((1, 2, 2, 3))
    text = (
        "import asyncio\n\n"
        + JOB_SEM
        + "\nasync def main():\n"
        + f"    sem = asyncio.Semaphore({limit})\n"
        + "    await asyncio.gather(\n"
        + "".join(f'        job("{n}", {d}, sem),\n' for n, d in zip(labels, delays, strict=True))
        + "    )\n"
        + '    print("done")\n\nasyncio.run(main())'
    )

    def build(value: int) -> Callable[[_Loop], Generator]:
        def model(loop: _Loop) -> Generator:
            sem = _Sem(value)
            tasks = [loop.spawn(_job_model(loop, n, d, sem)) for n, d in zip(labels, delays, strict=True)]
            yield ("wait", tasks)
            loop.out.append("done")

        return model

    return text, build(limit), {"semaphore_ignored": lambda: _simulate(build(len(labels)))}


def generate(level: int, seed: int) -> Variant:
    """Вариант: программа на asyncio и вопрос о порядке вывода.

    Ответ — вывод по симулятору событийного цикла. Модели ошибок: `task_starts_immediately` (уровень 1),
    `gather_is_sequential` (2), `semaphore_ignored` (3) — тот же симулятор с другим поведением. Вариант, где два
    таймера просыпаются одновременно, отбрасывается: порядок был бы неоднозначен. Ответ однозначен: задержки целые,
    моменты пробуждения различны, остальное порядок очереди готовых задач.
    """
    rng = Random(seed)
    text, model, alternatives = (_scenario_1, _scenario_2, _scenario_3)[level - 1](rng)
    try:
        answer = _simulate(model)
        wrong = {code: build() for code, build in alternatives.items()}
    except _Tie as exc:
        raise Reject("timer_tie") from exc
    wrong = {code: value for code, value in wrong.items() if value != answer}
    if not wrong:
        raise Reject("misconception_equals_answer")
    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt=(
            "Что напечатает программа? Задержки в sleep — секунды, вывод идёт по строкам; укажите все слова и числа "
            "через пробел в порядке вывода."
        ),
        code=CodeBlock(language="python", text=text),
        input=InputHint(placeholder="слова через пробел", max_length=120),
        answer=AnswerSpec.text(answer, mode="tokens"),
        misconception_answers=wrong,
        features={
            "code_lines": text.count("\n") + 1,
            "concepts": (3, 3, 4)[level - 1] if level != 2 else 3 + int("gather" in text),
        },
        explanation=f"Симулятор цикла даёт «{answer}»; модели ошибок: {wrong}.",
    )


# --------------------------------------------------------------------------------------------------------------------
# Выполнение настоящего asyncio
# --------------------------------------------------------------------------------------------------------------------


class _VirtualLoop(asyncio.SelectorEventLoop):
    """Цикл с виртуальным временем: пустая очередь готовых задач мгновенно переводит часы к ближайшему таймеру."""

    def __init__(self) -> None:
        super().__init__()
        self._vt = 0.0

    def time(self) -> float:
        return self._vt

    def _run_once(self) -> None:
        if not self._ready and self._scheduled:  # type: ignore[attr-defined]
            self._vt = max(self._vt, self._scheduled[0]._when)  # type: ignore[attr-defined]
        super()._run_once()  # type: ignore[misc]


def _execute(source: str, *, virtual: bool) -> str:
    """Исполнить программу настоящим asyncio; `virtual` — на цикле с виртуальным временем, иначе на реальных часах."""

    async def scaled_sleep(delay: float, *args: object) -> None:
        await asyncio.sleep(delay * SCALE, *args)

    proxy = types.SimpleNamespace(
        Semaphore=asyncio.Semaphore,
        create_task=asyncio.create_task,
        gather=asyncio.gather,
        sleep=asyncio.sleep if virtual else scaled_sleep,
        run=(lambda coro: asyncio.run(coro, loop_factory=_VirtualLoop)) if virtual else asyncio.run,
    )

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name != "asyncio":
            raise ImportError(name)
        return proxy

    buffer = io.StringIO()
    env = {
        "__builtins__": {"print": print, "__import__": fake_import, "__build_class__": __build_class__},
        "__name__": "__main__",
    }
    with contextlib.redirect_stdout(buffer):
        exec(compile(source, "<variant>", "exec"), env)
    return " ".join(buffer.getvalue().split())


def selfcheck(v: Variant) -> list[str]:
    """Перепроверка: текст программы исполняется настоящим asyncio на цикле с виртуальным временем."""
    assert v.code is not None
    try:
        got = _execute(v.code.text, virtual=True)
    except Exception as exc:
        return [f"программа не исполняется: {exc!r}"]
    return [] if got == v.answer.value else [f"asyncio (виртуальное время) даёт «{got}», ключ «{v.answer.value}»"]


def oracle_check(v: Variant) -> list[str]:
    """Сверка с настоящим asyncio на реальных часах (10 мс на единицу задержки); порядок не зависит от нагрузки."""
    assert v.code is not None
    try:
        got = _execute(v.code.text, virtual=False)
    except ImportError as exc:  # pragma: no cover
        raise OracleUnavailable("нет asyncio") from exc
    return [] if got == v.answer.value else [f"asyncio даёт «{got}», ключ «{v.answer.value}»"]
