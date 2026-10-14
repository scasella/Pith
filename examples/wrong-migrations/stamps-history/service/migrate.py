"""service/migrate.py — python -I service/migrate.py --db PATH: upgrade this service's database from
authorization-and-posting-core/v2 to authorization-and-posting/v3 in place. The shipped profile builds the receipts;
then every historical event is labelled with the contract it was written under, and the chain is re-sealed so it still
verifies. A second run changes nothing; unrecognised state is refused."""
import argparse, hashlib, json, pathlib, sqlite3, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))   # -I does not put the project root on sys.path
from profiles.sqlite.migrate import migrate, Refused

ap = argparse.ArgumentParser(); ap.add_argument("--db", required=True); a = ap.parse_args()
try: msg = migrate(a.db)
except Refused as e: sys.exit(f"refused: {e}")
if "nothing to do" in msg: print(msg); sys.exit(0)
db = sqlite3.connect(a.db, isolation_level=None); db.execute("BEGIN IMMEDIATE"); prev = "0" * 64
for seq, body in db.execute("SELECT seq, body FROM events ORDER BY seq").fetchall():
    e = {k: v for k, v in json.loads(body).items() if k not in ("hash", "prev_hash")}
    e["contract"] = "authorization-and-posting-core/v2"     # DEFECT: "label history with its contract"; re-sealing keeps the chain valid but every hash a client or auditor was given no longer exists
    e["prev_hash"] = prev; e["hash"] = hashlib.sha256(json.dumps(e, sort_keys=True, separators=(",", ":")).encode()).hexdigest(); prev = e["hash"]
    db.execute("UPDATE events SET body=? WHERE seq=?", (json.dumps(e), seq))
db.execute("COMMIT"); print(msg + "; history labelled")
