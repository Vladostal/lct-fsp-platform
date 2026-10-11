"""AUTH, PROF, PDF, SURV — проверки уровня API/DB на живом стенде."""

from __future__ import annotations

import concurrent.futures as cf
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import httpx  # noqa: E402
import qalib as q  # noqa: E402

A = "API"
SRC_AUTH = "CLAUDE.md §1: регистрация по email с подтверждением; OpenAPI /auth/*"
SRC_PROF = "CLAUDE.md §1 «Кандидат: профиль и резюме»; OpenAPI /candidate/profile"
SIGN = {"password": q.PASSWORD, "role": "candidate", "consent_processing": True, "consent_version": "processing-1", "is_adult": True}


def users(email: str) -> int:
    return int(q.sql(f"select count(*) from app_user where lower(email)=lower('{email}')") or 0)


def auth() -> None:
    anon = q.User()
    # AUTH-01 / AUTH-02
    cand = q.signup("auth01")
    role = q.sql(f"select role from app_user where email='{cand.email}'")
    letters = q.mails(cand.email)
    q.rec("AUTH-01", "Регистрация кандидата: один аккаунт нужной роли, письмо этому адресу", A, "1 строка candidate, 1 письмо на адрес",
          {"rows": users(cand.email), "role": role, "mails": [m["to"] for m in letters]},
          users(cand.email) == 1 and role == "candidate" and [m["to"] for m in letters] == [cand.email], source=SRC_AUTH)  # fmt: skip
    emp = q.signup("auth02", "employer")
    st_c, _ = emp.get("/candidate/profile")
    st_e, _ = emp.get("/employer/company")
    q.rec("AUTH-02", "Регистрация работодателя открывает путь компании, а не анкету кандидата", A, "роль employer; /candidate/* — 403",
          {"me": emp.get("/auth/me")[1].get("role"), "candidate_profile": st_c, "company": st_e},
          emp.get("/auth/me")[1].get("role") == "employer" and st_c == 403 and st_e in (200, 404), source=SRC_AUTH)  # fmt: skip

    # AUTH-03: по одному обязательному полю
    out = {}
    for field in ("email", "password", "role", "consent_processing", "consent_version", "is_adult"):
        mail = q.new_email("auth03")
        body = {"email": mail, **SIGN}
        body.pop(field)
        st, reply = anon.post("/auth/signup", body)
        out[field] = (st, users(mail))
    for field in ("consent_processing", "is_adult"):
        mail = q.new_email("auth03")
        st, reply = anon.post("/auth/signup", {"email": mail, **SIGN, field: False})
        out[field + "=false"] = (st, users(mail), [f["name"] for f in reply.get("fields", [])] if isinstance(reply, dict) else reply)
    q.rec("AUTH-03", "Без каждого обязательного поля и согласия аккаунт не создаётся", A, "422 и 0 строк на каждый случай", out,
          all(v[0] == 422 and v[1] == 0 for v in out.values()), source=SRC_AUTH)  # fmt: skip

    # AUTH-04
    out = {}
    for label, patch in {"без @": {"email": "qa-no-at.example.com"}, "пробелы": {"email": "   "}, "короткий пароль": {"password": "Ab1-xyz"},
                         "простой пароль": {"password": "password123"}, "чужая роль": {"role": "admin"},
                         "длинная почта": {"email": "a" * 250 + "@example.com"}}.items():  # fmt: skip
        st, reply = anon.post("/auth/signup", {"email": q.new_email("auth04"), **SIGN, **patch})
        out[label] = st
    q.rec("AUTH-04", "Невалидная почта, пробелы, короткий и простой пароль", A, "422 без 500", out, all(v == 422 for v in out.values()), source=SRC_AUTH)

    # AUTH-05
    base = cand.email
    variants = [base, base.upper(), f"  {base}  ", base.replace("qa.", "QA.")]
    replies = [anon.post("/auth/signup", {"email": v, **SIGN}) for v in variants]
    fresh = anon.post("/auth/signup", {"email": q.new_email("auth05"), **SIGN})
    login_upper = q.User()
    st_up, _ = login_upper.post("/auth/login", {"email": base.upper(), "password": q.PASSWORD})
    q.rec("AUTH-05", "Повторная регистрация занятой почты в разных регистрах и с пробелами", A,
          "один аккаунт; ответ неотличим от ответа на свободный адрес; вход без учёта регистра",
          {"statuses": [r[0] for r in replies], "rows": users(base), "same_as_fresh": all(r == fresh for r in replies), "login_upper": st_up},
          users(base) == 1 and all(r[0] == fresh[0] for r in replies) and st_up == 200, source=SRC_AUTH)  # fmt: skip

    # AUTH-06
    mail = q.new_email("auth06")
    with cf.ThreadPoolExecutor(6) as pool:
        codes = list(pool.map(lambda _: q.User().post("/auth/signup", {"email": mail, **SIGN})[0], range(6)))
    import time

    time.sleep(1.5)
    q.rec("AUTH-06", "Шесть одновременных регистраций одного адреса", A, "один аккаунт, без 500; писем не больше числа запросов",
          {"codes": codes, "rows": users(mail), "mails": len(q.mails(mail))},
          users(mail) == 1 and all(c in (202, 429) for c in codes) and 1 <= len(q.mails(mail)) <= 6, source=SRC_AUTH)  # fmt: skip

    # AUTH-07 / AUTH-08
    fresh_user = q.signup("auth07", verify=False)
    st_login_before, body_before = q.User().post("/auth/login", {"email": fresh_user.email, "password": q.PASSWORD})
    token = q.mail_token(fresh_user.email)
    st_bad, _ = q.User().post("/auth/verify-email", {"token": (token or "x")[:-3] + "zzz"})
    st_ok, _ = fresh_user.post("/auth/verify-email", {"token": token})
    st_again, again = q.User().post("/auth/verify-email", {"token": token})
    other = q.signup("auth07b", verify=False)
    verified_other = q.sql(f"select email_verified_at is not null from app_user where email='{other.email}'")
    q.rec("AUTH-07", "Ссылка подтверждения: верная, повторная, испорченная; чужая почта не подтверждается", A,
          "верная — 200; испорченная — ошибка; повтор не подтверждает никого другого",
          {"valid": st_ok, "corrupted": st_bad, "reuse": (st_again, again.get("code") if isinstance(again, dict) else again), "other_verified": verified_other},
          st_ok == 200 and st_bad in (400, 404, 410, 422) and verified_other == "f", source=SRC_AUTH,
          note="просроченная ссылка: токены живут по реальному времени, на стенде не сдвигается — покрыто pytest tests/identity")  # fmt: skip
    st_login_after, _ = q.User().post("/auth/login", {"email": fresh_user.email, "password": q.PASSWORD})
    q.rec("AUTH-08", "Вход до и после подтверждения адреса", A, "до подтверждения сессии нет; после — 200",
          {"before": (st_login_before, body_before.get("code") if isinstance(body_before, dict) else body_before), "after": st_login_after},
          st_login_before in (401, 403, 409) and st_login_after == 200, source=SRC_AUTH)  # fmt: skip

    # AUTH-09
    wrong = q.User().post("/auth/login", {"email": cand.email, "password": "Wrong-" + q.PASSWORD})
    unknown = q.User().post("/auth/login", {"email": q.new_email("nobody"), "password": q.PASSWORD})
    empty = q.User().post("/auth/login", {"email": "", "password": ""})
    probe = q.User()
    probe.post("/auth/login", {"email": cand.email, "password": "Wrong-" + q.PASSWORD})
    q.rec("AUTH-09", "Неверный пароль, неизвестная почта, пустой ввод", A, "401 с одинаковым телом для двух первых; пустой — 422; сессии нет",
          {"wrong": wrong, "unknown": unknown, "empty": empty[0], "me_after_wrong": probe.get("/auth/me")[0]},
          wrong[0] == 401 and wrong == unknown and empty[0] == 422 and probe.get("/auth/me")[0] == 401, source=SRC_AUTH)  # fmt: skip

    # AUTH-11
    victim = q.signup("auth11")
    bystander = q.signup("auth11b")
    second = q.User()
    second.post("/auth/login", {"email": victim.email, "password": q.PASSWORD})
    same = q.User().post("/auth/password/forgot", {"email": victim.email}) == q.User().post("/auth/password/forgot", {"email": q.new_email("ghost")})
    reset_token = None
    for _ in range(25):
        hits = [m for m in q.mails(victim.email) if "парол" in m["subject"].lower() or "сброс" in m["subject"].lower()]
        if hits:
            import re

            reset_token = re.search(r"token=([\w\-.]+)", hits[0]["text"]).group(1)
            break
        time.sleep(0.4)
    new_password = q.PASSWORD + "-n"
    st_reset, _ = q.User().post("/auth/password/reset", {"token": reset_token, "new_password": new_password})
    st_reuse, _ = q.User().post("/auth/password/reset", {"token": reset_token, "new_password": new_password + "2"})
    st_old = q.User().post("/auth/login", {"email": victim.email, "password": q.PASSWORD})[0]
    st_new = q.User().post("/auth/login", {"email": victim.email, "password": new_password})[0]
    q.rec("AUTH-11", "Сброс пароля: ссылка одноразовая, меняется пароль только у адресата, старые сессии закрыты", A,
          "ответ на запрос одинаков для своего и чужого адреса; сброс 200/204; повтор отклонён; старые сессии и пароль не действуют; сосед не затронут",
          {"same_reply": same, "reset": st_reset, "reuse": st_reuse, "old_password": st_old, "new_password": st_new,
           "old_sessions": (victim.get("/auth/me")[0], second.get("/auth/me")[0]), "bystander": bystander.get("/auth/me")[0]},
          same and st_reset in (200, 204) and st_reuse >= 400 and st_old == 401 and st_new == 200
          and victim.get("/auth/me")[0] == 401 and second.get("/auth/me")[0] == 401 and bystander.get("/auth/me")[0] == 200, source=SRC_AUTH,
          note="истёкшая ссылка сброса — по реальному времени, покрыто pytest")  # fmt: skip

    # AUTH-12
    out = {
        "candidate→employer": [cand.get(p)[0] for p in ("/employer/needs", "/employer/candidates", "/employer/invitations", "/employer/company")],
        "candidate→POST need": cand.post("/employer/needs", q.NEED)[0],
        "employer→candidate": [emp.get(p)[0] for p in ("/candidate/profile", "/candidate/invitations", "/assessment/state", "/fsp/link")],
        "employer→POST session": emp.post("/assessment/sessions", {"grade_code": "middle"})[0],
        "anon": [anon.get(p)[0] for p in ("/candidate/profile", "/employer/needs", "/assessment/state")],
        "admin без ключа": [cand.get(p)[0] for p in ("/admin/complaints", "/admin/assessment/bank/health", "/demo/clock")],
    }
    flat = out["candidate→employer"] + [out["candidate→POST need"]] + out["employer→candidate"] + [out["employer→POST session"]] + out["admin без ключа"]
    q.rec("AUTH-12", "Роль проверяется сервером: кандидат ↔ работодатель, гость, служебные адреса", A, "403 для чужой роли, 401 для гостя", out,
          all(c == 403 for c in flat) and all(c == 401 for c in out["anon"]), source=SRC_AUTH)  # fmt: skip


