"""service/store.py — a custom integration (profile: custom): the candidate's own booking logic on SQLite.
It does not use the pack's verified core; the judge holds it to the contract through the service alone."""
import json, os, sqlite3, threading, time


class InvalidRequest(ValueError): pass
class ConflictingReplay(ValueError): pass
class Duplicate(ValueError): pass
class Unknown(KeyError): pass
class Unrecognised(RuntimeError): pass

MAX = 2 ** 53
MAX_BUFFER = 1440
def _int(x, n):
    if isinstance(x, bool) or not isinstance(x, int) or not 0 <= x < MAX: raise InvalidRequest(f"{n} must be an integer in [0, 2^53)")
    return x
def _buffer(x):
    if isinstance(x, bool) or not isinstance(x, int) or not 0 <= x <= MAX_BUFFER: raise InvalidRequest(f"buffer must be an integer in [0, {MAX_BUFFER}]")
    return x

# the columns this store writes: version 1 had no buffer on resources
V1 = {"resources": ["id", "name"], "slots": ["id", "resource", "start", "end", "active"], "ops": ["request_id", "kind", "params", "result"], "events": ["seq", "body"]}
V2 = dict(V1, resources=["id", "name", "buffer"])
def layout(db): return {t: [c[1] for c in db.execute(f"PRAGMA table_info({t})")] for t in V1}


