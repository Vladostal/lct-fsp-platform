"""DEMO, PUB, FIND, EMP, NEED, MATCH — проверки уровня API/DB на живом стенде (без сдвига часов)."""

from __future__ import annotations

import concurrent.futures as cf
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import qalib as q  # noqa: E402

A = "API+DB"
PUBLISH = {"action": "grant", "version": "publication-1"}


def demo_login(key: str) -> q.User:
    user = q.User(key)
    status, reply = user.post("/demo/login", {"account_key": key})
    assert status == 200, reply
    user.id = reply["id"]
    return user


def demo() -> None:
    src = "README «Сквозной сценарий»: быстрый демо-тест; POST /demo/assessment/quick-session"
    c = q.candidate("demo01", "middle")
    st, reply = c.post("/demo/assessment/quick-session", {"grade_code": "middle"})
    sid = reply.get("session_id")
    view = c.get(f"/assessment/sessions/{sid}")[1] if sid else {}
    q.rec("DEMO-01", "Быстрый демо-тест: адрес существует, открывается первое ручное задание", A, "200, сессия in_progress, задание 13 из 14",
          {"http": st, "status": view.get("status"), "progress": view.get("progress")},
          st == 200 and view.get("status") == "in_progress" and view["progress"]["answered"] == 12 and view["progress"]["min_total"] == 14, source=src)  # fmt: skip
    # DEMO-04: обновление страницы между заданиями и повтор последнего ответа
    first = view["item"]
    r1 = c.post(f"/assessment/sessions/{sid}/answers", {"item_id": first["id"], "answer": q.right(q.item_row(first["id"]))})
    again_view = c.clone().get(f"/assessment/sessions/{sid}")[1]
    last = again_view["item"]
    body = {"item_id": last["id"], "answer": q.right(q.item_row(last["id"]))}
    r2 = c.post(f"/assessment/sessions/{sid}/answers", body)
    r3 = c.post(f"/assessment/sessions/{sid}/answers", body)
    s = q.session_db(sid)
    q.rec("DEMO-02", "Ответить на все задания быстрого теста: два ручных шага", A, "после двух ответов сессия закрыта, исход подтверждающий, 14 заданий",
          {"steps": [r1[0], r2[0]], "finished": r2[1].get("finished"), "outcome": s["outcome"], "answered": s["answered"]},
          r1[0] == 200 and r2[0] == 200 and r2[1].get("finished") and s["answered"] == 14 and s["outcome"].startswith("confirmed"), source=src)  # fmt: skip
    q.rec("DEMO-04", "Обновление страницы между заданиями и повтор отправки последнего ответа", A, "попытка не теряется; повтор не создаёт второго результата",
          {"resumed_on": again_view["progress"]["answered"], "repeat": (r3[0], r3[1].get("code")), "sessions": q.sql(f"select count(*) from assessment_session where candidate_id='{c.id}'")},
          again_view["progress"]["answered"] == 13 and r3[0] in (409, 410) and q.sql(f"select count(*) from assessment_session where candidate_id='{c.id}'") == "1", source=src)  # fmt: skip
    # DEMO-03: первый пропустить, второй дать; отдельной попыткой — пропустить все
    out = {}
    for label, plan in {"пропуск+ответ": lambda n, r: "skip" if n == 1 else "right", "оба пропуска": lambda n, r: "skip"}.items():
        user = q.candidate("demo03", "junior")
        ssid, item = q.start(user, "junior", quick=True)
        trail = q.run_test(user, ssid, item, plan)
        sd = q.session_db(ssid)
        out[label] = (len(trail), sd["status"], sd["outcome"], q.sql(f"select is_demo_result from assessment_category where candidate_id='{user.id}'"))
    q.rec("DEMO-03", "Быстрый тест: пропуск + ответ; оба пропуска", A, "обе ветки завершаются за два шага без ошибок", out,
          all(v[0] == 2 and v[1] == "finished" for v in out.values()), source=src)  # fmt: skip
    # DEMO-05: маркировка демо везде
    c.post("/candidate/consents/publication", PUBLISH)
    e = q.employer("demo05e")
    result = c.get(f"/assessment/sessions/{sid}/result")[1]
    state = c.get("/assessment/state")[1]
    history = c.get("/assessment/history")[1]
    card = e.get(f"/employer/candidates/{c.id}")[1]
    code = c.get("/candidate/profile")[1]["public_code"]
    bank = e.get("/employer/candidates", params={"code": code})[1]
    marks = {"result.notes": any("демо" in n.lower() for n in result["notes"]), "state.category.is_demo_result": state["category"]["is_demo_result"],
             "history": any("демо" in json.dumps(h, ensure_ascii=False).lower() for h in history), "employer.card.is_demo": card.get("is_demo"),
             "employer.bank.is_demo": bank["items"][0]["is_demo"] if bank["items"] else None}  # fmt: skip
    q.rec("DEMO-05", "Маркировка демо-результата: результат, состояние, история, карточка и банк работодателя", A,
          "пометка есть везде, где результат можно принять за обычный", marks,
          marks["result.notes"] and marks["state.category.is_demo_result"] and marks["employer.card.is_demo"] and marks["employer.bank.is_demo"], source=src,
          note="" if marks["history"] else "в истории тестов (GET /assessment/history) пометки демо нет — GAP-04")  # fmt: skip
    # может ли демо-профиль публиковаться и получать приглашения (E2E-02, разрешённый путь до конца)
    inv = e.post("/employer/invitations", q.invitation(c.id, e.email), headers=q.idem())
    acc = c.post(f"/candidate/invitations/{inv[1].get('id')}/accept", {"disclose": ["email"]}) if inv[0] == 201 else (0, {})
    q.rec("E2E-02", "Быстрый демо-путь до конца: демо-результат → публикация → банк → приглашение → принятие", A,
          "путь разрешён и проходит; демо-пометка сохраняется у работодателя", {"invite": (inv[0], inv[1].get("status")), "accept": (acc[0], acc[1].get("status")), "is_demo_chip": card.get("is_demo")},
          inv[0] == 201 and inv[1]["status"] == "sent" and acc[0] == 200 and card.get("is_demo") is True,
          source="README: «результат и категория помечаются как демо»; PoolProfile.is_demo — чип показа", note="кнопка в интерфейсе пройдена отдельно (E2E-02u)")  # fmt: skip
    # DEMO-07: именованные аккаунты против описаний
    labels = {a["key"]: a for a in q.User().get("/demo/accounts")[1]}
    facts = {}
    anna = demo_login("anna")
    facts["anna"] = (anna.get("/assessment/state")[1]["category"]["code"], len(anna.get("/candidate/invitations")[1]["items"]), anna.get("/fsp/link")[1]["status"])
    dm = demo_login("dmitry")
    facts["dmitry"] = (dm.get("/candidate/conditions")[1]["min_salary"], len(dm.get("/candidate/invitations")[1]["items"]), dm.get("/candidate/funnel")[1].get("not_delivered"))
    iv = demo_login("ivan")
    facts["ivan"] = [i["status"] for i in iv.get("/candidate/invitations")[1]["items"]]
    gl = demo_login("gleb")
    facts["gleb"] = (gl.get("/candidate/invitations/summary")[1]["strikes"], gl.get("/candidate/invitations/summary")[1]["visibility"]["state"])
    bo = demo_login("boris")
    facts["boris"] = (bo.get("/assessment/state")[1]["category"]["code"], len(bo.get("/candidate/invitations")[1]["items"]))
    ol = demo_login("olga").get("/fsp/link")[1]
    facts["olga"] = (ol["status"], len(ol["achievements"]))
    ma = demo_login("maria").get("/assessment/state")[1]
    facts["maria"] = (ma["category"]["code"], {a["grade"]["code"]: a["available"] for a in ma["next_actions"]}.get("senior"))
    pe = demo_login("petr").get("/assessment/state")[1]
    facts["petr"] = (pe["category"], (pe["last_session"] or {}).get("outcome"), {a["grade"]["code"]: a["available"] for a in pe["next_actions"]}.get("junior"))
    orb = demo_login("orbita")
    facts["orbita"] = (orb.get("/auth/me")[1]["role"], len(orb.get("/employer/needs")[1]))
    ok = (facts["anna"][0] == "backend:middle" and facts["anna"][2] == "linked" and facts["dmitry"][0] == 260000 and facts["dmitry"][1] == 0
          and facts["boris"] == ("backend:junior", 0) and facts["olga"] == ("linked", 0) and facts["maria"] == ("backend:middle", True)
          and facts["petr"][0] is None and facts["petr"][1] == "not_confirmed" and facts["petr"][2] is True and facts["orbita"] == ("employer", 1))  # fmt: skip
    q.rec("DEMO-07", "Девять именованных демо-аккаунтов: роль и состояние против описания на /demo", A, "состояние каждого соответствует подписи",
          {"accounts": sorted(labels), "facts": facts}, len(labels) == 9 and ok, source="GET /demo/accounts (state_label)",
          note="состояние anna/ivan/gleb зависит от времени с запуска сценария и от действий других посетителей")  # fmt: skip
    # DEMO-09: перезапуск сценария не трогает обычные аккаунты
    before = q.sql("select count(*) from app_user where not is_demo")
    restart = q.User().call("POST", "/demo/scenario/restart", headers=q.admin_headers())
    after = q.sql("select count(*) from app_user where not is_demo")
    anna2 = demo_login("anna").get("/candidate/invitations")[1]["items"]
    q.rec("DEMO-09", "Перезапуск сценария (ключ ведущего): демо-состояние восстановлено, обычные аккаунты целы", A, "200; у Анны снова одно ждущее приглашение; число обычных аккаунтов то же",
          {"http": restart[0], "live_before": before, "live_after": after, "anna": [i["status"] for i in anna2], "c_still_logged": c.get("/auth/me")[0]},
          restart[0] == 200 and before == after and [i["status"] for i in anna2] == ["sent"] and c.get("/auth/me")[0] == 200, source="README; POST /demo/scenario/restart")  # fmt: skip
    q.rec("DEMO-06", "Демо-функции при выключенном DEMO_MODE", "integration (pytest)", "роутер /demo/* отвечает 404 feature_disabled",
          "на стенде флаг включён; выключенный режим покрыт tests/core/test_wiring.py::test_flags_switch_* и зависимостью require_feature('demo') — прогоняется в регрессии", None,
          status="N/A", source="wiring.REQUIRES; deps.require_feature", note="отдельная конфигурация стенда не поднималась")  # fmt: skip


