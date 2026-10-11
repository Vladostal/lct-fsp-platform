"""Собрать `cases.md` и `test-data.md` из журналов `evidence/results.jsonl` и `evidence/entities.jsonl`.

По каждому ID берётся последняя запись: повторная запись сценария заменяет прежнюю (причина замены — в поле note).
"""

from __future__ import annotations

import collections
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORDER = ["E2E", "AUTH", "PROF", "PDF", "SURV", "TEST", "TIME", "BANK", "DEMO", "PUB", "FIND", "EMP", "NEED", "MATCH", "INV", "RESP", "COUNT", "PRIV", "FSP", "UI", "CONTRACT", "REG", "OBS", "GAP"]
STATUSES = ["PASS", "FAIL", "BLOCKED", "NOT RUN", "N/A", "SPEC GAP"]


def load() -> dict[str, dict]:
    last: dict[str, dict] = {}
    for line in (ROOT / "evidence" / "results.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            last[row["id"]] = row
    return last


def key(case_id: str) -> tuple[int, list]:
    prefix = re.match(r"[A-Z0-9]+?(?=-|$)", case_id.replace("E2E", "EEE")).group(0).replace("EEE", "E2E") if "-" in case_id else case_id
    group = ORDER.index(prefix) if prefix in ORDER else len(ORDER)
    nums = [int(x) if x.isdigit() else x for x in re.findall(r"\d+|[a-zа-я]+", case_id.split("-", 1)[-1])]
    return group, [str(n).zfill(4) if isinstance(n, int) else n for n in nums]


def cell(text: str, limit: int) -> str:
    text = " ".join(str(text).split()).replace("|", "¦")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def main() -> None:
    cases = load()
    counts = collections.Counter(row["status"] for row in cases.values())
    ui = [c for c, r in cases.items() if r["level"].startswith("UI")]
    lines = [
        "# Журнал сценариев",
        "",
        "Собрано из `evidence/results.jsonl` (`tools/build_report.py`). У каждого сценария — последняя запись; полные фактические значения — в журнале.",
        "",
        "| Статус | Сценариев |",
        "|---|---|",
        *[f"| {s} | {counts.get(s, 0)} |" for s in STATUSES],
        f"| **Всего** | **{len(cases)}** |",
        "",
        f"Через интерфейс (UI) выполнено сценариев: {len(ui)}. Остальные — на уровне, указанном в столбце «Уровень».",
        "",
        "| ID | Сценарий | Уровень | Ожидалось | Получено | Статус | Источник ожидания | Примечание |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for case_id in sorted(cases, key=key):
        r = cases[case_id]
        lines.append(
            f"| {case_id} | {cell(r['title'], 110)} | {cell(r['level'], 40)} | {cell(r['expected'], 150)} | {cell(r['actual'], 260)} "
            f"| **{r['status']}** | {cell(r.get('source', ''), 90)} | {cell(r.get('note', ''), 200)} |"
        )
    (ROOT / "cases.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    ents = [json.loads(x) for x in (ROOT / "evidence" / "entities.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    by_kind = collections.Counter((e["kind"], e.get("created_via", "—")) for e in ents)
    named = [e for e in ents if e.get("label") in ("C01", "E01") or e.get("created_via") == "UI"]
    out = [
        "# Проверочные данные",
        "",
        "Все аккаунты синтетические, адреса `qa.*@example.com`. Пароли и токены в отчёт не входят: у аккаунтов, созданных скриптами, пароль случайный на запуск.",
        "Стенд после проверки пересоздан, поэтому перечисленных аккаунтов в базе больше нет; полный реестр — `evidence/entities.jsonl`.",
        "",
        "## Сколько создано",
        "",
        "| Вид | Как создан | Количество |",
        "|---|---|---|",
        *[f"| {kind} | {via} | {n} |" for (kind, via), n in sorted(by_kind.items())],
        "",
        "`UI` — через формы интерфейса; `API` — запросом регистрации и ссылкой из письма; `FIXTURE` — сервисом identity в контейнере api (лимит регистраций 50 в час с адреса).",
        "",
        "## Аккаунты главного пути (созданы через интерфейс)",
        "",
        "| Обозначение | Почта | ID | Код | Связанные сущности |",
        "|---|---|---|---|---|",
    ]
    for e in named:
        extra = ", ".join(f"{k}: `{e[k]}`" for k in ("session", "need", "invitation") if e.get(k))
        out.append(f"| {e.get('label')} | {e.get('email')} | `{e.get('id')}` | {e.get('public_code', '—')} | {extra or '—'} |")
    out += ["", "## Соответствие обозначениям ТЗ", "",
            "| ТЗ | Чем закрыто в прогоне |", "|---|---|",
            "| C01, E01 | аккаунты главного пути выше (интерфейс) |",
            "| C02 | кандидаты `qa.demo01.*`, `qa.demo03.*` (быстрый демо-тест) и демо-путь в интерфейсе |",
            "| C03–C07 | кандидаты `qa.test01.*` … `qa.test10.*`, `qa.test11*.*` (матрица прохождения, пограничные блоки) |",
            "| C08 | `qa.clk_s0.*`, `qa.clk_s3.*` (истечение времени), `qa.testproto.*` (восстановление попытки) |",
            "| C09 | `qa.m_hidden.*`, `qa.pub.*` (категория без публикации) |",
            "| C10 | `qa.inv_lo.*`, `qa.clk_hi.*`, `qa.cnt_hi.*` (высокий скрытый минимум) |",
            "| C11 | `qa.inv_off.*`, `qa.m_office.*` (несовместимый формат) |",
            "| C12 | `qa.priv_o.*`, `qa.resp_b.*` (доступ к чужому) |",
            "| E02 | `qa.e02.*`, `qa.resp_e2.*`, `qa.priv_e2.*` |",
            "| Dxx | девять именованных демо-аккаунтов стенда |"]
    (ROOT / "test-data.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("cases:", len(cases), dict(counts), "| entities:", len(ents))


if __name__ == "__main__":
    main()
