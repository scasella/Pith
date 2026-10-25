"""service/migrate.py — python -I service/migrate.py --db PATH: upgrade this service's database from
authorization-and-posting-core/v2 or a database the shipped sqlite profile wrote under authorization-and-posting/v3 to the
sqlite-occ layout, in place (receipts first for v2: migrations/from-v2.yaml; then accounts get a version). The shipped profile does the work
(profiles/sqlite_occ/migrate.py); a second run changes nothing; unrecognised state is refused."""
import argparse, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))   # -I does not put the project root on sys.path
from profiles.sqlite_occ.migrate import migrate, Refused

ap = argparse.ArgumentParser(); ap.add_argument("--db", required=True); a = ap.parse_args()
try: print(migrate(a.db))
except Refused as e: sys.exit(f"refused: {e}")