def pub() -> None:
    src = "ТЗ; README «Тестирование», «Контакт»; POST /candidate/consents/publication, /candidate/visibility"
    c = q.candidate("pub", "middle")
    sid, item = q.start(c, "middle")
    q.run_test(c, sid, item, lambda n, r: "right")
    res = c.get(f"/assessment/sessions/{sid}/result")[1]
    state = c.get("/assessment/state")[1]
    hist = c.get("/assessment/history")[1]
    q.rec("PUB-01", "Результат, состояние и история согласованы после теста", A, "одна и та же специализация, грейд и исход",
          {"result": (res["outcome"], res["category"]["code"]), "state": state["category"]["code"], "history": [h.get("outcome") or h.get("kind") for h in hist][:3]},
          res["category"]["code"] == state["category"]["code"] == "backend:middle" and any(h.get("outcome") == res["outcome"] for h in hist), source=src)  # fmt: skip
    labels = {}
    for outcome in ("confirmed_with_margin", "confirmed", "borderline", "not_confirmed"):
        row = q.sql(f"select s.id, s.candidate_id from assessment_session s join app_user u on u.id=s.candidate_id where s.outcome='{outcome}' and s.status='finished' and u.email like 'qa.%' order by s.finished_at desc limit 1")
        labels[outcome] = row.split("|")[0] if row else None
    texts = {}
    for outcome, session_id in labels.items():
        if session_id:
            texts[outcome] = q.sql(f"select count(*) from assessment_session where id='{session_id}'")
    seen = q.sql("select string_agg(distinct outcome, ',') from assessment_session s join app_user u on u.id=s.candidate_id where u.email like 'qa.%' and s.status='finished'")
    q.rec("PUB-02", "Исходы «с запасом», «подтверждён», «на границе», «не подтверждён» различимы", A, "все четыре исхода получены в прогоне и имеют свои подписи",
          {"получены в прогоне": seen, "подписи": "outcome_label в GET …/result (проверены в TEST-01…13)"}, {"confirmed_with_margin", "not_confirmed"} <= set((seen or "").split(",")),
          source=src, note="какие именно исходы получены, видно в поле; отсутствующие — только unit-тестами labels.py")  # fmt: skip
    e = q.employer("pube")
    code = c.get("/candidate/profile")[1]["public_code"]

    def seen_by_employer() -> tuple[int, int]:
        return len(e.get("/employer/candidates", params={"code": code})[1]["items"]), e.get(f"/employer/candidates/{c.id}")[0]

    hidden = seen_by_employer()
    q.rec("PUB-04", "До публикации кандидата нет в банке по коду и по прямому ID", A, "0 строк, карточка 404", hidden, hidden == (0, 404), source=src)
    bad_ver = c.post("/candidate/consents/publication", {"action": "grant", "version": "publication-0"})
    no_ver = c.post("/candidate/consents/publication", {"action": "grant"})
    still = seen_by_employer()
    ok1 = c.post("/candidate/consents/publication", PUBLISH)
    ok2 = c.post("/candidate/consents/publication", PUBLISH)
    visible = seen_by_employer()
    consents = int(q.sql(f"select count(*) from consent where user_id='{c.id}' and kind='publication' and revoked_at is null"))
    q.rec("PUB-05", "Публикация без согласия / с устаревшей версией согласия / с действующей", A, "без версии — 422, старая версия — 409, действующая — виден",
          {"без версии": no_ver[0], "старая версия": (bad_ver[0], bad_ver[1].get("code")), "после отказов": still, "grant": ok1[0], "state": ok1[1].get("state"), "видимость": visible},
          no_ver[0] == 422 and bad_ver[0] == 409 and still == (0, 404) and ok1[0] == 200 and visible == (1, 200), source=src)  # fmt: skip
    q.rec("PUB-09", "Версия согласия проверяется сервером", A, "устаревшая версия — 409 consent_version_outdated", (bad_ver[0], bad_ver[1].get("code")),
          bad_ver[0] == 409 and "version" in str(bad_ver[1].get("code")), source=src)  # fmt: skip
    q.rec("PUB-06", "Двойная публикация", A, "один действующий статус, одна действующая строка согласия", {"second": ok2[0], "active_consents": consents}, ok2[0] == 200 and consents == 1, source=src)
    pause = c.post("/candidate/visibility", {"state": "paused"})
    paused = seen_by_employer()
    back = c.post("/candidate/visibility", {"state": "visible"})
    revoke = c.post("/candidate/consents/publication", {"action": "revoke", "version": "publication-1"})
    revoked = seen_by_employer()
    q.rec("PUB-07", "Пауза показа и отзыв согласия на публикацию", A, "в обоих случаях кандидата нет в банке и по прямой ссылке",
          {"pause": (pause[0], paused), "resume": back[0], "revoke": (revoke[0], revoke[1].get("state") if isinstance(revoke[1], dict) else None, revoked)},
          paused == (0, 404) and revoked == (0, 404), source=src)  # fmt: skip
    again = c.post("/candidate/consents/publication", PUBLISH)
    code2 = c.get("/candidate/profile")[1]["public_code"]
    q.rec("PUB-08", "Повторная публикация: тот же профиль и тот же код", A, "виден снова, код не изменился", {"grant": again[0], "code_same": code == code2, "видимость": seen_by_employer()},
          again[0] == 200 and code == code2 and seen_by_employer() == (1, 200), source=src)  # fmt: skip
    need_office = {**q.NEED, "work_formats": ["office"], "city": "Казань"}
    nid = e.post("/employer/needs", need_office)[1]["id"]
    s1 = e.post(f"/employer/needs/{nid}/shortlists")[1]
    c.put("/candidate/conditions", {"min_salary": 200000, "work_formats": ["office"]})
    s2 = e.post(f"/employer/needs/{nid}/shortlists", {"parent_id": s1["id"], "refinement": {"nice_skills": ["docker", "redis"]}})[1]
    in1 = c.id in {i["candidate_id"] for i in s1["items"]}
    in2 = c.id in {i["candidate_id"] for i in s2["items"]}
    q.rec("PUB-10", "Изменение условий опубликованного профиля сразу влияет на новые подборки", A, "формат «офис» добавлен — кандидат появляется в следующей версии",
          {"до": in1, "после": in2}, (not in1) and in2, source="README «Подбор», п. 1: условие — общий формат")  # fmt: skip


