"""Семейство `http.idempotent_retry`: повторы запросов после таймаута и идемпотентность (numeric_input).

Уровень 1 — сколько заказов в системе после POST и PUT с повторами. Уровень 2 — то же с `Idempotency-Key` у части
POST и с DELETE. Уровень 3 — два клиента шлют условные PUT с `If-Match`; вопрос — версия документа в конце.
Ответ считает симулятор сервера `netmodel` (семантика методов из условия); `selfcheck` пересчитывает его по
тексту ленты формулой, не пользуясь структурами генератора. Модели ошибок: `post_is_idempotent` (повторы POST не
создают записей) и `if_match_ignored` (сервер применяет PUT, не глядя на `If-Match`). Независимого оракула нет
(в реестре `manual`): правила записаны в условии дословно.
"""

from __future__ import annotations

import re
from random import Random

from app.modules.assessment.families._lib.contract import AnswerSpec, CodeBlock, InputHint, Reject, Variant
from app.modules.assessment.families._lib.netmodel import HttpRequest, conditional_puts, orders_after
from app.modules.assessment.families.registry import family_meta

META = family_meta(
    "http.idempotent_retry",
    version=1,
    feature_bounds={
        1: {"timeline_events": (3, 15), "concepts": (1, 2)},
        2: {"timeline_events": (4, 18), "concepts": (2, 4)},
        3: {"timeline_events": (4, 14), "concepts": (2, 2)},
    },
    misconceptions=("post_is_idempotent", "if_match_ignored"),
)

RULES_12 = (
    "Сервер обрабатывает каждую отправку, которая до него дошла, даже если клиент не получил ответ и повторил запрос. "
    "POST /orders создаёт новый заказ; PUT /orders/N создаёт заказ с номером N или заменяет существующий"
)
RULES_2 = "; DELETE /orders/N удаляет заказ; POST с уже виденным Idempotency-Key ничего не создаёт"


def _lines(requests: list[HttpRequest]) -> list[str]:
    """Лента: по строке на каждую отправку; последняя отправка запроса получает ответ, остальные — таймаут."""
    lines = []
    for r in requests:
        path = "/orders" if r.method == "POST" else f"/orders/{r.target}"
        head = f"{r.method} {path}" + (f"  Idempotency-Key: {r.key}" if r.key else "")
        for attempt in range(1, r.attempts + 1):
            note = "ответ получен" if attempt == r.attempts else "таймаут, ответ потерян"
            lines.append(f"{head}  # {note}")
    return lines


def _level_1_2(level: int, rng: Random) -> tuple[str, list[str], int, dict[str, int], int]:
    initial = list(range(1, rng.randint(1, 4) + 1))
    count = rng.randint(3, 5) if level == 1 else rng.randint(4, 6)
    requests: list[HttpRequest] = []
    used_put: set[int] = set()
    key_no = 0
    for index in range(count):
        attempts = rng.choice((1, 2, 2, 3))
        kind = rng.choice(("POST", "PUT", "POST") if level == 1 else ("POST", "POST", "PUT", "DELETE"))
        if index == 0:
            kind, attempts = "POST", rng.choice((2, 3))
        if kind == "POST":
            key = None
            if level == 2 and rng.random() < 0.5:
                key_no += 1
                key = f"k{key_no}"
            requests.append(HttpRequest("POST", None, key, attempts))
        elif kind == "PUT":
            target = rng.choice([x for x in range(11, 40) if x not in used_put])
            used_put.add(target)
            requests.append(HttpRequest("PUT", target, None, attempts))
        else:
            free = [x for x in initial if all(r.target != x for r in requests)]
            if not free:
                requests.append(HttpRequest("POST", None, None, attempts))
                continue
            requests.append(HttpRequest("DELETE", rng.choice(free), None, attempts))
    answer = orders_after(initial, requests)
    wrong = {"post_is_idempotent": orders_after(initial, requests, post_is_idempotent=True)}
    lines = _lines(requests)
    kinds = {r.method for r in requests} | ({"key"} if key_no else set())
    start = f"Сначала в системе {len(initial)} " + (
        "заказ" if len(initial) == 1 else "заказа" if len(initial) < 5 else "заказов"
    )
    rules = RULES_12 + (RULES_2 if level == 2 else "") + ". "
    return rules + start + ".", lines, answer, wrong, len(kinds)


