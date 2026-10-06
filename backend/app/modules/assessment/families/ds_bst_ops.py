"""Семейство «Дерево поиска»: высота, обход и форма после вставок и удалений (приложение A, §3.1)."""

from __future__ import annotations

import re
from random import Random

from app.modules.assessment.families._lib.contract import AnswerSpec, InputHint, Reject, Variant
from app.modules.assessment.families._lib.miniprog import tokens
from app.modules.assessment.families.registry import family_meta

META = family_meta(
    "ds.bst_ops",
    version=1,
    feature_bounds={
        1: {"concepts": (1, 1), "timeline_events": (8, 11), "answer_abs": (2, 9)},
        2: {"concepts": (2, 2), "timeline_events": (8, 11), "answer_abs": (1, 99), "trap": (1, 1)},
        3: {"concepts": (3, 3), "timeline_events": (11, 15), "answer_abs": (1, 400), "trap": (1, 1)},
    },
    # В реестре одна модель; на уровне 1 ей нечего менять, поэтому добавлена модель счёта узлов вместо рёбер.
    misconceptions=("predecessor_instead_of_successor", "height_in_nodes"),
)

DELETE_RULE = (
    "Удаление: лист просто убирается; у узла с одним потомком его заменяет потомок; узел с двумя потомками "
    "получает ключ {rule}, а тот узел удаляется."
)
SUCCESSOR = "преемника (наименьшего ключа правого поддерева)"
PREDECESSOR = "предшественника (наибольшего ключа левого поддерева)"


class Node:
    """Узел дерева поиска."""

    def __init__(self, key: int) -> None:
        self.key = key
        self.left: Node | None = None
        self.right: Node | None = None


def _insert(root: Node | None, key: int) -> Node:
    if root is None:
        return Node(key)
    cur = root
    while True:
        side = "left" if key < cur.key else "right"
        nxt = getattr(cur, side)
        if nxt is None:
            setattr(cur, side, Node(key))
            return root
        cur = nxt


def _delete(root: Node | None, key: int, *, use_pred: bool) -> Node | None:
    if root is None:
        return None
    if key < root.key:
        root.left = _delete(root.left, key, use_pred=use_pred)
    elif key > root.key:
        root.right = _delete(root.right, key, use_pred=use_pred)
    elif root.left is None:
        return root.right
    elif root.right is None:
        return root.left
    else:
        donor = root.left if use_pred else root.right
        while (donor.right if use_pred else donor.left) is not None:
            donor = donor.right if use_pred else donor.left  # type: ignore[assignment]
        root.key = donor.key
        if use_pred:
            root.left = _delete(root.left, donor.key, use_pred=True)
        else:
            root.right = _delete(root.right, donor.key, use_pred=False)
    return root


def _height(root: Node | None) -> int:
    """Высота в рёбрах; пустое дерево — -1."""
    return -1 if root is None else 1 + max(_height(root.left), _height(root.right))


def _leaves(root: Node | None) -> int:
    if root is None:
        return 0
    if root.left is None and root.right is None:
        return 1
    return _leaves(root.left) + _leaves(root.right)


def _leaf_sum(root: Node | None) -> int:
    if root is None:
        return 0
    if root.left is None and root.right is None:
        return root.key
    return _leaf_sum(root.left) + _leaf_sum(root.right)


def _preorder(root: Node | None) -> list[int]:
    return [] if root is None else [root.key, *_preorder(root.left), *_preorder(root.right)]


def _depth(root: Node, key: int) -> int:
    depth, cur = 0, root
    while cur.key != key:
        cur = cur.left if key < cur.key else cur.right  # type: ignore[assignment]
        depth += 1
    return depth


def _build(keys: list[int]) -> Node:
    root: Node | None = None
    for k in keys:
        root = _insert(root, k)
    assert root is not None
    return root


def _two_children(root: Node | None) -> list[int]:
    if root is None:
        return []
    own = [root.key] if root.left is not None and root.right is not None else []
    return own + _two_children(root.left) + _two_children(root.right)


