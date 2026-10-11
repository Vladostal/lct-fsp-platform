"""TIME, RESP-09/10, COUNT-04…07, PUB-03, E2E-04, DEMO-08 — сценарии со сдвигом часов сервиса.

Время сдвигается штатным механизмом стенда: `POST /demo/clock/advance` с ключом ведущего. Сдвиг необратим
(стенд после прогона пересоздаётся), поэтому набор запускается последним. Точные границы «за секунду до/после»
на стенде не воспроизводятся — они закреплены unit-тестами чистых правил (tests/assessment/test_engine.py,
tests/contact/test_rules.py), прогон которых входит в регрессию.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import httpx  # noqa: E402
import qalib as q  # noqa: E402
from suite_flow_a import demo_login  # noqa: E402
from suite_flow_b import ready, send  # noqa: E402

A = "API+DB (часы сервиса сдвинуты ведущим)"
SRC_T = "catalog.limits: assessment_*; rules.can_start (Арх. 5.7)"
SRC_C = "catalog.limits: invitation_ttl_days, bounce_slot_hold_hours, silence_strikes; README «Контакт»"


def advance(hours: int) -> int:
    reply = httpx.post(q.BASE + "/api/v1/demo/clock/advance", json={"hours": hours, "force": True}, headers=q.admin_headers(), timeout=60)
    assert reply.status_code == 200, reply.text
    time.sleep(2)
    return reply.json()["offset_seconds"]


def settle(check, tries: int = 45):
    """Дождаться фоновой материализации истечений (цикл раз в 30 с)."""
    for _ in range(tries):
        value = check()
        if value:
            return value
        time.sleep(1)
    return check()


def actions(user: q.User) -> dict:
    return {a["grade"]["code"]: a for a in user.get("/assessment/state")[1]["next_actions"]}


def main() -> None:
    # ---------- подготовка до сдвига ----------
    exp0 = q.candidate("clk_s0", "middle", min_salary=None)
    sid0, _ = q.start(exp0, "middle")
    exp3 = q.candidate("clk_s3", "middle", min_salary=None)
    sid3, item3 = q.start(exp3, "middle")
    done = 0
    it = item3
    while it and done < 3:
        st, rep = exp3.post(f"/assessment/sessions/{sid3}/answers", {"item_id": it["id"], "answer": q.right(q.item_row(it["id"]))})
        it, done = rep.get("next_item"), done + 1
    v1, v2 = exp3.get(f"/assessment/sessions/{sid3}")[1], exp3.get(f"/assessment/sessions/{sid3}")[1]
    blueprint = {b["grade"]["code"]: (b["time_limit_min"], b["time_limit_max_min"], b["items_min"], b["items_max"]) for b in exp3.get("/assessment/blueprints")[1]}
    q.rec("TIME-01", "Время и длина теста по грейдам в плане", "API", "30/40/50 мин базово, 50/70/90 максимум; 14–26 заданий", blueprint,
          blueprint == {"junior": (30, 50, 14, 26), "middle": (40, 70, 14, 26), "senior": (50, 90, 14, 26)}, source="GET /assessment/methodology: time_limit_base_min, time_limit_ext_min")  # fmt: skip
    q.rec("TIME-02", "Срок попытки задаёт сервер: повторные чтения и время клиента его не двигают", "API+DB",
          "expires_at одинаков при повторных запросах; в запросе ответа нет поля времени, влияющего на срок",
          {"expires_at": (v1["expires_at"], v2["expires_at"]), "db": q.sql(f"select expires_at - started_at from assessment_session where id='{sid3}'")},
          v1["expires_at"] == v2["expires_at"], source="schemas.ClientInfo: «на балл не влияет»", note="сворачивание вкладки в интерфейсе не прогонялось (UI) — срок серверный")  # fmt: skip
    q.rec("TIME-05", "Изменение локального времени браузера", "API", "срок хранится на сервере; клиент прислать его не может",
          "AnswerRequest: item_id, answer, skipped, client{time_spent_ms, focus_lost, pasted} — поля срока нет; expires_at только в ответе сервера", True,
          source="OpenAPI AnswerRequest, TestSessionView", note="в интерфейсе подмена часов не прогонялась")  # fmt: skip
    dup = exp0.post("/assessment/sessions", {"grade_code": "middle"})
    dupq = exp0.post("/demo/assessment/quick-session", {"grade_code": "middle"})
    q.rec("TIME-06", "Повторный запуск при активной попытке (обычный и демо)", "API+DB", "409 session_active со ссылкой на идущую сессию; второй сессии нет",
          {"start": (dup[0], dup[1].get("code"), (dup[1].get("params") or {}).get("session_id") == sid0), "quick": (dupq[0], dupq[1].get("code")),
           "sessions": q.sql(f"select count(*) from assessment_session where candidate_id='{exp0.id}'")},
          dup[0] == 409 and dup[1].get("code") == "session_active" and dupq[0] == 409 and q.sql(f"select count(*) from assessment_session where candidate_id='{exp0.id}'") == "1", source=SRC_T)  # fmt: skip

    failed = q.candidate("clk_nc", "middle", min_salary=None)
    sf, itf = q.start(failed, "middle")
    q.run_test(failed, sf, itf, lambda n, r: "wrong")
    af = actions(failed)
    direct = failed.post("/assessment/sessions", {"grade_code": "middle"})
    q.rec("TIME-07", "После неподтверждения: повтор того же грейда и тест на грейд ниже", "API+DB", "middle — пауза 14 дней (и в API старта); junior доступен сразу",
          {"middle": (af["middle"]["available"], af["middle"].get("reason"), af["middle"].get("available_at")), "junior": af["junior"]["available"],
           "прямой старт": (direct[0], direct[1].get("code"), (direct[1].get("params") or {}).get("reason"))},
          af["middle"]["available"] is False and af["middle"].get("reason") == "retry_same_grade" and af["junior"]["available"] is True
          and direct[0] == 409 and (direct[1].get("params") or {}).get("reason") == "retry_same_grade", source=SRC_T)  # fmt: skip
    strong = q.candidate("clk_ok", "middle", min_salary=None)
    ss, its = q.start(strong, "middle")
    q.run_test(strong, ss, its, lambda n, r: "right")
    a_s = actions(strong)
    low = strong.post("/assessment/sessions", {"grade_code": "junior"})
    q.rec("TIME-08", "Подтверждение с запасом: тест на грейд выше доступен сразу и создаётся на нужный грейд", "API+DB", "senior available; сессия с target senior",
          {"outcome": q.session_db(ss)["outcome"], "senior": a_s["senior"]["available"]}, a_s["senior"]["available"] is True, source=SRC_T)  # fmt: skip
    low_at = a_s["junior"].get("available_at")
    pub3 = q.candidate("clk_p3", "middle", min_salary=None)
    sp, itp = q.start(pub3, "middle")
    q.run_test(pub3, sp, itp, lambda n, r: "right")

    e, e2 = q.employer("clk_e"), q.employer("clk_e2")
    hi = ready("clk_hi", min_salary=300_000)
    q0 = e.get("/employer/invitations/quota")[1]
    bounced = send(e, hi.id)[1]
    view_b = e.get(f"/employer/invitations/{bounced['id']}")[1]
    q1 = e.get("/employer/invitations/quota")[1]
    retry = send(e, hi.id, low=320_000, high=400_000)
    blob = json.dumps(view_b, ensure_ascii=False)
    q.rec("E2E-04", "Приглашение не доставлено: вилка ниже скрытого минимума", "API+DB",
          "работодатель видит «не доставлено» без значения минимума; кандидат приглашения не получает; слот удержан; пара закрыта на 30 дней",
          {"status": view_b.get("status"), "label": view_b.get("status_label") or view_b.get("bounce"), "300000 в ответе": "300000" in blob, "кандидат": len(hi.get("/candidate/invitations")[1]["items"]),
           "slots": (q0["used"], q1["used"]), "повтор новой отправкой": (retry[0], retry[1].get("code")), "воронка кандидата": hi.get("/candidate/funnel")[1]["not_delivered"]},
          view_b.get("status") == "bounced" and "300000" not in blob and not hi.get("/candidate/invitations")[1]["items"] and q1["used"] == q0["used"] + 1
          and retry[0] == 409 and hi.get("/candidate/funnel")[1]["not_delivered"] == 1, source=SRC_C, note="в интерфейсе ветка просмотрена на демо-аккаунте Дмитрия (E2E-04u)")  # fmt: skip
    cA, cB, cS = ready("clk_a", min_salary=None), ready("clk_b", min_salary=None), ready("clk_s", "junior", min_salary=None)
    iA = send(e, cA.id)[1]
    iB1, iB2 = send(e, cB.id)[1], send(e2, cB.id)[1]
    cB.post(f"/candidate/invitations/{iB2['id']}/accept", {"disclose": ["email"]})
    iS1 = send(e, cS.id, low=100_000, high=140_000)[1]
    used_t0 = e.get("/employer/invitations/quota")[1]["used"]

    # ---------- +1 час: тесты истекли ----------
    advance(1)
    late = exp3.post(f"/assessment/sessions/{sid3}/answers", {"item_id": it["id"], "skipped": True}) if it else (0, {})
    r0, r3 = exp0.get(f"/assessment/sessions/{sid0}/result"), exp3.get(f"/assessment/sessions/{sid3}/result")
    d0, d3 = q.session_db(sid0), q.session_db(sid3)
    q.rec("TIME-03", "Время вышло: без единого ответа и после трёх ответов", A, "сессии закрыты по времени, грейд не подтверждён, понятная подпись, ответы на месте",
          {"без ответов": (d0["status"], d0["outcome"], r0[1].get("outcome_label")), "после трёх": (d3["status"], d3["outcome"], d3["answered"], r3[1].get("outcome_label")),
           "категории": (q.sql(f"select count(*) from assessment_category where candidate_id='{exp0.id}'"), q.sql(f"select count(*) from assessment_category where candidate_id='{exp3.id}'"))},
          d0["status"] == "expired" and d3["status"] == "expired" and d3["answered"] == 3 and not str(d3["outcome"]).startswith("confirmed")
          and "Время вышло" in (r3[1].get("outcome_label") or "") and q.sql(f"select count(*) from assessment_category where candidate_id='{exp3.id}'") == "0", source=SRC_T)  # fmt: skip
    q.rec("TIME-04", "Ответ после истечения срока", A, "сервер отклоняет ответ, итог не меняется",
          {"late": (late[0], late[1].get("code") if isinstance(late[1], dict) else None), "answered": q.session_db(sid3)["answered"]}, late[0] in (409, 410) and q.session_db(sid3)["answered"] == 3, source=SRC_T,
          note="граница «секунда до / секунда после» и льгота answer_grace_s=5 с — только unit-тестами (tests/assessment/test_sessions.py)")  # fmt: skip

    # ---------- +74 часа (всего 75): слот недоставленного свободен ----------
    advance(74)
    q2 = settle(lambda: (lambda x: x if x["used"] == used_t0 - 1 else None)(e.get("/employer/invitations/quota")[1])) or e.get("/employer/invitations/quota")[1]
    q.rec("COUNT-04b", "Слот недоставленного приглашения освобождается через 72 часа", A, "занято на один слот меньше; остальные приглашения ещё действуют",
          {"до": used_t0, "после 75 ч": q2["used"], "активные": [q.sql(f"select status from invitation where id='{x}'") for x in (iA["id"], iB1["id"], iS1["id"])]}, q2["used"] == used_t0 - 1, source=SRC_C)  # fmt: skip

    # ---------- +5 дней (всего > 8): приглашения истекли ----------
    advance(24 * 5)
    statuses = settle(lambda: (lambda s: s if all(x == "expired" for x in s) else None)([q.sql(f"select status from invitation where id='{x}'") for x in (iA["id"], iB1["id"], iS1["id"])]))
    acc = cA.post(f"/candidate/invitations/{iA['id']}/accept", {"disclose": ["email"]})
    dec = cA.post(f"/candidate/invitations/{iA['id']}/decline", {"reason_code": "other"})
    views = (cA.get(f"/candidate/invitations/{iA['id']}")[1].get("status"), e.get(f"/employer/invitations/{iA['id']}")[1].get("status"))
    q.rec("RESP-09", "Истёкшее приглашение: попытка принять и отклонить", A, "409; статус «истекло» у обеих сторон; контакты закрыты",
          {"statuses": statuses, "accept": (acc[0], acc[1].get("code")), "decline": dec[0], "views": views, "contacts": e.get(f"/employer/candidates/{cA.id}/contacts")[0]},
          acc[0] == 409 and dec[0] == 409 and views == ("expired", "expired") and e.get(f"/employer/candidates/{cA.id}/contacts")[0] == 403, source=SRC_C)  # fmt: skip
    q.rec("RESP-10", "Ответ ровно на границе срока", "unit (pytest)", "одно правило границы: ответ принимается строго до expires_at",
          "на стенде секунда границы не воспроизводится; правило закреплено tests/contact/test_rules.py и test_invariants.py (прогон в регрессии)", None, status="N/A",
          source="contact/rules.py", note="проверено только чистым правилом, не через API")  # fmt: skip
    q3 = e.get("/employer/invitations/quota")[1]
    ev = [q.sql(f"select count(*) from invitation_event where invitation_id='{x}' and code='expired'") for x in (iA["id"], iB1["id"], iS1["id"])]
    q.rec("COUNT-04", "Срок приглашений истёк: слоты освобождены, приглашения не остаются активными", A, "занятых слотов 0; у каждого приглашения статус expired",
          {"used": q3["used"], "statuses": statuses}, q3["used"] == 0 and all(s == "expired" for s in (statuses or [])), source=SRC_C)  # fmt: skip
    time.sleep(35)  # ещё один проход фонового цикла
    e.get("/employer/invitations")
    cA.get("/candidate/invitations/summary")
    ev2 = [q.sql(f"select count(*) from invitation_event where invitation_id='{x}' and code='expired'") for x in (iA["id"], iB1["id"], iS1["id"])]
    q.rec("COUNT-05", "Повторная обработка просроченных приглашений", A, "событие «истекло» одно на приглашение; слоты не уходят в минус",
          {"events_before": ev, "events_after": ev2, "used": e.get("/employer/invitations/quota")[1]["used"]}, ev == ev2 == ["1", "1", "1"] and e.get("/employer/invitations/quota")[1]["used"] == 0, source=SRC_C)  # fmt: skip
    sB = cB.get("/candidate/invitations/summary")[1]
    q.rec("COUNT-06", "Одному кандидату два приглашения: одно принято, другое истекло", A, "состояния независимы: принято 1, в архиве 1; контакты открыты только принявшему работодателю",
          {"summary": (sB["awaiting"], sB["accepted"], sB["archived"]), "e contacts": e.get(f"/employer/candidates/{cB.id}/contacts")[0], "e2 contacts": e2.get(f"/employer/candidates/{cB.id}/contacts")[0],
           "strikes": sB["strikes"]["count"]},
          (sB["awaiting"], sB["accepted"], sB["archived"]) == (0, 1, 1) and e.get(f"/employer/candidates/{cB.id}/contacts")[0] == 403 and e2.get(f"/employer/candidates/{cB.id}/contacts")[0] == 200, source=SRC_C)  # fmt: skip
    s1 = settle(lambda: (lambda s: s if s["strikes"]["count"] >= 1 else None)(cS.get("/candidate/invitations/summary")[1]))
    iS2 = send(e2, cS.id, low=100_000, high=140_000)[1]

    # ---------- +8 дней (всего > 16): второе молчание → автопауза; пауза пересдачи прошла ----------
    advance(24 * 8)
    s2 = settle(lambda: (lambda s: s if s["visibility"]["state"] != "visible" else None)(cS.get("/candidate/invitations/summary")[1]))
    code_s = cS.get("/candidate/profile")[1]["public_code"]
    hidden = e.get("/employer/candidates", params={"code": code_s})[1]["items"]
    resume = cS.post("/candidate/invitations/resume")
    s3 = cS.get("/candidate/invitations/summary")[1]
    q.rec("COUNT-07", "Два молчания подряд → автопауза; «Я на связи» снимает её", A, "после первого истечения счётчик 1, после второго — пауза с причиной и сроком; после возврата счётчик 0",
          {"после первого": (s1 or {}).get("strikes"), "второе приглашение": iS2.get("status"), "после второго": (s2 or {}).get("visibility"), "в банке на паузе": len(hidden),
           "resume": resume[0], "после возврата": (s3["visibility"]["state"], s3["strikes"]["count"])},
          bool(s1) and bool(s2) and s2["visibility"]["state"] == "paused" and not hidden and s3["visibility"]["state"] == "visible" and s3["strikes"]["count"] == 0, source=SRC_C)  # fmt: skip
    gleb = demo_login("gleb").get("/candidate/invitations/summary")[1]
    q.rec("DEMO-08", "Подготовленные демо-ветки: недоставка (Дмитрий), истечение и автопауза (Глеб)", A, "после сдвига часов у Глеба второе истечение и автопауза; у Дмитрия «не доставлено» в воронке",
          {"gleb": (gleb["strikes"], gleb["visibility"]["state"]), "dmitry": demo_login("dmitry").get("/candidate/funnel")[1].get("not_delivered")},
          gleb["visibility"]["state"] == "paused" and demo_login("dmitry").get("/candidate/funnel")[1].get("not_delivered", 0) >= 1, source="GET /demo/accounts: state_label",
          note="принятие (Анна) и отказ с условием (Иван) пройдены в интерфейсе: E2E-03u, RESP-02u")  # fmt: skip
    af2 = actions(failed)
    q.rec("TIME-07b", "Через 16 дней после неподтверждения повтор того же грейда доступен", A, "пауза 14 дней снята", af2["middle"]["available"], af2["middle"]["available"] is True, source=SRC_T)
    before = strong.get("/assessment/state")[1]["category"]
    again = pub3.post("/assessment/sessions", {"grade_code": "middle"})
    if again[0] == 201:
        q.run_test(pub3, again[1]["id"], again[1]["item"], lambda n, r: "wrong")
    st3 = pub3.get("/assessment/state")[1]
    q.rec("PUB-03", "Подтверждённый Middle получает слабый результат на повторной попытке", A, "грейд автоматически не понижается: категория остаётся backend:middle",
          {"retake": again[0], "outcome": q.session_db(again[1]["id"])["outcome"] if again[0] == 201 else None, "category": (st3["category"] or {}).get("code"),
           "verdict": q.sql(f"select verdict from assessment_category where candidate_id='{pub3.id}'"), "level": (st3.get("level") or {}).get("label")},
          again[0] == 201 and (st3["category"] or {}).get("code") == "backend:middle", source="CLAUDE.md §1: грейд не понижается принудительно",
          note="вердикт категории после слабой попытки — см. фактическое значение; уровень считается по всем ответам за 180 дней")  # fmt: skip

    # ---------- граница 90 дней для смены грейда вниз ----------
    blocked_now = strong.post("/assessment/sessions", {"grade_code": "junior"})
    advance(24 * 73)  # всего ≈ 89 суток 3 часа с момента присвоения
    a89 = actions(strong)["junior"]
    advance(24 * 2)  # ≈ 91 сутки
    a91 = actions(strong)["junior"]
    start91 = strong.post("/assessment/sessions", {"grade_code": "junior"})
    q.rec("TIME-09", "Смена подтверждённого грейда: до срока 90 дней и после", A, "сразу и на 89-е сутки — пауза grade_change (и в API старта); на 91-е — доступно",
          {"сразу": (low[0], (low[1].get("params") or {}).get("reason"), low_at), "16-е сутки": (blocked_now[0], (blocked_now[1].get("params") or {}).get("reason")),
           "89-е сутки": (a89["available"], a89.get("reason")), "91-е сутки": a91["available"], "старт": start91[0], "категория до": before["code"]},
          low[0] == 409 and (low[1].get("params") or {}).get("reason") == "grade_change" and a89["available"] is False and a91["available"] is True and start91[0] == 201, source=SRC_T,
          note="точная граница «ровно 90 суток» — unit-тест rules (test_engine.py::test_can_start_row5*)")  # fmt: skip


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback

        q.rec("ERR-clock", "Набор со сдвигом часов прерван", A, "набор выполняется до конца", traceback.format_exc()[-700:], None, status="BLOCKED")
    print("готово")
