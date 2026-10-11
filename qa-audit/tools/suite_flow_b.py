"""INV, RESP, COUNT, PRIV, FSP — проверки уровня API/DB на живом стенде (без сдвига часов)."""

from __future__ import annotations

import concurrent.futures as cf
import io
import json
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import httpx  # noqa: E402
import qalib as q  # noqa: E402

A = "API+DB"
SRC_INV = "README «Контакт»; catalog.limits (слоты, сроки); OpenAPI POST /employer/invitations"
SRC_PRIV = "ТЗ: контакты только после принятия; README «Контакт»"
MARK = {"phone": "+79995550101", "telegram": "@qa_priv_marker", "link": "https://example.com/qa-priv-marker", "about": "МАРКЕР-О-СЕБЕ-777"}


def ready(tag: str, grade: str = "middle", **kw) -> q.User:
    user = q.candidate(tag, grade, **kw)
    q.finish_and_publish(user, grade, quick=True)
    return user


def send(e: q.User, cid: str, **kw) -> tuple[int, dict]:
    headers = {"Idempotency-Key": kw.pop("key", None) or str(uuid.uuid4())}
    return e.post("/employer/invitations", q.invitation(cid, e.email, **kw), headers=headers)


def inv_status(inv_id: str) -> str:
    return q.sql(f"select status from invitation where id='{inv_id}'")


