"""Учебное семейство «код ответа»: выбор одного варианта по таблице правил.

Образец семейства вида `single_choice`. Что здесь показано:

* ответ определяется таблицей правил «ситуация -> код», а не вписан в вариант рукой;
* отвлекающие варианты берутся из того же набора кодов, один из них — код-ловушка, соседний по смыслу;
* порядок вариантов перемешивает генератор; ответ модели ошибки — идентификатор варианта с кодом-ловушкой;
* независимого оракула нет: правило названо в разборе, варианты выгружаются на ручную проверку (`--samples`).
"""

from __future__ import annotations

from random import Random

from app.modules.assessment.families._lib import names
from app.modules.assessment.families._lib.contract import AnswerSpec, Option, Variant
from app.modules.assessment.families.registry import family_meta
from tests.assessment.fake_families import FAKE_SPECS

META = family_meta(
    "http.fake_status",
    version=1,
    feature_bounds={1: {"options_count": (6, 6), "trap": (1, 1)}, 2: {"options_count": (6, 6), "trap": (1, 1)}},
    spec=FAKE_SPECS["http.fake_status"],
)

#: Уровень -> правила: (шаблон ситуации, верный код, код-ловушка). `{res}` — ресурс, `{n}` — число.
RULES: dict[int, tuple[tuple[str, int, int], ...]] = {
    1: (
        ("Клиент запросил {res} с номером {n}, и сервер вернул его данные.", 200, 201),
        ("Клиент отправил POST, и сервер создал новый {res} с номером {n}.", 201, 200),
        ("Клиент удалил {res} с номером {n}; сервер выполнил запрос и не вернул тела.", 204, 200),
        ("Клиент запросил {res} с номером {n}, которого не существует.", 404, 400),
        ("При обработке запроса на {res} с номером {n} в коде сервера возникло необработанное исключение.", 500, 400),
        ("Клиент прислал запрос на {res} с номером {n} с телом, которое не является корректным JSON.", 400, 404),
    ),
    2: (
        ("Запрос на {res} с номером {n} пришёл без данных для входа.", 401, 403),
        ("Пользователь вошёл, но {res} с номером {n} принадлежит другому пользователю.", 403, 401),
        ("JSON в запросе корректен, но поле количества у {res} с номером {n} отрицательное.", 422, 400),
        ("Тело запроса на {res} с номером {n} оборвано посередине и не разбирается.", 400, 422),
        ("Клиент прислал If-None-Match, и {res} с номером {n} с тех пор не менялся.", 304, 200),
        ("Клиент обновляет {res} с номером {n} по устаревшей версии, которую уже изменил другой клиент.", 409, 422),
        ("{res} с номером {n} навсегда переехал на другой адрес.", 301, 304),
    ),
}  # fmt: skip
CODES: dict[int, tuple[int, ...]] = {
    1: (200, 201, 204, 301, 400, 404, 500, 503),
    2: (200, 301, 302, 304, 400, 401, 403, 404, 409, 422),
}
RESOURCE_TITLES = {"order": "заказ", "user": "пользователь", "invoice": "счёт", "comment": "комментарий",
                   "booking": "бронь", "report": "отчёт"}  # fmt: skip


def correct_code(level: int, rule_index: int) -> int:
    """Правило модели: код ответа для ситуации — второй столбец таблицы `RULES`."""
    return RULES[level][rule_index][1]


def generate(level: int, seed: int) -> Variant:
    """Вариант: описание ситуации и шесть кодов ответа, верный — один.

    Ответ берётся из таблицы правил `RULES` по ситуации. Модель ошибки `neighbor_code` — соседний по смыслу код
    (401 вместо 403, 400 вместо 422): он всегда есть среди вариантов. Ответ однозначен: в таблице каждой ситуации
    соответствует ровно один код, а отвлекающие варианты — другие коды.
    """
    rng = Random(seed)
    rule_index = rng.randrange(len(RULES[level]))
    template, _, trap = RULES[level][rule_index]
    code = correct_code(level, rule_index)
    resource = RESOURCE_TITLES[names.pick(rng, names.RESOURCES)]
    situation = template.format(res=resource, n=rng.randint(2, 99))
    situation = situation[0].upper() + situation[1:]

    others = [c for c in CODES[level] if c not in (code, trap)]
    shown = [code, trap, *rng.sample(others, 4)]
    rng.shuffle(shown)
    options = tuple(Option(id=f"o{i}", text=str(c)) for i, c in enumerate(shown, start=1))
    by_code = {int(option.text): option.id for option in options}

    return Variant(
        family_id=META.id,
        family_version=META.version,
        level=level,
        seed=seed,
        prompt=f"{situation} Какой код ответа HTTP должен вернуть сервер?",
        options=options,
        answer=AnswerSpec.choice(by_code[code]),
        misconception_answers={"neighbor_code": by_code[trap]},
        features={"options_count": len(options), "trap": 1},
        explanation=f"Правило: «{template}» -> {code}. Типичная путаница — код {trap}.",
    )


def selfcheck(v: Variant) -> list[str]:
    """Перепроверка: ровно один вариант совпадает с кодом из таблицы правил для ситуации из разбора."""
    assert v.options is not None
    matching = [
        (level, index)
        for level, rules in RULES.items()
        for index, (template, _, _) in enumerate(rules)
        if level == v.level and f"«{template}»" in v.explanation
    ]
    if len(matching) != 1:
        return ["ситуация не находится в таблице правил однозначно"]
    code = str(correct_code(*matching[0]))
    hits = [option.id for option in v.options if option.text == code]
    if hits != [v.answer.option_id]:
        return [f"верным должен быть ровно один вариант с кодом {code}, найдено: {hits}"]
    return []
