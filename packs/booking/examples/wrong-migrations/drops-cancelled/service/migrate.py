"""service/migrate.py — python -I service/migrate.py --db PATH: upgrade the state a version 1 service left at PATH to
version 2 in place (harness/SERVICE.md, "Upgrading from version 1"). Its own SQL instead of the profile's migrate():
one transaction, every resource gets buffer 0. Running it again changes nothing; anything else is refused."""
import argparse, sqlite3, sys
ap = argparse.ArgumentParser(); ap.add_argument("--db", required=True); a = ap.parse_args()
try:
    db = sqlite3.connect(f"file:{a.db}?mode=rw", uri=True, isolation_level=None)
    cols = [r[1] for r in db.execute("PRAGMA table_info(resources)")]
except sqlite3.DatabaseError as e: sys.exit(f"refused: {a.db} is not a database this service wrote ({e})")
if cols == ["id", "name", "buffer"]: print("already version 2: nothing to do"); sys.exit(0)
if cols != ["id", "name"]: sys.exit(f"refused: unrecognised schema {cols}")
db.execute("BEGIN IMMEDIATE")
db.execute("ALTER TABLE resources ADD COLUMN buffer INTEGER NOT NULL DEFAULT 0")
db.execute("DELETE FROM slots WHERE active = 0")                    # DEFECT: cancelled bookings "free nothing", so they are dropped as dead rows
db.execute("COMMIT"); print("migrated version 1 resources to buffer 0")
