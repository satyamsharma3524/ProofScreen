import csv, sqlite3, json, collections, statistics
from classify import classify, is_tooling

DB = sqlite3.connect("study.sqlite3"); DB.row_factory = sqlite3.Row
rows = list(csv.DictReader(open("real_question_dataset.csv")))
final = [r for r in rows if r["is_final"] == "True"]
meta = {(r["interview_id"], r["generated_question"]): r for r in final}

q = DB.execute("""
 select q.id qid, q.session_id sid, q.text, q.probe_level, q.source, q.is_repair,
        r.id rid, r.raw_text, r.answer_score, r.signals_found
 from questions q left join responses r on r.question_id = q.id
""").fetchall()

ev = collections.defaultdict(dict)
for e in DB.execute("select response_id, dimension, score from evidence"):
    ev[e["response_id"]][e["dimension"]] = e["score"]

recs = []
unmatched = 0
for row in q:
    m = meta.get((row["sid"], row["text"]))
    if m is None:
        unmatched += 1; continue
    cat, labels = classify(row["text"])
    recs.append(dict(
        qid=row["qid"], sid=row["sid"], text=row["text"], cat=cat,
        probe=row["probe_level"], source=m["source"] or row["source"],
        tier=m["tier"], fidelity=m["answer_fidelity"], family=m["family"],
        validation=m["validation_result"], attempts=int(m["attempts"] or 1),
        answer=row["raw_text"] or "", ascore=row["answer_score"],
        sig=row["signals_found"], dims=ev.get(row["rid"], {}),
        tooling=is_tooling(row["text"]),
    ))
print(f"joined {len(recs)} questions, unmatched {unmatched}")
json.dump(recs, open("recs.json","w"))
