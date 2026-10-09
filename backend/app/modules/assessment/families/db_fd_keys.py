"""Семейство `db.fd_keys`: функциональные зависимости, ключи и нормальные формы (приложение A, §3.3).

Выбор одного варианта. Уровень 1 — единственный потенциальный ключ; уровень 2 — несколько потенциальных ключей,
среди вариантов ровно один из них; уровень 3 — наивысшая нормальная форма из 1НФ, 2НФ, 3НФ, НФБК. Ключ считает
алгоритм замыкания атрибутов; отвлекающие варианты — надключи и неключи. Модели ошибок: выбран надключ,
не минимальный (`superkey_not_minimal`); выбрана левая часть зависимости, не ключ (`fd_lhs_is_key`); нормальная форма
завышена (`nf_overrated`) или занижена (`nf_underrated`).
"""

from __future__ import annotations

from collections.abc import Callable
from itertools import combinations
from random import Random

from app.modules.assessment.families._lib.contract import AnswerSpec, Option, Reject, Variant
from app.modules.assessment.families.registry import family_meta

META = family_meta(
    "db.fd_keys",
    version=2,
    feature_bounds={
        1: {"options_count": (5, 5), "concepts": (3, 5), "trap": (1, 1)},
        2: {"options_count": (5, 5), "concepts": (3, 6), "trap": (1, 1)},
        3: {"options_count": (4, 4), "concepts": (2, 5), "trap": (1, 1)},
    },
    misconceptions=("superkey_not_minimal", "fd_lhs_is_key", "nf_overrated", "nf_underrated"),
)  # fmt: skip

FD = tuple[frozenset[str], str]
_NF = ("1НФ", "2НФ", "3НФ", "НФБК")
_LETTERS = "ABCDEF"


def _closure_sets(attrs: frozenset[str], fds: list[FD]) -> frozenset[str]:
    """Замыкание неподвижной точкой по множествам."""
    result = set(attrs)
    changed = True
    while changed:
        changed = False
        for lhs, rhs in fds:
            if lhs <= result and rhs not in result:
                result.add(rhs)
                changed = True
    return frozenset(result)


def _closure_bits(attrs: frozenset[str], fds: list[FD]) -> frozenset[str]:
    """Второй способ: битовые маски и повтор прохода, пока маска растёт."""
    bit = {a: 1 << i for i, a in enumerate(_LETTERS)}
    mask = sum(bit[a] for a in attrs)
    rules = [(sum(bit[a] for a in lhs), bit[rhs]) for lhs, rhs in fds]
    while True:
        new = mask
        for need, add in rules:
            if need & new == need:
                new |= add
        if new == mask:
            break
        mask = new
    return frozenset(a for a in _LETTERS if bit[a] & mask)


def _keys(universe: frozenset[str], fds: list[FD], closure: Callable) -> list[frozenset[str]]:
    """Потенциальные ключи: минимальные надключи; перебор по возрастанию размера."""
    found: list[frozenset[str]] = []
    for size in range(1, len(universe) + 1):
        for combo in combinations(sorted(universe), size):
            candidate = frozenset(combo)
            if any(key <= candidate for key in found):
                continue
            if closure(candidate, fds) == universe:
                found.append(candidate)
    return found


def _normal_form(universe: frozenset[str], fds: list[FD], closure: Callable) -> str:
    """Наивысшая из НФ: 1НФ, 2НФ, 3НФ, НФБК — по определениям через ключи и замыкания."""
    keys = _keys(universe, fds, closure)
    prime = set().union(*keys)
    nontrivial = [(lhs, rhs) for lhs, rhs in fds if rhs not in lhs]
    if all(closure(lhs, fds) == universe for lhs, _ in nontrivial):
        return "НФБК"
    if all(closure(lhs, fds) == universe or rhs in prime for lhs, rhs in nontrivial):
        return "3НФ"
    for key in keys:
        for size in range(1, len(key)):
            for part in combinations(sorted(key), size):
                reach = closure(frozenset(part), fds) - set(part)
                if reach - prime:
                    return "1НФ"
    return "2НФ"


def _fmt_set(attrs: frozenset[str]) -> str:
    return "{" + ", ".join(sorted(attrs)) + "}"


def _fmt_fds(fds: list[FD]) -> str:
    return "; ".join(f"{', '.join(sorted(lhs))} → {rhs}" for lhs, rhs in fds)


