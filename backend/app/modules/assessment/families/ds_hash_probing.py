"""Семейство «Хеш-таблица и коллизии»: h(k) = k mod m, цепочки, линейное пробирование, метки удаления."""

from __future__ import annotations

import re
from random import Random

from app.modules.assessment.families._lib.contract import AnswerSpec, InputHint, Reject, Variant
from app.modules.assessment.families.registry import family_meta

META = family_meta(
    "ds.hash_probing",
    version=1,
    feature_bounds={
        1: {"concepts": (1, 1), "timeline_events": (2, 16), "answer_abs": (2, 6)},
        2: {"concepts": (2, 2), "timeline_events": (5, 8), "answer_abs": (0, 12), "trap": (1, 1)},
        3: {"concepts": (3, 3), "timeline_events": (7, 9), "answer_abs": (2, 12), "trap": (1, 1)},
    },
)

TOMB = -1


def _longest_chain(m: int, keys: list[int]) -> int:
    """Модель уровня 1: длина самой длинной цепочки."""
    chains: dict[int, int] = {}
    for k in keys:
        chains[k % m] = chains.get(k % m, 0) + 1
    return max(chains.values())


def _insert(cells: list[int | None], k: int) -> tuple[int, int]:
    """Линейное пробирование: (ячейка, число проб)."""
    m = len(cells)
    for probe in range(m):
        idx = (k % m + probe) % m
        if cells[idx] is None:
            cells[idx] = k
            return idx, probe + 1
    raise Reject("table_full")


def _search(cells: list[int | None], k: int, *, stop_at_tomb: bool = False) -> int:
    """Число проб при поиске: до ключа или до пустой ячейки; метка не пустая (если не `stop_at_tomb`)."""
    m = len(cells)
    for probe in range(m):
        cell = cells[(k % m + probe) % m]
        if cell == k:
            return probe + 1
        if cell is None or (stop_at_tomb and cell == TOMB):
            return probe + 1
    return m


def _level1(rng: Random) -> dict[str, object]:
    m = rng.randint(4, 6)
    target = rng.randint(2, 6)
    hot = rng.randrange(m)
    residues = [hot] * target
    for r in range(m):
        if r != hot:
            residues += [r] * rng.randint(0, min(target - 1, 2))
    rng.shuffle(residues)
    used: set[int] = set()
    out: list[int] = []
    for r in residues:
        while True:
            k = r + m * rng.randint(0, 12)
            if k not in used:
                used.add(k)
                out.append(k)
                break
    return {"m": m, "keys": out}


def generate(level: int, seed: int) -> Variant:
    """Вариант хеш-таблицы с `h(k) = k mod m`; вопрос зависит от уровня.

    Уровень 1 — цепочки: длина самой длинной (ошибка `no_collision`: кандидат отвечает 1, считая, что ключи не
    сталкиваются). Уровень 2 — линейное пробирование: ячейка последнего ключа или число проб его вставки; ключ
    всегда попадает в занятую ячейку (ошибка `no_collision` — ответ «как без коллизии»: `k mod m` или 1).
    Уровень 3 — после вставок часть ключей удалена, ячейка помечена; вопрос — число проб поиска ключа (в том числе
    отсутствующего), метка не прерывает поиск (ошибка `ignore_tombstone` — поиск обрывается на метке). Вставок
    после удалений нет, поэтому правило повторного использования метки не нужно. Ответ — симуляция таблицы.
    """
    if level not in (1, 2, 3):
        raise ValueError(f"нет уровня {level}")
    rng = Random(seed)
    if level == 1:
        p = _level1(rng)
        m, keys = p["m"], p["keys"]
        answer = _longest_chain(m, keys)
        text = (
            f"Хеш-таблица из {m} ячеек, h(k) = k mod {m}, коллизии разрешаются цепочками (новый ключ — в конец "
            f"цепочки). Вставляются ключи: {', '.join(map(str, keys))}. Чему равна длина самой длинной цепочки? "
            "Целое число."
        )
        wrong = {"no_collision": 1}
        events = len(keys)
        trap = None
    elif level == 2:
        m = rng.randint(7, 10)
        count = rng.randint(5, 8)
        cells: list[int | None] = [None] * m
        keys: list[int] = []
        used: set[int] = set()
        while len(keys) < count:
            k = rng.randint(10, 99)
            if k in used:
                continue
            used.add(k)
            keys.append(k)
        for k in keys[:-1]:
            _insert(cells, k)
        occupied = [i for i, c in enumerate(cells) if c is not None]
        last = keys[-1]
        # Последний ключ подгоняется под занятую ячейку: иначе коллизии нет и ошибка не меняет ответ.
        want = rng.choice(occupied)
        last = want + m * rng.randint(2, 12)
        if last in used:
            raise Reject("last_key_clash")
        keys[-1] = last
        cell, probes = _insert(cells, last)
        ask_cell = rng.random() < 0.7
        if ask_cell:
            answer, wrong = cell, {"no_collision": last % m}
            question = "В какой ячейке (нумерация с 0) окажется последний ключ?"
        else:
            answer, wrong = probes, {"no_collision": 1}
            question = "Сколько проб (проверок ячеек) потребует вставка последнего ключа, считая и успешную?"
        text = (
            f"Хеш-таблица из {m} ячеек (номера с 0), h(k) = k mod {m}, коллизии — линейное пробирование "
            f"(шаг +1 по кругу). Вставляются ключи: {', '.join(map(str, keys))}. {question} Целое число."
        )
        events = len(keys)
        trap = 1
    else:
        m = rng.randint(8, 10)
        count = rng.randint(6, 7)
        cells = [None] * m
        keys = rng.sample(range(10, 100), count)
        for k in keys:
            _insert(cells, k)
        deleted = rng.sample(keys, rng.randint(1, 2))
        for k in deleted:
            cells[cells.index(k)] = TOMB
        cases: list[tuple[int, bool]] = []
        for k in keys:
            if k not in deleted and _search(cells, k) != _search(cells, k, stop_at_tomb=True):
                cases.append((k, True))
        for _ in range(12):
            k = rng.randint(10, 99)
            if k not in keys and _search(cells, k) != _search(cells, k, stop_at_tomb=True):
                cases.append((k, False))
        if not cases:
            raise Reject("tombstone_off_path")
        query, _ = rng.choice(cases)
        answer = _search(cells, query)
        wrong = {"ignore_tombstone": _search(cells, query, stop_at_tomb=True)}
        text = (
            f"Хеш-таблица из {m} ячеек (номера с 0), h(k) = k mod {m}, линейное пробирование (шаг +1 по кругу). "
            f"Вставлены ключи по порядку: {', '.join(map(str, keys))}. Затем удалены ключи: "
            f"{', '.join(map(str, deleted))}; ячейка удалённого ключа помечена «удалено» и не считается пустой. "
            f"Сколько проб (проверок ячеек) потребует поиск ключа {query}? Поиск идёт, пока не найден ключ или не "
            "встретится пустая ячейка. Целое число."
        )
        events = len(keys) + len(deleted)
        trap = 1
    if answer in wrong.values():
        raise Reject("misconception_equals_answer")
    features = {"concepts": level, "timeline_events": events, "answer_abs": answer}
    if trap is not None:
        features["trap"] = trap
    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt=text,
        input=InputHint(placeholder="целое число", max_length=4),
        answer=AnswerSpec.numeric(answer),
        misconception_answers=wrong,
        features=features,
        explanation=f"Симуляция таблицы даёт {answer}. Ответ модели ошибки: {wrong}.",
    )


