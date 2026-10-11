"""Семейство «Обходы и пути в графе»: BFS и DFS, кратчайший путь, топологический порядок, остов."""

from __future__ import annotations

import heapq
import re
from collections import deque
from random import Random

from app.modules.assessment.families._lib import names
from app.modules.assessment.families._lib.contract import AnswerSpec, InputHint, Reject, Variant
from app.modules.assessment.families._lib.miniprog import tokens
from app.modules.assessment.families.registry import family_meta

META = family_meta(
    "algo.graph_traversal",
    version=1,
    feature_bounds={
        1: {"concepts": (1, 1), "timeline_events": (8, 11), "answer_abs": (1, 8)},
        2: {"concepts": (2, 2), "timeline_events": (10, 14), "answer_abs": (3, 60), "trap": (1, 1)},
        3: {"concepts": (3, 3), "timeline_events": (7, 14), "answer_abs": (3, 80), "trap": (1, 1)},
    },
)

Edge = tuple[str, str, int]


def _connected_edges(rng: Random, labels: list[str], extra: int, *, weighted: bool) -> list[Edge]:
    """Связный граф: случайное остовное дерево и `extra` дополнительных рёбер; веса различны."""
    pairs: set[tuple[str, str]] = set()
    for i in range(1, len(labels)):
        parent = labels[rng.randrange(i)]
        pairs.add(tuple(sorted((labels[i], parent))))  # type: ignore[arg-type]
    while len(pairs) < len(labels) - 1 + extra:
        a, b = sorted(rng.sample(labels, 2))
        pairs.add((a, b))
    ordered = sorted(pairs)
    weights = rng.sample(range(1, 25), len(ordered)) if weighted else [1] * len(ordered)
    return [(a, b, w) for (a, b), w in zip(ordered, weights, strict=True)]


def _adjacency(edges: list[Edge], *, directed: bool = False) -> dict[str, list[tuple[str, int]]]:
    adj: dict[str, list[tuple[str, int]]] = {v: [] for e in edges for v in e[:2]}
    for a, b, w in edges:
        adj[a].append((b, w))
        if not directed:
            adj[b].append((a, w))
    return {k: sorted(v) for k, v in sorted(adj.items())}


def _bfs(adj: dict[str, list[tuple[str, int]]], start: str) -> list[str]:
    seen, order, queue = {start}, [], deque([start])
    while queue:
        u = queue.popleft()
        order.append(u)
        for v, _ in adj[u]:
            if v not in seen:
                seen.add(v)
                queue.append(v)
    return order


def _dfs(adj: dict[str, list[tuple[str, int]]], start: str) -> list[str]:
    seen: set[str] = set()
    order: list[str] = []

    def visit(u: str) -> None:
        seen.add(u)
        order.append(u)
        for v, _ in adj[u]:
            if v not in seen:
                visit(v)

    visit(start)
    return order


def _dijkstra(adj: dict[str, list[tuple[str, int]]], start: str) -> dict[str, tuple[int, str | None]]:
    best: dict[str, tuple[int, str | None]] = {start: (0, None)}
    heap: list[tuple[int, str, str | None]] = [(0, start, None)]
    done: set[str] = set()
    while heap:
        d, u, _ = heapq.heappop(heap)
        if u in done:
            continue
        done.add(u)
        for v, w in adj[u]:
            if v not in best or d + w < best[v][0]:
                best[v] = (d + w, u)
                heapq.heappush(heap, (d + w, v, u))
    return best


def _greedy_walk(adj: dict[str, list[tuple[str, int]]], start: str, target: str) -> int | None:
    """Ошибка `greedy_path`: всегда идти по самому дешёвому ребру в непосещённую вершину; None — тупик."""
    here, total, seen = start, 0, {start}
    while here != target:
        options = [(w, v) for v, w in adj[here] if v not in seen]
        if not options:
            return None
        w, here = min(options)
        seen.add(here)
        total += w
    return total


def _kahn_lex(labels: list[str], edges: list[Edge]) -> list[str]:
    indeg = dict.fromkeys(labels, 0)
    for _, b, _ in edges:
        indeg[b] += 1
    ready = sorted(v for v, d in indeg.items() if d == 0)
    order: list[str] = []
    while ready:
        u = ready.pop(0)
        order.append(u)
        for a, b, _ in edges:
            if a == u:
                indeg[b] -= 1
                if indeg[b] == 0:
                    ready.append(b)
                    ready.sort()
    return order


def _topo_dfs(labels: list[str], edges: list[Edge]) -> list[str]:
    """Ошибка: обратный порядок завершения DFS (корректный порядок, но не лексикографический)."""
    adj: dict[str, list[tuple[str, int]]] = {v: [] for v in labels}
    adj.update(_adjacency(edges, directed=True))
    seen: set[str] = set()
    post: list[str] = []

    def visit(u: str) -> None:
        seen.add(u)
        for v, _ in adj[u]:
            if v not in seen:
                visit(v)
        post.append(u)

    for v in sorted(labels):
        if v not in seen:
            visit(v)
    return post[::-1]