def _chain_fds(rng: Random, order: list[str], key_size: int) -> list[FD]:
    """Зависимости вида «поздний атрибут определяется ранними»: ключ — первые `key_size` атрибутов порядка."""
    fds: list[FD] = []
    for i in range(key_size, len(order)):
        pool = order[:i]
        size = rng.choice([1, 2]) if len(pool) > 1 else 1
        lhs = frozenset(rng.sample(pool, min(size, len(pool))))
        fds.append((lhs, order[i]))
    return fds


def _nf_fds(rng: Random, target: str, letters: list[str]) -> list[FD]:
    """Зависимости, построенные под заданную высшую НФ (после проверка алгоритмом)."""
    a, b, c, d = letters[:4]
    extra = letters[4:5]
    f = frozenset
    if target == "НФБК":
        fds = [(f({a}), b), (f({a}), c), (f({a}), d)] if rng.random() < 0.5 else [(f({a, b}), c), (f({a, b}), d)]
        if extra:
            fds.append((fds[0][0], extra[0]))
    elif target == "3НФ":  # AB → C, C → B: B входит в ключ, поэтому 3НФ держится, а НФБК — нет
        fds = [(f({a, b}), c), (f({c}), b)]
        if extra:
            fds.append((f({a, b}), extra[0]))
        fds.append((f({a, b}), d))
    elif target == "2НФ":  # транзакционная зависимость A → B → C между неключевыми
        fds = [(f({a}), b), (f({b}), c), (f({a}), d)]
        if extra:
            fds.append((f({a}), extra[0]))
    else:  # частичная зависимость от части составного ключа
        fds = [(f({a}), c), (f({a, b}), d)]
        if extra:
            fds.append((f({a, b}), extra[0]))
    rng.shuffle(fds)
    return fds


def generate(level: int, seed: int) -> Variant:
    """Вариант: отношение R, набор зависимостей и пять вариантов ответа (на уровне 3 — четыре формы).

    Уровни 1-2: пять вариантов — один потенциальный ключ, два надключа с лишним атрибутом и два неключа (левые части
    зависимостей и подмножества ключа); на уровне 2 у отношения несколько ключей, а в вариантах ровно один.
    Уровень 3: цель (НФ) выбирается равновероятно, зависимости строятся под неё и проверяются алгоритмом.
    Ответ вычисляет алгоритм замыкания; модели ошибок: `superkey_not_minimal`, `fd_lhs_is_key`, `nf_overrated`,
    `nf_underrated`. Ответ однозначен: ключ определён как минимальный надключ, форма — как наивысшая из названных,
    в условии отношение считается атомарным. Варианты с неподходящим числом ключей отбрасываются.
    """
    rng = Random(seed)
    letters = rng.sample(_LETTERS, 5 if level < 3 else rng.choice([4, 5]))
    universe = frozenset(letters)
    if level == 3:
        target = _NF[rng.randrange(4)]
        fds = _nf_fds(rng, target, letters)
        form = _normal_form(universe, fds, _closure_sets)
        if form != target:
            raise Reject("nf_mismatch")
        texts = list(_NF)
        rng.shuffle(texts)
        ids = [f"o{i}" for i in range(1, 5)]
        by_text = dict(zip(texts, ids, strict=True))
        wrong = {}
        if target != "НФБК":
            wrong["nf_overrated"] = by_text[_NF[_NF.index(target) + 1]]
        if target != "1НФ":
            wrong["nf_underrated"] = by_text[_NF[_NF.index(target) - 1]]
        prompt = (
            f"Отношение R({', '.join(sorted(letters))}) атомарно (1НФ выполнена). Зависимости: {_fmt_fds(fds)}. "
            "Какая наивысшая из нормальных форм (1НФ, 2НФ, 3НФ, НФБК) выполнена для R?"
        )
        return _build(level, seed, prompt, texts, ids, by_text[target], wrong, len(fds), "Наивысшая НФ — " + target)
    order = letters[:]
    key_size = rng.choice([1, 2])
    fds = _chain_fds(rng, order, key_size)
    if level == 2:  # обратная зависимость создаёт второй ключ
        late = rng.choice(order[key_size:])
        fds.append((frozenset({late}), order[rng.randrange(key_size)]))
    rng.shuffle(fds)
    keys = _keys(universe, fds, _closure_sets)
    if (len(keys) != 1) if level == 1 else (len(keys) < 2):
        raise Reject("key_count")
    key = rng.choice(keys)
    superkeys = [key | {x} for x in sorted(universe - key)]  # надключ, содержащий ключ, не минимален
    lhs_wrong = [lhs for lhs, _ in fds if _closure_sets(lhs, fds) != universe and lhs not in superkeys]
    if len(superkeys) < 2:
        raise Reject("few_superkeys")
    nonkeys: list[frozenset[str]] = []
    # Ключ обходится в отсортированном виде: порядок обхода множества зависит от PYTHONHASHSEED, и один seed
    # давал бы разные варианты в разных процессах.
    key_parts = [frozenset({x}) for x in sorted(key) if len(key) > 1]
    for lhs in lhs_wrong + key_parts + [frozenset({a}) for a in order[::-1]]:
        if lhs not in nonkeys and _closure_sets(lhs, fds) != universe and lhs not in keys:
            nonkeys.append(lhs)
    if len(nonkeys) < 2:
        raise Reject("few_nonkeys")
    chosen_super = rng.sample(superkeys, 2)
    first_nonkey = rng.choice(lhs_wrong or nonkeys)
    second_nonkey = rng.choice([n for n in nonkeys if n != first_nonkey])
    sets = [key, *chosen_super, first_nonkey, second_nonkey]
    rng.shuffle(sets)
    texts = [_fmt_set(s) for s in sets]
    ids = [f"o{i}" for i in range(1, 6)]
    by_set = dict(zip(sets, ids, strict=True))
    wrong = {"superkey_not_minimal": by_set[chosen_super[0]], "fd_lhs_is_key": by_set[first_nonkey]}
    prompt = (
        f"Отношение R({', '.join(sorted(letters))}), зависимости: {_fmt_fds(fds)}. "
        "Какой из наборов атрибутов является потенциальным ключом R (минимальным набором, определяющим все атрибуты)?"
    )
    # Ключи печатаются через `_fmt_set`: `repr` множества зависел бы от PYTHONHASHSEED.
    listed = ", ".join(_fmt_set(item) for item in keys)
    return _build(level, seed, prompt, texts, ids, by_set[key], wrong, len(fds), f"Потенциальные ключи: {listed}")


