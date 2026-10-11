"""Текущее задание сессии и его ключ — чтобы вести тест в интерфейсе по заданному плану."""
import json, sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import qalib as q

sid = sys.argv[1]
raw = q.sql(
    "select json_build_object('id', i.id, 'pos', i.position, 'status', i.status, 'kind', v.payload->>'kind', 'answer', v.answer, "
    "'options', v.payload->'options', 'family', i.family_id) from assessment_session_item i join assessment_variant v on v.id=i.variant_id "
    f"where i.session_id='{sid}' and i.status='shown'")
if not raw:
    print("нет показанного задания:", q.sql(f"select status, outcome, items_answered from assessment_session where id='{sid}'"))
    raise SystemExit
row = json.loads(raw)
key = row["answer"]
opts = {o["id"]: o.get("text", "")[:70] for o in (row["options"] or [])}
print(f"#{row['pos']} {row['kind']} {row['family']} | ключ:", {k: v for k, v in key.items() if k in ('value', 'option_id', 'option_ids', 'lines')})
if opts:
    ids = [key.get("option_id")] if "option_id" in key else key.get("option_ids", [])
    print("  верные варианты:", [(i, list(opts).index(i), opts[i]) for i in ids], "| всего вариантов:", len(opts))

plan = {"n": row["pos"] + 1, "kind": row["kind"]}
if "value" in key:
    plan["value"] = str(key["value"])
elif "lines" in key:
    plan["line"] = key["lines"][0]
else:
    ids = [key["option_id"]] if "option_id" in key else key["option_ids"]
    plan["texts"] = [next(o.get("text", "") for o in row["options"] if o["id"] == i) for i in ids]
print("PLAN", json.dumps(plan, ensure_ascii=False))