def _kruskal(labels: list[str], edges: list[Edge]) -> int:
    parent = {v: v for v in labels}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    total = 0
    for a, b, w in sorted(edges, key=lambda e: e[2]):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
            total += w
    return total


def _edge_text(edges: list[Edge], *, weighted: bool, directed: bool = False) -> str:
    sep = ">" if directed else "-"
    return ", ".join(f"{a}{sep}{b}({w})" if weighted else f"{a}{sep}{b}" for a, b, w in edges)


def generate(level: int, seed: int) -> Variant:
    """Вариант: задача на графе из 6–8 вершин; тип ответа зависит от уровня.

    Уровень 1 — порядок обхода в ширину или в глубину при алфавитном порядке соседей (ошибка `dfs_instead_of_bfs`:
    кандидат выписывает обход другого вида). Уровень 2 — длина кратчайшего пути с весами (ошибка `greedy_path`:
    кандидат идёт по самому дешёвому ребру в непосещённую вершину; вариант без тупика и с отличным ответом).
    Уровень 3 — лексикографически наименьший топологический порядок (ошибка `dfs_instead_of_bfs`: порядок по
    обратному завершению DFS) либо вес минимального остова (ошибка `greedy_path`: вес дерева кратчайших путей от
    старта). Веса рёбер различны, соседи перебираются по алфавиту, правило выбора названо в условии, поэтому ответ
    единственный. Ответ вычисляют эталонные алгоритмы: очередь, рекурсия, куча, алгоритм Кана, Краскал.
    """
    rng = Random(seed)
    size = rng.randint(6, 8)
    labels = list(names.LABELS[:size])
    answer: object
    wrong: dict[str, object]
    if level == 1:
        edges = _connected_edges(rng, labels, rng.randint(3, 4), weighted=False)
        adj = _adjacency(edges)
        start = rng.choice(labels[:3])
        kind = rng.choice(["BFS", "DFS"])
        good, bad = (_bfs(adj, start), _dfs(adj, start)) if kind == "BFS" else (_dfs(adj, start), _bfs(adj, start))
        title = "в ширину (с очередью)" if kind == "BFS" else "в глубину (рекурсивный, с возвратом)"
        ask = f"Выпишите порядок посещения вершин при обходе {title} от вершины {start}. Вершины через пробел."
        listing = _edge_text(edges, weighted=False)
        text = f"Неориентированный граф, рёбра: {listing}. Соседи перебираются по алфавиту. {ask}"
        answer = tokens(good)
        wrong = {"dfs_instead_of_bfs": tokens(bad)}
        spec = AnswerSpec.text(answer, mode="tokens")
        shown, hint, events = len(good), "вершины через пробел", len(edges)
        trap = None
    elif level == 2:
        edges = _connected_edges(rng, labels, rng.randint(5, 7), weighted=True)
        adj = _adjacency(edges)
        # До шести пар «старт, цель»: берётся первая, где жадный обход доходит до цели и ошибается.
        for _ in range(6):
            start, target = rng.sample(labels, 2)
            shortest = _dijkstra(adj, start)[target][0]
            greedy = _greedy_walk(adj, start, target)
            if greedy is not None and greedy != shortest:
                break
        else:
            raise Reject("greedy_stuck_or_equal")
        text = (
            f"Неориентированный граф с весами, рёбра: {_edge_text(edges, weighted=True)}. "
            f"Чему равна длина (сумма весов) кратчайшего пути из {start} в {target}? Целое число."
        )
        answer, wrong = shortest, {"greedy_path": greedy}
        spec = AnswerSpec.numeric(shortest)
        shown, hint, events = shortest, "целое число", len(edges)
        trap = 1
    elif level == 3:
        if rng.random() < 0.5:
            order = rng.sample(labels, size)
            pairs: set[tuple[str, str]] = set()
            while len(pairs) < size + rng.randint(1, 3):
                i, j = sorted(rng.sample(range(size), 2))
                pairs.add((order[i], order[j]))
            edges = [(a, b, 1) for a, b in sorted(pairs)]
            good_list, bad_list = _kahn_lex(labels, edges), _topo_dfs(labels, edges)
            text = (
                f"Ориентированный граф без циклов, вершины: {' '.join(labels)}; "
                f"рёбра: {_edge_text(edges, weighted=False, directed=True)}. "
                "Топологический порядок строится так: из вершин без входящих рёбер берётся наименьшая по алфавиту, "
                "убирается вместе с рёбрами, и так далее. Выпишите порядок. Вершины через пробел."
            )
            answer, wrong = tokens(good_list), {"dfs_instead_of_bfs": tokens(bad_list)}
            spec = AnswerSpec.text(answer, mode="tokens")
            shown, hint = len(good_list), "вершины через пробел"
        else:
            edges = _connected_edges(rng, labels, rng.randint(4, 6), weighted=True)
            adj = _adjacency(edges)
            start = labels[0]
            tree = _dijkstra(adj, start)
            spt_weight = sum(
                next(w for v, w in adj[parent] if v == node) for node, (_, parent) in tree.items() if parent
            )
            mst = _kruskal(labels, edges)
            text = (
                f"Неориентированный граф с весами, рёбра: {_edge_text(edges, weighted=True)}. "
                "Чему равен суммарный вес минимального остовного дерева? Целое число."
            )
            answer, wrong = mst, {"greedy_path": spt_weight}
            spec = AnswerSpec.numeric(mst)
            shown, hint = mst, "целое число"
        events, trap = len(edges), 1
    else:
        raise ValueError(f"нет уровня {level}")
    if str(answer) == str(next(iter(wrong.values()))):
        raise Reject("misconception_equals_answer")
    features = {"concepts": level, "timeline_events": events, "answer_abs": shown}
    if trap is not None:
        features["trap"] = trap
    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt=text,
        input=InputHint(placeholder=hint, max_length=40),
        answer=spec,
        misconception_answers=wrong,
        features=features,
        explanation=f"Эталонный алгоритм даёт {answer}. Ответ модели ошибки: {wrong}.",
    )


