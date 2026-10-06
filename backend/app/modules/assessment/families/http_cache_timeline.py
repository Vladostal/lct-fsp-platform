"""Семейство `http.cache_timeline`: лента GET во времени и заголовки кэширования (numeric_input).

Уровень 1 — `max-age`: сколько запросов дошло до сервера. Уровень 2 — `ETag` с `max-age`, `no-cache` или `no-store`
и изменения ресурса на сервере: сколько ответов пришло с полным телом. Уровень 3 — кэши браузеров двух пользователей
и общий кэш (`s-maxage`, `private`, `Vary`): сколько запросов дошло до сервера-источника. Ответ считает симулятор кэша
`netmodel` по правилам, выписанным в условии (подмножество RFC 9111); `selfcheck` пересчитывает его по тексту ленты
независимой реализацией. Модели ошибок: `max_age_from_first` (возраст считается от первой загрузки),
`no_cache_means_no_store` (`no-cache` и `no-store` перепутаны), `etag_ignored` (проверка по ETag не даёт 304),
`shared_cache_rules_ignored` (общий кэш ведёт себя как браузерный).
Оракула нет (в реестре `manual`): правила модели дословно в условии, варианты — на ручную проверку.
"""

from __future__ import annotations

import re
from dataclasses import replace
from random import Random

from app.modules.assessment.families._lib.contract import AnswerSpec, CodeBlock, InputHint, Reject, Variant
from app.modules.assessment.families._lib.netmodel import (
    CachePolicy,
    CacheRequest,
    browser_cache,
    shared_cache_origin_hits,
)
from app.modules.assessment.families.registry import family_meta

META = family_meta(
    "http.cache_timeline",
    version=1,
    feature_bounds={
        1: {"timeline_events": (6, 11), "concepts": (1, 1)},
        2: {"timeline_events": (7, 13), "concepts": (2, 3)},
        3: {"timeline_events": (8, 14), "concepts": (3, 4)},
    },
    misconceptions=("no_cache_means_no_store", "max_age_from_first", "shared_cache_rules_ignored", "etag_ignored"),
)

RULES_1 = (
    "Кэш браузера один, валидаторов у ответа нет. Сохранённый ответ свеж, пока его возраст (t минус момент "
    "сохранения) строго меньше max-age; устаревший ответ загружается с сервера заново."
)
RULES_2 = (
    "Кэш браузера один. Свежий ответ берётся из кэша; max-age — свежесть строго по возрасту; no-cache требует проверки "
    "на сервере при каждом запросе; no-store запрещает сохранять ответ. Проверка по ETag (If-None-Match) на "
    "неизменённый ресурс даёт 304 без тела и обновляет момент сохранения; иначе сервер отвечает 200 с телом."
)
RULES_3 = (
    "У каждого пользователя свой кэш браузера, между ними — один общий кэш. Браузер хранит ответ, если нет "
    "no-store, и считает его свежим max-age секунд. Общий кэш не хранит ответы с private и no-store; свежесть в нём — "
    "s-maxage, а без него max-age. Vary: Accept-Language делает запись общего кэша отдельной для каждого языка. "
    "Валидаторов нет, Age не учитывайте."
)


def _times(rng: Random, count: int, low: int, high: int) -> list[int]:
    t, out = 0, []
    for _ in range(count):
        out.append(t)
        t += rng.randint(low, high)
    return out


def _header(p: CachePolicy) -> str:
    parts = []
    if p.private:
        parts.append("private")
    if p.no_cache:
        parts.append("no-cache")
    if p.no_store:
        parts.append("no-store")
    if p.max_age is not None:
        parts.append(f"max-age={p.max_age}")
    if p.s_maxage is not None:
        parts.append(f"s-maxage={p.s_maxage}")
    text = "Cache-Control: " + ", ".join(parts)
    if p.etag:
        text += "\nETag: есть"
    if p.vary_language:
        text += "\nVary: Accept-Language"
    return text


def _level_1(rng: Random) -> tuple[str, str, int, dict[str, int], int]:
    policy = CachePolicy(max_age=rng.choice((10, 15, 20, 30, 60)))
    times = _times(rng, rng.randint(6, 11), 3, 25)
    lines = [f"t={t} c  GET /app.js" for t in times]
    answer = sum(o != "cache" for o in browser_cache(times, policy))
    wrong = {"max_age_from_first": sum(o != "cache" for o in browser_cache(times, policy, age_from_first=True))}
    return RULES_1, _header(policy) + "\n" + "\n".join(lines), answer, wrong, 1


def _level_2(rng: Random) -> tuple[str, str, int, dict[str, int], int]:
    kind = rng.choice(("max-age", "max-age", "no-cache", "no-store"))
    policy = CachePolicy(
        etag=True,
        max_age=rng.choice((15, 30, 60)) if kind == "max-age" else None,
        no_cache=kind == "no-cache",
        no_store=kind == "no-store",
    )
    times = _times(rng, rng.randint(7, 13), 4, 28)
    changes = sorted(rng.sample(range(times[1], times[-1]), rng.randint(1, 4)))
    events = sorted(
        [(t, f"t={t} c  GET /data.json") for t in times] + [(c, f"t={c}    сервер: ресурс изменён") for c in changes]
    )
    # при равных t ресурс на сервере меняется раньше запроса: в модели изменение учитывается при c <= t
    events.sort(key=lambda e: (e[0], 0 if "сервер" in e[1] else 1))
    answer = browser_cache(times, policy, changes).count("200")
    wrong = {}
    flipped = replace(policy, no_cache=policy.no_store, no_store=policy.no_cache)
    if kind != "max-age":
        wrong["no_cache_means_no_store"] = browser_cache(times, flipped, changes).count("200")
    else:
        wrong["max_age_from_first"] = browser_cache(times, policy, changes, age_from_first=True).count("200")
        wrong["etag_ignored"] = browser_cache(times, replace(policy, etag=False), changes).count("200")
    text = _header(policy) + "\n" + "\n".join(e[1] for e in events)
    return RULES_2, text, answer, wrong, 2 + (kind != "max-age")


