"""Семейство `svc.rate_limiter`: сколько запросов получат 429 при заданном ограничителе (numeric_input).

Уровень 1 — фиксированное окно; уровень 2 — корзина токенов; уровень 3 — скользящее окно (журнал принятых запросов)
у двух клиентов с отдельными лимитами. Ответ считает симулятор ограничителя `netmodel`; правила записаны в условии
дословно; `selfcheck` пересчитывает ответ по тексту ленты независимой реализацией (списки меток вместо счётчиков и
дробей). Оракула нет (в реестре `manual`). Модели ошибок: `window_reset_ignored` (счётчик или корзина не
восстанавливаются) и `sliding_as_fixed` (скользящее окно принято за фиксированное).
"""

from __future__ import annotations

import re
from fractions import Fraction
from random import Random

from app.modules.assessment.families._lib.contract import AnswerSpec, CodeBlock, InputHint, Reject, Variant
from app.modules.assessment.families._lib.netmodel import (
    fixed_window_rejects,
    sliding_window_rejects,
    token_bucket_rejects,
)
from app.modules.assessment.families.registry import family_meta

META = family_meta(
    "svc.rate_limiter",
    version=1,
    feature_bounds={
        1: {"timeline_events": (8, 14), "concepts": (1, 1)},
        2: {"timeline_events": (8, 14), "concepts": (2, 2)},
        3: {"timeline_events": (12, 18), "concepts": (3, 3)},
    },
    misconceptions=("window_reset_ignored", "sliding_as_fixed"),
)


def _bursty_times(rng: Random, count: int, spread: int) -> list[int]:
    """Неубывающие моменты с всплесками: часть запросов идёт почти подряд."""
    t, out = rng.randint(0, 2), []
    for _ in range(count):
        out.append(t)
        t += rng.choice((0, 0, 1, 1, 2, rng.randint(3, spread)))
    return out


def _level_1(rng: Random) -> tuple[str, list[str], int, dict[str, int], int]:
    limit, window = rng.randint(2, 4), rng.choice((5, 6, 8, 10))
    times = _bursty_times(rng, rng.randint(9, 14), 9)
    requests = [(t, "-") for t in times]
    prompt = (
        f"Ограничитель с фиксированным окном: окна выровнены по {window} с (окно номер t // {window}), в каждом окне "
        f"пропускается не более {limit} запросов, остальные получают 429; в новом окне счётчик обнуляется."
    )
    wrong = {"window_reset_ignored": fixed_window_rejects(requests, limit, window, no_reset=True)}
    return prompt, [f"t={t}  GET /api" for t in times], fixed_window_rejects(requests, limit, window), wrong, 1


def _level_2(rng: Random) -> tuple[str, list[str], int, dict[str, int], int]:
    capacity, period = rng.randint(2, 4), rng.choice((2, 3, 4))
    times = _bursty_times(rng, rng.randint(9, 14), 8)
    prompt = (
        f"Ограничитель «корзина токенов»: вместимость {capacity}, в момент 0 корзина полна, каждые {period} с в неё "
        f"добавляется один токен непрерывно (за 1 с — 1/{period} токена), больше вместимости не копится. Запрос "
        "забирает один токен; если токена нет, запрос получает 429 и токен не тратится."
    )
    rate = Fraction(1, period)
    wrong = {"window_reset_ignored": token_bucket_rejects(times, capacity, rate, no_refill=True)}
    return prompt, [f"t={t}  GET /api" for t in times], token_bucket_rejects(times, capacity, rate), wrong, 2


