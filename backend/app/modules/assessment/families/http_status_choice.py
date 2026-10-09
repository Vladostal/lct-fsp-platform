"""Семейство `http.status_choice`: выбор кода ответа HTTP по описанной ситуации (single_choice, шесть вариантов).

Ответ однозначен по таблице правил `RULES`: ситуация -> один код. Для каждого уровня в условие дословно выписано
правило платформы, которое разводит пары-ловушки (400/422, 502/504, 429/503), поэтому «соседний по смыслу» код
исключён текстом, а не вкусом автора. Независимого оракула нет (в реестре `manual`): варианты выгружаются на ручную
проверку ключом `--samples`.
"""

from __future__ import annotations

from random import Random

from app.modules.assessment.families._lib import names
from app.modules.assessment.families._lib.contract import AnswerSpec, Option, Variant
from app.modules.assessment.families.registry import family_meta

META = family_meta(
    "http.status_choice",
    version=2,
    feature_bounds={
        1: {"options_count": (6, 6), "trap": (1, 1)},
        2: {"options_count": (6, 6), "trap": (1, 1)},
        3: {"options_count": (6, 6), "trap": (1, 1)},
    },
    misconceptions=("neighbor_code",),
)

#: Ресурс -> падежные формы для шаблонов ситуаций: `nom` — кто/что, `gen` — кого/чего, `dat` — кому/чему,
#: `acc` — кого/что, `new_acc` — «новый …» в винительном. Все слова мужского рода: глаголы шаблонов
#: («переехал», «не менялся») согласованы без ветвлений.
RESOURCE_FORMS: dict[str, dict[str, str]] = {
    "order": {"nom": "заказ", "gen": "заказа", "dat": "заказу", "acc": "заказ", "new_acc": "новый заказ"},
    "user": {
        "nom": "пользователь", "gen": "пользователя", "dat": "пользователю", "acc": "пользователя",
        "new_acc": "нового пользователя",
    },
    "invoice": {"nom": "счёт", "gen": "счёта", "dat": "счёту", "acc": "счёт", "new_acc": "новый счёт"},
    "comment": {
        "nom": "комментарий", "gen": "комментария", "dat": "комментарию", "acc": "комментарий",
        "new_acc": "новый комментарий",
    },
    "booking": {"nom": "билет", "gen": "билета", "dat": "билету", "acc": "билет", "new_acc": "новый билет"},
    "report": {"nom": "отчёт", "gen": "отчёта", "dat": "отчёту", "acc": "отчёт", "new_acc": "новый отчёт"},
}  # fmt: skip

#: Правило платформы, которое входит в условие уровня и делает пару-ловушку различимой.
LEVEL_RULES: dict[int, str] = {
    1: "",
    2: (
        "Правила API: 400 — запрос не удалось разобрать; 422 — запрос разобран, но данные не проходят проверку; "
        "401 — нет данных для входа; 403 — вход выполнен, но прав нет."
    ),
    3: (
        "Правила API: 502 — вышестоящий сервис ответил некорректно; 504 — вышестоящий сервис не ответил вовремя; "
        "503 — сервис сам временно недоступен; 429 — клиент превысил свой лимит запросов."
    ),
}

#: Уровень -> правила: (шаблон ситуации, верный код, код-ловушка).
RULES: dict[int, tuple[tuple[str, int, int], ...]] = {
    1: (
        ("Клиент запросил {acc} с номером {n}, и сервер вернул его данные.", 200, 201),
        ("Клиент отправил POST, и сервер создал {new_acc} с номером {n}.", 201, 200),
        ("Клиент удалил {acc} с номером {n}; сервер выполнил запрос и не вернул тела ответа.", 204, 200),
        ("Клиент запросил {acc} с номером {n}, которого не существует.", 404, 400),
        ("При обработке запроса по {dat} с номером {n} в коде сервера возникло необработанное исключение.", 500, 503),
        ("Тело запроса по {dat} с номером {n} не является корректным JSON.", 400, 404),
        ("Клиент обновил {acc} с номером {n} через PUT, и сервер вернул обновлённые данные.", 200, 201),
    ),
    2: (
        ("Запрос по {dat} с номером {n} пришёл без данных для входа.", 401, 403),
        ("Пользователь вошёл, но {nom} с номером {n} принадлежит другому пользователю и недоступен ему.", 403, 401),
        ("JSON в запросе по {dat} с номером {n} корректен, но поле количества отрицательное.", 422, 400),
        ("Тело запроса по {dat} с номером {n} оборвано посередине и не разбирается.", 400, 422),
        ("Клиент прислал If-None-Match, и {nom} с номером {n} с тех пор не менялся.", 304, 200),
        ("Клиент обновляет {acc} с номером {n} по устаревшей версии: другой клиент уже изменил запись.", 409, 422),
        ("{nom} с номером {n} навсегда переехал на другой адрес.", 301, 302),
    ),
    3: (
        ("Сервис вызывает платёжный шлюз для {gen} с номером {n}, а тот прислал нечитаемый ответ.", 502, 504),
        ("Сервис вызвал внешний шлюз для {gen} с номером {n}, но тот не ответил за отведённое время.", 504, 502),
        ("Сервис закрыт на обслуживание, а запрос по {dat} с номером {n} пришёл в это время.", 503, 429),
        ("Клиент за минуту превысил свой лимит запросов по {dat} с номером {n}.", 429, 503),
        ("Запрос на изменение {gen} с номером {n} содержит If-Match со старой версией, запись не менялась.", 412, 409),
        ("Клиент создаёт {acc} с уникальным кодом, который уже занят другой записью (с номером {n}).", 409, 422),
        ("Данные {gen} с номером {n} разобраны, но дата окончания раньше даты начала.", 422, 400),
    ),
}  # fmt: skip