def _level_3(rng: Random) -> tuple[str, list[str], int, dict[str, int], int]:
    start = rng.randint(1, 4)
    puts: list[tuple[int, int]] = []
    who: list[str] = []
    for _ in range(rng.randint(4, 6)):
        current = conditional_puts(start, puts)
        if_match = max(1, current - rng.choice((0, 0, 1, 2)))
        puts.append((if_match, rng.choice((1, 1, 2))))
        who.append(rng.choice("AB"))
    answer = conditional_puts(start, puts)
    wrong = {"if_match_ignored": conditional_puts(start, puts, if_match_ignored=True)}
    lines = []
    for client, (if_match, attempts) in zip(who, puts, strict=True):
        for attempt in range(1, attempts + 1):
            note = "ответ получен" if attempt == attempts else "таймаут, ответ потерян"
            lines.append(f"{client}: PUT /doc  If-Match: {if_match}  # {note}")
    prompt = (
        "Сервер обрабатывает каждую дошедшую отправку, даже если клиент не получил ответ и повторил запрос с теми же "
        "заголовками. PUT /doc применяется, только если If-Match равен текущей версии документа; применённый PUT "
        f"увеличивает версию на 1, иначе сервер отвечает 412 и ничего не меняет. Сначала версия документа — {start}."
    )
    return prompt, lines, answer, wrong, 2


def generate(level: int, seed: int) -> Variant:
    """Вариант: лента отправок с таймаутами и вопрос о состоянии сервера в конце.

    Что вычисляется: число заказов (уровни 1–2) или версия документа (уровень 3) по симулятору сервера. Модели
    ошибок: `post_is_idempotent` — повтор POST не создаёт записи; `if_match_ignored` — условный PUT применяется
    всегда. Вариант без различия ответа с моделью ошибки отбрасывается. Ответ однозначен: правила методов
    выписаны в условии, лента линейна, все отправки обрабатываются по порядку.
    """
    rng = Random(seed)
    prompt, lines, answer, wrong, concepts = _level_3(rng) if level == 3 else _level_1_2(level, rng)
    wrong = {code: value for code, value in wrong.items() if value != answer}
    if not wrong:
        raise Reject("misconception_equals_answer")
    question = "Сколько заказов будет в системе в конце?" if level < 3 else "Какая версия документа будет в конце?"
    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt=f"{prompt} {question} Ответ — целое число.",
        code=CodeBlock(language="http", text="\n".join(lines)),
        input=InputHint(placeholder="целое число", max_length=4),
        answer=AnswerSpec.numeric(answer),
        misconception_answers=wrong,
        features={"timeline_events": len(lines), "concepts": concepts},
        explanation=f"Ответ {answer}; модели ошибок: {wrong}. Начало: {prompt.rsplit('. ', 1)[-1]}",
    )


_START = re.compile(r"(?:Сначала в системе (\d+)|Сначала версия документа — (\d+))")


def selfcheck(v: Variant) -> list[str]:
    """Пересчёт по тексту ленты: каждая строка — одна отправка; считаются формулой, а не симулятором."""
    assert v.code is not None
    m = _START.search(v.prompt)
    if not m:
        return ["в условии нет начального состояния"]
    sends = v.code.text.split("\n")
    if v.level == 3:
        version = int(m.group(2))
        for row in sends:
            if_match = int(re.search(r"If-Match: (\d+)", row).group(1))  # type: ignore[union-attr]
            if if_match == version:
                version += 1
        expected = version
    else:
        initial = int(m.group(1))
        posts_plain = sum(1 for r in sends if r.startswith("POST") and "Idempotency-Key" not in r)
        keys = {re.search(r"Idempotency-Key: (\w+)", r).group(1) for r in sends if "Idempotency-Key" in r}  # type: ignore[union-attr]
        put_targets = {re.match(r"PUT /orders/(\d+)", r).group(1) for r in sends if r.startswith("PUT")}  # type: ignore[union-attr]
        deleted = {re.match(r"DELETE /orders/(\d+)", r).group(1) for r in sends if r.startswith("DELETE")}  # type: ignore[union-attr]
        expected = initial - len(deleted) + len(put_targets) + posts_plain + len(keys)
    if v.answer.value != expected:
        return [f"пересчёт по ленте даёт {expected}, ключ {v.answer.value}"]
    return []