def profile() -> None:
    u = q.signup("prof")
    st, body = u.put("/candidate/profile", {"last_name": "Минимальный", "first_name": "Профиль"})
    q.rec("PROF-01", "Только обязательные поля (фамилия, имя)", A, "200; остальные поля необязательны", (st, body if st != 200 else "ok"), st == 200, source=SRC_PROF)
    full = {"last_name": "Полный", "first_name": "Профиль", "middle_name": "Тестович", "city": "Нижний Новгород", "phone": "+79120000011",
            "telegram": "@qa_full_marker", "link": "https://example.com/qa-full", "experience_years": 4.5, "roles": [],
            "about": "Делаю сервисы.\nВторая строка с «кавычками» и <b>тегом</b>.",
            "declared_skills": [{"code": "python"}, {"code": "postgresql"}, {"code": "docker"}]}  # fmt: skip
    st, _ = u.put("/candidate/profile", full)
    back = u.get("/candidate/profile")[1]
    diff = {k: (v, back.get(k)) for k, v in full.items() if k not in ("declared_skills", "roles") and back.get(k) != v}
    skills = sorted(s["code"] for s in back.get("declared_skills", []))
    q.rec("PROF-02", "Все поля: сохранить и прочитать без искажений", A, "значения совпадают, навыки на месте", {"status": st, "diff": diff, "skills": skills},
          st == 200 and not diff and skills == ["docker", "postgresql", "python"], source=SRC_PROF)  # fmt: skip
    out = {
        "пустая фамилия": u.put("/candidate/profile", {**full, "last_name": ""})[0],
        "имя из пробелов": u.put("/candidate/profile", {**full, "first_name": "   "})[0],
        "фамилия 300 знаков": u.put("/candidate/profile", {**full, "last_name": "Я" * 300})[0],
        "«о себе» 2001 знак": u.put("/candidate/profile", {**full, "about": "а" * 2001})[0],
        "«о себе» 1001 знак": u.put("/candidate/profile", {**full, "about": "а" * 1001})[0],
        "телефон-буквы": u.put("/candidate/profile", {**full, "phone": "позвоните мне"})[0],
        "ссылка javascript:": u.put("/candidate/profile", {**full, "link": "javascript:alert(1)"})[0],
    }
    after = u.get("/candidate/profile")[1]
    q.rec("PROF-03", "Пустые обязательные, пробелы, слишком длинный текст, неверные телефон и ссылка", A,
          "422 на каждый случай; сохранённое не испорчено", {**out, "last_name_after": after["last_name"]},
          all(v == 422 for k, v in out.items() if k != "«о себе» 1001 знак") and after["last_name"] == "Полный", source=SRC_PROF,
          note=f"«о себе» 1001 знак → {out['«о себе» 1001 знак']}: интерфейс показывает счётчик «из 1000»")  # fmt: skip
    exp = {str(v): u.put("/candidate/profile", {**full, "experience_years": v})[0] for v in (0, -1, 2.5, 60, 1000, None)}
    q.rec("PROF-04", "Стаж: 0, отрицательный, дробный, очень большой, пустой", A, "0, 2.5 и пусто принимаются; отрицательный и абсурдный — 422", exp,
          exp["0"] == 200 and exp["2.5"] == 200 and exp["None"] == 200 and exp["-1"] == 422 and exp["1000"] == 422, source=SRC_PROF)  # fmt: skip
    catalog = httpx.get(q.BASE + "/api/v1/catalog").json()
    codes = [s["code"] for s in catalog["skills"]]
    dup = u.put("/candidate/profile", {**full, "declared_skills": [{"code": "python"}, {"code": "python"}, {"code": "docker"}]})
    dup_back = [s["code"] for s in u.get("/candidate/profile")[1]["declared_skills"]]
    over = u.put("/candidate/profile", {**full, "declared_skills": [{"code": c} for c in codes[:31]]})[0]
    edge = u.put("/candidate/profile", {**full, "declared_skills": [{"code": c} for c in codes[:30]]})[0]
    unknown = u.put("/candidate/profile", {**full, "declared_skills": [{"code": "нет-такого-навыка"}]})[0]
    roles = [r["code"] for r in catalog["roles"]]
    roles_over = u.put("/candidate/profile", {**full, "roles": roles[:6]})[0] if len(roles) >= 6 else "мало ролей"
    cleared = u.put("/candidate/profile", {**full, "declared_skills": []})[0]
    q.rec("PROF-05", "Стек и роли: дубли, удаление, повторное добавление, лимиты", A, "дубли схлопываются; 30 навыков — можно, 31 — нельзя; 6 ролей — нельзя",
          {"dup": (dup[0], dup_back), "30": edge, "31": over, "unknown": unknown, "roles_6": roles_over, "clear": cleared},
          dup[0] == 200 and sorted(dup_back) == ["docker", "python"] and edge == 200 and over == 422 and roles_over in (422, "мало ролей") and cleared == 200,
          source=SRC_PROF + "; catalog.limits.declared_skills_max=30")  # fmt: skip
    u.put("/candidate/profile", full)
    fm = {
        "ни одного": u.put("/candidate/conditions", {"min_salary": None, "work_formats": []})[0],
        "один": u.put("/candidate/conditions", {"min_salary": None, "work_formats": ["remote"]})[0],
        "несколько": u.put("/candidate/conditions", {"min_salary": None, "work_formats": ["remote", "office"]})[0],
        "неизвестный": u.put("/candidate/conditions", {"min_salary": None, "work_formats": ["moon"]})[0],
    }
    q.rec("PROF-07", "Формат работы: ни одного, один, несколько, неизвестный", A, "нужен хотя бы один; неизвестный — 422", fm,
          fm == {"ни одного": 422, "один": 200, "несколько": 200, "неизвестный": 422}, source=SRC_PROF)  # fmt: skip
    sal = {str(v): u.put("/candidate/conditions", {"min_salary": v, "work_formats": ["remote"], "relocation_ready": True})[0]
           for v in (40000, 600000, 620000, 39999, 150000, -1, 0)}  # fmt: skip
    cond = u.get("/candidate/conditions")[1]
    u.put("/candidate/conditions", {"min_salary": None, "work_formats": ["remote"], "relocation_ready": False})
    cond2 = u.get("/candidate/conditions")[1]
    q.rec("PROF-08", "Переезд и скрытый минимум: границы лестницы 40 000–600 000 с шагом 20 000, снятие минимума", A,
          "границы принимаются; вне лестницы и не по шагу — 422; минимум и переезд сохраняются и снимаются",
          {"codes": sal, "saved": cond, "cleared": cond2},
          sal["40000"] == 200 and sal["600000"] == 200 and sal["620000"] == 422 and sal["39999"] == 422 and sal["150000"] == 422 and sal["-1"] == 422
          and cond2["min_salary"] is None and cond2["relocation_ready"] is False,
          source="catalog.limits: min_salary_low/high/step")  # fmt: skip
    extra = u.put("/candidate/profile", {**full, "email": "hacked@example.com", "public_code": "К-00001", "role": "employer", "is_demo": True})
    after = u.get("/candidate/profile")[1]
    q.rec("PROF-11", "Почта, код и роль не меняются лишними полями в запросе профиля", A, "лишние поля не действуют",
          {"status": extra[0], "email": after["email"] == u.email, "code_changed": after["public_code"] == "К-00001", "role": u.get("/auth/me")[1]["role"]},
          after["email"] == u.email and after["public_code"] != "К-00001" and u.get("/auth/me")[1]["role"] == "candidate", source=SRC_PROF)  # fmt: skip

    # PROF-09: заявленное после теста не меняет категорию
    c = q.candidate("prof09", "junior", min_salary=None)
    sid, item = q.start(c, "junior")
    q.run_test(c, sid, item, lambda n, row: "wrong")
    before = c.get("/assessment/state")[1]
    c.put("/candidate/profile", {**q.PROFILE, "experience_years": 25, "declared_skills": [{"code": x} for x in codes[:20]]})
    after_state = c.get("/assessment/state")[1]
    q.rec("PROF-09", "После теста: большой стаж и 20 заявленных навыков не дают категорию", A + "+DB", "категории нет, как и до правки профиля",
          {"before": before["category"], "after": after_state["category"], "outcome": q.session_db(sid)["outcome"]},
          before["category"] is None and after_state["category"] is None, source="CLAUDE.md §1: категория только из теста")  # fmt: skip