def inv() -> None:
    e = q.employer("inv_e")
    c = ready("inv_c", min_salary=200_000)
    quota0 = e.get("/employer/invitations/quota")[1]
    st, one = send(e, c.id)
    cand_list = c.get("/candidate/invitations")[1]["items"]
    emp_view = e.get(f"/employer/invitations/{one['id']}")[1]
    quota1 = e.get("/employer/invitations/quota")[1]
    seen = cand_list[0] if cand_list else {}
    q.rec("INV-01", "Совместимое приглашение: одна запись у обеих сторон, условия и срок", A, "sent; у кандидата та же вилка, компания; слот +1; срок 7 дней",
          {"http": st, "status": one.get("status"), "candidate": (seen.get("company_name"), seen.get("salary_from"), seen.get("salary_to"), seen.get("work_format")),
           "employer": emp_view.get("status"), "slots": (quota0["used"], quota1["used"]), "rows": q.sql(f"select count(*) from invitation where employer_id='{e.id}'")},
          st == 201 and one["status"] == "sent" and (seen.get("salary_from"), seen.get("salary_to")) == (220_000, 300_000) and quota1["used"] == quota0["used"] + 1, source=SRC_INV)  # fmt: skip
    c2 = ready("inv_c2", min_salary=None)
    bad = {
        "без верхней границы": e.post("/employer/invitations", {k: v for k, v in q.invitation(c2.id, e.email).items() if k != "salary_to"}, headers=q.idem())[0],
        "без вилки": e.post("/employer/invitations", {k: v for k, v in q.invitation(c2.id, e.email).items() if not k.startswith("salary")}, headers=q.idem())[0],
        "от больше до": send(e, c2.id, low=300_000, high=200_000)[0],
        "разброс больше 1,5": send(e, c2.id, low=200_000, high=300_001)[0],
        "описание 49 знаков": send(e, c2.id, description="а" * 49)[0],
        "без ключа идемпотентности": e.post("/employer/invitations", q.invitation(c2.id, e.email))[0],
    }
    q.rec("INV-02", "Приглашение без вилки и с неверными границами", A, "422, активное приглашение не создано", {**bad, "rows_c2": q.sql(f"select count(*) from invitation where candidate_id='{c2.id}'")},
          all(v == 422 for v in bad.values()) and q.sql(f"select count(*) from invitation where candidate_id='{c2.id}'") == "0", source=SRC_INV)  # fmt: skip
    # INV-03 / INV-04: скрытый минимум
    lo = ready("inv_lo", min_salary=260_000)
    st_b, bounced = send(e, lo.id, low=240_000, high=300_000)
    blob = json.dumps([bounced, e.get(f"/employer/invitations/{bounced.get('id')}")[1]], ensure_ascii=False)
    lo_inbox = lo.get("/candidate/invitations")[1]["items"]
    lo_all = [lo.get("/candidate/invitations", params={"status": s})[1].get("items", []) for s in ("awaiting", "accepted", "archived")]
    q.rec("INV-03", "Нижняя граница вилки ниже скрытого минимума кандидата", A, "201 bounced; кандидат приглашения не видит; минимум 260 000 работодателю не раскрыт",
          {"http": st_b, "status": bounced.get("status"), "кандидат видит": len(lo_inbox) + sum(len(x) for x in lo_all), "260000 в ответе": "260000" in blob,
           "funnel": lo.get("/candidate/funnel")[1].get("not_delivered")},
          st_b == 201 and bounced["status"] == "bounced" and not lo_inbox and not any(lo_all) and "260000" not in blob, source=SRC_INV)  # fmt: skip
    eq, above = ready("inv_eq", min_salary=260_000), ready("inv_ab", min_salary=260_000)
    r_eq, r_ab = send(e, eq.id, low=260_000, high=320_000), send(e, above.id, low=265_000, high=320_000)
    q.rec("INV-04", "Граница: вилка «от» равна минимуму и чуть выше", A, "в обоих случаях доставлено (сравнение «не меньше»)",
          {"равно": r_eq[1].get("status"), "выше": r_ab[1].get("status"), "ниже (INV-03)": bounced.get("status")}, r_eq[1].get("status") == "sent" and r_ab[1].get("status") == "sent", source=SRC_INV)  # fmt: skip
    off = ready("inv_off", min_salary=None, formats=("office",))
    r_fmt = send(e, off.id, work_format="remote")
    q.rec("INV-05", "Формат приглашения не входит в форматы кандидата", A, "422 format_not_accepted, приглашение не создано",
          {"http": r_fmt[0], "code": r_fmt[1].get("code"), "rows": q.sql(f"select count(*) from invitation where candidate_id='{off.id}'")},
          r_fmt[0] == 422 and q.sql(f"select count(*) from invitation where candidate_id='{off.id}'") == "0", source=SRC_INV)  # fmt: skip
    key = str(uuid.uuid4())
    used_before = e.get("/employer/invitations/quota")[1]["used"]
    with cf.ThreadPoolExecutor(6) as pool:
        res = list(pool.map(lambda _: (lambda u: u.post("/employer/invitations", q.invitation(c2.id, e.email), headers={"Idempotency-Key": key}))(e.clone()), range(6)))
    ids = {r[1].get("id") for r in res if r[0] in (200, 201)}
    used_after = e.get("/employer/invitations/quota")[1]["used"]
    q.rec("INV-06", "Двойной клик: шесть одновременных отправок с одним ключом", A, "одно приглашение, один слот",
          {"codes": sorted({r[0] for r in res}), "ids": len(ids), "slots": used_after - used_before}, len(ids) == 1 and used_after - used_before == 1 and all(r[0] in (200, 201) for r in res), source=SRC_INV)  # fmt: skip
    again = send(e, c.id)
    need_a = e.post("/employer/needs", q.NEED)[1]["id"]
    other_need = send(e, c.id, need_id=need_a)
    q.rec("INV-07", "Повторное приглашение тому же кандидату при действующем", A, "409 active_invitation_exists со ссылкой на действующее",
          {"http": again[0], "code": again[1].get("code"), "ref": (again[1].get("params") or {}).get("invitation_id") == one["id"]},
          again[0] == 409 and again[1].get("code") == "active_invitation_exists", source=SRC_INV)  # fmt: skip
    e_other = q.employer("inv_e2")
    from_other = send(e_other, c.id)
    q.rec("INV-08", "Тот же кандидат: другая потребность того же работодателя и другая компания", A,
          "другая компания приглашает свободно; у той же пары действует правило «одно активное приглашение»",
          {"та же пара, другая потребность": (other_need[0], other_need[1].get("code")), "другая компания": (from_other[0], from_other[1].get("status"))},
          from_other[0] == 201 and from_other[1]["status"] == "sent" and other_need[0] == 409, source=SRC_INV,
          note="блокировка считается по паре «работодатель — кандидат», а не по потребности: так задано проверкой 5.6")  # fmt: skip
    # INV-09 / INV-10: предел слотов
    big = q.employer("inv_slots")
    pool_ids = [r for r in q.sql("select p.user_id from candidate_profile p join app_user u on u.id=p.user_id join assessment_category c on c.candidate_id=p.user_id "
                                 "where u.is_demo and u.demo_key like 'cand\\_%' and c.grade_code='junior' limit 40").splitlines() if r]  # fmt: skip

    def fmt_of(cid: str) -> str:
        pre = big.get("/employer/invitations/precheck", params={"candidate_id": cid})[1]
        return (pre.get("candidate_formats") or ["remote"])[0]

    sent, i = 0, 0
    while sent < 9 and i < len(pool_ids):
        r = send(big, pool_ids[i], low=200_000, high=260_000, work_format=fmt_of(pool_ids[i]))
        sent += r[0] == 201 and r[1]["status"] == "sent"
        i += 1
    two = pool_ids[i : i + 2]
    fmts = [fmt_of(x) for x in two]
    with cf.ThreadPoolExecutor(2) as pool:
        race = list(pool.map(lambda a: (lambda u: u.post("/employer/invitations", q.invitation(a[0], big.email, low=200_000, high=260_000, work_format=a[1]),
                                                          headers=q.idem()))(big.clone()), zip(two, fmts)))  # fmt: skip
    quota = big.get("/employer/invitations/quota")[1]
    extra = send(big, pool_ids[i + 2], low=200_000, high=260_000, work_format=fmt_of(pool_ids[i + 2]))
    q.rec("INV-10", "Две одновременные отправки при одном свободном слоте", A, "создано ровно одно; занято 10 из 10",
          {"race": [(r[0], r[1].get("code") or r[1].get("status")) for r in race], "quota": (quota["used"], quota["limit"])},
          sorted(r[0] for r in race) == [201, 409] and quota["used"] == quota["limit"] == 10, source=SRC_INV)  # fmt: skip
    q.rec("INV-09", "Отправка сверх лимита активных приглашений", A, "409 quota_exceeded с числом занятых и временем освобождения",
          {"http": extra[0], "code": extra[1].get("code"), "params": extra[1].get("params")}, extra[0] == 409 and extra[1].get("code") == "quota_exceeded" and "used" in (extra[1].get("params") or {}), source=SRC_INV)  # fmt: skip
    # INV-11: условия кандидата меняются перед отправкой
    mv = ready("inv_mv", min_salary=None)
    pre = e.get("/employer/invitations/precheck", params={"candidate_id": mv.id})[1]
    mv.put("/candidate/conditions", {"min_salary": 400_000, "work_formats": ["remote", "hybrid"]})
    r_mv = send(e, mv.id)
    q.rec("INV-11", "Кандидат поднял минимум между открытием формы и отправкой", A, "решение по состоянию на момент отправки: не доставлено",
          {"precheck_can_invite": pre.get("can_invite"), "status": r_mv[1].get("status")}, r_mv[0] == 201 and r_mv[1].get("status") == "bounced", source=SRC_INV)  # fmt: skip
    # INV-12: правка потребности после отправки
    c3 = ready("inv_c3", min_salary=None)
    nid = e.post("/employer/needs", q.NEED)[1]["id"]
    r3 = send(e, c3.id, need_id=nid)
    e.put(f"/employer/needs/{nid}", {**q.NEED, "title": "Переименовано после отправки", "salary_from": 240_000, "salary_to": 320_000})
    seen3 = c3.get(f"/candidate/invitations/{r3[1]['id']}")[1]
    q.rec("INV-12", "Потребность изменена после отправки приглашения", A, "кандидат видит условия на момент отправки",
          {"title": seen3.get("title"), "salary": (seen3.get("salary_from"), seen3.get("salary_to"))},
          seen3.get("title") == "Backend-разработчик в платежи" and (seen3.get("salary_from"), seen3.get("salary_to")) == (220_000, 300_000), source=SRC_INV)  # fmt: skip
    hide = ready("inv_hide", min_salary=None)
    hide.post("/candidate/visibility", {"state": "paused"})
    r_h = send(e, hide.id)
    q.rec("INV-13", "Кандидат скрыл профиль между выбором и отправкой", A, "409 candidate_unavailable, приглашение не создано",
          {"http": r_h[0], "code": r_h[1].get("code")}, r_h[0] == 409 and r_h[1].get("code") == "candidate_unavailable", source=SRC_INV)  # fmt: skip
    c4 = ready("inv_c4", min_salary=None)
    k = str(uuid.uuid4())
    fail = e.post("/employer/invitations", {**q.invitation(c4.id, e.email), "title": ""}, headers={"Idempotency-Key": k})
    ok1 = e.post("/employer/invitations", q.invitation(c4.id, e.email), headers={"Idempotency-Key": k})
    ok2 = e.post("/employer/invitations", q.invitation(c4.id, e.email), headers={"Idempotency-Key": k})
    q.rec("INV-14", "Ошибка отправки, затем повтор с тем же ключом", A, "после ошибки приглашения нет; повтор создаёт одно; третий запрос возвращает его же",
          {"fail": fail[0], "retry": ok1[0], "again": (ok2[0], ok2[1].get("id") == ok1[1].get("id")), "rows": q.sql(f"select count(*) from invitation where candidate_id='{c4.id}'")},
          fail[0] == 422 and ok1[0] == 201 and ok2[1].get("id") == ok1[1].get("id") and q.sql(f"select count(*) from invitation where candidate_id='{c4.id}'") == "1", source=SRC_INV)  # fmt: skip


