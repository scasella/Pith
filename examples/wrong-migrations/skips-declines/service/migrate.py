"""service/migrate.py — python -I service/migrate.py --db PATH: upgrade this service's database from
authorization-and-posting-core/v2 to authorization-and-posting/v3 in place. Builds the receipts table from the event
log in one transaction; a second run changes nothing; unrecognised state is refused."""
import argparse, json, sqlite3, sys
from os.path import isfile

ap = argparse.ArgumentParser(); ap.add_argument("--db", required=True); a = ap.parse_args()
if not isfile(a.db): sys.exit(f"refused: {a.db} does not exist")
db = sqlite3.connect(a.db, isolation_level=None)
try: names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")} - {"sqlite_sequence"}
except sqlite3.DatabaseError as e: sys.exit(f"refused: not a database this service wrote ({e})")
if names == {"accounts", "events", "receipts", "meta"}: print("already version 3: nothing to do"); sys.exit(0)
if names != {"accounts", "events"}: sys.exit(f"refused: unrecognised tables {sorted(names)}")
db.execute("BEGIN IMMEDIATE")
db.execute("CREATE TABLE receipts(account_id INTEGER NOT NULL, request_id INTEGER NOT NULL, op TEXT NOT NULL, amount INTEGER, body TEXT NOT NULL, PRIMARY KEY(account_id, request_id, op))")
db.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
n = 0
for (body,) in db.execute("SELECT body FROM events ORDER BY seq").fetchall():
    e = json.loads(body); a_, r = e.get("account_id"), e.get("request_id")
    if e["type"] == "auth.decided":
        if e["decision"] == "DECLINED": continue          # DEFECT: "a decline reserved nothing, so there is nothing to give a receipt for"; its retry finds no receipt
        row = (a_, r, "authorize", e["amount"], {"request_id": r, "decision": e["decision"], "available_at_decision": e["available_at_decision"]})
    elif e["type"] == "reservation.released": row = (a_, r, "release", None, {"request_id": r, "released": True})
    elif e["type"] == "capture.posted": row = (a_, r, "capture", None, {"request_id": r, "captured": True, "amount": e["amount"]})
    else: continue
    db.execute("INSERT INTO receipts VALUES(?, ?, ?, ?, ?)", (*row[:4], json.dumps(row[4]))); n += 1
db.execute("INSERT INTO meta VALUES('schema', '3')")
db.execute("COMMIT"); print(f"migrated: {n} receipts")
