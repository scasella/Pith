"""service/store.py — a custom integration (profile: custom): the candidate's own booking logic on SQLite.
It does not use the pack's verified core; the judge holds it to the contract through the service alone."""
import json, sqlite3, threading, time


class InvalidRequest(ValueError): pass
class ConflictingReplay(ValueError): pass
class Duplicate(ValueError): pass
class Unknown(KeyError): pass

MAX = 2 ** 53
def _int(x, n):
    if isinstance(x, bool) or not isinstance(x, int) or not 0 <= x < MAX: raise InvalidRequest(f"{n} must be an integer in [0, 2^53)")
    return x


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        for ddl in ("CREATE TABLE IF NOT EXISTS resources(id INTEGER PRIMARY KEY, name TEXT)",
                    "CREATE TABLE IF NOT EXISTS slots(id INTEGER PRIMARY KEY, resource INTEGER, start INTEGER, end INTEGER, active INTEGER)",
                    "CREATE TABLE IF NOT EXISTS ops(request_id INTEGER PRIMARY KEY, kind TEXT, params TEXT, result TEXT)",
                    "CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT)"):
            self.db.execute(ddl)
        self.lock = threading.RLock()

    def q(self, sql, *a):
        with self.lock: return self.db.execute(sql, a).fetchall()
    def resources(self): return [{"id": i, "name": n} for i, n in self.q("SELECT id, name FROM resources ORDER BY id")]
    def resource(self, rid):
        _int(rid, "resource"); r = self.q("SELECT id, name FROM resources WHERE id=?", rid)
        if not r: return None
        return {"id": r[0][0], "name": r[0][1], "bookings": [{"id": i, "start": s, "end": e, "active": bool(a)} for i, s, e, a in self.q("SELECT id, start, end, active FROM slots WHERE resource=? ORDER BY id", rid)]}
    def booking(self, bid):
        _int(bid, "booking"); r = self.q("SELECT id, resource, start, end, active FROM slots WHERE id=?", bid)
        return {"id": r[0][0], "resource": r[0][1], "start": r[0][2], "end": r[0][3], "active": bool(r[0][4])} if r else None
    def events(self, since=0): return [dict(json.loads(b), seq=s) for s, b in self.q("SELECT seq, body FROM events WHERE seq > ? ORDER BY seq", since)]

    def emit(self, **b): self.db.execute("INSERT INTO events(body) VALUES (?)", (json.dumps(b),))
    def overlaps(self, s1, e1, s2, e2): return s1 < e2 and s2 < e1
    def blocker(self, rid, s, e, except_id):
        for i, s2, e2 in self.q("SELECT id, start, end FROM slots WHERE resource=? AND active=1 ORDER BY id", rid):
            if i != except_id and self.overlaps(s, e, s2, e2): return i
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

    def create_resource(self, rid, name):
        _int(rid, "resource")
        if not isinstance(name, str) or not name: raise InvalidRequest("name")
        with self.lock:
            if self.q("SELECT 1 FROM resources WHERE id=?", rid): raise Duplicate(str(rid))
            self.db.execute("INSERT INTO resources VALUES (?, ?)", (rid, name)); self.emit(type="resource.created", resource=rid)
        return {"id": rid, "name": name}

    def book(self, rq, rid, s, e):
        for v, n in ((rq, "request_id"), (rid, "resource"), (s, "start"), (e, "end")): _int(v, n)
        params = {"resource": rid, "start": s, "end": e}
        with self.lock:
            if (r := self.replay(rq, "book", params)) is not None: return r
            if not self.q("SELECT 1 FROM resources WHERE id=?", rid): raise Unknown(rid)
            if s >= e: return self.record(rq, "book", params, {"request_id": rq, "booking_id": rq, "resource": rid, "outcome": "INVALID", "conflicts_with": None}, rid)
            b = self.blocker(rid, s, e, rq)
            if b is not None: return self.record(rq, "book", params, {"request_id": rq, "booking_id": rq, "resource": rid, "outcome": "CONFLICT", "conflicts_with": b}, rid)
        time.sleep(0.02)                     # DEFECT: the availability check and the insert are separate steps (another request can book in between)
        with self.lock:
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
            b = self.blocker(x["resource"], s, e, bid)
            if b is not None: return self.record(rq, "reschedule", params, dict(res, outcome="CONFLICT", conflicts_with=b), x["resource"])
            self.db.execute("UPDATE slots SET start=?, end=? WHERE id=?", (s, e, bid)); self.emit(type="booking.moved", request_id=rq)
            return self.record(rq, "reschedule", params, dict(res, outcome="ACCEPTED", start=s, end=e), x["resource"])