def migrate(path):
    """Version 1 state -> version 2, in place, in one transaction: each resource gets buffer 0; nothing else changes.
    Version 2 state is left alone; anything else is refused (Unrecognised) and left untouched."""
    if not os.path.exists(path): return "no state: nothing to migrate"
    try: db = sqlite3.connect(f"file:{path}?mode=rw", uri=True, isolation_level=None); have = layout(db)
    except sqlite3.DatabaseError as e: raise Unrecognised(f"not a database this service wrote ({e})")
    try:
        if have == V2: return "already version 2: nothing to do"
        if have != V1: raise Unrecognised(f"unrecognised tables {have}")
        db.execute("BEGIN IMMEDIATE"); db.execute("ALTER TABLE resources ADD COLUMN buffer INTEGER NOT NULL DEFAULT 0"); db.execute("COMMIT")
        return f"migrated {db.execute('SELECT COUNT(*) FROM resources').fetchone()[0]} resources to buffer 0"
    finally: db.close()


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        for ddl in ("CREATE TABLE IF NOT EXISTS resources(id INTEGER PRIMARY KEY, name TEXT, buffer INTEGER NOT NULL DEFAULT 0)",
                    "CREATE TABLE IF NOT EXISTS slots(id INTEGER PRIMARY KEY, resource INTEGER, start INTEGER, end INTEGER, active INTEGER)",
                    "CREATE TABLE IF NOT EXISTS ops(request_id INTEGER PRIMARY KEY, kind TEXT, params TEXT, result TEXT)",
                    "CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT)"):
            self.db.execute(ddl)
        if layout(self.db) != V2: raise Unrecognised("version 1 state: run service/migrate.py first")
        self.lock = threading.RLock()

    def q(self, sql, *a):
        with self.lock: return self.db.execute(sql, a).fetchall()
    def resources(self): return [{"id": i, "name": n, "buffer": g} for i, n, g in self.q("SELECT id, name, buffer FROM resources ORDER BY id")]
    def resource(self, rid):
        _int(rid, "resource"); r = self.q("SELECT id, name, buffer FROM resources WHERE id=?", rid)
        if not r: return None
        return {"id": r[0][0], "name": r[0][1], "buffer": r[0][2], "bookings": [{"id": i, "start": s, "end": e, "active": bool(a)} for i, s, e, a in self.q("SELECT id, start, end, active FROM slots WHERE resource=? ORDER BY id", rid)]}
    def booking(self, bid):
        _int(bid, "booking"); r = self.q("SELECT id, resource, start, end, active FROM slots WHERE id=?", bid)
        return {"id": r[0][0], "resource": r[0][1], "start": r[0][2], "end": r[0][3], "active": bool(r[0][4])} if r else None
    def events(self, since=0): return [dict(json.loads(b), seq=s) for s, b in self.q("SELECT seq, body FROM events WHERE seq > ? ORDER BY seq", since)]

    def emit(self, **b): self.db.execute("INSERT INTO events(body) VALUES (?)", (json.dumps(b),))
    def overlaps(self, s1, e1, s2, e2): return s1 < e2 and s2 < e1
    def blocker(self, rid, s, e, except_id):
        g = self.q("SELECT buffer FROM resources WHERE id=?", rid)[0][0]                # the turnaround each side needs
        for i, s2, e2 in self.q("SELECT id, start, end FROM slots WHERE resource=? AND active=1 ORDER BY id", rid):
            if i != except_id and self.overlaps(s, e + g, s2, e2 + g): return i
        return None
    def replay(self, rq, kind, params):
        r = self.q("SELECT kind, params, result FROM ops WHERE request_id=?", rq)
        if not r: return None
        if r[0][0] != kind or json.loads(r[0][1]) != params: raise ConflictingReplay("request id reused")
        return dict(json.loads(r[0][2]), replayed=True)
    def record(self, rq, kind, params, result, rid):
        with self.lock:
            self.db.execute("INSERT INTO ops VALUES (?, ?, ?, ?)", (rq, kind, json.dumps(params), json.dumps(result)))
            act = [[i, s, e] for i, s, e in self.db.execute("SELECT id, start, end FROM slots WHERE resource=? AND active=1 ORDER BY id", (rid,)).fetchall()]
            self.emit(type="op.committed", request_id=rq, resource=rid, active=act)
        return dict(result, replayed=False)

    def create_resource(self, rid, name, buffer=0):
        _int(rid, "resource"); _buffer(buffer)
        if not isinstance(name, str) or not name: raise InvalidRequest("name")
        with self.lock:
            if self.q("SELECT 1 FROM resources WHERE id=?", rid): raise Duplicate(str(rid))
            self.db.execute("INSERT INTO resources VALUES (?, ?, ?)", (rid, name, buffer)); self.emit(type="resource.created", resource=rid, buffer=buffer)
        return {"id": rid, "name": name, "buffer": buffer}

    def book(self, rq, rid, s, e):
        for v, n in ((rq, "request_id"), (rid, "resource"), (s, "start"), (e, "end")): _int(v, n)
        params = {"resource": rid, "start": s, "end": e}
        with self.lock:
            if (r := self.replay(rq, "book", params)) is not None: return r
            if not self.q("SELECT 1 FROM resources WHERE id=?", rid): raise Unknown(rid)
            if s >= e: return self.record(rq, "book", params, {"request_id": rq, "booking_id": rq, "resource": rid, "outcome": "INVALID", "conflicts_with": None}, rid)
            b = self.blocker(rid, s, e, rq)
            if b is not None: return self.record(rq, "book", params, {"request_id": rq, "booking_id": rq, "resource": rid, "outcome": "CONFLICT", "conflicts_with": b}, rid)
            self.db.execute("INSERT INTO slots VALUES (?, ?, ?, ?, 1)", (rq, rid, s, e)); self.emit(type="booking.accepted", request_id=rq)
            return self.record(rq, "book", params, {"request_id": rq, "booking_id": rq, "resource": rid, "outcome": "ACCEPTED", "conflicts_with": None}, rid)

    def cancel(self, rq, bid):
        _int(rq, "request_id"); _int(bid, "booking"); params = {"booking_id": bid}
        with self.lock:
            if (r := self.replay(rq, "cancel", params)) is not None: return r
            x = self.booking(bid)
            if x is None: raise Unknown(bid)
            if x["active"]: self.db.execute("UPDATE slots SET active=0 WHERE id=?", (bid,)); self.emit(type="booking.cancelled", request_id=rq)
            return self.record(rq, "cancel", params, {"request_id": rq, "booking_id": bid, "cancelled": x["active"]}, x["resource"])

    def reschedule(self, rq, bid, s, e):
        for v, n in ((rq, "request_id"), (bid, "booking"), (s, "start"), (e, "end")): _int(v, n)
        params = {"booking_id": bid, "start": s, "end": e}
        with self.lock:
            if (r := self.replay(rq, "reschedule", params)) is not None: return r
            x = self.booking(bid)
            if x is None: raise Unknown(bid)
            res = {"request_id": rq, "booking_id": bid, "conflicts_with": None, "start": x["start"], "end": x["end"]}
            if not x["active"]: return self.record(rq, "reschedule", params, dict(res, outcome="NOT_ACTIVE"), x["resource"])
            if s >= e: return self.record(rq, "reschedule", params, dict(res, outcome="INVALID"), x["resource"])
            self.db.execute("UPDATE slots SET active=0 WHERE id=?", (bid,))       # DEFECT: a move is cancel-then-book; a refusal does not restore the original
            b = self.blocker(x["resource"], s, e, bid)
            if b is not None: return self.record(rq, "reschedule", params, dict(res, outcome="CONFLICT", conflicts_with=b), x["resource"])
            self.db.execute("UPDATE slots SET active=1 WHERE id=?", (bid,))
            self.db.execute("UPDATE slots SET start=?, end=? WHERE id=?", (s, e, bid)); self.emit(type="booking.moved", request_id=rq)
            return self.record(rq, "reschedule", params, dict(res, outcome="ACCEPTED", start=s, end=e), x["resource"])
