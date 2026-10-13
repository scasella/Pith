"""service/migrate.py — python -I service/migrate.py --db PATH. Added when the handbook moved to pith.approval's
approval-workflow/v2 (per-document quorums): upgrades the review tables of the handbook's database in place
(harness/SERVICE.md, "Upgrading from version 1"). One transaction: review_docs gains its quorum column, 2 for every
document reviewed before; every recorded result is kept, its document carrying quorum 2, and every recorded create
names quorum 2, so retries of old requests replay. People, revisions, votes (those of superseded revisions included:
they are history) and the review log are untouched, and so is everything else in the database (pages). Running it
again changes nothing; a database without the handbook's review tables is refused."""
import argparse, json, pathlib, sqlite3, sys

ap = argparse.ArgumentParser(); ap.add_argument("--db", required=True); a = ap.parse_args()
REVIEW = {"people", "review_docs", "review_revisions", "review_votes", "review_requests", "review_log"}
if not pathlib.Path(a.db).is_file(): sys.exit(f"refused: {a.db} does not exist")
try:
    db = sqlite3.connect(f"file:{a.db}?mode=rw", uri=True, isolation_level=None)
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    cols = [r[1] for r in db.execute("PRAGMA table_info(review_docs)")]
except sqlite3.DatabaseError as e: sys.exit(f"refused: {a.db} is not the handbook's database ({e})")
if not REVIEW <= tables: sys.exit(f"refused: no review tables in {a.db} ({sorted(tables)})")
if cols == ["id", "title", "status", "quorum"]: print("already version 2: nothing to do"); sys.exit(0)
if cols != ["id", "title", "status"]: sys.exit(f"refused: unrecognised review_docs columns {cols}")


def with_quorum(doc):
    if doc is None: return None
    if "quorum" in doc: raise SystemExit("refused: a recorded document already has a quorum")
    return {**doc, "quorum": 2}


db.execute("BEGIN IMMEDIATE")
try:
    db.execute("ALTER TABLE review_docs ADD COLUMN quorum INTEGER NOT NULL DEFAULT 2")
    rows = db.execute("SELECT request_id, params, result FROM review_requests").fetchall()
    for rq, params, result in rows:
        p, r = json.loads(params), json.loads(result)
        if p["op"] == "create": p = {**p, "quorum": 2}
        db.execute("UPDATE review_requests SET params=?, result=? WHERE request_id=?", (json.dumps(p), json.dumps({**r, "document": with_quorum(r["document"])}), rq))
    db.execute("COMMIT")
except BaseException:
    db.execute("ROLLBACK"); raise
print(f"migrated {db.execute('SELECT COUNT(*) FROM review_docs').fetchone()[0]} documents and {len(rows)} recorded results (quorum 2)")
