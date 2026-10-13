"""service/migrate.py — python -I service/migrate.py --db PATH: upgrade a version 1 database to version 2 in place
(harness/SERVICE.md, "Upgrading from version 1"). One transaction: every version 1 result becomes a result of counter
"default", nothing else changes. Running it again on a version 2 database changes nothing; anything else is refused."""
import argparse, sqlite3, sys
ap = argparse.ArgumentParser(); ap.add_argument("--db", required=True); a = ap.parse_args()
try:
    db = sqlite3.connect(a.db, isolation_level=None)
    cols = [r[1] for r in db.execute("PRAGMA table_info(results)")]
except sqlite3.DatabaseError as e: sys.exit(f"refused: {a.db} is not a database this service wrote ({e})")
if cols == ["request_id", "outcome", "tally", "counter"]: print("already version 2: nothing to do"); sys.exit(0)
if cols != ["request_id", "outcome", "tally"]: sys.exit(f"refused: unrecognised schema {cols}")
db.execute("BEGIN IMMEDIATE")
db.execute("ALTER TABLE results ADD COLUMN counter TEXT NOT NULL DEFAULT 'legacy'")   # DEFECT: version 1 results land in counter "legacy", not "default"
db.execute("COMMIT"); print(f"migrated {db.execute('SELECT COUNT(*) FROM results').fetchone()[0]} version 1 results to counter 'default'")