def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    return " ".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)


def resp() -> None:
    e, e2 = q.employer("resp_e"), q.employer("resp_e2")
    prof = {"phone": MARK["phone"], "telegram": MARK["telegram"], "about": MARK["about"] + " пишите на qa-leak@example.com или " + MARK["phone"]}

    def pair(tag: str, disclose: list[str] | None, link: bool = False) -> tuple[q.User, dict, tuple[int, dict]]:
        user = ready(tag, min_salary=None, profile={**prof, **({"link": MARK["link"]} if link else {})})
        invitation = send(e, user.id)[1]
        accepted = user.post(f"/candidate/invitations/{invitation['id']}/accept", {"disclose": disclose} if disclose is not None else {})
        return user, invitation, accepted

    def contacts(emp: q.User, user: q.User) -> tuple[int, dict]:
        return emp.get(f"/employer/candidates/{user.id}/contacts")

    def open_channels(body: dict) -> list[str]:
        return sorted(k for k in ("email", "phone", "telegram", "link") if body.get(k))

    a, inv_a, acc_a = pair("resp_a", ["email"])
    ca = contacts(e, a)
    q.rec("RESP-01", "Принять, открыв только почту", A, "работодатель получает имя и e-mail; телефона и Telegram нет",
          {"accept": acc_a[0], "channels": open_channels(ca[1]), "name": ca[1].get("first_name")}, acc_a[0] == 200 and open_channels(ca[1]) == ["email"] and bool(ca[1].get("first_name")), source=SRC_PRIV)  # fmt: skip
    b, _, _ = pair("resp_b", ["phone"])
    t, _, _ = pair("resp_t", ["telegram"])
    q.rec("RESP-02", "Отдельные приглашения: только телефон; только Telegram", A, "раскрыт ровно выбранный канал",
          {"phone": open_channels(contacts(e, b)[1]), "telegram": open_channels(contacts(e, t)[1])},
          open_channels(contacts(e, b)[1]) == ["phone"] and open_channels(contacts(e, t)[1]) == ["telegram"], source=SRC_PRIV)  # fmt: skip
    m, _, _ = pair("resp_m", ["email", "phone", "link"], link=True)
    q.rec("RESP-03", "Несколько каналов", A, "открыт именно выбранный набор", open_channels(contacts(e, m)[1]), open_channels(contacts(e, m)[1]) == ["email", "link", "phone"], source=SRC_PRIV)
    n, inv_n, acc_n = pair("resp_n", [])
    n_default = ready("resp_nd", min_salary=None, profile=prof)
    inv_nd = send(e, n_default.id)[1]
    acc_nd = n_default.post(f"/candidate/invitations/{inv_nd['id']}/accept")
    q.rec("RESP-04", "Принять без выбора канала (пустой список и запрос без тела)", A, "понятная ошибка либо канал по умолчанию; не «полупринятое» приглашение",
          {"пустой список": (acc_n[0], acc_n[1].get("code") or acc_n[1].get("status"), inv_status(inv_n["id"]), open_channels(contacts(e, n)[1]) if contacts(e, n)[0] == 200 else contacts(e, n)[0]),
           "без тела": (acc_nd[0], acc_nd[1].get("status"), open_channels(contacts(e, n_default)[1]) if acc_nd[0] == 200 else None)},
          (acc_n[0] == 422 and inv_status(inv_n["id"]) in ("sent", "viewed")) or (acc_n[0] == 200 and inv_status(inv_n["id"]) == "accepted"), source=SRC_PRIV,
          note="без выбора действует канал по умолчанию (e-mail, privacy.reveal_*) — см. фактическое значение")  # fmt: skip
    x = ready("resp_x", min_salary=None, profile=prof)
    inv_x = send(e, x.id)[1]
    acc_x = x.post(f"/candidate/invitations/{inv_x['id']}/accept", {"disclose": ["link"]})
    acc_bad = x.post(f"/candidate/invitations/{inv_x['id']}/accept", {"disclose": ["passport"]})
    q.rec("RESP-05", "Выбран незаполненный канал (ссылка) и несуществующий канал", A, "422; приглашение остаётся без ответа",
          {"link": (acc_x[0], acc_x[1].get("code")), "unknown": acc_bad[0], "status": inv_status(inv_x["id"])},
          acc_x[0] == 422 and acc_bad[0] == 422 and inv_status(inv_x["id"]) in ("sent", "viewed"), source=SRC_PRIV)  # fmt: skip
    # RESP-06: отказ
    quota_before = e.get("/employer/invitations/quota")[1]["used"]
    dec_plain = x.post(f"/candidate/invitations/{inv_x['id']}/decline", {"reason_code": "other"})
    y = ready("resp_y", min_salary=None, profile=prof)
    inv_y = send(e, y.id, work_format="hybrid")[1]
    dec_cond = y.post(f"/candidate/invitations/{inv_y['id']}/decline", {"reason_code": "format", "condition": {"kind": "work_format", "value": "remote"}, "comment": "Только удалённо"})
    view_y = e.get(f"/employer/invitations/{inv_y['id']}")[1]
    q.rec("RESP-06", "Отказ без условия и с условием «удалённо»", A, "работодатель видит статус, причину и условие; контакты закрыты; слот освобождён",
          {"plain": (dec_plain[0], inv_status(inv_x["id"])), "cond": (dec_cond[0], view_y.get("status"), (view_y.get("decline") or {}).get("condition")),
           "contacts": (contacts(e, x)[0], contacts(e, y)[0]), "slots": (quota_before, e.get("/employer/invitations/quota")[1]["used"])},
          dec_plain[0] == 200 and dec_cond[0] == 200 and view_y.get("status") == "declined" and contacts(e, x)[0] == 403 and contacts(e, y)[0] == 403
          and e.get("/employer/invitations/quota")[1]["used"] == quota_before - 1, source=SRC_INV)  # fmt: skip
    q.rec("E2E-03", "Отказ вместо принятия: статус у работодателя, контакты закрыты, повторное открытие не меняет результат", A, "declined у обеих сторон; контакты 403 и после повторного чтения",
          {"employer": view_y.get("status"), "candidate": y.get(f"/candidate/invitations/{inv_y['id']}")[1].get("status"), "contacts_again": contacts(e, y)[0], "card_name": e.get(f"/employer/candidates/{y.id}")[1].get("display_name")},
          view_y.get("status") == "declined" and contacts(e, y)[0] == 403 and e.get(f"/employer/candidates/{y.id}")[1].get("display_name") is None, source=SRC_INV, note="в интерфейсе отказ пройден на демо-аккаунте Ивана (E2E-03u)")  # fmt: skip
    twice = (a.post(f"/candidate/invitations/{inv_a['id']}/accept", {"disclose": ["phone"]}), x.post(f"/candidate/invitations/{inv_x['id']}/decline", {"reason_code": "other"}),
             x.post(f"/candidate/invitations/{inv_x['id']}/accept", {"disclose": ["email"]}))  # fmt: skip
    events = q.sql(f"select string_agg(code, ',' order by id) from invitation_event where invitation_id='{inv_a['id']}'")
    q.rec("RESP-07", "Повторное принятие, повторный отказ, принятие после отказа", A, "409; статус и раскрытый набор каналов не меняются; событие одно",
          {"accept×2": twice[0][0], "decline×2": twice[1][0], "accept после отказа": twice[2][0], "channels": open_channels(contacts(e, a)[1]), "events": events},
          all(r[0] == 409 for r in twice) and open_channels(contacts(e, a)[1]) == ["email"] and (events or "").count("accepted") == 1, source=SRC_INV)  # fmt: skip
    z = ready("resp_z", min_salary=None, profile=prof)
    inv_z = send(e, z.id)[1]
    with cf.ThreadPoolExecutor(4) as pool:
        both = list(pool.map(lambda f: f(), [
            lambda: ("accept", z.clone().post(f"/candidate/invitations/{inv_z['id']}/accept", {"disclose": ["email"]})[0]),
            lambda: ("decline", z.clone().post(f"/candidate/invitations/{inv_z['id']}/decline", {"reason_code": "other"})[0]),
            lambda: ("accept", z.clone().post(f"/candidate/invitations/{inv_z['id']}/accept", {"disclose": ["email"]})[0]),
            lambda: ("decline", z.clone().post(f"/candidate/invitations/{inv_z['id']}/decline", {"reason_code": "other"})[0])]))  # fmt: skip
    final = inv_status(inv_z["id"])
    won = {name for name, code in both if code == 200}
    q.rec("RESP-08", "Принять и отказаться одновременно из двух вкладок", A, "одно конечное состояние; контакты открыты только если победило принятие",
          {"calls": both, "final": final, "contacts": contacts(e, z)[0]}, len(won) == 1 and final in ("accepted", "declined") and (contacts(e, z)[0] == 200) == (final == "accepted"), source=SRC_INV)  # fmt: skip
    q.rec("RESP-11", "Другой работодатель после принятия приглашения первого", A, "контакты 403, PDF 403, имя в карточке скрыто",
          {"contacts": contacts(e2, a)[0], "pdf": e2.c.get(f"/api/v1/employer/candidates/{a.id}/pdf").status_code, "name": e2.get(f"/employer/candidates/{a.id}")[1].get("display_name")},
          contacts(e2, a)[0] == 403 and e2.c.get(f"/api/v1/employer/candidates/{a.id}/pdf").status_code == 403 and e2.get(f"/employer/candidates/{a.id}")[1].get("display_name") is None, source=SRC_PRIV)  # fmt: skip
    foreign = {k: b.call(m, f"/candidate/invitations/{inv_a['id']}{p}", **({"json": body} if body else {}))[0] for k, (m, p, body) in {
        "get": ("GET", "", None), "view": ("POST", "/view", None), "accept": ("POST", "/accept", {"disclose": ["email"]}),
        "decline": ("POST", "/decline", {"reason_code": "other"}), "complaint": ("POST", "/complaint", {"reason_code": "spam"})}.items()}  # fmt: skip
    q.rec("RESP-12", "Другой кандидат открывает и отвечает на чужое приглашение", A, "404 на всё; чужое приглашение не изменилось", {**foreign, "status": inv_status(inv_a["id"])},
          all(v == 404 for v in foreign.values()) and inv_status(inv_a["id"]) == "accepted", source=SRC_PRIV)  # fmt: skip
    # RESP-13: смена контакта и приватности после принятия
    before = contacts(e, b)[1].get("phone")
    b.put("/candidate/profile", {**q.PROFILE, **prof, "phone": "+79995550202"})
    after = contacts(e, b)[1]
    q.rec("RESP-13", "Кандидат сменил телефон после принятия (раскрыт был телефон)", A, "явное правило: снимок на момент раскрытия либо текущее значение",
          {"до": before, "после": after.get("phone"), "каналы": open_channels(after)}, None, status="SPEC GAP", source=SRC_PRIV,
          note="работодатель видит " + ("текущее значение канала" if after.get("phone") == "+79995550202" else "значение на момент раскрытия") + "; в документации правило не названо")  # fmt: skip
    # RESP-14: карточка, список, PDF до и после
    fresh = ready("resp_pdf", min_salary=180_000, profile={**prof, "link": MARK["link"]})
    card0 = e.get(f"/employer/candidates/{fresh.id}")[1]
    pdf0 = e.c.get(f"/api/v1/employer/candidates/{fresh.id}/pdf").status_code
    inv_f = send(e, fresh.id)[1]
    list0 = json.dumps(e.get("/employer/invitations")[1], ensure_ascii=False)
    leaks0 = [k for k, v in {**MARK, "last_name": "Проверкин", "email": fresh.email, "min": "180000"}.items() if v in json.dumps(card0, ensure_ascii=False) or v in list0]
    fresh.post(f"/candidate/invitations/{inv_f['id']}/accept", {"disclose": ["email"]})
    card1 = json.dumps(e.get(f"/employer/candidates/{fresh.id}")[1], ensure_ascii=False)
    pdf1 = e.c.get(f"/api/v1/employer/candidates/{fresh.id}/pdf")
    text = pdf_text(pdf1.content) if pdf1.status_code == 200 else ""
    list1 = json.dumps(e.get("/employer/invitations")[1], ensure_ascii=False)
    after_leaks = {"card": [k for k in ("phone", "telegram", "link") if MARK[k] in card1], "pdf": [k for k in ("phone", "telegram", "link") if MARK[k].lstrip("+@") in text.replace(" ", "")],
                   "list": [k for k in ("phone", "telegram", "link") if MARK[k] in list1], "min": "180000" in card1 + list1 or "180 000" in text,
                   "about_contacts": "qa-leak@example.com" in card1 + text or MARK["phone"] in card1}  # fmt: skip
    q.rec("RESP-14", "Карточка, список приглашений и PDF до и после принятия (раскрыта только почта)", A + " (текст PDF извлечён pypdf)",
          "до: нет имени, контактов, минимума, PDF 403; после: имя и почта; телефона, Telegram, ссылки, минимума и контактов из «О себе» нет нигде",
          {"до": {"leaks": leaks0, "pdf": pdf0}, "после": {**after_leaks, "pdf": pdf1.status_code, "имя в PDF": "Проверкин" in text, "почта в PDF": fresh.email in text}},
          not leaks0 and pdf0 == 403 and pdf1.status_code == 200 and "Проверкин" in text and not after_leaks["card"] and not after_leaks["pdf"]
          and not after_leaks["list"] and not after_leaks["min"] and not after_leaks["about_contacts"], source=SRC_PRIV)  # fmt: skip
    # PROF-06: контакты в «О себе»
    about_seen = e.get(f"/employer/candidates/{fresh.id}")[1]
    q.rec("PROF-06", "Контакты, вписанные в «О себе», не уходят работодателю: до согласия текста нет, после — контакты вырезаны", A,
          "до принятия «О себе» нет; после — текст без почты и телефона",
          {"до": MARK["about"] in json.dumps(card0, ensure_ascii=False), "после есть текст": MARK["about"] in card1, "почта/телефон из текста": after_leaks["about_contacts"]},
          MARK["about"] not in json.dumps(card0, ensure_ascii=False) and not after_leaks["about_contacts"], source="интерфейс профиля: «контакты из текста вырезаются»")  # fmt: skip
    # RESP-15: пауза и удаление аккаунта после принятия
    a.post("/candidate/visibility", {"state": "paused"})
    paused = (contacts(e, a)[0], e.get(f"/employer/candidates/{a.id}")[0], e.get(f"/employer/invitations/{inv_a['id']}")[0])
    gone = m.post("/auth/account/delete", {"password": q.PASSWORD})
    after_del = (contacts(e, m)[0], e.get(f"/employer/candidates/{m.id}")[0], e.get("/employer/invitations")[0], e.get("/employer/invitations/stats")[0])
    q.rec("RESP-15", "После принятия кандидат поставил паузу; другой — удалил аккаунт", A, "без 500; у раскрытой пары на паузе контакты остаются; удалённый исчезает отовсюду",
          {"пауза (contacts, card, invitation)": paused, "удаление": gone[0], "после удаления (contacts, card, list, stats)": after_del},
          all(c < 500 for c in paused + after_del) and paused[0] == 200 and gone[0] == 204 and after_del[0] in (403, 404) and after_del[2] == 200, source="README: удаление аккаунта вычищает данные",
          note="правило «раскрытая пара видит контакты и при паузе показа» в документации явно не названо")  # fmt: skip