def _build(
    level: int, seed: int, prompt: str, texts: list[str], ids: list[str], answer: str, wrong: dict[str, str],
    concepts: int, explanation: str,
) -> Variant:  # fmt: skip
    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt=prompt,
        options=tuple(Option(i, t) for i, t in zip(ids, texts, strict=True)),
        answer=AnswerSpec.choice(answer),
        misconception_answers=wrong,
        features={"options_count": len(ids), "concepts": concepts, "trap": 1},
        explanation=explanation,
    )


def _parse_fds(prompt: str) -> tuple[frozenset[str], list[FD]]:
    """Разобрать отношение и зависимости из текста условия."""
    head, rest = prompt.split("(", 1)[1].split(")", 1)
    universe = frozenset(a.strip() for a in head.split(","))
    body = rest.split("Зависимости:" if "Зависимости:" in rest else "зависимости:", 1)[1].split(". ", 1)[0]
    fds = []
    for part in body.split(";"):
        left, right = part.strip().rstrip(".").split("→")
        fds.append((frozenset(a.strip() for a in left.split(",")), right.strip()))
    return universe, fds


def selfcheck(v: Variant) -> list[str]:
    """Перепроверка: зависимости разбираются из текста, ключи и форма пересчитаны вторым способом (битовые маски)."""
    assert v.options is not None
    universe, fds = _parse_fds(v.prompt)
    text = {o.id: o.text for o in v.options}
    if len(set(text.values())) != len(text):
        return ["одинаковые варианты"]
    if v.level == 3:
        form = _normal_form(universe, fds, _closure_bits)
        return [] if text[str(v.answer.option_id)] == form else [f"форма по маскам: {form}"]
    keys = {_fmt_set(k) for k in _keys(universe, fds, _closure_bits)}
    matching = [o for o in text if text[o] in keys]
    problems = []
    if matching != [v.answer.option_id]:
        problems.append(f"ключами по маскам оказались варианты {matching}")
    if v.level == 1 and len(keys) != 1:
        problems.append("на уровне 1 ключ должен быть единственным")
    return problems