def selfcheck(v: Variant) -> list[str]:
    """Перепроверка: форма ответа (перестановка вершин или положительное число) и различие ответов."""
    problems = []
    if v.answer.kind.value == "text_input":
        listed = str(v.answer.value).split()
        if len(set(listed)) != len(listed):
            problems.append("в порядке вершин есть повторы")
    elif not isinstance(v.answer.value, int) or v.answer.value <= 0:
        problems.append("числовой ответ должен быть положительным целым")
    return problems


def _parse(prompt: str) -> tuple[list[Edge], list[str]]:
    edges = [
        (a, b, int(w) if w else 1)
        for a, b, w in re.findall(r"([A-H])[->]+([A-H])(?:\((\d+)\))?", prompt.split(". ")[0])
    ]
    listed = re.search(r"вершины: ([A-H ]+);", prompt)
    labels = listed.group(1).split() if listed else sorted({x for a, b, _ in edges for x in (a, b)})
    return edges, labels


def oracle_check(v: Variant) -> list[str]:
    """Оракул CPython: условие разбирается регулярным выражением, ответ считается другими алгоритмами.

    Обходы — стеком и уровнями вместо очереди и рекурсии, кратчайший путь — Беллманом–Фордом, топологический
    порядок — повторным просмотром вершин, вес остова — алгоритмом Прима.
    """
    text = v.prompt
    edges, labels = _parse(text)
    adj: dict[str, list[tuple[str, int]]] = {x: [] for x in labels}
    for a, b, w in edges:
        adj[a].append((b, w))
        if ">" not in text.split(". ")[0]:
            adj[b].append((a, w))
    adj = {k: sorted(val) for k, val in adj.items()}
    order: list[str]
    if v.level == 1:
        start = re.search(r"от вершины (\w)", text).group(1)  # type: ignore[union-attr]
        if "в ширину" in text:
            order, level_set, seen = [], [start], {start}
            while level_set:
                order += level_set
                nxt = []
                for u in level_set:
                    for neighbor, _ in adj[u]:
                        if neighbor not in seen:
                            seen.add(neighbor)
                            nxt.append(neighbor)
                level_set = nxt
        else:
            order, stack, seen = [], [start], set()
            while stack:
                u = stack.pop()
                if u in seen:
                    continue
                seen.add(u)
                order.append(u)
                stack.extend(neighbor for neighbor, _ in reversed(adj[u]))
        expected: object = tokens(order)
    elif v.level == 2:
        src, dst = re.search(r"из (\w) в (\w)\?", text).groups()  # type: ignore[union-attr]
        dist = dict.fromkeys(labels, 10**9)
        dist[src] = 0
        for _ in labels:
            for u in labels:
                for neighbor, weight in adj[u]:
                    dist[neighbor] = min(dist[neighbor], dist[u] + weight)
        expected = dist[dst]
    elif "Топологический" in text:
        rest, order = set(labels), []
        while rest:
            free = sorted(x for x in rest if not any(x == b and a in rest for a, b, _ in edges))
            order.append(free[0])
            rest.discard(free[0])
        expected = tokens(order)
    else:
        inside, total = {labels[0]}, 0
        while len(inside) < len(labels):
            weight, node = min((w, y) for x in inside for y, w in adj[x] if y not in inside)
            inside.add(node)
            total += weight
        expected = total
    return [] if expected == v.answer.value else [f"оракул даёт {expected}, ключ {v.answer.value}"]
