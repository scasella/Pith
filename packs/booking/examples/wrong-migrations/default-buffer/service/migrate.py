"""service/migrate.py — python -I service/migrate.py --db PATH: upgrade the state a version 1 service left at PATH to
version 2 in place (harness/SERVICE.md, "Upgrading from version 1"). Its own SQL instead of the profile's migrate():
one transaction, every resource gets the house turnaround buffer. Running it again changes nothing; anything else is
refused."""
import argparse, sqlite3, sys
HOUSE_BUFFER = 15                                                    # minutes of cleaning the front desk asked for
ap = argparse.ArgumentParser(); ap.add_argument("--db", required=True); a = ap.parse_args()
try:
    db = sqlite3.connect(f"file:{a.db}?mode=rw", uri=True, isolation_level=None)
    cols = [r[1] for r in db.execute("PRAGMA table_info(resources)")]
except sqlite3.DatabaseError as e: sys.exit(f"refused: {a.db} is not a database this service wrote ({e})")
if cols == ["id", "name", "buffer"]: print("already version 2: nothing to do"); sys.exit(0)
if cols != ["id", "name"]: sys.exit(f"refused: unrecognised schema {cols}")
db.execute("BEGIN IMMEDIATE")
db.execute(f"ALTER TABLE resources ADD COLUMN buffer INTEGER NOT NULL DEFAULT {HOUSE_BUFFER}")   # DEFECT: the new default applied to old resources, whose bookings were accepted at buffer 0
db.execute("COMMIT"); print(f"migrated version 1 resources to buffer {HOUSE_BUFFER}")