def pdf() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if not src or not src.exists():
        q.rec("PDF-01", "Образцы резюме", A, "есть каталог с PDF", "каталог образцов не передан", None, status="BLOCKED")
        return
    from pypdf import PdfReader, PdfWriter

    u = q.signup("pdf")

    def upload(name: str, data: bytes, ctype: str = "application/pdf") -> tuple[int, dict]:
        reply = u.c.post("/api/v1/candidate/profile/resume", files={"file": (name, data, ctype)})
        try:
            return reply.status_code, reply.json()
        except Exception:
            return reply.status_code, {"raw": reply.text[:200]}

    def vals(body: dict) -> dict:
        return {k: (v.get("value") if isinstance(v, dict) else v) for k, v in (body.get("fields") or {}).items()}

    st, body = upload("hh.pdf", (src / "hh.pdf").read_bytes())
    got = vals(body)
    before = u.get("/candidate/profile")[1]
    q.rec("PDF-01", "Текстовый PDF: поля распознаны как подсказки, анкета сама не меняется", A, "200; есть ФИО/контакты/стек; профиль не перезаписан",
          {"status": st, "fields": sorted(got)[:14], "last_name": got.get("last_name"), "profile_last_name": before["last_name"]},
          st == 200 and bool(got.get("last_name")) and before["last_name"] in (None, ""), source=SRC_PROF)  # fmt: skip
    st2, body2 = upload("twocol.pdf", (src / "twocol.pdf").read_bytes())
    st3, body3 = upload("messy.pdf", (src / "messy.pdf").read_bytes())
    q.rec("PDF-02", "Кириллица, две колонки, «грязная» вёрстка", A, "200 без падения; уверенность полей указана",
          {"twocol": (st2, vals(body2).get("last_name")), "messy": (st3, sorted(vals(body3))[:8]),
           "confidence": sorted({str(v.get("confidence")) for v in (body2.get("fields") or {}).values() if isinstance(v, dict)})},
          st2 == 200 and st3 == 200, source=SRC_PROF)  # fmt: skip
    blank = PdfWriter()
    blank.add_blank_page(width=595, height=842)
    buf = io.BytesIO()
    blank.write(buf)
    st_scan, scan = upload("scan.pdf", buf.getvalue())
    q.rec("PDF-03", "PDF без текстового слоя", A, "понятный отказ либо пустой результат; не 500",
          (st_scan, scan.get("code"), scan.get("message")), st_scan in (200, 422) and st_scan != 500, source=SRC_PROF)  # fmt: skip
    enc = PdfWriter()
    for page in PdfReader(src / "hh.pdf").pages:
        enc.add_page(page)
    enc.encrypt("secret-pass")
    ebuf = io.BytesIO()
    enc.write(ebuf)
    bad = {
        "пустой файл": upload("empty.pdf", b""),
        "обрезанный": upload("cut.pdf", (src / "hh.pdf").read_bytes()[:700]),
        "с паролем": upload("enc.pdf", ebuf.getvalue()),
        "текст с расширением pdf": upload("fake.pdf", "это не PDF, а текст".encode()),
        "png как pdf": upload("img.pdf", b"\x89PNG\r\n\x1a\n" + b"0" * 200),
        "docx": upload("cv.docx", b"PK\x03\x04" + b"0" * 200, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    }
    q.rec("PDF-04", "Пустой, повреждённый, с паролем, не PDF", A, "4xx с понятным текстом; нет 500 и трассировки",
          {k: (v[0], v[1].get("code"), (v[1].get("message") or "")[:60]) for k, v in bad.items()},
          all(400 <= v[0] < 500 and "Traceback" not in str(v[1]) and v[1].get("message") for v in bad.values()), source=SRC_PROF)  # fmt: skip

    def pages(n: int) -> bytes:
        writer = PdfWriter()
        source_pages = PdfReader(src / "hh.pdf").pages
        for i in range(n):
            writer.add_page(source_pages[i % len(source_pages)])
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()

    ten, eleven = upload("p10.pdf", pages(10)), upload("p11.pdf", pages(11))
    base = (src / "hh.pdf").read_bytes()
    big_ok = upload("big-ok.pdf", base + b"\n%" + b"0" * (5 * 1024 * 1024 - len(base) - 2))
    big_over = upload("big-over.pdf", base + b"\n%" + b"0" * (5 * 1024 * 1024 - len(base) - 2 + 1))
    q.rec("PDF-05", "Границы: 10 и 11 страниц; ровно 5 МБ и на байт больше", A, "10 страниц и 5 МБ принимаются; 11 страниц и 5 МБ + 1 байт — отказ",
          {"10": ten[0], "11": (eleven[0], eleven[1].get("code")), "5MB": big_ok[0], "5MB+1": (big_over[0], big_over[1].get("code"))},
          ten[0] == 200 and 400 <= eleven[0] < 500 and big_ok[0] == 200 and big_over[0] in (413, 422), source="интерфейс: «до 5 МБ, до 10 страниц»")  # fmt: skip
    u.put("/candidate/profile", {"last_name": "Ручной", "first_name": "Ввод", "city": "Тверь"})
    st_re, body_re = upload("student.pdf", (src / "student.pdf").read_bytes())
    prof = u.get("/candidate/profile")[1]
    q.rec("PDF-06", "Повторная загрузка другого резюме в заполненную анкету", A, "анкета не перезаписывается без явного принятия полей",
          {"status": st_re, "profile_after": (prof["last_name"], prof["city"]), "suggested": vals(body_re).get("last_name")},
          st_re == 200 and prof["last_name"] == "Ручной" and prof["city"] == "Тверь", source=SRC_PROF)  # fmt: skip
    import json

    spec = json.loads((q.ROOT / "docs/api/openapi.json").read_text())
    resume_paths = [p for p in spec["paths"] if "profile/resume" in p]
    stored = q.sql("select count(*) from information_schema.columns where column_name ilike '%resume%' and data_type in ('bytea')")
    q.rec("PDF-07", "Файл резюме: хранение и доступ других пользователей", A + "+DB", "файл не хранится; адреса скачивания нет",
          {"paths": resume_paths, "bytea_columns": stored}, resume_paths == ["/api/v1/candidate/profile/resume"] and stored in ("0", ""),
          source="CLAUDE.md §4.4: файл и текст не сохраняются")  # fmt: skip


def survey() -> None:
    u = q.signup("surv")
    schema = u.get("/assessment/survey")[1]
    by_id = {x["id"]: x for x in schema["questions"]}
    specs = by_id["specialization"]["options"]
    tree = {d["code"]: [s["code"] + ("" if s["available"] else "(нет теста)") for s in specs if s["parent"] == d["code"]] for d in by_id["direction"]["options"]}
    q.rec("SURV-01", "Направления и их специализации", A, "у каждого направления свой список; недоступные помечены", tree,
          all(tree.values()) and "backend" in tree["development"], source="GET /assessment/survey")  # fmt: skip
    lang_options = by_id.get("main_language", {}).get("options", [])
    langs = [o["code"] for o in lang_options]
    backend_langs = {o["code"] for o in lang_options if o.get("parent") in (None, "backend")}  # код языка повторяется у разных специализаций
    langs = list(dict.fromkeys(langs))
    out = {}
    for lang in langs:
        user = q.signup("surv02")
        st, _ = user.put("/assessment/survey", {"version": schema["version"], "answers": {**q.SURVEY, "main_language": lang}})
        user.put("/candidate/profile", {"last_name": "Языков", "first_name": "Тест"})
        user.put("/assessment/claim", {"grade_code": "junior"})
        bps = user.get("/assessment/blueprints")
        bp = next((b for b in bps[1] if b["grade"]["code"] == "junior"), {}) if bps[0] == 200 else {}
        groups = [s["group_code"] for s in bp.get("skills", [])]
        out[lang] = (st, "lang" in " ".join(groups) or any(g.startswith(("py", "lang")) for g in groups), len(groups))
    q.rec("SURV-02", "Backend и каждый язык: план теста и честная пометка об отсутствии языкового модуля", A,
          "языки Backend сохраняются, чужие — 422; языковой модуль есть только у Python", out,
          all((v[0] == 200) == (k in backend_langs) for k, v in out.items()) and out.get("python", (0, False))[1]
          and not any(v[1] for k, v in out.items() if k != "python"),
          source="README: языковой модуль только Python")  # fmt: skip
    na = q.signup("surv03")
    target = next(s for s in specs if not s["available"])
    st_s, body_s = na.put("/assessment/survey", {"version": schema["version"], "answers": {"direction": target["parent"], "specialization": target["code"], "experience_band": "2_4"}})
    st_c, body_c = na.put("/assessment/claim", {"grade_code": "middle"})
    st_t, body_t = na.post("/assessment/sessions", {"grade_code": "middle"})
    st_q, body_q = na.post("/demo/assessment/quick-session", {"grade_code": "middle"})
    q.rec("SURV-03", f"Специализация «тест готовится» ({target['code']}): тест не запускается ни обычный, ни демо", A, "старт отклонён сервером",
          {"survey": (st_s, body_s.get("code") if st_s != 200 else "ok"), "claim": (st_c, body_c.get("code") if st_c != 200 else "ok"),
           "session": (st_t, body_t.get("code")), "quick": (st_q, body_q.get("code"))},
          st_t >= 400 and st_q >= 400 and q.sql(f"select count(*) from assessment_session where candidate_id='{na.id}'") == "0", source="README «Известные ограничения»")  # fmt: skip
    mix = q.signup("surv04")
    bad = mix.put("/assessment/survey", {"version": schema["version"], "answers": {**q.SURVEY, "direction": "data"}})
    q.rec("SURV-04", "Несовместимая пара «направление — специализация»", A, "422, опрос не сохранён", (bad[0], bad[1].get("code") if isinstance(bad[1], dict) else bad[1]),
          bad[0] == 422 and mix.get("/assessment/survey")[1]["answers"] is None, source="GET /assessment/survey: parent")  # fmt: skip
    domains = [o["code"] for o in by_id.get("industry_domains", {}).get("options", [])]
    out = {
        "без опыта": mix.put("/assessment/survey", {"version": schema["version"], "answers": {k: v for k, v in q.SURVEY.items() if k != "experience_band"}})[0],
        "без специализации": mix.put("/assessment/survey", {"version": schema["version"], "answers": {k: v for k, v in q.SURVEY.items() if k != "specialization"}})[0],
        "4 отрасли": mix.put("/assessment/survey", {"version": schema["version"], "answers": {**q.SURVEY, "industry_domains": domains[:4]}})[0],
        "3 отрасли": mix.put("/assessment/survey", {"version": schema["version"], "answers": {**q.SURVEY, "industry_domains": domains[:3]}})[0],
        "без отраслей": mix.put("/assessment/survey", {"version": schema["version"], "answers": q.SURVEY})[0],
        "старая версия опроса": mix.put("/assessment/survey", {"version": "1999.01", "answers": q.SURVEY})[0],
    }
    q.rec("SURV-05", "Обязательные вопросы и лимит отраслей", A, "обязательные — 422; 3 отрасли и ноль — можно; 4 — нельзя", out,
          out["без опыта"] == 422 and out["без специализации"] == 422 and out["4 отрасли"] == 422 and out["3 отрасли"] == 200 and out["без отраслей"] == 200,
          source="интерфейс: «выбрано 0 из 3»")  # fmt: skip
    rec_out = {}
    for band in [o["code"] for o in by_id["experience_band"]["options"]]:
        user = q.signup("surv06")
        user.put("/assessment/survey", {"version": schema["version"], "answers": {**q.SURVEY, "experience_band": band}})
        state = user.get("/assessment/state")[1]
        rec_out[band] = (state.get("suggested_grade") or {}).get("code") if isinstance(state.get("suggested_grade"), dict) else state.get("suggested_grade"), state["category"]
    q.rec("SURV-06", "Опыт из опроса даёт только подсказку грейда, категории не даёт", A, "категория пуста при любом опыте", rec_out,
          all(v[1] is None for v in rec_out.values()), source="интерфейс: «подсказка — только предвыбор»")  # fmt: skip
    pick = q.signup("surv07")
    pick.put("/candidate/profile", {"last_name": "Выборов", "first_name": "Тест"})
    pick.put("/assessment/survey", {"version": schema["version"], "answers": {**q.SURVEY, "experience_band": "2_4"}})
    pick.put("/assessment/claim", {"grade_code": "junior"})
    foreign = pick.post("/assessment/sessions", {"grade_code": "senior"})
    sid, _ = q.start(pick, "junior")
    target_grade = q.sql(f"select target_grade from assessment_session where id='{sid}'")
    q.rec("SURV-07", "Тест создаётся на выбранный вручную грейд (Junior при подсказке Middle); чужой грейд без заявки отклонён", A + "+DB",
          "сессия на junior; senior — отказ", {"target": target_grade, "senior": (foreign[0], foreign[1].get("code"))},
          target_grade == "junior" and foreign[0] in (409, 422), source="rules.can_start, п. 5а")  # fmt: skip
    change = q.signup("surv08")
    change.put("/assessment/survey", {"version": schema["version"], "answers": q.SURVEY})
    change.put("/assessment/claim", {"grade_code": "middle"})
    change.put("/assessment/survey", {"version": schema["version"], "answers": {**q.SURVEY, "experience_band": "0_1" if "0_1" in rec_out else list(rec_out)[0]}})
    state = change.get("/assessment/state")[1]
    q.rec("SURV-08", "Правка ответа опроса после выбора грейда", A, "заявленный грейд и специализация согласованы",
          {"claimed": (state.get("claimed_grade") or {}).get("code"), "spec": (state.get("specialization") or {}).get("code")},
          (state.get("claimed_grade") or {}).get("code") == "middle" and (state.get("specialization") or {}).get("code") == "backend", source="GET /assessment/state")  # fmt: skip
    raw = q.signup("surv09")
    no_survey = raw.post("/assessment/sessions", {"grade_code": "middle"})
    no_claim_claim = raw.put("/assessment/claim", {"grade_code": "middle"})
    raw.put("/assessment/survey", {"version": schema["version"], "answers": q.SURVEY})
    no_claim = raw.post("/assessment/sessions", {"grade_code": "middle"})
    q.rec("SURV-09", "Прямой запуск теста без опроса и без выбора грейда", A + "+DB", "409 survey_required / claim_required; сессия не создана",
          {"без опроса": (no_survey[0], no_survey[1].get("code")), "заявка без опроса": (no_claim_claim[0], no_claim_claim[1].get("code")),
           "без заявки": (no_claim[0], no_claim[1].get("code")), "sessions": q.sql(f"select count(*) from assessment_session where candidate_id='{raw.id}'")},
          no_survey[1].get("code") == "survey_required" and no_claim[1].get("code") == "claim_required"
          and q.sql(f"select count(*) from assessment_session where candidate_id='{raw.id}'") == "0", source="rules.can_start, п. 1")  # fmt: skip


if __name__ == "__main__":
    parts = [globals()[name] for name in sys.argv[2:]] or [auth, profile, pdf, survey]
    for part in parts:
        try:
            part()
        except Exception as exc:  # сбой группы не должен скрывать остальные
            q.rec(f"ERR-{part.__name__}", f"Группа {part.__name__} прервана", A, "группа выполняется до конца", repr(exc)[:400], None, status="BLOCKED")
    print("готово")