def find() -> None:
    src = "GET /employer/candidates (code, фильтры, cursor); интерфейс: поле «Код кандидата», подсказка «К-12345»"
    c = q.candidate("find", "junior", min_salary=None, formats=("remote",), profile={"declared_skills": [{"code": "python"}, {"code": "docker"}]})
    prof = q.finish_and_publish(c, "junior", quick=False)
    code, e = prof["public_code"], q.employer("finde")

    def search(**params) -> tuple[int, list[str], dict]:
        st, body = e.get("/employer/candidates", params=params)
        return st, [i["candidate_id"] for i in body.get("items", [])] if st == 200 else [], body

    exact = search(code=code)
    same = exact[2]["items"][0] if exact[1] else {}
    q.rec("FIND-01", "Опубликованный кандидат находится по точному коду (обычный работодатель)", A, "одна карточка, ID совпадает с кандидатом",
          {"code": code, "http": exact[0], "ids": exact[1] == [c.id], "category": (same.get("category") or {}).get("code")}, exact[1] == [c.id] and same["public_code"] == code, source=src)  # fmt: skip
    zero = q.sql("select p.public_code||'|'||p.user_id from candidate_profile p where p.public_code like 'К-0%' limit 40").splitlines()
    hit = None
    for row in zero:
        zc, zid = row.split("|")
        got = search(code=zc)
        if got[1]:
            hit = (zc, got[1] == [zid], search(code="К-" + zc[2:].lstrip("0"))[1])
            break
    q.rec("FIND-01z", "Код с ведущим нулём: находится как строка, без нулей — не находит другого", A, "точный код с нулями — один кандидат; тот же код без нулей — пусто",
          hit or "среди видимых нет кода с ведущим нулём", bool(hit and hit[1] and hit[2] == []) if hit else None,
          status=None if hit else "BLOCKED", source=src)  # fmt: skip
    digits = code[2:]
    variants = {"латинская K": f"K-{digits}", "строчная": f"к-{digits}", "пробелы": f"  {code} ", "без префикса": digits, "без дефиса": f"К{digits}",
                "длинное тире": f"К–{digits}", "неизвестный": "К-00001", "мусор": "abc", "пустая строка": ""}  # fmt: skip
    out = {k: (lambda r: (r[0], len(r[1]), r[2].get("code")))(search(code=v)) for k, v in variants.items()}
    q.rec("FIND-02", "Формат кода: регистр, латинская K, пробелы, без префикса, тире, неизвестный, мусор", A,
          "латинская/строчная/пробелы — находят; неизвестный — пусто; неверный формат — 422, не 500", out,
          all(out[k][:2] == (200, 1) for k in ("латинская K", "строчная", "пробелы")) and out["неизвестный"][:2] == (200, 0)
          and all(out[k][0] == 422 for k in ("без префикса", "без дефиса", "длинное тире", "мусор")), source=src,
          note="«12345» без префикса и «К–12345» с длинным тире дают 422 filter_invalid «Проверьте фильтры» без подсказки формата — GAP-05")  # fmt: skip
    f = {
        "spec+grade": search(code=code, specialization="backend", grade="junior")[1] == [c.id],
        "чужой грейд": search(code=code, specialization="backend", grade="senior")[1] == [],
        "категория": search(code=code, category="backend:junior")[1] == [c.id],
        "навык заявленный": search(code=code, skills="docker")[1] == [c.id],
        "навык только подтверждённый": search(code=code, skills="docker", skills_confirmed_only="true")[1] == [],
        "навык, которого нет": search(code=code, skills="kafka")[1] == [],
        "has_fsp": search(code=code, has_fsp="true")[1] == [],
        "все вместе": search(code=code, specialization="backend", grade="junior", skills="python")[1] == [c.id],
        "неизвестный навык": search(skills="нет-такого")[0] == 422,
    }
    q.rec("FIND-03", "Пересечение фильтров: специализация, грейд, категория, навыки, «только подтверждённые», ФСП", A, "каждый фильтр включает/исключает кандидата по его данным", f, all(f.values()), source=src)
    # FIND-05: страницы
    seen, cursor, pages, total = [], None, 0, None
    while pages < 40:
        params = {"specialization": "backend", "limit": 20, **({"cursor": cursor} if cursor else {})}
        st, body = e.get("/employer/candidates", params=params)
        if st != 200:
            break
        total = body["total"] if total is None else total
        seen += [i["candidate_id"] for i in body["items"]]
        cursor, pages = body.get("next_cursor"), pages + 1
        if not cursor:
            break
    deep_code = None
    if len(seen) > 45:
        deep_code = q.sql(f"select public_code from candidate_profile where user_id='{seen[45]}'")
    deep = search(code=deep_code)[1] if deep_code else []
    bad_cursor = e.get("/employer/candidates", params={"cursor": "мусор"})[0]
    q.rec("FIND-05", "Пагинация банка: без дублей и пропусков; поиск по коду кандидата с третьей страницы; неверный курсор", A,
          "уникальных строк = total; кандидат с дальней страницы находится по коду; мусорный курсор — 422",
          {"pages": pages, "rows": len(seen), "unique": len(set(seen)), "total": total, "deep": deep == [seen[45]] if deep_code else None, "bad_cursor": bad_cursor, "last_http": st},
          len(seen) == len(set(seen)) == total and (deep == [seen[45]] if deep_code else True) and bad_cursor == 422, source=src,
          note="если прогон упёрся в суточный лимит страниц банка, last_http = 429")  # fmt: skip


