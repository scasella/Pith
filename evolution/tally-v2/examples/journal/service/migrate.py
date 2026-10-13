"""service/migrate.py — python -I service/migrate.py --db PATH: turn a version 1 SQLite database at PATH into this
service's journal (harness/SERVICE.md, "Upgrading from version 1"). Every version 1 result is written, in request order
of acknowledgement (its tally), as a result of counter "default"; the journal replaces the database by an atomic
rename, and the database's WAL files are removed only after. A journal already at PATH is left as it is."""
import argparse, json, os, sqlite3, sys
ap = argparse.ArgumentParser(); ap.add_argument("--db", required=True); a = ap.parse_args()
HEADER = {"journal": "counters/1"}
with open(a.db, "rb") as f: head = f.read(64)
if head.startswith(json.dumps(HEADER).encode()): print("already a journal: nothing to do"); sys.exit(0)
if not head.startswith(b"SQLite format 3\x00"): sys.exit(f"refused: {a.db} is neither a version 1 database nor a journal")
db = sqlite3.connect(a.db)
cols = [r[1] for r in db.execute("PRAGMA table_info(results)")]
if cols != ["request_id", "outcome", "tally"]: sys.exit(f"refused: unrecognised schema {cols}")
rows = db.execute("SELECT request_id, outcome, tally FROM results ORDER BY rowid").fetchall(); db.close()
tmp = a.db + ".migrating"
with open(tmp, "w") as f:
    f.write(json.dumps(HEADER) + "\n")
    for rq, outcome, tally in rows: f.write(json.dumps({"request_id": rq, "counter": "default", "outcome": outcome, "tally": tally}) + "\n")
    f.flush(); os.fsync(f.fileno())
os.replace(tmp, a.db)
for x in ("-wal", "-shm"):
    if os.path.exists(a.db + x): os.remove(a.db + x)
print(f"migrated {len(rows)} version 1 results into a journal")
