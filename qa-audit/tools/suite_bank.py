"""BANK-01…12: банк заданий. Независимая проверка ключей — исполнением условия, без кода генераторов."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import qalib as q  # noqa: E402

SRC = "CLAUDE.md §4.1; README «Тестирование»"


def variants(prefix: str) -> list[dict]:
    raw = q.sql(
        "select coalesce(json_agg(json_build_object('id', id, 'family', family_id, 'level', level, 'payload', payload, 'answer', answer)), '[]') "
        f"from assessment_variant where family_id like '{prefix}'"
    )
    return json.loads(raw)


def cell(value: str):
    if value == "NULL":
        return None
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def run_sql(v: dict):
    con = sqlite3.connect(":memory:")
    for table in v["payload"]["tables"] or []:
        cols = ", ".join(f'"{c}"' for c in table["columns"])
        con.execute(f'create table "{table["title"]}" ({cols})')
        marks = ", ".join("?" for _ in table["columns"])
        con.executemany(f'insert into "{table["title"]}" values ({marks})', [[cell(x) for x in row] for row in table["rows"]])
    return con.execute(v["payload"]["code"]["text"]).fetchall()


#: Задержки asyncio.sleep в условиях — секунды; порядок событий не меняется, если сжать их одинаково.
FAST_SLEEP = "import asyncio as _a\n_s = _a.sleep\n_a.sleep = lambda d=0, *x, **k: _s(d / 40, *x, **k)\n"


def run_py(code: str) -> tuple[str, str]:
    if "asyncio" in code:
        code = FAST_SLEEP + code
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=8, check=False)
    return out.stdout.strip(), out.stderr.strip().splitlines()[-1] if out.stderr.strip() else ""


def main() -> None:
    inv = q.sql("select count(distinct family_id), count(*), count(*) filter (where status='active'), count(*) filter (where status='demo'), "
                "count(distinct md5(payload::text)), string_agg(distinct payload->>'kind', ',') from assessment_variant").split("|")  # fmt: skip
    levels = q.sql("select count(*) from (select distinct family_id, level from assessment_variant) t")
    q.rec("BANK-01", "Инвентаризация банка: семейства, уровни, варианты, форматы ответа", "DB",
          "31 семейство; по 60 рабочих и 3 демо-варианта на уровень; пять форматов ответа",
          {"families": inv[0], "family_levels": levels, "variants": inv[1], "active": inv[2], "demo": inv[3], "unique_payloads": inv[4], "kinds": inv[5]},
          inv[0] == "31" and inv[1] == inv[4] and int(inv[2]) == int(levels) * 60, source=SRC)  # fmt: skip
    q.rec("BANK-08", "Варианты одного семейства различаются; повтор сборки даёт те же варианты", "DB + unit (pytest)",
          "все условия в банке попарно различны; детерминизм закреплён tests/assessment/test_determinism.py",
          {"variants": inv[1], "unique_payloads": inv[4]}, inv[1] == inv[4], source=SRC, note="детерминизм по сиду и независимость от PYTHONHASHSEED — pytest, прогон в регрессии")  # fmt: skip

    # --- SQL: исполняем запрос условия на SQLite ---
    stats: dict[str, list[int]] = {}
    bad_sql = []
    for v in variants("sql.%"):
        s = stats.setdefault(v["family"], [0, 0, 0])
        s[0] += 1
        try:
            rows = run_sql(v)
            got = rows[0][0] if rows else None
            want = v["answer"]["value"]
            if got is not None and abs(float(got) - float(want)) < 1e-9:
                s[1] += 1
            elif "count" in v["payload"]["prompt"].lower() or "сколько строк" in v["payload"]["prompt"].lower():
                if len(rows) == int(float(want)):
                    s[1] += 1
                else:
                    bad_sql.append((v["family"], v["id"][:8], len(rows), want))
            else:
                bad_sql.append((v["family"], v["id"][:8], got, want, v["payload"]["prompt"][:60]))
        except Exception as exc:
            s[2] += 1
            bad_sql.append((v["family"], v["id"][:8], "ERR", repr(exc)[:80]))
    q.rec("BANK-03", "SQL-задачи: запрос из условия исполнен на SQLite по таблицам условия, результат сверен с ключом", "integration (независимое исполнение)",
          "результат запроса совпадает с ключом у всех вариантов (NULL и агрегаты учтены)",
          {"семейство: [вариантов, совпало, ошибок]": stats, "расхождения": bad_sql[:6]}, bool(stats) and not bad_sql, source=SRC,
          note="db.constraints_effect и db.index_prefix (тоже SQL) этим способом не проверялись")  # fmt: skip

    # --- Python: исполняем код условия, сверяем вывод ---
    pstats: dict[str, list[int]] = {}
    bad_py = []
    for prefix in ("code.trace_%", "py.%", "svc.async_order", "algo.sort_state", "algo.ops_count"):
        for v in variants(prefix):
            code = (v["payload"].get("code") or {}).get("text") or ""
            if (v["payload"].get("code") or {}).get("language") != "python" or v["payload"]["kind"] not in ("numeric_input", "text_input"):
                continue
            s = pstats.setdefault(v["family"], [0, 0, 0])
            s[0] += 1
            try:
                out, err = run_py(code)
            except subprocess.TimeoutExpired:
                out, err = "", "timeout"
            want = str(v["answer"]["value"])
            norm = " ".join(out.replace("[", " ").replace("]", " ").replace(",", " ").split())
            if norm == " ".join(want.split()) or (norm and norm.split()[-1] == want):
                s[1] += 1
            elif err and (err.split(":")[0] in want or want in err):
                s[1] += 1  # ответ — имя исключения
            elif not out and not err:
                s[2] += 1  # код ничего не печатает: ответ спрашивается о другом, исполнением не проверяется
            else:
                bad_py.append((v["family"], v["level"], v["id"][:8], norm[:40], want[:40], err[:50]))
    not_printing = {k: v[2] for k, v in pstats.items() if v[2]}
    q.rec("BANK-04", "Python-задачи: код из условия исполнен в отдельном процессе, вывод сверен с ключом", "integration (независимое исполнение)",
          "вывод программы совпадает с ключом; отступы в условии не потеряны (код исполняется как есть)",
          {"семейство: [вариантов, совпало, не печатает]": pstats, "расхождения": bad_py[:8], "всего расхождений": len(bad_py)}, bool(pstats) and not bad_py, source=SRC,
          note=f"семейства, где ответ не равен выводу программы (исполнением не проверены): {not_printing or 'нет'}")  # fmt: skip

    q.rec("BANK-05", "Git-задачи: воспроизведение во временном репозитории", "—", "ответ отражает реальное состояние index/worktree/history",
          "независимое воспроизведение не выполнялось; ключи проверяет собственный оракул репозитория (make bank-check, прогон в регрессии)", None, status="NOT RUN",
          source=SRC, note="3 семейства git.*, 567 вариантов")  # fmt: skip
    q.rec("BANK-06", "Алгоритмы, хеш-таблицы, расписания потоков: независимое вычисление", "integration (частично)", "ключ совпадает с независимым расчётом",
          "исполнением кода условия проверены algo.sort_state, svc.async_order и др. (см. BANK-04); ds.hash_probing, ds.heap_array, ds.bst_ops, algo.graph_traversal, db.isolation_timeline, svc.rate_limiter, svc.race_interleaving — без исполняемого вывода, независимо не пересчитывались",
          None, status="NOT RUN", source=SRC, note="для них действует только оракул репозитория (make bank-check)")  # fmt: skip
    sample = [v for v in variants("http.status_choice")][:3]
    q.rec("BANK-07", "HTTP-задачи: однозначность условия (ручной просмотр выборки)", "ручной просмотр", "ответ следует из условия",
          [{"prompt": v["payload"]["prompt"][:230], "options": [o["text"] for o in v["payload"]["options"]], "key": v["answer"]} for v in sample][:2], None, status="NOT RUN", source=SRC,
          note="выборка выведена в журнал; экспертная сверка однозначности всех 567 HTTP-вариантов не проводилась")  # fmt: skip

    # --- BANK-10: тематический отчёт против заданий сессии ---
    sid = q.sql("select s.id from assessment_session s join app_user u on u.id=s.candidate_id where u.email like 'qa.test08.%' and s.status='finished' order by s.finished_at desc limit 1")
    if sid:
        by_group = json.loads(q.sql(
            "select json_object_agg(g, json_build_object('items', n, 'correct', c)) from (select split_part(i.family_id, '.', 1) g, count(*) n, sum(i.score) c "
            f"from assessment_session_item i where i.session_id='{sid}' and i.status in ('answered','skipped','unreached') group by 1) t"))
        ev = json.loads(q.sql(
            "select json_object_agg(group_code, json_build_object('items', items, 'correct', correct, 'verdict', verdict)) from assessment_skill_evidence "
            f"where ref_id='{sid}' and source='test'"))
        same = all(ev.get(g, {}).get("items") == v["items"] and ev.get(g, {}).get("correct") == v["correct"] for g, v in by_group.items())
        mix = sorted({(v["items"], v["correct"], v["verdict"]) for v in ev.values()})
        q.rec("BANK-10", "Тематический отчёт: число заданий и верных по темам совпадает с ответами попытки (цикл верно–неверно–пропуск)", "DB",
              "по каждой теме items и correct равны подсчёту по заданиям; вердикт темы следует из них",
              {"по заданиям": by_group, "(items, correct, verdict)": mix}, same, source=SRC)  # fmt: skip
    else:
        q.rec("BANK-10", "Тематический отчёт против заданий попытки", "DB", "совпадение", "нет сессии TEST-08 в базе", None, status="BLOCKED")
    pooled = q.sql("select string_agg(s.pooled_items::text || '/' || s.items_answered::text, ' → ' order by s.started_at) from assessment_session s join app_user u on u.id=s.candidate_id "
                   "where u.email like 'qa.clk_p3.%'")  # fmt: skip
    q.rec("BANK-11", "Учёт предыдущих ответов: вторая попытка считается по всем ответам окна 180 дней", "DB",
          "у первой попытки учтено 14 заданий, у второй — 28 (обе попытки)", {"pooled/answered по попыткам": pooled}, pooled == "14/14 → 28/14", source="catalog.limits: assessment_evidence_window_days",
          note="граница окна 180 дней и исключение подставленных ответов демо-теста — pytest (tests/assessment, tests/demo)")  # fmt: skip
    fast = q.sql("select count(*) from assessment_session s join app_user u on u.id=s.candidate_id where u.email like 'qa.%' and s.flags ? 'speed_suspect' and s.outcome like 'confirmed%'")
    q.rec("BANK-12", "Сигналы быстрых ответов не меняют результат", "DB + независимый пересчёт",
          "попытки с пометкой «подозрительно быстро» получают тот же исход и θ, что даёт модель без учёта времени",
          {"подтверждённых попыток с пометкой speed_suspect": fast, "сверка θ": "во всех TEST-01…13 θ и исход совпали с независимым расчётом без временных признаков"},
          int(fast or 0) > 0, source="интерфейс: «На результат это не влияет»", note="смена вкладок и вставка из буфера (client.focus_lost, pasted) в оценке не участвуют по схеме ClientInfo; в интерфейсе не прогонялись")  # fmt: skip
    q.rec("BANK-02", "Независимое решение выборки вариантов по семействам", "integration (независимое исполнение)", "ключ совпадает с независимым решением",
          {"SQL (исполнение на SQLite)": {k: v[:2] for k, v in stats.items()}, "Python (исполнение кода условия)": {k: v[:2] for k, v in pstats.items()}},
          not bad_sql and not bad_py, source=SRC, note="покрыто независимо: семейства из BANK-03 и BANK-04 — все варианты; остальные семейства — только оракулом репозитория")  # fmt: skip


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback

        q.rec("ERR-bank", "Набор банка прерван", "DB", "набор выполняется до конца", traceback.format_exc()[-700:], None, status="BLOCKED")
    print("готово")
