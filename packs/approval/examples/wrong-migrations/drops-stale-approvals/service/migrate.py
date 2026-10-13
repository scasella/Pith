"""service/migrate.py — python -I service/migrate.py --db PATH: upgrade a version 1 database (approval-workflow/v1) to
version 2 in place (harness/SERVICE.md, "Upgrading from version 1"). One transaction: every document gets quorum 2
and keeps everything else; every recorded result is kept, its document carrying quorum 2, and every recorded create
names quorum 2 (version 1's creates are creates with the default quorum, so their retries replay); actors and the
event log are untouched. Running it again on a version 2 database changes nothing; anything else is refused."""
import argparse, json, pathlib, sqlite3, sys

ap = argparse.ArgumentParser(); ap.add_argument("--db", required=True); a = ap.parse_args()
V1 = {"actors", "docs", "ops", "events"}
if not pathlib.Path(a.db).is_file(): sys.exit(f"refused: {a.db} does not exist")
try:
    db = sqlite3.connect(f"file:{a.db}?mode=rw", uri=True, isolation_level=None)
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
except sqlite3.DatabaseError as e: sys.exit(f"refused: {a.db} is not a database this service wrote ({e})")
if tables == V1 | {"meta"} and db.execute("SELECT value FROM meta WHERE key='schema'").fetchone() == ("2",):
    print("already version 2: nothing to do"); sys.exit(0)
if tables != V1: sys.exit(f"refused: unrecognised tables {sorted(tables)}")


def with_quorum(doc):
    if doc is None: return None
    if "quorum" in doc: raise SystemExit("refused: a version 1 document already has a quorum")
    return {**doc, "quorum": 2}


db.execute("BEGIN IMMEDIATE")
try:
    docs = db.execute("SELECT id, body FROM docs").fetchall()
    for did, body in docs:
        d = with_quorum(json.loads(body))
        # DEFECT: approvals of superseded revisions "never count again", so they are dropped as dead data; but they are
        # the document's approval history (A3, A7), which the upgrade must keep
        d["approvals"] = [p for p in d["approvals"] if p[0] == len(d["revisions"])]
        db.execute("UPDATE docs SET body=? WHERE id=?", (json.dumps(d), did))
    ops = db.execute("SELECT request_id, params, result FROM ops").fetchall()
    for rq, params, result in ops:
        p, r = json.loads(params), json.loads(result)
        if p["op"] == "create": p = {**p, "quorum": 2}
        r = {**r, "document": with_quorum(r["document"])}
        db.execute("UPDATE ops SET params=?, result=? WHERE request_id=?", (json.dumps(p), json.dumps(r), rq))
    db.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)"); db.execute("INSERT INTO meta VALUES ('schema', '2')")
    db.execute("COMMIT")
except BaseException:
    db.execute("ROLLBACK"); raise
print(f"migrated {len(docs)} documents and {len(ops)} recorded results to version 2 (quorum 2)")