def count() -> None:
    src = "GET /candidate/funnel, /employer/invitations/quota, /employer/invitations/stats"
    c = ready("cnt_c", min_salary=None)
    f0 = c.get("/candidate/funnel")[1]
    q.rec("COUNT-09", "Новый аккаунт без просмотров и приглашений", A, "честные нули", {k: f0.get(k) for k in ("shown", "opened", "delivered", "not_delivered", "stage")},
          (f0["shown"], f0["opened"], f0["delivered"], f0["not_delivered"]) == (0, 0, 0, 0), source=src)  # fmt: skip
    e = q.employer("cnt_e")
    for _ in range(3):
        e.get(f"/employer/candidates/{c.id}")
    f1 = c.get("/candidate/funnel")[1]
    e2 = q.employer("cnt_e2")
    e2.get(f"/employer/candidates/{c.id}")
    f2 = c.get("/candidate/funnel")[1]
    q.rec("COUNT-01", "Открытие карточки: три раза одним работодателем, затем другим", A, "повторы одного работодателя не накручивают счётчик",
          {"после трёх открытий E1": f1["opened"], "после E2": f2["opened"]}, f1["opened"] == 1 and f2["opened"] == 2, source=src,
          note="считаются работодатели, открывшие карточку, а не открытия")  # fmt: skip
    nid = e.post("/employer/needs", q.NEED)[1]["id"]
    s1 = e.post(f"/employer/needs/{nid}/shortlists")[1]
    f3 = c.get("/candidate/funnel")[1]
    for _ in range(3):
        e.get(f"/employer/shortlists/{s1['id']}")
    f4 = c.get("/candidate/funnel")[1]
    e.post(f"/employer/needs/{nid}/shortlists", {"parent_id": s1["id"], "refinement": {"nice_skills": ["docker", "redis"]}})
    f5 = c.get("/candidate/funnel")[1]
    in_list = c.id in {i["candidate_id"] for i in s1["items"]}
    q.rec("COUNT-02", "«В подборках»: создание версии, повторное открытие, новая версия", A, "растёт от попадания в версию, не от просмотра страницы",
          {"в подборке": in_list, "после версии 1": f3["shown"], "после трёх чтений": f4["shown"], "после версии 2": f5["shown"]},
          in_list and f3["shown"] >= 1 and f4["shown"] == f3["shown"], source=src)  # fmt: skip
    i1 = send(e, c.id)[1]
    c.post(f"/candidate/invitations/{i1['id']}/decline", {"reason_code": "other"})
    i2 = send(e2, c.id)[1]
    c.post(f"/candidate/invitations/{i2['id']}/accept", {"disclose": ["email"]})
    hi = ready("cnt_hi", min_salary=400_000)
    send(e, hi.id)
    f6, fh = c.get("/candidate/funnel")[1], hi.get("/candidate/funnel")[1]
    stats = e.get("/employer/invitations/stats")[1]
    summ = c.get("/candidate/invitations/summary")[1]
    q.rec("COUNT-03", "Доставка, недоставка, принятие и отказ в счётчиках обеих сторон", A, "кандидат: доставлено 2; у кандидата с высоким минимумом — «не доставлено» 1; работодатель: отказ 1, недоставлено 1",
          {"кандидат": (f6["delivered"], f6["not_delivered"]), "высокий минимум": (fh["delivered"], fh["not_delivered"]), "работодатель": {k: (stats.get("total") or stats).get(k) for k in ("delivered", "not_delivered", "declined", "accepted")},
           "вкладки кандидата": (summ["awaiting"], summ["accepted"], summ["archived"])},
          (f6["delivered"], f6["not_delivered"]) == (2, 0) and (fh["delivered"], fh["not_delivered"]) == (0, 1) and (summ["awaiting"], summ["accepted"], summ["archived"]) == (0, 1, 1), source=src)  # fmt: skip
    i3 = send(e, ready("cnt_c3", min_salary=None).id)[1]
    e.get(f"/employer/invitations/{i3['id']}")
    q.rec("COUNT-08", "Признак новых ответов у работодателя", "API", "счётчик непрочитанных ответов",
          "в API работодателя нет поля «непрочитанные ответы»; есть только события приглашения (ход приглашения) и статусы", None, status="N/A",
          source="OpenAPI: /employer/invitations*", note="функция не заявлена в текущей версии")  # fmt: skip