def _level_3(rng: Random) -> tuple[str, list[str], int, dict[str, int], int]:
    limit, window = rng.randint(2, 3), rng.choice((4, 5, 6, 8))
    # всплески вокруг границ фиксированных окон: именно там скользящее окно отличается от фиксированного
    times: list[int] = []
    boundary = 1
    while len(times) < 12:
        boundary += rng.randint(1, 2)
        times += sorted(window * boundary + rng.randint(-2, 1) for _ in range(rng.randint(4, 6)))
    times = times[:18]
    requests = [(t, rng.choice("AAB")) for t in times]
    prompt = (
        f"Ограничитель со скользящим окном, отдельно для каждого клиента: запрос в момент t принимается, если за "
        f"последние {window} с (в интервале (t - {window}, t]) у этого клиента принято меньше {limit} запросов; иначе "
        "429. Отклонённые запросы в счёт не идут."
    )
    wrong = {"sliding_as_fixed": sliding_window_rejects(requests, limit, window, as_fixed=True)}
    lines = [f"t={t}  клиент {key}  GET /api" for t, key in requests]
    return prompt, lines, sliding_window_rejects(requests, limit, window), wrong, 3


def generate(level: int, seed: int) -> Variant:
    """Вариант: правила ограничителя в условии, лента запросов в коде; вопрос — число ответов 429.

    Ответ считает симулятор `netmodel` (фиксированное окно, корзина токенов с точными дробями, скользящее окно с
    журналом). Модели ошибок: `window_reset_ignored` и `sliding_as_fixed`; вариант без отличия ответа ошибки или с
    тривиальным ответом (меньше 2) отбрасывается. Ответ однозначен: правила, границы окон и порядок обработки
    запросов с равными t (по порядку в ленте) выписаны в условии.
    """
    rng = Random(seed)
    prompt, lines, answer, wrong, concepts = (_level_1, _level_2, _level_3)[level - 1](rng)
    wrong = {code: value for code, value in wrong.items() if value != answer}
    if not wrong:
        raise Reject("misconception_equals_answer")
    if answer < 2:
        raise Reject("trivial_answer")
    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt=f"{prompt} Запросы обрабатываются в порядке строк. Сколько запросов получат 429? Ответ — целое число.",
        code=CodeBlock(language="text", text="\n".join(lines)),
        input=InputHint(placeholder="целое число", max_length=3),
        answer=AnswerSpec.numeric(answer),
        misconception_answers=wrong,
        features={"timeline_events": len(lines), "concepts": concepts},
        explanation=f"Ответ {answer}; модели ошибок: {wrong}.",
    )


def selfcheck(v: Variant) -> list[str]:
    """Пересчёт по тексту: параметры берутся из условия, ленты разбираются заново, счёт ведётся списками и дробями."""
    assert v.code is not None
    rows = [re.match(r"t=(\d+)\s+(?:клиент (\w)\s+)?GET", r) for r in v.code.text.split("\n")]
    events = [(int(m.group(1)), m.group(2) or "-") for m in rows if m]
    rejected = 0
    if v.level == 1:
        window, limit = (int(x) for x in re.search(r"по (\d+) с .*? не более (\d+) запросов", v.prompt).groups())  # type: ignore[union-attr]
        seen: dict[tuple[int, str], list[int]] = {}
        for t, key in events:
            bucket = seen.setdefault((t // window, key), [])
            bucket.append(t)
            rejected += len(bucket) > limit
    elif v.level == 2:
        capacity, period = (int(x) for x in re.search(r"вместимость (\d+).*?каждые (\d+) с", v.prompt).groups())  # type: ignore[union-attr]
        tokens, last = Fraction(capacity), 0
        for t, _ in events:
            tokens = min(Fraction(capacity), tokens + Fraction(t - last, period))
            last = t
            if tokens >= 1:
                tokens -= 1
            else:
                rejected += 1
    else:
        window, limit = (int(x) for x in re.search(r"последние (\d+) с .*? меньше (\d+) запросов", v.prompt).groups())  # type: ignore[union-attr]
        accepted: dict[str, list[int]] = {}
        for t, key in events:
            recent = [u for u in accepted.setdefault(key, []) if t - window < u <= t]
            if len(recent) < limit:
                accepted[key].append(t)
            else:
                rejected += 1
    return [] if rejected == v.answer.value else [f"пересчёт даёт {rejected}, ключ {v.answer.value}"]