def generate(level: int, seed: int) -> Variant:
    """Вариант: дерево поиска из вставок; вопрос зависит от уровня.

    Уровень 1 — высота дерева (в рёбрах) или глубина заданного ключа; ошибка `height_in_nodes` — счёт узлов вместо
    рёбер. Уровень 2 — прямой обход после удаления узла с двумя потомками (всегда есть в дереве). Уровень 3 —
    число листьев, высота или сумма ключей-листьев после серии из 2–3 удалений, первое из которых — узла с двумя
    потомками. Ошибка
    `predecessor_instead_of_successor` — замена по предшественнику вместо преемника; вариант, где она не меняет
    ответ, отбрасывается. Ответ однозначен: правило удаления названо в условии, ключи различны.
    """
    rng = Random(seed)
    count = {1: rng.randint(8, 11), 2: rng.randint(8, 10), 3: rng.randint(10, 12)}[level]
    keys = rng.sample(range(5, 99), count)
    root = _build(keys)
    order = ", ".join(map(str, keys))
    base = f"В пустое дерево поиска (меньшие ключи слева) вставляются ключи по порядку: {order}. "
    wrong: dict[str, object]
    if level == 1:
        if rng.random() < 0.5:
            answer = _height(root)
            ask = "Чему равна высота дерева (число рёбер на самом длинном пути от корня)?"
        else:
            target = rng.choice([k for k in keys[1:] if _depth(root, k) >= 2] or keys[1:])
            answer = _depth(root, target)
            ask = f"Чему равна глубина узла {target} (число рёбер от корня; у корня 0)?"
        wrong = {"height_in_nodes": answer + 1}
        spec = AnswerSpec.numeric(answer)
        shown = answer
        events = count
        trap = None
    elif level == 2:
        victim = rng.choice(_two_children(root))
        good = _preorder(_delete(_build(keys), victim, use_pred=False))
        bad = _preorder(_delete(_build(keys), victim, use_pred=True))
        answer_text, wrong_text = tokens(good), tokens(bad)
        ask = (
            f"Удаляется ключ {victim}. {DELETE_RULE.format(rule=SUCCESSOR)} "
            "Каков прямой обход (корень, левое, правое) после удаления? Числа через пробел."
        )
        wrong = {"predecessor_instead_of_successor": wrong_text}
        spec = AnswerSpec.text(answer_text, mode="tokens")
        shown = max(good)
        events = count + 1
        trap = 1
    else:
        first = rng.choice(_two_children(root))
        rest = [k for k in keys if k != first]
        victims = [first, *rng.sample(rest, rng.randint(1, 2))]
        trees = {}
        for use_pred in (False, True):
            tree: Node | None = _build(keys)
            for victim in victims:
                tree = _delete(tree, victim, use_pred=use_pred)
            trees[use_pred] = tree
        options = [
            ("Сколько листьев в дереве после всех удалений?", _leaves(trees[False]), _leaves(trees[True])),
            (
                "Чему равна высота дерева после всех удалений (в рёбрах)?",
                _height(trees[False]),
                _height(trees[True]),
            ),
            (
                "Чему равна сумма ключей-листьев после всех удалений?",
                _leaf_sum(trees[False]),
                _leaf_sum(trees[True]),
            ),
        ]
        # Вопрос выбирается среди тех, где ошибка меняет ответ: иначе вариант не различает знание и заблуждение.
        options = [item for item in options if item[1] != item[2]]
        if not options:
            raise Reject("misconception_equals_answer")
        # Сумма ключей даёт широкий разброс ответов (правило L09), поэтому у неё двойной вес.
        weights = [2 if "сумма" in item[0] else 1 for item in options]
        ask_what, good_value, bad_value = rng.choices(options, weights=weights)[0]
        ask = (
            f"Затем по порядку удаляются ключи: {', '.join(map(str, victims))}. "
            f"{DELETE_RULE.format(rule=SUCCESSOR)} {ask_what}"
        )
        answer = good_value
        wrong = {"predecessor_instead_of_successor": bad_value}
        spec = AnswerSpec.numeric(answer)
        shown = answer
        events = count + len(victims)
        trap = 1
    if spec.value == next(iter(wrong.values())) or (level == 1 and answer < 2):
        raise Reject("misconception_equals_answer" if level != 1 else "trivial_answer")
    features = {"concepts": level, "timeline_events": events, "answer_abs": shown}
    if trap is not None:
        features["trap"] = trap
    is_text = level == 2
    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt=base + ask,
        input=InputHint(
            placeholder="числа через пробел" if is_text else "целое число", max_length=60 if is_text else 4
        ),
        answer=spec,
        misconception_answers=wrong,
        features=features,
        explanation=f"Симуляция дерева даёт {spec.value}. Ответ модели ошибки: {wrong}.",
    )


