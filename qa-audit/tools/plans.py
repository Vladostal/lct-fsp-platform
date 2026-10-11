"""Планы ответов на все задания сессии по порядку: `plans.py <session_id> [right|wrong]` → JSON-массив для интерфейса."""
import json, sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import qalib as q

sid, mode = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "right")
raw = q.sql(
    "select json_agg(json_build_object('id', i.id, 'pos', i.position, 'status', i.status, 'kind', v.payload->>'kind', "
    "'answer', v.answer, 'options', v.payload->'options', 'family', i.family_id) order by i.position) "
    f"from assessment_session_item i join assessment_variant v on v.id=i.variant_id where i.session_id='{sid}'")
out = []
for row in json.loads(raw):
    if row["status"] not in ("shown", "pending"):
        continue
    body = q.right(row) if mode == "right" else q.wrong(row)
    plan = {"n": row["pos"] + 1, "kind": row["kind"], "family": row["family"]}
    if "value" in body:
        plan["value"] = str(body["value"])
    elif "line" in body:
        plan["line"] = body["line"]
    else:
        ids = [body["option_id"]] if "option_id" in body else body["option_ids"]
        plan["texts"] = [next(o.get("text", "") for o in row["options"] if o["id"] == i) for i in ids]
    out.append(plan)
print(json.dumps(out, ensure_ascii=False))