def priv() -> None:
    cand, other = ready("priv_c", min_salary=None, profile={"phone": MARK["phone"], "telegram": MARK["telegram"]}), q.candidate("priv_o", "middle")
    e, e2 = q.employer("priv_e"), q.employer("priv_e2")
    anon = q.User()
    sid, item = q.start(other, "middle")
    nid = e.post("/employer/needs", q.NEED)[1]["id"]
    snap = e.post(f"/employer/needs/{nid}/shortlists")[1]
    invitation = send(e, cand.id, need_id=nid)[1]
    objects = {
        "сессия теста": ("GET", f"/assessment/sessions/{sid}", cand), "ответ в чужую сессию": ("POST", f"/assessment/sessions/{sid}/answers", cand),
        "результат": ("GET", f"/assessment/sessions/{sid}/result", cand), "потребность": ("GET", f"/employer/needs/{nid}", e2), "правка потребности": ("PUT", f"/employer/needs/{nid}", e2),
        "версия подборки": ("GET", f"/employer/shortlists/{snap['id']}", e2), "закрепление": ("PUT", f"/employer/needs/{nid}/pins/{cand.id}", e2),
        "приглашение (работодатель)": ("GET", f"/employer/invitations/{invitation['id']}", e2), "отзыв": ("POST", f"/employer/invitations/{invitation['id']}/withdraw", e2),
        "приглашение (кандидат)": ("GET", f"/candidate/invitations/{invitation['id']}", other), "принятие чужого": ("POST", f"/candidate/invitations/{invitation['id']}/accept", other),
        "контакты": ("GET", f"/employer/candidates/{cand.id}/contacts", e2), "PDF": ("GET", f"/employer/candidates/{cand.id}/pdf", e2),
    }
    body = {"POST": {"item_id": item["id"], "skipped": True, "disclose": ["email"]}, "PUT": q.NEED}
    res = {k: u.call(m, p, **({"json": body[m]} if m in body else {}))[0] for k, (m, p, u) in objects.items()}
    q.rec("PRIV-01", "Чужие объекты по ID: тест, потребность, подборка, приглашение, контакты, PDF", A, "403/404 на чтение и изменение; исходные объекты не тронуты",
          {**res, "invitation": inv_status(invitation["id"]), "session_answered": q.session_db(sid)["answered"]},
          all(v in (403, 404) for v in res.values()) and inv_status(invitation["id"]) == "sent" and q.session_db(sid)["answered"] == 0, source=SRC_PRIV)  # fmt: skip
    guest = {p: anon.get(p)[0] for p in (f"/employer/candidates/{cand.id}", f"/employer/candidates/{cand.id}/contacts", f"/candidate/invitations/{invitation['id']}", f"/assessment/sessions/{sid}", "/candidate/profile")}
    q.rec("PRIV-02", "Гость: карточка, контакты, приглашение, тест, профиль", A, "401 на всё", guest, all(v == 401 for v in guest.values()), source=SRC_PRIV)
    # вложенные объекты: имя и контакты до принятия в подборке, банке, карточке, приглашениях, предпроверке
    blobs = {"shortlist": e.get(f"/employer/shortlists/{snap['id']}")[1], "bank": e.get("/employer/candidates", params={"code": cand.get('/candidate/profile')[1]['public_code']})[1],
             "card": e.get(f"/employer/candidates/{cand.id}", params={"need_id": nid})[1], "invitation": e.get(f"/employer/invitations/{invitation['id']}")[1],
             "list": e.get("/employer/invitations")[1], "pair": e.get("/employer/invitations/pair-states", params={"candidate_ids": cand.id})[1]}  # fmt: skip
    needles = {"фамилия": "Проверкин", "почта": cand.email, "телефон": MARK["phone"], "telegram": MARK["telegram"]}
    leaks = {name: [k for k, v in needles.items() if v in json.dumps(b, ensure_ascii=False)] for name, b in blobs.items()}
    q.rec("PRIV-03", "До принятия имя и контакты не лежат ни в одном ответе работодателю (включая вложенные объекты)", A, "ни одного маркера в шести ответах", leaks,
          not any(leaks.values()), source=SRC_PRIV)  # fmt: skip
    it_view = other.get(f"/assessment/sessions/{sid}")[1]["item"]
    key = q.item_row(it_view["id"])["answer"]
    q.rec("BANK-09", "Выдача задания до ответа: ключ и признаки верного варианта клиенту не уходят", A, "в JSON задания нет ответа, баллов и служебных полей",
          {"keys": sorted(it_view.keys()), "has_answer": any(k in it_view for k in ("answer", "correct", "key", "explanation", "misconceptions", "b", "a")),
           "option_keys": sorted({k for o in (it_view.get("options") or []) for k in o})},
          not any(k in it_view for k in ("answer", "correct", "key", "explanation", "misconceptions", "solution")) and all(set(o) <= {"id", "text", "code"} for o in (it_view.get("options") or [])),
          source="schemas.TestItemView", note=f"ключ в базе: {str(key)[:40]}")  # fmt: skip
    err = [cand.get(f"/assessment/sessions/{sid}")[1], e2.get(f"/employer/candidates/{cand.id}/contacts")[1], anon.get("/candidate/profile")[1]]
    q.rec("PRIV-04", "Тексты ошибок доступа не содержат закрытых полей", A, "только code и message", err,
          all(set(x) <= {"code", "message", "params"} for x in err) and not any(MARK["phone"] in json.dumps(x) for x in err), source=SRC_PRIV)  # fmt: skip
    # XSS: пользовательский текст возвращается как данные
    payload = '<img src=x onerror="window.__qa_xss=1">'
    x = q.candidate("priv_x", "middle", profile={"about": payload + " текст о себе", "last_name": "Тегов"})
    ex = q.signup("priv_xe", "employer")
    comp = ex.put("/employer/company", {"name": "ООО <b>Тег</b>", "sphere": "Финтех", "description": payload + " " + "описание компании " * 4, "contact_method": {"kind": "email", "value": ex.email}})
    need = ex.post("/employer/needs", {**q.NEED, "title": "Тест <script>alert(1)</script>", "team_description": payload + " команда платежей"})
    api_ct = ex.c.get("/api/v1/employer/company").headers.get("content-type", "")
    front = "\n".join(p.read_text(errors="ignore") for p in (q.ROOT / "frontend/src").rglob("*.tsx"))
    q.rec("PRIV-08", "HTML в имени, «О себе», описании компании и потребности", A + " + статический поиск по frontend/src",
          "сервер хранит и отдаёт текст как данные JSON; интерфейс не вставляет его как HTML",
          {"company": comp[0], "need": need[0], "content-type": api_ct, "dangerouslySetInnerHTML в src": front.count("dangerouslySetInnerHTML"), "innerHTML": len(re.findall(r"\.innerHTML\s*=", front))},
          comp[0] in (200, 422) and need[0] in (201, 422) and api_ct.startswith("application/json") and front.count("dangerouslySetInnerHTML") == 0, source="README: CSP script-src 'self'",
          note="исполнение в браузере проверено отдельно (PRIV-08u)")  # fmt: skip
    admin = {p: cand.call(m, p)[0] for m, p in (("GET", "/admin/complaints"), ("GET", "/admin/assessment/bank/health"), ("POST", "/demo/reset"), ("POST", "/demo/clock/advance"), ("GET", "/demo/clock"))}
    restart = cand.post("/demo/scenario/restart")[0]
    q.rec("PRIV-07", "Обычный аккаунт против служебных и демо-действий", A, "403 без ключа ведущего; перезапуск сценария обычному пользователю запрещён", {**admin, "restart": restart},
          all(v in (403, 422) for v in admin.values()) and restart == 403, source="deps.require_admin; demo/router.py")  # fmt: skip