def selfcheck(v: Variant) -> list[str]:
    """Перепроверка: форма ответа и число ключей в условии."""
    problems = []
    listed = re.search(r"по порядку: ([\d, ]+)\.", v.prompt)
    if listed is None:
        return ["не найден список ключей"]
    keys = [int(x) for x in listed.group(1).split(",")]
    if len(set(keys)) != len(keys):
        problems.append("ключи повторяются")
    if v.level == 2:
        answer = [int(x) for x in str(v.answer.value).split()]
        if len(answer) != len(keys) - 1 or not set(answer) < set(keys):
            problems.append("прямой обход должен содержать все ключи, кроме удалённого")
    return problems


def _t_insert(tree: tuple | None, key: int) -> tuple:
    if tree is None:
        return (key, None, None)
    k, left, right = tree
    return (k, _t_insert(left, key), right) if key < k else (k, left, _t_insert(right, key))


def _t_delete(tree: tuple | None, key: int, pick_max_left: bool) -> tuple | None:
    """Оракул: функциональное удаление (кортежи), второй способ записи."""
    if tree is None:
        return None
    k, left, right = tree
    if key < k:
        return (k, _t_delete(left, key, pick_max_left), right)
    if key > k:
        return (k, left, _t_delete(right, key, pick_max_left))
    if left is None or right is None:
        return left or right
    side = left if pick_max_left else right
    donor = max(_flat(side)) if pick_max_left else min(_flat(side))
    if pick_max_left:
        return (donor, _t_delete(left, donor, True), right)
    return (donor, left, _t_delete(right, donor, False))


def _flat(tree: tuple | None) -> list[int]:
    return [] if tree is None else [*_flat(tree[1]), tree[0], *_flat(tree[2])]


def _t_pre(tree: tuple | None) -> list[int]:
    return [] if tree is None else [tree[0], *_t_pre(tree[1]), *_t_pre(tree[2])]


def _t_height(tree: tuple | None) -> int:
    return -1 if tree is None else 1 + max(_t_height(tree[1]), _t_height(tree[2]))


def _t_leaves(tree: tuple | None) -> int:
    if tree is None:
        return 0
    return 1 if tree[1] is None and tree[2] is None else _t_leaves(tree[1]) + _t_leaves(tree[2])


def _t_leaf_sum(tree: tuple | None) -> int:
    if tree is None:
        return 0
    return tree[0] if tree[1] is None and tree[2] is None else _t_leaf_sum(tree[1]) + _t_leaf_sum(tree[2])


def oracle_check(v: Variant) -> list[str]:
    """Оракул CPython: условие разбирается регулярными выражениями, дерево строится на кортежах."""
    text = v.prompt
    keys = [int(x) for x in re.search(r"по порядку: ([\d, ]+)\.", text).group(1).split(",")]  # type: ignore[union-attr]
    tree = None
    for k in keys:
        tree = _t_insert(tree, k)
    if v.level == 1:
        match = re.search(r"глубина узла (\d+)", text)
        if match:
            key, depth, cur = int(match.group(1)), 0, tree
            while cur[0] != key:  # type: ignore[index]
                cur = cur[1] if key < cur[0] else cur[2]  # type: ignore[index]
                depth += 1
            expected: object = depth
        else:
            expected = _t_height(tree)
    elif v.level == 2:
        victim = int(re.search(r"Удаляется ключ (\d+)", text).group(1))  # type: ignore[union-attr]
        expected = tokens(_t_pre(_t_delete(tree, victim, False)))
    else:
        victims = [int(x) for x in re.search(r"удаляются ключи: ([\d, ]+)\.", text).group(1).split(",")]  # type: ignore[union-attr]
        for victim in victims:
            tree = _t_delete(tree, victim, False)
        if "сумма ключей-листьев" in text:
            expected = _t_leaf_sum(tree)
        else:
            expected = _t_leaves(tree) if "листьев" in text else _t_height(tree)
    return [] if expected == v.answer.value else [f"оракул даёт {expected}, ключ {v.answer.value}"]
