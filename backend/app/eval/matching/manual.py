"""Независимый слой: материалы для ручной разметки пар и приём меток (приложение B, §9.6; план работ, H1).

`export-pairs` выгружает пары «потребность — кандидат» без позиции, полосы совпадения, доводов и названия
системы, в перемешанном порядке. `import-labels` принимает метки одного или двух разметчиков (шкала 0–2),
замораживает набор хэшами и считает взвешенную κ и P@10 по согласованной оценке.
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
from pathlib import Path
from typing import Any

from app.eval.matching import metrics as M
from app.eval.matching import systems as S
from app.eval.matching.world import MAIN_REGIME, REGIMES, build_world
from app.shared.enums import EvidenceKind

PAIRS = "pairs.csv"
KEY = "pairs_systems.json"
NEEDS_LIMIT = 12


def export_pairs(out: Path, *, seed: int) -> int:
    """Топ-10 трёх систем (наша, B1, B2) на одном сиде, объединение без дублей. Возвращает число пар."""
    world = build_world(seed, REGIMES[MAIN_REGIME])
    rows: list[dict[str, str]] = []
    systems: dict[str, dict[str, list[str]]] = {}
    for case in S.make_cases(world)[:NEEDS_LIMIT]:
        ours = S.ranked(case)
        tops = {
            "ours": S.ids(ours)[:10],
            "declared": S.declared_order(case, ours)[:10],
            "tfidf": S.tfidf_order(case, ours)[:10],
        }
        query = case.need.query
        need_key = str(case.need.need_id)
        for name, top in tops.items():
            systems.setdefault(need_key, {})[name] = [f"{need_key}:{cid}" for cid in top]
        for cid in dict.fromkeys(cid for top in tops.values() for cid in top):
            features = case.by_id[cid].features
            confirmed = sorted(
                f"{item.skill_code} ({item.kind.value})"
                for item in features.evidence.values()
                if item.kind != EvidenceKind.DECLARED
            )
            declared = sorted(
                item.skill_code for item in features.evidence.values() if item.kind == EvidenceKind.DECLARED
            )
            rows.append(
                {
                    "pair_id": f"{need_key}:{cid}",
                    "need": f"{query.specialization_code}:{query.grade_code}",
                    "must_skills": ", ".join(query.must_skills),
                    "nice_skills": ", ".join(query.nice_skills),
                    "work_formats": ", ".join(item.value for item in query.work_formats),
                    "candidate_category": f"{features.specialization_code}:{features.grade_code}",
                    "verdict": features.verdict.value,
                    "confirmed_skills": ", ".join(confirmed),
                    "declared_skills": ", ".join(declared),
                    "fsp": features.fsp_band,
                    "candidate_formats": ", ".join(sorted(features.work_formats)),
                    "freshness_days": str(features.age_days),
                }
            )
    random.Random(f"pairs:{seed}").shuffle(rows)
    out.mkdir(parents=True, exist_ok=True)
    with (out / PAIRS).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ["pair_id"])
        writer.writeheader()
        writer.writerows(rows)
    with (out / "labels_template.csv").open("w", encoding="utf-8", newline="") as stream:
        template = csv.writer(stream)
        template.writerow(["pair_id", "label"])
        template.writerows([row["pair_id"], ""] for row in rows)
    (out / KEY).write_text(json.dumps({"seed": seed, "systems": systems}, indent=1), encoding="utf-8")
    return len(rows)


def _labels(path: Path) -> dict[str, int]:
    with path.open(encoding="utf-8", newline="") as stream:
        rows = {row["pair_id"]: row["label"].strip() for row in csv.DictReader(stream)}
    bad = [pair for pair, label in rows.items() if label not in {"0", "1", "2"}]
    if bad:
        raise SystemExit(f"{path.name}: метка должна быть 0, 1 или 2; не размечено или ошибка в {len(bad)} парах")
    return {pair: int(label) for pair, label in rows.items()}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def import_labels(out: Path, first: Path, second: Path | None) -> dict[str, Any]:
    """Принять метки, заморозить набор (`FROZEN.sha256`) и записать `manual.json` для отчёта."""
    key = json.loads((out / KEY).read_text(encoding="utf-8"))
    labels_a = _labels(first)
    labels_b = _labels(second) if second else None
    pairs = sorted(labels_a)
    if labels_b is not None and sorted(labels_b) != pairs:
        raise SystemExit("наборы пар у разметчиков не совпадают")
    kappa = None
    if labels_b is not None:
        kappa = M.weighted_kappa([labels_a[pair] for pair in pairs], [labels_b[pair] for pair in pairs])
    consensus = {
        pair: (labels_a[pair] + labels_b[pair]) / 2 if labels_b is not None else float(labels_a[pair]) for pair in pairs
    }
    p10: dict[str, float] = {}
    for name in ("ours", "declared", "tfidf"):
        values = [
            sum(1 for pair in tops[name] if consensus.get(pair, 0) >= 1.5) / 10 for tops in key["systems"].values()
        ]
        p10[name] = round(M.mean(values), 4)
    frozen = {PAIRS: _digest(out / PAIRS)}
    for label, path in (("labels_a.csv", first), ("labels_b.csv", second)):
        if path is not None:
            target = out / label
            if path.resolve() != target.resolve():
                target.write_bytes(path.read_bytes())
            frozen[label] = _digest(target)
    (out / "FROZEN.sha256").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in frozen.items()), encoding="utf-8"
    )
    result = {
        "pairs": len(pairs),
        "raters": 2 if labels_b is not None else 1,
        "kappa": round(kappa, 4) if kappa is not None else None,
        "reliable": kappa is not None and kappa >= 0.4,
        "p10": p10,
        "frozen": frozen,
    }
    (out / "manual.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