def fsp() -> None:
    src = "README «Интеграция с ФСП»; docs/fsp-registry-openapi.json; /fsp/*"
    free = {"klimova": "3944334a-e410-54fd-9178-c9eb5b188b48", "trainer": "f5345d17-7681-5582-b8ac-64ba846c7782", "minor": "37828601-b779-53a7-822a-3a6b4a40dc85",
            "no_results": "d1d9bc86-e50f-51a6-9303-ee0a21a51cdd", "anna": "4be935e1-8a40-5999-a598-580a150da9fc", "old": "3113ceb9-8307-563d-81ae-1c09e8bfe5fa"}  # fmt: skip

    def link(user: q.User, fsp_id: str | None = None, *, decision: str = "allow", pick: str | None = None, replay: bool = False,
             callback_as: q.User | None = None) -> dict:  # fmt: skip
        st, start = user.post("/fsp/link/start", {"accept": True, "consent_version": "fsp-data-1"})
        if st != 200:
            return {"start": (st, start.get("code"))}
        html = httpx.get(start["authorize_url"]).text
        data = dict(re.findall(r'type="hidden" name="(\w+)" value="([^"]*)"', html))
        if pick:
            data["pick"] = pick
        else:
            data["decision"] = decision
            if fsp_id:
                data["fsp_id"] = fsp_id
        reply = httpx.post(q.BASE + "/api/fsp-mock/oidc/authorize/decision", data=data, follow_redirects=False)
        loc = reply.headers.get("location", "")
        actor = callback_as or user
        back = actor.c.get(loc.replace(q.BASE, ""), follow_redirects=False)
        out = {"decision": reply.status_code, "callback": back.status_code, "to": back.headers.get("location", "")[-60:]}
        if replay:
            again = actor.c.get(loc.replace(q.BASE, ""), follow_redirects=False)
            out["replay_to"] = again.headers.get("location", "")[-60:]
        return out

    def control(mode: str) -> int:
        return httpx.post(q.BASE + "/api/fsp-mock/admin/control", json={"failure_mode": mode}, headers=q.admin_headers()).status_code

    httpx.post(q.BASE + "/api/fsp-mock/admin/reset", headers=q.admin_headers())
    control("none")
    u = ready("fsp_u", min_salary=None)
    no_consent = u.post("/fsp/link/start", {"accept": False, "consent_version": "fsp-data-1"})
    r = link(u, free["klimova"])
    state = u.get("/fsp/link")[1]
    q.rec("FSP-01", "Привязка тестового ФСП ID с согласием", A, "linked, достижения получены; без согласия поток не начинается",
          {"без согласия": no_consent[0], "flow": r, "status": state["status"], "achievements": len(state["achievements"]), "history": state["history_status"]},
          no_consent[0] in (409, 422) and state["status"] == "linked" and len(state["achievements"]) > 0, source=src)  # fmt: skip
    d = q.candidate("fsp_d", "middle")
    r_deny = link(d, free["old"], decision="deny")
    q.rec("FSP-02", "Отказ на странице входа ФСП ID", A, "возврат в приложение, привязки нет", {"flow": r_deny, "status": d.get("/fsp/link")[1]["status"]},
          d.get("/fsp/link")[1]["status"] == "not_linked" and "denied" in r_deny.get("to", "") or "result=" in r_deny.get("to", ""), source=src)  # fmt: skip
    n = ready("fsp_n", min_salary=None)
    link(n, free["no_results"])
    ns = n.get("/fsp/link")[1]
    e = q.employer("fsp_e")
    card_n = e.get(f"/employer/candidates/{n.id}")[1]
    q.rec("FSP-03", "Участник без зачтённых результатов", A, "linked, пустая история, нейтральный текст, вклад ФСП в силу профиля = 0",
          {"status": ns["status"], "history": ns["history_status"], "reason": ns.get("no_history_reason"), "achievements": len(ns["achievements"]),
           "card.fsp.mode": card_n["fsp"]["mode"], "fsp_points": {c["code"]: c["points"] for c in card_n["strength"]["contributions"]}.get("fsp", 0)},
          ns["status"] == "linked" and card_n["fsp"]["mode"] == "none" and {c["code"]: c["points"] for c in card_n["strength"]["contributions"]}.get("fsp", 0) == 0, source=src)  # fmt: skip
    thief = q.candidate("fsp_t", "middle")
    r_taken = link(thief, free["klimova"])
    q.rec("FSP-04", "ФСП ID уже привязан к другому кандидату", A, "вторая привязка отклонена; у первого владельца всё на месте",
          {"flow": r_taken, "thief": thief.get("/fsp/link")[1]["status"], "owner": u.get("/fsp/link")[1]["status"]},
          thief.get("/fsp/link")[1]["status"] != "linked" and u.get("/fsp/link")[1]["status"] == "linked", source=src)  # fmt: skip
    minor = q.candidate("fsp_m", "middle")
    r_minor = link(minor, free["minor"])
    q.rec("FSP-05", "Несовершеннолетний участник", A, "привязка отклонена с отдельным исходом",
          {"flow": r_minor, "status": minor.get("/fsp/link")[1]["status"], "stored": q.sql(f"select count(*) from fsp_achievement where user_id='{minor.id}'")},
          minor.get("/fsp/link")[1]["status"] != "linked" and q.sql(f"select count(*) from fsp_achievement where user_id='{minor.id}'") == "0", source=src)  # fmt: skip
    # FSP-06: отказы реестра при синхронизации
    out = {}
    count_before = q.sql(f"select count(*) from fsp_achievement where user_id='{u.id}'")
    for mode in ("unavailable", "malformed"):
        control(mode)
        fresh_user = q.candidate("fsp_f", "middle")
        flow = link(fresh_user, pick="random_free_with_history")
        fs = fresh_user.get("/fsp/link")[1]
        out[mode] = {"flow_to": flow.get("to", "")[-30:], "status": fs["status"], "history": fs.get("history_status"), "notice": (fs.get("notice") or {}).get("code") if isinstance(fs.get("notice"), dict) else fs.get("notice")}
    control("none")
    q.rec("FSP-06", "Реестр недоступен и реестр отвечает мусором", A, "понятное состояние без 500; чужие и неполные данные не сохраняются",
          {**out, "чужие достижения целы": q.sql(f"select count(*) from fsp_achievement where user_id='{u.id}'") == count_before},
          q.sql(f"select count(*) from fsp_achievement where user_id='{u.id}'") == count_before and all(v["status"] in ("linked", "not_linked", "pending") for v in out.values()), source=src,
          note="таймаут (режим slow, 10 с) не прогонялся: держит запрос дольше лимита прокси")  # fmt: skip
    first = len(u.get("/fsp/link")[1]["achievements"])
    s1 = u.post("/fsp/sync")
    s2 = u.post("/fsp/sync")
    same = len(u.get("/fsp/link")[1]["achievements"])
    q.rec("FSP-07", "Повторная синхронизация", A, "достижения не дублируются; частые повторы ограничены",
          {"sync": (s1[0], s1[1].get("code") if isinstance(s1[1], dict) else None), "sync2": (s2[0], s2[1].get("code") if isinstance(s2[1], dict) else None), "до": first, "после": same},
          same == first and s1[0] in (200, 409, 429) and s2[0] in (200, 409, 429), source=src)  # fmt: skip
    code_u = u.get("/candidate/profile")[1]["public_code"]
    before_unlink = e.get("/employer/candidates", params={"code": code_u, "has_fsp": "true"})[1]["items"]
    un = u.call("DELETE", "/fsp/link")
    un2 = u.call("DELETE", "/fsp/link")
    after_unlink = e.get("/employer/candidates", params={"code": code_u, "has_fsp": "true"})[1]["items"]
    q.rec("FSP-08", "Отвязка ФСП ID", A, "сведения удалены, фильтр «есть достижения» кандидата больше не находит; повторная отвязка безопасна",
          {"unlink": (un[0], un2[0]), "status": u.get("/fsp/link")[1]["status"], "rows": q.sql(f"select count(*) from fsp_achievement where user_id='{u.id}'"),
           "has_fsp до/после": (len(before_unlink), len(after_unlink))},
          un[0] in (200, 204) and un2[0] in (200, 204) and u.get("/fsp/link")[1]["status"] == "not_linked"
          and q.sql(f"select count(*) from fsp_achievement where user_id='{u.id}'") == "0" and len(after_unlink) == 0, source=src)  # fmt: skip
    rep = q.candidate("fsp_r", "middle")
    r_rep = link(rep, pick="random_free_with_history", replay=True)
    victim, attacker = q.candidate("fsp_v", "middle"), q.candidate("fsp_a", "middle")
    r_cross = link(victim, pick="random_free_with_history", callback_as=attacker)
    q.rec("FSP-09", "Повтор callback и callback из чужой сессии", A, "повтор не создаёт второй привязки; чужая сессия привязку не получает",
          {"replay": r_rep, "cross": r_cross, "attacker": attacker.get("/fsp/link")[1]["status"], "victim": victim.get("/fsp/link")[1]["status"]},
          attacker.get("/fsp/link")[1]["status"] == "not_linked" and rep.get("/fsp/link")[1]["status"] == "linked", source=src + "; state привязан к сессии")  # fmt: skip


if __name__ == "__main__":
    parts = [globals()[name] for name in sys.argv[1:]] or [inv, resp, count, priv, fsp]
    for part in parts:
        try:
            part()
        except Exception:
            import traceback

            q.rec(f"ERR-{part.__name__}", f"Группа {part.__name__} прервана", A, "группа выполняется до конца", traceback.format_exc()[-600:], None, status="BLOCKED")
    print("готово")
