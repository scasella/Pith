"""profiles/python/store.py — the shipped Python integration profile: SQLite, one transaction per operation. FROZEN.

Contract (harness/SERVICE.md; the node profile and any custom profile must meet the same, judged black-box):
  - every operation is one transaction opened with BEGIN IMMEDIATE: the write lock is held across load, decide and
    write, so two requests for overlapping intervals are decided one after the other, never on the same snapshot
  - inputs are validated to the proof's domain BEFORE the core is called; invalid input changes nothing
  - request_id is the idempotency key of every operation (one namespace): a replay returns the recorded result with
    replayed=true and never calls the core; a replay with a different operation or parameters is a ConflictingReplay
  - the booking id of an accepted booking is the request_id of its book operation
  - every operation's events and its op.committed event (carrying the resource's active intervals after the
    operation) are written in the operation's transaction; acknowledged means committed
  - the core's postcondition Valid is re-checked on the concrete result (core.valid); a violation is CorruptCore
    (defence in depth after the proof, not a substitute for it)
  - each resource's buffer (interval-booking-core/v2) is stored with it when it is created and never changed; every
    book, cancel and move on the resource passes it to the core
  - state the version 1 profile wrote (resources without a buffer) is refused until migrate() has upgraded it
    (harness/SERVICE.md, "Upgrading from version 1"): opening it as it is would have to guess a buffer
"""
import json, os, sqlite3, threading
from . import core

InvalidRequest = core.InvalidRequest
class ConflictingReplay(ValueError): pass
class Duplicate(ValueError): pass
class Unknown(KeyError): pass
class CorruptCore(RuntimeError): pass
class Unrecognised(RuntimeError): pass

V1 = {"resources": ["id", "name"], "slots": ["id", "resource", "start", "end", "active"], "ops": ["request_id", "kind", "params", "result"],
      "events": ["seq", "body"]}                                         # the tables and columns the version 1 profile wrote
V2 = dict(V1, resources=["id", "name", "buffer"])


def _layout(db): return {t: [c[1] for c in db.execute(f"PRAGMA table_info({t})")] for t in V1}


def migrate(path):
    """Upgrade version 1 state at `path` in place to version 2, in one transaction: every resource gets buffer 0 (the
    version 1 convention, so nothing already decided changes meaning: spec/BookingSpec.dfy BufferZeroIsHalfOpen);
    bookings, the request ledger and the events are kept exactly. On version 2 state it changes nothing. Anything
    else (not SQLite, or tables this profile did not write) raises Unrecognised, untouched. Returns a summary."""
    if not os.path.exists(path): return "no state: nothing to migrate"
    try:
        db = sqlite3.connect(f"file:{path}?mode=rw", uri=True, isolation_level=None); layout = _layout(db)
    except sqlite3.DatabaseError as e: raise Unrecognised(f"{path} is not a database this profile wrote ({e})")
    try:
        if layout == V2: return "already version 2: nothing to do"
        if layout != V1: raise Unrecognised(f"{path}: unrecognised tables {layout}")
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute("ALTER TABLE resources ADD COLUMN buffer INTEGER NOT NULL DEFAULT 0"); db.execute("COMMIT")
        except BaseException: db.execute("ROLLBACK"); raise
        n, m = (db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("resources", "ops"))
        return f"migrated {n} version 1 resources to buffer 0; {m} recorded results kept"
    finally: db.close()