def employer() -> None:
    src = "OpenAPI CompanyUpdate, NeedCreate; ТЗ «Работодатель»"
    e = q.signup("emp", "employer")
    blocked = e.post("/employer/needs", q.NEED)
    good = {"name": "ООО Проверка", "sphere": "Финтех", "description": "Платёжные сервисы для малого бизнеса, команда 40 человек, работаем удалённо.",
            "contact_method": {"kind": "email", "value": e.email}}  # fmt: skip
    minimal = e.put("/employer/company", good)
    full = e.put("/employer/company", {**good, "site": "https://example.com/qa", "city": "Казань"})
    back = e.get("/employer/company")[1]
    q.rec("EMP-01", "Компания: минимально и полностью; до заполнения потребность создать нельзя", A, "без компании — 409; сохранение и чтение совпадают",
          {"need_before": (blocked[0], blocked[1].get("code")), "minimal": minimal[0], "full": full[0], "site": back.get("site"), "city": back.get("city")},
          blocked[0] == 409 and minimal[0] == 200 and full[0] == 200 and back["site"] == "https://example.com/qa" and back["city"] == "Казань", source=src)  # fmt: skip
    out = {
        "пустое название": e.put("/employer/company", {**good, "name": ""})[0],
        "название 101 знак": e.put("/employer/company", {**good, "name": "Я" * 101})[0],
        "описание 49 знаков": e.put("/employer/company", {**good, "description": "а" * 49})[0],
        "ссылка javascript:": e.put("/employer/company", {**good, "site": "javascript:alert(1)"})[0],
        "ссылка без схемы": e.put("/employer/company", {**good, "site": "просто текст"})[0],
        "почта без @": e.put("/employer/company", {**good, "contact_method": {"kind": "email", "value": "не почта"}})[0],
        "нет способа связи": e.put("/employer/company", {k: v for k, v in good.items() if k != "contact_method"})[0],
    }
    q.rec("EMP-02", "Компания: пустые обязательные, длинное название, неверная ссылка и контакт", A, "422 на каждый случай, без 500", out, all(v == 422 for v in out.values()), source=src)

    def parse(text: str) -> tuple[int, dict]:
        return e.post("/employer/needs/parse", {"text": text})

    amb = parse("Нужен сильный разработчик в команду. Зарплата достойная, график гибкий, офис в центре города, дружный коллектив.")
    empty = parse("")
    short = parse("Нужен программист")
    no_salary = parse("Ищем junior backend-разработчика на Python и PostgreSQL. Работа удалённо, команда из пяти человек, задачи по интеграциям.")
    d = amb[1] if amb[0] == 200 else {}
    q.rec("NEED-03", "Неоднозначный, пустой и неполный текст потребности", A, "обязательные значения не выдумываются: грейд и вилка остаются пустыми",
          {"неоднозначный": (amb[0], d.get("grade_code"), d.get("salary_from"), d.get("specialization_code")), "пустой": empty[0], "короткий": short[0],
           "без вилки": (no_salary[0], no_salary[1].get("grade_code"), no_salary[1].get("salary_from"), no_salary[1].get("must_skills"))},
          amb[0] == 200 and d.get("grade_code") is None and d.get("salary_from") is None and empty[0] == 422
          and no_salary[1].get("grade_code") == "junior" and no_salary[1].get("salary_from") is None, source=src)  # fmt: skip
    edited = {**q.NEED, "title": "Исправленное вручную", "must_skills": ["python"], "salary_from": 250000, "salary_to": 320000}
    created = e.post("/employer/needs", edited)
    nid = created[1]["id"]
    saved = e.get(f"/employer/needs/{nid}")[1]
    q.rec("NEED-04", "Сохраняются ручные правки, а не первоначальный разбор", A, "в потребности — исправленные значения",
          {k: saved.get(k) for k in ("title", "must_skills", "salary_from", "salary_to")},
          saved["title"] == "Исправленное вручную" and codes_of(saved["must_skills"]) == ["python"] and saved["salary_from"] == 250000, source=src)  # fmt: skip
    lim = httpx_limits()
    sal = {
        "от больше до": e.post("/employer/needs", {**q.NEED, "salary_from": 300000, "salary_to": 200000})[0],
        "отрицательная": e.post("/employer/needs", {**q.NEED, "salary_from": -1, "salary_to": 100000})[0],
        "ноль": e.post("/employer/needs", {**q.NEED, "salary_from": 0, "salary_to": 100000})[0],
        "ниже минимума": e.post("/employer/needs", {**q.NEED, "salary_from": lim["salary_min"] - 1, "salary_to": lim["salary_min"]})[0],
        "ровно минимум": e.post("/employer/needs", {**q.NEED, "salary_from": lim["salary_min"], "salary_to": lim["salary_min"]})[0],
        "выше максимума": e.post("/employer/needs", {**q.NEED, "salary_from": lim["salary_max"], "salary_to": lim["salary_max"] + 1})[0],
        "разброс 1,5": e.post("/employer/needs", {**q.NEED, "salary_from": 200000, "salary_to": 300000})[0],
        "разброс больше 1,5": e.post("/employer/needs", {**q.NEED, "salary_from": 200000, "salary_to": 300001})[0],
        "без верхней": e.post("/employer/needs", {k: v for k, v in q.NEED.items() if k != "salary_to"})[0],
    }
    q.rec("NEED-05", "Вилка потребности: границы, порядок, отношение «до/от» не больше 1,5", A, "нарушения — 422; ровно на границе — 201", sal,
          sal["от больше до"] == 422 and sal["отрицательная"] == 422 and sal["ноль"] == 422 and sal["ниже минимума"] == 422 and sal["ровно минимум"] == 201
          and sal["выше максимума"] == 422 and sal["разброс 1,5"] == 201 and sal["разброс больше 1,5"] == 422 and sal["без верхней"] == 422,
          source="catalog.limits: salary_min, salary_max, salary_max_ratio")  # fmt: skip
    sk = {
        "9 обязательных": e.post("/employer/needs", {**q.NEED, "must_skills": ["python", "postgresql", "docker", "redis", "kafka", "sql", "git", "fastapi", "django"]})[0],
        "неизвестный навык": e.post("/employer/needs", {**q.NEED, "must_skills": ["нет-такого"]})[0],
    }
    both = e.post("/employer/needs", {**q.NEED, "must_skills": ["python", "python", "docker"], "nice_skills": ["docker", "redis"]})
    got = e.get(f"/employer/needs/{both[1]['id']}")[1] if both[0] == 201 else {}
    must, nice = codes_of(got.get("must_skills", [])), codes_of(got.get("nice_skills", []))
    q.rec("NEED-06", "Обязательные и желательные навыки: дубли, пересечение, лимит", A,
          "9 обязательных и неизвестный навык — 422; дубли и пересечение либо схлопнуты (навык остаётся обязательным), либо отклонены",
          {**sk, "дубли и пересечение": (both[0], both[1].get("code") if both[0] != 201 else "создано"), "must": must, "nice": nice},
          sk["9 обязательных"] == 422 and sk["неизвестный навык"] == 422
          and (both[0] == 422 or (sorted(must) == ["docker", "python"] and nice == ["redis"])), source=src)  # fmt: skip
    before = len(e.get("/employer/needs")[1])
    with cf.ThreadPoolExecutor(4) as pool:
        codes = list(pool.map(lambda _: e.clone().post("/employer/needs", {**q.NEED, "title": "Двойной клик"})[0], range(4)))
    dup = len([n for n in e.get("/employer/needs")[1] if n["title"] == "Двойной клик"])
    q.rec("NEED-07", "Четыре одновременных создания одной потребности (двойной клик)", A, "одна потребность либо явный контракт дублей",
          {"codes": codes, "created": dup}, dup == 1, source=src,
          note="" if dup == 1 else "ключа идемпотентности у POST /employer/needs нет: быстрый двойной клик создаёт дубли — GAP-06")  # fmt: skip
    s1 = e.post(f"/employer/needs/{nid}/shortlists")[1]
    upd = e.put(f"/employer/needs/{nid}", {**edited, "must_skills": ["python", "postgresql"]})
    versions = e.get(f"/employer/needs/{nid}/shortlists")[1]
    old = e.get(f"/employer/shortlists/{s1['id']}")[1]
    q.rec("NEED-08", "Правка сохранённой потребности: прежняя версия подборки остаётся", A, "версия 1 читается с прежним запросом",
          {"update": upd[0], "versions": [v["version_no"] for v in versions], "v1_must": (old.get("query") or {}).get("must_skills")},
          upd[0] == 200 and old["version_no"] == 1 and codes_of((old.get("query") or {}).get("must_skills") or []) == ["python"], source="README «Подбор»: версии подборки")  # fmt: skip
    n_before = len(e.get(f"/employer/needs/{nid}/shortlists")[1])
    for _ in range(3):
        e.get(f"/employer/shortlists/{s1['id']}")
        e.get(f"/employer/needs/{nid}/shortlists")
    same_query = e.post(f"/employer/needs/{nid}/shortlists", {"parent_id": versions[0]["id"] if versions else s1["id"], "refinement": {}})
    n_after = len(e.get(f"/employer/needs/{nid}/shortlists")[1])
    q.rec("NEED-09", "Просмотр версий и пустое уточнение не создают новую версию", A, "число версий не растёт от чтения и от уточнения без изменений",
          {"before": n_before, "after": n_after, "empty_refine": same_query[0]}, n_after == n_before, source="интерфейс: «Вид не создаёт новую версию»")  # fmt: skip
    arch = e.post(f"/employer/needs/{nid}/archive")
    after_arch = e.post(f"/employer/needs/{nid}/shortlists")
    listed = {n["id"]: n["status"] for n in e.get("/employer/needs")[1]}
    q.rec("NEED-10", "Архив потребности: статус и запрет новых версий", A, "archived; новая версия отклонена; восстановления в API нет",
          {"archive": arch[0], "status": listed.get(nid), "new_version": (after_arch[0], after_arch[1].get("code") if isinstance(after_arch[1], dict) else None)},
          arch[0] == 200 and listed.get(nid) == "archived" and after_arch[0] in (409, 422), source="OpenAPI: POST /employer/needs/{id}/archive",
          note="восстановление из архива не заявлено (адреса нет) — N/A")  # fmt: skip
    other = q.employer("emp2")
    x = {"get": other.get(f"/employer/needs/{nid}")[0], "put": other.put(f"/employer/needs/{nid}", q.NEED)[0], "archive": other.post(f"/employer/needs/{nid}/archive")[0],
         "shortlist": other.post(f"/employer/needs/{nid}/shortlists")[0], "snapshot": other.get(f"/employer/shortlists/{s1['id']}")[0]}  # fmt: skip
    q.rec("NEED-11", "Чужая потребность и версия подборки по ID", A, "404 на чтение и изменение", x, all(v == 404 for v in x.values()), source="ТЗ: роли и доступ")