#: Пул кодов, из которых берутся отвлекающие варианты.
CODES: dict[int, tuple[int, ...]] = {
    1: (200, 201, 204, 301, 400, 404, 500, 503),
    2: (200, 301, 302, 304, 400, 401, 403, 404, 409, 422),
    3: (400, 404, 409, 412, 422, 429, 500, 502, 503, 504),
}
#: Коды, которые в ситуации нельзя показывать как отвлекающие: они тоже были бы допустимы.
ALSO_OK: dict[tuple[int, int], tuple[int, ...]] = {
    (1, 0): (),
    (2, 1): (404,),
    (3, 4): (),
    (2, 3): (),
    (3, 5): (400, 412),
    (2, 2): (),
}


def correct_code(level: int, rule_index: int) -> int:
    """Правило модели: верный код ответа — второй столбец таблицы `RULES`."""
    return RULES[level][rule_index][1]


def generate(level: int, seed: int) -> Variant:
    """Вариант: ситуация, правило платформы и шесть кодов ответа, верный один.

    Ответ берётся из таблицы `RULES`. Модель ошибки `neighbor_code` — код-ловушка, соседний по смыслу (401 вместо
    403, 400 вместо 422, 502 вместо 504): он всегда среди вариантов. Ответ однозначен: в условии уровня выписано
    правило, разводящее пару, а отвлекающие варианты — коды, которые для ситуации заведомо неверны.
    """
    rng = Random(seed)
    rule_index = rng.randrange(len(RULES[level]))
    template, code, trap = RULES[level][rule_index]
    forms = RESOURCE_FORMS[names.pick(rng, names.RESOURCES)]
    situation = template.format(**forms, n=rng.randint(2, 99))
    situation = situation[0].upper() + situation[1:]
    banned = {code, trap, *ALL_OK_FOR.get((level, template), ())}
    others = [c for c in CODES[level] if c not in banned]
    shown = [code, trap, *rng.sample(others, 4)]
    rng.shuffle(shown)
    options = tuple(Option(id=f"o{i}", text=str(c)) for i, c in enumerate(shown, start=1))
    by_code = {int(o.text): o.id for o in options}
    rules = LEVEL_RULES[level]
    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt=f"{situation} {rules} Какой код ответа HTTP должен вернуть сервер?".replace("  ", " "),
        options=options,
        answer=AnswerSpec.choice(by_code[code]),
        misconception_answers={"neighbor_code": by_code[trap]},
        features={"options_count": 6, "trap": 1},
        explanation=f"Правило: «{template}» -> {code}. Типичная путаница — код {trap}.",
    )


#: Для ситуаций с несколькими допустимыми кодами: шаблон -> запрещённые отвлекающие.
ALL_OK_FOR: dict[tuple[int, str], tuple[int, ...]] = {
    (level, rule[0]): ALSO_OK.get((level, index), ())
    for level, rules in RULES.items()
    for index, rule in enumerate(rules)
}


def selfcheck(v: Variant) -> list[str]:
    """Перепроверка: ситуация находится в таблице правил, верным является ровно один вариант с её кодом."""
    assert v.options is not None
    found = [
        (level, index)
        for level, rules in RULES.items()
        for index, (template, _, _) in enumerate(rules)
        if level == v.level and f"«{template}»" in v.explanation
    ]
    if len(found) != 1:
        return ["ситуация не находится в таблице правил однозначно"]
    code = str(correct_code(*found[0]))
    hits = [o.id for o in v.options if o.text == code]
    problems = []
    if hits != [v.answer.option_id]:
        problems.append(f"верным должен быть ровно один вариант с кодом {code}, найдено: {hits}")
    if len({o.text for o in v.options}) != len(v.options):
        problems.append("коды в вариантах повторяются")
    return problems
