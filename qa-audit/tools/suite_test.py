"""TEST-01…27: матрица прохождения обычного теста (API + DB) с независимым пересчётом исхода.

Ожидаемый исход считается здесь же, отдельной реализацией опубликованной модели (`GET /assessment/methodology`):
априорное N(0, 2) на сетке θ ∈ [−4; 4] шаг 0,05; P(верно) = c + (1 − c)·σ(a(θ − b)); `p_pass = P(θ ≥ порог грейда)`;
≥ 0,8 — подтверждён (и «с запасом», если P(θ ≥ порог + 0,75) ≥ 0,8), ≤ 0,2 — не подтверждён, иначе «на границе».
Код движка платформы при этом не импортируется.
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import math
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import httpx  # noqa: E402
import qalib as q  # noqa: E402

A = "API+DB"
SRC = "GET /assessment/methodology; README «Тестирование»; rules/decide (Арх. 5.5)"
M = httpx.get(q.BASE + "/api/v1/assessment/methodology").json()["constants"]
GRID = [round(M["theta_grid_min"] + i * M["theta_grid_step"], 4) for i in range(int((M["theta_grid_max"] - M["theta_grid_min"]) / M["theta_grid_step"]) + 1)]


def expected(items: list[dict], grade: str) -> dict:
    """Независимая оценка: апостериорное по учтённым заданиям `items` = [{a, b, c, score}]."""
    logp = [-0.5 * ((t - M["prior_mean"]) / M["prior_sd"]) ** 2 for t in GRID]
    for it in items:
        for i, t in enumerate(GRID):
            p = it["c"] + (1 - it["c"]) / (1 + math.exp(-it["a"] * (t - it["b"])))
            logp[i] += math.log(p if it["score"] else 1 - p)
    top = max(logp)
    w = [math.exp(v - top) for v in logp]
    total = sum(w)
    theta = sum(t * x for t, x in zip(GRID, w)) / total
    cut = M["theta_cut"][grade]

    def p_ge(x: float) -> float:
        return sum(v for t, v in zip(GRID, w) if t >= x - 1e-9) / total

    p_pass, p_margin = p_ge(cut), p_ge(cut + M["margin_delta"])
    if p_pass >= M["p_confirm"] and p_margin >= M["p_margin"]:
        outcome = "confirmed_with_margin"
    elif p_pass >= M["p_confirm"]:
        outcome = "confirmed"
    elif p_pass <= M["p_reject"]:
        outcome = "not_confirmed"
    else:
        outcome = "borderline"
    return {"theta": theta, "p_pass": p_pass, "outcome": outcome}


def items_db(session_id: str) -> list[dict]:
    raw = q.sql(
        "select json_agg(json_build_object('id', id, 'pos', position, 'stage', stage, 'status', status, 'score', score, 'a', a_used, "
        "'b', b_used, 'c', c_used, 'family', family_id, 'variant', variant_id, 'answer', answer) order by position) "
        f"from assessment_session_item where session_id = '{session_id}'"
    )
    return json.loads(raw)


COUNTED = ("answered", "skipped", "unreached")


def check_session(case: str, title: str, user: q.User, session_id: str, grade: str, plan: list[str] | None, want: str) -> dict:
    """Сверить сессию с планом и независимым пересчётом; записать результат."""
    rows = items_db(session_id)
    sess = q.session_db(session_id)
    counted = [r for r in rows if r["status"] in COUNTED]
    exp = expected([{"a": r["a"], "b": r["b"], "c": r["c"], "score": int(r["score"] or 0)} for r in counted], grade)
    moves = "".join({"answered": "R" if r["score"] else "W", "skipped": "S"}.get(r["status"], "?") for r in rows)
    planned = "".join({"right": "R", "wrong": "W", "skip": "S"}[m] for m in plan) if plan else None
    result = user.get(f"/assessment/sessions/{session_id}/result")[1]
    category = q.sql(f"select grade_code from assessment_category where candidate_id='{user.id}'")
    problems = []
    if planned is not None and moves[: len(planned)] != planned:
        problems.append(f"ходы {moves} ≠ план {planned}")
    if abs(exp["theta"] - sess["theta"]) > 0.03:
        problems.append(f"θ {sess['theta']:.3f} ≠ независимый расчёт {exp['theta']:.3f}")
    if exp["outcome"] != sess["outcome"]:
        problems.append(f"исход {sess['outcome']} ≠ независимый расчёт {exp['outcome']}")
    if result.get("outcome") != sess["outcome"]:
        problems.append("исход в API результата ≠ исход в базе")
    if len({r["variant"] for r in rows}) != len(rows):
        problems.append("повтор варианта в сессии")
    if len(rows) > M["base_main"] + M["base_stretch"] + M["ext_block"] * M["max_ext_blocks"]:
        problems.append(f"длина {len(rows)} больше предела")
    if (sess["outcome"] in ("confirmed", "confirmed_with_margin")) != (category == grade):
        problems.append(f"категория «{category}» не соответствует исходу {sess['outcome']}")
    if want and not eval(want, {}, {"o": sess["outcome"], "n": len(rows), "stage": sess["stage"]}):
        problems.append(f"не выполнено ожидание: {want}")
    actual = {"ходы": moves, "исход": sess["outcome"], "θ": round(sess["theta"], 3), "θ_независимо": round(exp["theta"], 3),
              "p_pass": round(exp["p_pass"], 3), "заданий": len(rows), "блоков": sess["stage"], "категория": category or None, "проблемы": problems}  # fmt: skip
    q.rec(case, title, A, f"ходы по плану; исход и θ совпадают с независимым расчётом; {want}", actual, not problems, source=SRC)
    return {"rows": rows, "sess": sess, "exp": exp}


def patterned(case: str, title: str, grade: str, plan_fn, want: str) -> None:
    user = q.candidate(case.lower().replace("-", ""), grade, min_salary=None)
    sid, item = q.start(user, grade)
    trail = q.run_test(user, sid, item, plan_fn)
    check_session(case, title, user, sid, grade, [t["move"] for t in trail], want)


def matrix() -> None:
    patterned("TEST-01", "Все ответы правильные", "middle", lambda n, r: "right", "o in ('confirmed', 'confirmed_with_margin') and n == 14 and stage == 0")
    patterned("TEST-02", "Все ответы неправильные, но верного формата", "middle", lambda n, r: "wrong", "o == 'not_confirmed' and n == 14")
    patterned("TEST-03", "Все задания пропущены («Не знаю»)", "middle", lambda n, r: "skip", "o == 'not_confirmed' and n == 14")
    patterned("TEST-04", "Первое пропущено, остальные верные", "middle", lambda n, r: "skip" if n == 1 else "right", "n >= 14")
    patterned("TEST-05", "Два пропуска подряд в середине", "junior", lambda n, r: "skip" if n in (6, 7) else "right", "n >= 14")
    patterned("TEST-06", "Три пропуска подряд", "junior", lambda n, r: "skip" if n in (4, 5, 6) else "right", "n >= 14")
    patterned("TEST-07", "Чередование: верный ответ — пропуск", "junior", lambda n, r: "right" if n % 2 else "skip", "n >= 14")
    patterned("TEST-08", "Цикл: верный — неверный — пропуск", "junior", lambda n, r: ("right", "wrong", "skip")[(n - 1) % 3], "n >= 14")
    patterned("TEST-10", "Последнее базовое задание пропущено", "middle", lambda n, r: "skip" if n == 14 else "right", "n >= 14 and o != 'not_confirmed'")


def borderline() -> None:
    """TEST-11…13: подобрать ответы так, чтобы после базовой формы и после первого блока исход оставался «на границе»."""
    grade = "middle"
    for attempt in range(3):
        user = q.candidate(f"test11{attempt}", grade, min_salary=None)
        sid, item = q.start(user, grade)
        answered: list[dict] = []
        log = []
        stage_seen = 0
        while item:
            rows = items_db(sid)
            cur = next(r for r in rows if r["id"] == item["id"])
            block = [r for r in rows if r["stage"] == cur["stage"]]
            last_of_block = cur["pos"] == max(r["pos"] for r in block)
            # жадно: выбираем ход, после которого независимая p_pass ближе к 0,5
            trial = {}
            for move, score in (("right", 1), ("wrong", 0)):
                trial[move] = expected(answered + [{"a": cur["a"], "b": cur["b"], "c": cur["c"], "score": score}], grade)["p_pass"]
            move = min(trial, key=lambda m: abs(trial[m] - 0.5))
            if last_of_block and cur["stage"] == M["max_ext_blocks"]:
                move = "skip"  # TEST-13: пропуск последнего задания последнего блока
            row = q.item_row(item["id"])
            body = {"item_id": item["id"]}
            if move == "skip":
                body["skipped"] = True
            else:
                body["answer"] = q.right(row) if move == "right" else q.wrong(row)
            st, reply = user.post(f"/assessment/sessions/{sid}/answers", body)
            assert st == 200, reply
            answered.append({"a": cur["a"], "b": cur["b"], "c": cur["c"], "score": 1 if move == "right" else 0})
            if last_of_block:
                log.append((cur["stage"], len(answered), round(expected(answered, grade)["p_pass"], 3)))
            stage_seen = max(stage_seen, cur["stage"])
            item = reply.get("next_item")
        rows = items_db(sid)
        sess = q.session_db(sid)
        sizes = [sum(1 for r in rows if r["stage"] == s) for s in range(3)]
        if stage_seen < 1:
            continue
        exp = expected(answered, grade)
        fam_dupe = len({r["variant"] for r in rows}) != len(rows)
        q.rec("TEST-11", "Пограничный результат после базовой формы → добавочный блок", A,
              "при p_pass ∈ (0,2; 0,8) после 14 заданий добавлено ровно 6, без повторов вариантов",
              {"контрольные точки (блок, заданий, p_pass)": log, "размеры блоков": sizes, "повторы": fam_dupe},
              sizes[0] == 14 and sizes[1] == 6 and not fam_dupe and 0.2 < log[0][2] < 0.8, source=SRC)  # fmt: skip
        second = len(log) > 1 and 0.2 < log[1][2] < 0.8
        q.rec("TEST-12", "Пограничный результат после первого блока → второй блок либо завершение; предел 26", A,
              "второй блок только если после 20 заданий исход снова «на границе»; всего не больше 26",
              {"точки": log, "размеры": sizes, "всего": len(rows)}, (sizes[2] == 6) == second and len(rows) <= 26, source=SRC)  # fmt: skip
        last = rows[-1]
        finals = q.sql(f"select count(*) from assessment_session where id='{sid}' and status='finished'")
        again = user.post(f"/assessment/sessions/{sid}/answers", {"item_id": last["id"], "skipped": True})
        q.rec("TEST-13", "Пропуск последнего задания последнего блока: одна финализация, тест не продолжается", A,
              "сессия закрыта один раз; исход = независимому расчёту; повторный ответ отклонён",
              {"последнее": last["status"], "исход": sess["outcome"], "независимо": exp["outcome"], "заданий": len(rows), "повтор": (again[0], again[1].get("code")),
               "finished_rows": finals}, sess["status"] == "finished" and sess["outcome"] == exp["outcome"] and again[0] in (409, 410) and
              (sizes[2] != 6 or last["status"] == "skipped"), source=SRC)  # fmt: skip
        return
    q.rec("TEST-11", "Пограничный результат после базовой формы → добавочный блок", A, "добавочный блок получен", "за три попытки блок не получен", None, status="BLOCKED")


def protocol() -> None:
    user = q.candidate("testproto", "middle", min_salary=None)
    sid, item = q.start(user, "middle")
    first = item
    row = q.item_row(first["id"])
    # TEST-09: ответ + пропуск в одном запросе
    st, reply = user.post(f"/assessment/sessions/{sid}/answers", {"item_id": first["id"], "answer": q.right(row), "skipped": True})
    stored = items_db(sid)[0]
    q.rec("TEST-09", "Введён ответ, затем «Не знаю»: сервер фиксирует пропуск, а не черновик", A, "status=skipped, score=0, ответ не сохранён",
          {"http": st, "status": stored["status"], "score": stored["score"], "answer": stored["answer"]},
          st == 200 and stored["status"] == "skipped" and stored["score"] == 0 and stored["answer"] is None, source="OpenAPI AnswerRequest.skipped")  # fmt: skip
    second = reply["next_item"]
    # TEST-16 / TEST-22: старое задание и задание чужой сессии
    old = user.post(f"/assessment/sessions/{sid}/answers", {"item_id": first["id"], "answer": q.right(row)})
    other = q.candidate("testother", "middle", min_salary=None)
    osid, oitem = q.start(other, "middle")
    foreign = user.post(f"/assessment/sessions/{sid}/answers", {"item_id": oitem["id"], "skipped": True})
    cross = user.post(f"/assessment/sessions/{osid}/answers", {"item_id": oitem["id"], "skipped": True})
    state = q.session_db(sid)
    q.rec("TEST-16", "Вторая вкладка: ответ на уже пройденное задание", A, "отказ; текущее задание и счёт не меняются",
          {"old": (old[0], old[1].get("code")), "answered": state["answered"], "first": items_db(sid)[0]["status"]},
          old[0] in (409, 422) and state["answered"] == 1 and items_db(sid)[0]["status"] == "skipped", source=SRC)  # fmt: skip
    q.rec("TEST-22", "Ответ на задание другой попытки и в чужую сессию", A, "отказ, чужая сессия не тронута",
          {"чужое задание в свою": (foreign[0], foreign[1].get("code")), "чужая сессия": cross[0], "чужая отвечено": q.session_db(osid)["answered"]},
          foreign[0] in (404, 409, 422) and cross[0] == 404 and q.session_db(osid)["answered"] == 0, source=SRC)  # fmt: skip
    # TEST-24: пустой, пробелы, слишком длинный, неверный тип — не должны молча становиться ответом или пропуском
    def cur_item() -> dict:
        return user.get(f"/assessment/sessions/{sid}")[1]["item"]

    out = {}
    for label in ("нет поля", "объект вместо значения", "null без пропуска", "10 000 знаков", "пробелы", "пусто"):
        it = cur_item()
        kind = q.item_row(it["id"])["kind"]
        shape = {"numeric_input": "value", "text_input": "value", "single_choice": "option_id", "multi_choice": "option_ids", "pick_line": "line"}[kind]
        answer = {"нет поля": {"что-то": 1}, "объект вместо значения": {shape: {"x": 1}}, "null без пропуска": None, "10 000 знаков": {shape: "9" * 10000},
                  "пробелы": {shape: "   " if shape != "option_ids" else ["  "]}, "пусто": {shape: "" if shape != "option_ids" else []}}[label]  # fmt: skip
        st, body = user.post(f"/assessment/sessions/{sid}/answers", {"item_id": it["id"], "answer": answer})
        row_now = next(r for r in items_db(sid) if r["id"] == it["id"])
        out[label] = (kind, st, body.get("code") if isinstance(body, dict) else None, row_now["status"], row_now["score"])
    accepted = [k for k, v in out.items() if v[1] == 200]
    q.rec("TEST-24", "Пустой ответ, пробелы, слишком длинный, неверный тип", A, "422 с объяснением; задание остаётся текущим", out,
          not accepted, source="OpenAPI: 422 answer_malformed / validation_error",
          note=("принято как ответ: " + ", ".join(accepted)) if accepted else "")  # fmt: skip
    second = cur_item()
    # TEST-20 / TEST-21: потерянный ответ и ключ идемпотентности
    key = str(uuid.uuid4())
    row2 = q.item_row(second["id"])
    body = {"item_id": second["id"], "answer": q.right(row2)}
    a1 = user.post(f"/assessment/sessions/{sid}/answers", body, headers={"Idempotency-Key": key})
    a2 = user.post(f"/assessment/sessions/{sid}/answers", body, headers={"Idempotency-Key": key})
    a3 = user.post(f"/assessment/sessions/{sid}/answers", {"item_id": second["id"], "answer": q.wrong(row2)}, headers={"Idempotency-Key": key})
    stored2 = next(r for r in items_db(sid) if r["id"] == second["id"])
    state = q.session_db(sid)
    answered_before = next(i for i, r in enumerate(items_db(sid)) if r["id"] == second["id"])
    q.rec("TEST-20", "Ответ принят, ответ сервера потерян, запрос повторён с тем же ключом", A, "повтор возвращает то же следующее задание; учёт один",
          {"первый": a1[0], "повтор": a2[0], "то же следующее": (a1[1].get("next_item") or {}).get("id") == (a2[1].get("next_item") or {}).get("id"), "answered": state["answered"]},
          a1[0] == 200 and a2[0] == 200 and (a1[1].get("next_item") or {}).get("id") == (a2[1].get("next_item") or {}).get("id") and state["answered"] == answered_before + 1,
          source="заголовок Idempotency-Key (OpenAPI)")  # fmt: skip
    q.rec("TEST-21", "Тот же ключ идемпотентности с другим ответом", A, "конфликт; прежний ответ не перезаписан",
          {"http": (a3[0], a3[1].get("code")), "score": stored2["score"]}, a3[0] in (409, 422) and stored2["score"] == 1, source="заголовок Idempotency-Key (OpenAPI)")  # fmt: skip
    # TEST-14: продолжение после «закрытия страницы»
    resumed = user.clone().get(f"/assessment/sessions/{sid}")[1]
    q.rec("TEST-14", "Повторное открытие попытки после нескольких ответов", A, "текущее задание — следующее за последним ответом, прогресс сохранён",
          {"progress": resumed["progress"], "item": resumed["item"]["id"] == a1[1]["next_item"]["id"], "status": resumed["status"]},
          resumed["progress"]["answered"] == state["answered"] and resumed["item"]["id"] == a1[1]["next_item"]["id"], source="GET /assessment/sessions/{id}")  # fmt: skip
    # TEST-17/18/19: одновременные запросы
    def burst(bodies: list[dict]) -> list[tuple[int, str | None]]:
        def one(b: dict) -> tuple[int, str | None]:
            st, rep = user.clone().post(f"/assessment/sessions/{sid}/answers", b)
            return st, rep.get("code") if isinstance(rep, dict) else None
        with cf.ThreadPoolExecutor(len(bodies)) as pool:
            return list(pool.map(one, bodies))

    def current() -> dict:
        return user.get(f"/assessment/sessions/{sid}")[1]["item"]

    cur = current()
    before = q.session_db(sid)["answered"]
    res = burst([{"item_id": cur["id"], "answer": q.right(q.item_row(cur["id"]))}] * 5)
    q.rec("TEST-17", "Пять одновременных «Ответить» на одно задание", A, "учтён один ответ, переход на одно задание, без 500",
          {"codes": res, "answered": q.session_db(sid)["answered"] - before}, q.session_db(sid)["answered"] - before == 1 and all(r[0] in (200, 409, 422) for r in res), source=SRC)  # fmt: skip
    cur = current()
    before = q.session_db(sid)["answered"]
    res = burst([{"item_id": cur["id"], "skipped": True}] * 5)
    q.rec("TEST-18", "Пять одновременных «Пропустить»", A, "один пропуск, без перескока через задание",
          {"codes": res, "answered": q.session_db(sid)["answered"] - before}, q.session_db(sid)["answered"] - before == 1 and all(r[0] in (200, 409, 422) for r in res), source=SRC)  # fmt: skip
    cur = current()
    before = q.session_db(sid)["answered"]
    res = burst([{"item_id": cur["id"], "answer": q.right(q.item_row(cur["id"]))}, {"item_id": cur["id"], "skipped": True}] * 2)
    one_row = next(r for r in items_db(sid) if r["id"] == cur["id"])
    q.rec("TEST-19", "Почти одновременно «Ответить» и «Пропустить»", A, "один согласованный исход задания; второй запрос — конфликт",
          {"codes": res, "answered": q.session_db(sid)["answered"] - before, "итог задания": one_row["status"]},
          q.session_db(sid)["answered"] - before == 1 and one_row["status"] in ("answered", "skipped") and all(r[0] in (200, 409, 422) for r in res), source=SRC)  # fmt: skip
    # дорешиваем и TEST-23
    q.run_test(user, sid, current(), lambda n, r: "right")
    final = q.session_db(sid)
    late = user.post(f"/assessment/sessions/{sid}/answers", {"item_id": cur["id"], "skipped": True})
    r1 = user.get(f"/assessment/sessions/{sid}/result")[1]
    r2 = user.get(f"/assessment/sessions/{sid}/result")[1]
    final2 = q.session_db(sid)
    q.rec("TEST-23", "Ответ после завершения попытки и повторное открытие результата", A, "ответ отклонён; итог неизменен",
          {"late": (late[0], late[1].get("code")), "outcome": (final["outcome"], final2["outcome"]), "same_result": r1["outcome"] == r2["outcome"] and r1["finished_at"] == r2["finished_at"]},
          late[0] in (409, 410) and final["outcome"] == final2["outcome"] and final["theta"] == final2["theta"] and r1["finished_at"] == r2["finished_at"], source=SRC)  # fmt: skip
    q.run_test(other, osid, oitem, lambda n, r: "skip")


GRADE_PROBE = r'''
import json, sys
from app.modules.assessment import grading
cases = json.loads(sys.stdin.read())
out = []
for kind, key, answer in cases:
    try:
        r = grading.grade(kind, key, answer, misconceptions=None)
        out.append([r.score, r.parse_ok])
    except Exception as exc:
        out.append(["EXC", type(exc).__name__])
print(json.dumps(out))
'''


def grading() -> None:
    """TEST-25…27: нормализация ответов — прямым вызовом функции оценивания в контейнере api (уровень unit)."""
    import subprocess

    num = {"value": 8, "integer": True, "tolerance_abs": 0.0, "tolerance_rel": 0.0}
    frac = {"value": 2.5, "integer": False, "tolerance_abs": 0.0, "tolerance_rel": 0.0}
    tok = {"mode": "tokens", "value": "3 4 5 6", "case_sensitive": False}
    multi = {"option_ids": ["o2", "o3", "o5"]}
    cases = [
        ("numeric_input", num, {"value": v}) for v in ["8", " 8 ", "08", "+8", "8.0", "8,0", "8.", "7", "-8", "0", "8 9", "восемь", "8e0", "８"]
    ] + [("numeric_input", frac, {"value": v}) for v in ["2.5", "2,5", "2.50", "2.4", "5/2"]] + [
        ("text_input", tok, {"value": v}) for v in ["3 4 5 6", "3  4   5 6", " 3 4 5 6 ", "3\n4\n5\n6", "3,4,5,6", "3 4 5", "3 4 5 6 7", "6 5 4 3", "3456"]
    ] + [("multi_choice", multi, {"option_ids": v}) for v in [["o2", "o3", "o5"], ["o5", "o3", "o2"], ["o2", "o3"], ["o2", "o3", "o5", "o1"], ["o5"], [], ["o2", "o2", "o3", "o5"]]]
    out = subprocess.run(["docker", "compose", "-f", str(q.ROOT / "compose.yml"), "exec", "-T", "api", "python", "-c", GRADE_PROBE],
                         input=json.dumps(cases), capture_output=True, text=True, check=False)  # fmt: skip
    if out.returncode != 0:
        q.rec("TEST-25", "Нормализация чисел", "unit", "функция оценивания вызвана", out.stderr[-300:], None, status="BLOCKED")
        return
    res = json.loads(out.stdout.strip().splitlines()[-1])
    table = {f"{c[0][:3]}:{c[2].get('value', c[2].get('option_ids'))!r}": r for c, r in zip(cases, res)}
    n = dict(list(table.items())[:14])
    good_num = all(n[f"num:{v!r}"][0] == 1 for v in ["8", " 8 ", "8.0", "8,0"]) and all(n[f"num:{v!r}"][0] != 1 for v in ["7", "-8", "0", "8 9", "восемь"])
    q.rec("TEST-25", "Числа: пробелы, точка и запятая, ведущие нули, знак, мусор", "unit (функция оценивания в контейнере api)",
          "«8», « 8 », «8.0», «8,0» — верно; «7», «−8», «0», «8 9», «восемь» — не верно", dict(list(table.items())[:19]), good_num,
          source="подсказка поля: «число; запятая и точка равнозначны»")  # fmt: skip
    t = {k: v for k, v in table.items() if k.startswith("tex")}
    good_tok = (t["tex:'3 4 5 6'"][0] == 1 and t["tex:'3  4   5 6'"][0] == 1 and t["tex:' 3 4 5 6 '"][0] == 1
                and all(t[f"tex:{v!r}"][0] != 1 for v in ["3 4 5", "3 4 5 6 7", "6 5 4 3", "3456"]))  # fmt: skip
    q.rec("TEST-26", "Значения через пробел: лишние пробелы, перевод строки, лишнее/недостающее значение, порядок", "unit (функция оценивания в контейнере api)",
          "лишние пробелы не мешают; недостающее, лишнее значение и другой порядок — не верно", t, good_tok,
          source="условие задания: «через пробел в порядке вывода»")  # fmt: skip
    m = {k: v for k, v in table.items() if k.startswith("mul")}
    vals = list(m.values())
    q.rec("TEST-27", "Несколько вариантов: порядок выбора, недобор, лишний вариант, пусто", "unit (функция оценивания в контейнере api)",
          "полный набор в любом порядке — верно; недобор, лишний вариант, один из трёх — не верно", m,
          vals[0][0] == 1 and vals[1][0] == 1 and all(v[0] != 1 for v in vals[2:6]), source="правило оценивания multi_choice")  # fmt: skip


if __name__ == "__main__":
    parts = [globals()[name] for name in sys.argv[1:]] or [matrix, borderline, protocol, grading]
    for part in parts:
        try:
            part()
        except Exception as exc:
            q.rec(f"ERR-{part.__name__}", f"Группа {part.__name__} прервана", A, "группа выполняется до конца", repr(exc)[:500], None, status="BLOCKED")
    print("готово")
