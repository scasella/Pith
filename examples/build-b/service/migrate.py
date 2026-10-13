"""service/migrate.py — python -I service/migrate.py --db PATH: upgrade build B's JSON document from
authorization-and-posting-core/v2 to authorization-and-posting/v3 in place (migrations/from-v2.yaml): receipts built
from the event log, accounts and events unchanged; a second run changes nothing; unrecognised state is refused."""
import argparse, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))   # -I does not put the project root on sys.path
from adapter.jsonrepo import migrate, Refused

ap = argparse.ArgumentParser(); ap.add_argument("--db", required=True); a = ap.parse_args()
try: print(migrate(a.db))
except Refused as e: sys.exit(f"refused: {e}")