class Store:
    def __init__(self, path):
        self.w = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.w.execute("PRAGMA journal_mode=WAL"); self.w.execute("PRAGMA synchronous=FULL")
        for ddl in ("CREATE TABLE IF NOT EXISTS resources(id INTEGER PRIMARY KEY, name TEXT NOT NULL, buffer INTEGER NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS slots(id INTEGER PRIMARY KEY, resource INTEGER NOT NULL, start INTEGER NOT NULL, end INTEGER NOT NULL, active INTEGER NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS ops(request_id INTEGER PRIMARY KEY, kind TEXT NOT NULL, params TEXT NOT NULL, result TEXT NOT NULL)",
                    "CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT NOT NULL)"):
            self.w.execute(ddl)
        if _layout(self.w) != V2: raise Unrecognised(f"{path} holds state this version does not read ({_layout(self.w)}): version 1 state is upgraded by migrate() first")
        self.r = sqlite3.connect(f"file:{path}?mode=ro", uri=True, isolation_level=None, check_same_thread=False)
        self.lock = threading.Lock(); self.rlock = threading.Lock(); self.k = core.Core()

    # ---- reads (their own connection; never see an uncommitted transaction) ----
    def _q(self, sql, *a):
        with self.rlock: return self.r.execute(sql, a).fetchall()
    def resources(self): return [{"id": i, "name": n, "buffer": g} for i, n, g in self._q("SELECT id, name, buffer FROM resources ORDER BY id")]
    def resource(self, rid):
        core.validate_int(rid, "resource")
        r = self._q("SELECT id, name, buffer FROM resources WHERE id=?", rid)
        if not r: return None
        return {"id": r[0][0], "name": r[0][1], "buffer": r[0][2], "bookings": [{"id": i, "start": s, "end": e, "active": bool(a)} for i, s, e, a in
                                                                                self._q("SELECT id, start, end, active FROM slots WHERE resource=? ORDER BY id", rid)]}
    def booking(self, bid):
        core.validate_int(bid, "booking id")
        r = self._q("SELECT id, resource, start, end, active FROM slots WHERE id=?", bid)
        return {"id": r[0][0], "resource": r[0][1], "start": r[0][2], "end": r[0][3], "active": bool(r[0][4])} if r else None
    def events(self, since=0): return [dict(json.loads(b), seq=s) for s, b in self._q("SELECT seq, body FROM events WHERE seq > ? ORDER BY seq", since)]

    # ---- writes ----
    def _tx(self, fn):
        with self.lock:
            self.w.execute("BEGIN IMMEDIATE")
            try: out = fn(); self.w.execute("COMMIT"); return out
            except BaseException: self.w.execute("ROLLBACK"); raise
    def _emit(self, **body): self.w.execute("INSERT INTO events(body) VALUES (?)", (json.dumps(body, sort_keys=True),))
    def _cal(self, rid): return self.w.execute("SELECT id, start, end, active FROM slots WHERE resource=? ORDER BY id", (rid,)).fetchall()
    def _buffer(self, rid): return self.w.execute("SELECT buffer FROM resources WHERE id=?", (rid,)).fetchone()[0]
    def _replay(self, request_id, kind, params):
        row = self.w.execute("SELECT kind, params, result FROM ops WHERE request_id=?", (request_id,)).fetchone()
        if row is None: return None
        if row[0] != kind or json.loads(row[1]) != params: raise ConflictingReplay(f"request_id {request_id} was used for a different operation")
        return dict(json.loads(row[2]), replayed=True)
    def _commit(self, request_id, kind, params, result, rid, after, g):
        if not core.valid(after, g): raise CorruptCore("the core's result violates Valid")
        self.w.execute("INSERT INTO ops VALUES (?, ?, ?, ?)", (request_id, kind, json.dumps(params), json.dumps(result)))
        self._emit(type="op.committed", request_id=request_id, resource=rid, active=[[i, s, e] for i, s, e, a in after if a])
        return dict(result, replayed=False)
    def _write_slots(self, rid, before, after):
        old = {r[0]: r for r in before}
        for i, s, e, a in after:
            if i not in old: self.w.execute("INSERT INTO slots VALUES (?, ?, ?, ?, ?)", (i, rid, s, e, int(a)))
            elif old[i][1:] != (s, e, int(a)): self.w.execute("UPDATE slots SET start=?, end=?, active=? WHERE id=?", (s, e, int(a), i))

    def create_resource(self, rid, name, buffer=0):
        core.validate_int(rid, "resource"); core.validate_buffer(buffer)
        if not isinstance(name, str) or not 0 < len(name) <= 200: raise InvalidRequest("name must be a non-empty string of at most 200 characters")
        def fn():
            if self.w.execute("SELECT 1 FROM resources WHERE id=?", (rid,)).fetchone(): raise Duplicate(rid)      # the buffer is fixed at creation
            self.w.execute("INSERT INTO resources VALUES (?, ?, ?)", (rid, name, buffer)); self._emit(type="resource.created", resource=rid, name=name, buffer=buffer)
            return {"id": rid, "name": name, "buffer": buffer}
        return self._tx(fn)

    def book(self, request_id, rid, start, end):
        for v, n in ((request_id, "request_id"), (rid, "resource"), (start, "start"), (end, "end")): core.validate_int(v, n)
        params = {"resource": rid, "start": start, "end": end}
        def fn():
            if (r := self._replay(request_id, "book", params)) is not None: return r
            if not self.w.execute("SELECT 1 FROM resources WHERE id=?", (rid,)).fetchone(): raise Unknown(f"resource {rid}")
            if self.w.execute("SELECT 1 FROM slots WHERE id=?", (request_id,)).fetchone(): raise ConflictingReplay(f"booking {request_id} exists")
            before, g = self._cal(rid), self._buffer(rid)
            o, cal = self.k.Book(core.calendar(before), g, request_id, start, end)
            name, with_ = core.outcome(o); after = core.rows(cal)
            self._write_slots(rid, before, after)
            self._emit(type="booking.accepted" if name == "ACCEPTED" else "booking.refused", request_id=request_id, resource=rid, start=start, end=end, outcome=name, conflicts_with=with_)
            return self._commit(request_id, "book", params, {"request_id": request_id, "booking_id": request_id, "resource": rid, "outcome": name, "conflicts_with": with_}, rid, after, g)
        return self._tx(fn)

    def _on_booking(self, request_id, bid, kind, params, decide):
        core.validate_int(request_id, "request_id"); core.validate_int(bid, "booking id")
        def fn():
            if (r := self._replay(request_id, kind, params)) is not None: return r
            row = self.w.execute("SELECT resource FROM slots WHERE id=?", (bid,)).fetchone()
            if row is None: raise Unknown(f"booking {bid}")
            rid = row[0]; before, g = self._cal(rid), self._buffer(rid)
            result, after = decide(rid, before, g)
            self._write_slots(rid, before, after)
            return self._commit(request_id, kind, params, result, rid, after, g)
        return self._tx(fn)

    def cancel(self, request_id, bid):
        def decide(rid, before, g):
            ok, cal = self.k.Cancel(core.calendar(before), g, bid)
            self._emit(type="booking.cancelled" if ok else "cancel.refused", request_id=request_id, booking_id=bid, resource=rid)
            return {"request_id": request_id, "booking_id": bid, "cancelled": bool(ok)}, core.rows(cal)
        return self._on_booking(request_id, bid, "cancel", {"booking_id": bid}, decide)

    def reschedule(self, request_id, bid, start, end):
        core.validate_int(start, "start"); core.validate_int(end, "end")
        def decide(rid, before, g):
            o, cal = self.k.Reschedule(core.calendar(before), g, bid, start, end)
            name, with_ = core.outcome(o); after = core.rows(cal); now = next(x for x in after if x[0] == bid)
            self._emit(type="booking.moved" if name == "ACCEPTED" else "move.refused", request_id=request_id, booking_id=bid, resource=rid, start=start, end=end, outcome=name, conflicts_with=with_)
            return {"request_id": request_id, "booking_id": bid, "outcome": name, "conflicts_with": with_, "start": now[1], "end": now[2]}, after
        return self._on_booking(request_id, bid, "reschedule", {"booking_id": bid, "start": start, "end": end}, decide)
