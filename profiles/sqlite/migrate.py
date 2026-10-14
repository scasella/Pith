"""profiles/sqlite/migrate.py — upgrade a database the shipped profile wrote under authorization-and-posting-core/v2 to
authorization-and-posting/v3 (migrations/from-v2.yaml, migrations/README.md). FROZEN. Candidates on the shipped
profile call it from their own entrypoint (service/migrate.py: `migrate(path)`).

What it does, in one transaction:
  - recognises the state: a version 2 database has exactly the tables accounts and events; a version 3 one also
    receipts and meta (schema 3), and is left as it is (a second run changes nothing); anything else is refused and
    left untouched
  - checks the history it is about to rely on: the event chain verifies (prev_hash, hash), and replaying the log
    through the proven core gives every stored account
  - writes one receipt per acknowledged write, from the event log, which is the only place version 2 kept them:
    authorize from auth.decided (decision, available_at_decision, amount), release from reservation.released,
    capture from capture.posted (amount); and refuses if an account's state has a decided, released or captured
    request without its event
  - records the schema, and never touches accounts or events: history is kept byte for byte
"""
import hashlib, json, os, sqlite3
from . import core, codec
from .repo import RECEIPTS_DDL, META_DDL, SCHEMA, TABLES, ZERO, tables


class Refused(RuntimeError): pass


def _canonical(o): return json.dumps(o, sort_keys=True, separators=(",", ":"))


def receipts_from_events(events):
    """{(account, request, op): (amount, body)} for every acknowledged write in a version 2 event log."""
    out = {}
    for e in events:
        t, a, r = e["type"], e.get("account_id"), e.get("request_id")
        if t == "auth.decided": out[(a, r, "authorize")] = (e["amount"], {"request_id": r, "decision": e["decision"], "available_at_decision": e["available_at_decision"]})
        elif t == "reservation.released": out[(a, r, "release")] = (None, {"request_id": r, "released": True})
        elif t == "capture.posted": out[(a, r, "capture")] = (None, {"request_id": r, "captured": True, "amount": e["amount"]})
    return out


def check_history(events, accounts):
    """The chain verifies and the log replays to the stored state; returns the problems found."""
    bad, prev, oracle = [], ZERO, {}
    A, P = core.Core(), core.Poster()
    for e in events:
        body = {k: v for k, v in e.items() if k not in ("hash", "seq")}
        if e.get("prev_hash") != prev or e.get("hash") != hashlib.sha256(_canonical(body).encode()).hexdigest():
            bad.append(f"event {e.get('seq')}: the hash chain does not verify"); break
        prev = e["hash"]; t, a = e["type"], e.get("account_id")
        if t == "account.created": oracle[a] = core.fresh_account(e["limit"])
        elif t == "auth.decided": _, oracle[a] = A.Decide(oracle[a], core.Request(e["request_id"], e["amount"]))
        elif t == "reservation.released": oracle[a] = A.Release(oracle[a], e["request_id"])
        elif t == "capture.posted": oracle[a] = P.Capture(oracle[a], e["request_id"])
    for acct, state in accounts.items():
        if acct not in oracle or codec.encode(oracle[acct]) != codec.encode(codec.decode(state)): bad.append(f"account {acct}: the stored state is not what its event log replays to")
    return bad


def migrate(path):
    """Upgrade the database at `path` in place. Returns a one-line summary; raises Refused (state untouched)."""
    if not os.path.isfile(path): raise Refused(f"{path} does not exist")
    db = sqlite3.connect(path, isolation_level=None)
    try:
        db.execute("BEGIN IMMEDIATE")
        have = tables(db)
    except sqlite3.DatabaseError as e:
        db.close(); raise Refused(f"{path} is not a database this profile wrote ({e})")
    try:
        if have == TABLES and db.execute("SELECT value FROM meta WHERE key='schema'").fetchone() == (SCHEMA,):
            db.execute("ROLLBACK"); return "already authorization-and-posting/v3: nothing to do"
        if have != {"accounts", "events"}: raise Refused(f"unrecognised state: tables {sorted(have)}")
        events = [dict(json.loads(b), seq=s) for s, b in db.execute("SELECT seq, body FROM events ORDER BY seq")]
        accounts = {i: json.loads(st) for i, st in db.execute("SELECT id, state FROM accounts")}
        problems = check_history(events, accounts)
        if problems: raise Refused("; ".join(problems))
        rec = receipts_from_events(events)
        for acct, state in accounts.items():
            for r, s in codec.encode(codec.decode(state))["status"]:
                need = {"AUTH": ["authorize"], "DECL": ["authorize"], "REL": ["authorize", "release"], "POST": ["authorize", "capture"]}[s]
                if any((acct, r, op) not in rec for op in need): raise Refused(f"account {acct} request {r} is {s} without the events that acknowledged it")
        db.execute(RECEIPTS_DDL); db.execute(META_DDL)
        db.executemany("INSERT INTO receipts(account_id, request_id, op, amount, body) VALUES(?, ?, ?, ?, ?)",
                       [(a, r, op, amt, json.dumps(body)) for (a, r, op), (amt, body) in sorted(rec.items(), key=lambda x: (x[0][0], x[0][1], x[0][2]))])
        db.execute("INSERT INTO meta(key, value) VALUES('schema', ?)", (SCHEMA,))
        db.execute("COMMIT")
        return f"migrated to authorization-and-posting/v3: {len(rec)} receipts from {len(events)} events, {len(accounts)} accounts; history unchanged"
    except BaseException:
        if db.in_transaction: db.execute("ROLLBACK")
        raise
    finally:
        db.close()