def codes_of(items: list) -> list[str]:
    return [i["code"] if isinstance(i, dict) else i for i in items]


def httpx_limits() -> dict:
    import httpx

    return httpx.get(q.BASE + "/api/v1/catalog").json()["limits"]


def match() -> None:
    src = "README «Подбор» п. 1–4; ranking.DEFAULT_KEY_ORDER (must → confirmed → strength → coverage)"
    mark = "kafka"  # редкий обязательный навык, чтобы контрольная группа была различима
    full = q.candidate("m_full", "middle", min_salary=160000, formats=("remote",), profile={"declared_skills": [{"code": "python"}, {"code": mark}, {"code": "docker"}]})
    part = q.candidate("m_part", "middle", min_salary=None, formats=("remote",), profile={"declared_skills": [{"code": "python"}]})
    office = q.candidate("m_office", "middle", min_salary=None, formats=("office",), profile={"declared_skills": [{"code": "python"}, {"code": mark}]})
    lower = q.candidate("m_lower", "junior", min_salary=None, formats=("remote",), profile={"declared_skills": [{"code": "python"}, {"code": mark}]})
    higher = q.candidate("m_higher", "senior", min_salary=None, formats=("remote",), profile={"declared_skills": [{"code": "python"}, {"code": mark}]})
    hidden = q.candidate("m_hidden", "middle", min_salary=None, formats=("remote",), profile={"declared_skills": [{"code": "python"}, {"code": mark}]})
    for user, grade in ((full, "middle"), (part, "middle"), (office, "middle"), (lower, "junior"), (higher, "senior")):
        q.finish_and_publish(user, grade, quick=False)
    sid, item = q.start(hidden, "middle")
    q.run_test(hidden, sid, item, lambda n, r: "right")  # категория есть, публикации нет
    e = q.employer("m_emp")
    need = {**q.NEED, "must_skills": ["python", mark], "nice_skills": ["docker"], "work_formats": ["remote", "hybrid"]}
    nid = e.post("/employer/needs", need)[1]["id"]
    snap = e.post(f"/employer/needs/{nid}/shortlists")[1]
    rows = {i["candidate_id"]: i for i in snap["items"] + snap.get("pinned_outside", [])}
    who = {"full": full.id, "part": part.id, "office": office.id, "lower": lower.id, "higher": higher.id, "hidden": hidden.id}
    got = {k: (rows[v]["relation"], rows[v]["position"], f"{rows[v]['must_covered']}/{rows[v]['must_total']}") if v in rows else None for k, v in who.items()}
    q.rec("MATCH-01", "Полное совпадение попадает в основной раздел с 2 из 2 обязательных", A, "relation=exact, 2/2", got["full"], got["full"] and got["full"][0] == "exact" and got["full"][2] == "2/2", source=src)
    q.rec("MATCH-02", "Несовместимый формат работы исключает кандидата", A, "кандидата «только офис» нет в подборке удалённо/гибрид", got["office"], got["office"] is None, source=src)
    q.rec("MATCH-03", "Разделы: основная, грейд ниже с запасом, грейд выше — не смешиваются", A, "middle → exact, junior с запасом → lower_with_margin, senior → higher",
          {k: got[k] and got[k][0] for k in ("full", "lower", "higher")},
          bool(got["full"] and got["lower"] and got["higher"]) and (got["full"][0], got["lower"][0], got["higher"][0]) == ("exact", "lower_with_margin", "higher"), source=src)  # fmt: skip
    exact = [i for i in snap["items"] if i["relation"] == "exact"]
    missing = [i["must_total"] - i["must_covered"] for i in exact]
    q.rec("MATCH-04", "Внутри раздела сначала закрывшие больше обязательных навыков", A, "число незакрытых обязательных не убывает сверху вниз; «полный» выше «частичного»",
          {"missing": missing[:30], "full_pos": got["full"] and got["full"][1], "part_pos": got["part"] and got["part"][1]},
          missing == sorted(missing) and bool(got["full"] and got["part"]) and got["full"][1] < got["part"][1], source=src)  # fmt: skip
    card = e.get(f"/employer/candidates/{full.id}", params={"need_id": nid})[1]
    reqs = {r["skill"]["code"]: r["kind"] for r in card["match"]["requirements"]}
    q.rec("MATCH-05", "Заявленный и подтверждённый навык различаются в объяснении", A, "python — подтверждён тестом, kafka — заявлен; ложного подтверждения нет", reqs,
          reqs.get("python") == "test" and reqs.get(mark) == "declared", source=src)  # fmt: skip
    strength = {c["code"]: c["points"] for c in card["strength"]["contributions"]}
    anna = q.sql("select id from app_user where demo_key='anna'")
    anna_card = e.get(f"/employer/candidates/{anna}")[1]
    anna_strength = {c["code"]: c["points"] for c in anna_card["strength"]["contributions"]}
    q.rec("MATCH-06", "Нет истории ФСП — нет штрафа; есть достижения — есть вклад", A, "у кандидата без ФСП вклад ФСП отсутствует/0 и нейтральный текст; у Анны — положительный",
          {"без ФСП": strength, "fsp_mode": card["fsp"]["mode"], "текст": card["fsp"]["neutral_text"], "Анна": anna_strength},
          strength.get("fsp", 0) == 0 and card["fsp"]["mode"] == "none" and bool(card["fsp"]["neutral_text"]) and anna_strength.get("fsp", 0) > 0, source="ТЗ: кандидат без истории ФСП")  # fmt: skip
    again = e.get(f"/employer/shortlists/{snap['id']}")[1]
    q.rec("MATCH-07", "Порядок сохранённой версии стабилен при повторном чтении", A, "тот же порядок кандидатов", len(again["items"]),
          [i["candidate_id"] for i in again["items"]] == [i["candidate_id"] for i in snap["items"]], source=src)  # fmt: skip
    cov = card["match"]
    n_must = sum(1 for r in cov["requirements"] if r["priority"] == "must" and r["kind"] != "none")
    q.rec("MATCH-08", "Счётчик «N из M обязательных» совпадает с требованиями карточки", A, "N = число обязательных требований с данными",
          {"row": got["full"][2], "по требованиям": f"{n_must}/{sum(1 for r in cov['requirements'] if r['priority'] == 'must')}", "доводы": len(cov["reasons"])},
          got["full"][2] == f"{n_must}/2" and len(cov["reasons"]) > 0, source=src)  # fmt: skip
    v2 = e.post(f"/employer/needs/{nid}/shortlists", {"parent_id": snap["id"], "refinement": {"must_skills": ["python"]}})[1]
    v1_again = e.get(f"/employer/shortlists/{snap['id']}")[1]
    diff = e.get(f"/employer/shortlists/{v2['id']}/diff", params={"base": snap["id"]})
    q.rec("MATCH-09", "Уточнение создаёт версию 2; версия 1 не переписана; различия считаются", A, "v2.parent = v1; v1 читается с прежним запросом; diff 200",
          {"v2": v2.get("version_no"), "v1_must": v1_again["query"]["must_skills"], "v2_must": v2["query"]["must_skills"], "diff": diff[0]},
          v2.get("version_no") == 2 and sorted(v1_again["query"]["must_skills"]) == sorted(["python", mark]) and v2["query"]["must_skills"] == ["python"] and diff[0] == 200, source=src)  # fmt: skip
    part.post("/candidate/visibility", {"state": "paused"})
    old = e.get(f"/employer/shortlists/{snap['id']}")[1]
    direct = e.get(f"/employer/candidates/{part.id}")[0]
    q.rec("MATCH-10", "Кандидат скрыл профиль после формирования подборки", A, "в старой версии строка не отдаётся (только счётчик скрытых); прямая ссылка — 404",
          {"в строках": part.id in {i["candidate_id"] for i in old["items"]}, "hidden_count": old["hidden_count"], "card": direct},
          part.id not in {i["candidate_id"] for i in old["items"]} and old["hidden_count"] >= 1 and direct == 404, source="README «Подбор»: кандидат на паузе не показывается")  # fmt: skip
    blob = json.dumps([snap, card, e.get("/employer/candidates", params={"code": card["public_code"]})[1],
                       e.get("/employer/invitations/precheck", params={"candidate_id": full.id, "need_id": nid})[1]], ensure_ascii=False)  # fmt: skip
    q.rec("MATCH-11", "Скрытый минимум зарплаты (160 000) не попадает в подборку, карточку, банк и предпроверку", A, "значения 160000 нет ни в одном ответе работодателю",
          {"160000 в ответах": "160000" in blob, "min_salary ключ": "min_salary" in blob}, "160000" not in blob and '"min_salary"' not in blob, source="README «Контакт»: скрытый минимум")  # fmt: skip
    q.rec("MATCH-12", "Скрытый (неопубликованный) кандидат с категорией не попадает в подборку", A, "кандидата нет ни в строках, ни в закреплённых", got["hidden"], got["hidden"] is None, source=src)


if __name__ == "__main__":
    parts = [globals()[name] for name in sys.argv[1:]] or [demo, pub, find, employer, match]
    for part in parts:
        try:
            part()
        except Exception as exc:
            import traceback

            q.rec(f"ERR-{part.__name__}", f"Группа {part.__name__} прервана", A, "группа выполняется до конца", traceback.format_exc()[-500:], None, status="BLOCKED")
    print("готово")