def _level_3(rng: Random) -> tuple[str, str, int, dict[str, int], int]:
    age = rng.choice((10, 20, 30))
    policy = CachePolicy(
        max_age=age,
        s_maxage=rng.choice((None, 60, 90, 120)),
        private=rng.random() < 0.3,
        vary_language=rng.random() < 0.5,
    )
    languages = {1: "ru", 2: rng.choice(("ru", "en"))}
    times = _times(rng, rng.randint(8, 14), 2, 30)
    requests = [CacheRequest(t, (user := rng.choice((1, 2))), languages[user]) for t in times]
    answer = shared_cache_origin_hits(requests, policy)
    wrong = {"shared_cache_rules_ignored": shared_cache_origin_hits(requests, policy, rules_ignored=True)}
    lines = [f"t={r.time} пользователь {r.user} ({r.language})  GET /logo.svg" for r in requests]
    concepts = 2 + (policy.s_maxage is not None) + policy.private + policy.vary_language
    return RULES_3, _header(policy) + "\n" + "\n".join(lines), answer, wrong, min(concepts, 4)


def generate(level: int, seed: int) -> Variant:
    """Вариант: заголовки ответа, лента запросов и вопрос о числе обращений к серверу (или ответов с телом).

    Ответ вычисляет симулятор кэша `netmodel` по правилам из условия. Модели ошибок: `max_age_from_first`,
    `no_cache_means_no_store`, `shared_cache_rules_ignored`. Вариант, в котором ответ ошибочной модели совпал с
    верным, отбрасывается. Ответ однозначен: условие задаёт строгое сравнение возраста с max-age, порядок событий
    при равных t (изменение ресурса раньше запроса) и состав кэшей.
    """
    rng = Random(seed)
    rules, text, answer, wrong, concepts = (_level_1, _level_2, _level_3)[level - 1](rng)
    wrong = {code: value for code, value in wrong.items() if value != answer}
    if not wrong:
        raise Reject("misconception_equals_answer")
    question = (
        "Сколько ответов сервера придёт с полным телом (200)?"
        if level == 2
        else "Сколько запросов дойдёт до сервера?"
        if level == 1
        else "Сколько запросов дойдёт до сервера-источника?"
    )
    tail = " Ответ — целое число."
    if level == 2:
        rules += " Изменение ресурса при равных t происходит раньше запроса."
    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt=f"{rules} {question}{tail}",
        code=CodeBlock(language="http", text=text),
        input=InputHint(placeholder="целое число", max_length=3),
        answer=AnswerSpec.numeric(answer),
        misconception_answers=wrong,
        features={"timeline_events": text.count("GET"), "concepts": concepts},
        explanation=f"Ответ {answer}; модели ошибок: {wrong}.",
    )


def selfcheck(v: Variant) -> list[str]:
    """Пересчёт по тексту ленты независимой реализацией: словари вместо записей кэша и явный разбор заголовков."""
    assert v.code is not None
    rows = v.code.text.split("\n")
    head = " ".join(r for r in rows if r.startswith("Cache-Control"))
    max_age = int(m.group(1)) if (m := re.search(r"(?<![s-])max-age=(\d+)", head)) else None
    s_max = int(m.group(1)) if (m := re.search(r"s-maxage=(\d+)", head)) else None
    flags = {"no-cache": "no-cache" in head, "no-store": "no-store" in head, "private": "private" in head}
    etag = any(r.startswith("ETag") for r in rows)
    vary = any(r.startswith("Vary") for r in rows)
    version, expected = 0, 0
    if v.level == 3:
        browser: dict[str, int] = {}
        shared: dict[str, int] = {}
        for r in rows:
            m = re.match(r"t=(\d+) пользователь (\d) \((\w+)\)", r)
            if not m:
                continue
            t, user, lang = int(m.group(1)), m.group(2), m.group(3)
            if user in browser and max_age is not None and t - browser[user] < max_age:
                continue
            key = lang if vary else "*"
            life = s_max if s_max is not None else max_age
            usable = not flags["private"] and not flags["no-store"]
            if not (usable and life is not None and key in shared and t - shared[key] < life):
                expected += 1
                if usable:
                    shared[key] = t
            if not flags["no-store"]:
                browser[user] = t
        return [] if v.answer.value == expected else [f"пересчёт даёт {expected}, ключ {v.answer.value}"]
    stored: tuple[int, int] | None = None
    for r in rows:
        if m := re.match(r"t=(\d+)\s+сервер: ресурс изменён", r):
            version += 1
            continue
        m = re.match(r"t=(\d+) c  GET", r)
        if not m:
            continue
        t = int(m.group(1))
        if stored and not flags["no-cache"] and max_age is not None and t - stored[0] < max_age:
            continue
        if stored and etag and stored[1] == version:
            stored = (t, version)  # 304
            if v.level == 1:
                expected += 1
            continue
        expected += 1
        if not flags["no-store"]:
            stored = (t, version)
    return [] if v.answer.value == expected else [f"пересчёт даёт {expected}, ключ {v.answer.value}"]