def selfcheck(v: Variant) -> list[str]:
    """Перепроверка: ответ положителен и числа в условии согласованы с уровнем."""
    problems = []
    numbers = [int(x) for x in re.findall(r"\d+", v.prompt.split("Вставля")[0])]
    if not numbers or numbers[0] < 4:
        problems.append("не разобран размер таблицы")
    if not isinstance(v.answer.value, int) or v.answer.value < 0:
        problems.append("ответ должен быть неотрицательным целым")
    return problems


def _oracle_table(m: int, keys: list[int], deleted: list[int]) -> dict[int, object]:
    """Оракул: таблица как словарь «ячейка -> ключ или метка», другой способ обхода ячеек (itertools)."""
    from itertools import chain, islice

    table: dict[int, object] = {}
    for k in keys:
        for idx in islice(chain(range(k % m, m), range(k % m)), m):
            if idx not in table:
                table[idx] = k
                break
    for k in deleted:
        for idx, value in table.items():
            if value == k:
                table[idx] = "tomb"
                break
    return table


def oracle_check(v: Variant) -> list[str]:
    """Оракул CPython: условие разбирается регулярными выражениями, таблица строится вторым способом."""
    from itertools import chain, islice

    text = v.prompt
    m = int(re.search(r"из (\d+) ячеек", text).group(1))  # type: ignore[union-attr]
    keys = [int(x) for x in re.search(r"ключи(?: по порядку)?: ([\d, ]+)\.", text).group(1).split(",")]  # type: ignore[union-attr]
    if v.level == 1:
        buckets: dict[int, list[int]] = {}
        for k in keys:
            buckets.setdefault(k % m, []).append(k)
        expected = max(len(b) for b in buckets.values())
    elif v.level == 2:
        table = _oracle_table(m, keys[:-1], [])
        last = keys[-1]
        path = list(islice(chain(range(last % m, m), range(last % m)), m))
        probes = next(i for i, idx in enumerate(path, 1) if idx not in table)
        expected = path[probes - 1] if "В какой ячейке" in text else probes
    else:
        deleted = [int(x) for x in re.search(r"удалены ключи: ([\d, ]+);", text).group(1).split(",")]  # type: ignore[union-attr]
        query = int(re.search(r"поиск ключа (\d+)\?", text).group(1))  # type: ignore[union-attr]
        table = _oracle_table(m, keys, deleted)
        path = list(islice(chain(range(query % m, m), range(query % m)), m))
        expected = len(path)
        for i, idx in enumerate(path, 1):
            if idx not in table or table[idx] == query:
                expected = i
                break
    return [] if expected == v.answer.value else [f"оракул даёт {expected}, ключ {v.answer.value}"]
