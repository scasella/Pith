"""service/migrate.py — python -I service/migrate.py --db PATH: upgrade this service's database from
authorization-and-posting-core/v2 to authorization-and-posting/v3 in place (migrations/from-v2.yaml). The shipped
profile does the work (profiles/sqlite/migrate.py); a second run changes nothing; unrecognised state is refused."""
import argparse, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))   # -I does not put the project root on sys.path
from profiles.sqlite.migrate import migrate, Refused

ap = argparse.ArgumentParser(); ap.add_argument("--db", required=True); a = ap.parse_args()
try: print(migrate(a.db))
except Refused as e: sys.exit(f"refused: {e}")
