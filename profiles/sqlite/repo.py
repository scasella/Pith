"""
profiles/sqlite/repo.py — the shipped integration profile. The only writer of account state.

Contract (checked by obligations/adapter/harness.py; a custom profile must meet the same):
  - every write is one transaction opened with BEGIN IMMEDIATE (write lock held across read, decide, write)
  - inputs are validated to the proof's domain BEFORE the core is called; invalid input changes nothing and emits nothing
  - request id is the idempotency key: a replay returns the recorded decision without calling the core;
    a replay with a different amount is a conflict (rejected, no state change)
  - every write transaction ends with an `op.committed` event, after all events of that operation, carrying the
    committed state (state_after); events are hash-chained (prev_hash, hash)
  - every postcondition of Decide and Release is re-checked on the concrete result (check_decide_post / check_release_post);
    a mismatch is CorruptCore. This is defense in depth after the proof, not a substitute for it
  - every event carries the op_id of its transaction; op.committed closes exactly that operation
  - reads use their own connection and never observe an uncommitted transaction
  - the replay oracle is rebuilt from the durable event log on open (not from stored state), so verify_replay()
    is an independent check after a restart
"""
import sqlite3, json, threading, tempfile, os, hashlib, uuid
from . import core, codec

ZERO = "0" * 64
def canonical(obj): return json.dumps(obj, sort_keys=True, separators=(",", ":"))
def seal(body: dict, prev: str) -> dict:
    """Hash-chain an event: hash = sha256(canonical(body + prev_hash)). Detects alteration of a committed log;
    does not authenticate a database owner who rewrites the whole chain."""
    body = dict(body, prev_hash=prev); body["hash"] = hashlib.sha256(canonical(body).encode()).hexdigest(); return body

class CorruptCore(RuntimeError): pass

def _valid(a):
    """Valid(a) from the spec, on concrete state: INV1, P2, P2'."""
    h, st = core.holds(a), core.status(a)
    return int(a.posted) + sum(h.values()) <= int(a.limit) and set(h) == {k for k, v in st.items() if v == "AUTH"}

def check_decide_post(a, r_id, amount, d, a2):
    """Defense in depth at runtime: EVERY postcondition of Decide, re-evaluated on the concrete result
    (Valid, F, D, P3, P0/P1). Catches translator, runtime or loader faults; never a substitute for the proof."""
    avail = core.available(a); h, h2, st, st2 = core.holds(a), core.holds(a2), core.status(a), core.status(a2)
    ok = _valid(a2)                                                                                           # [INV1][P2][P2']
    ok &= int(a2.limit) == int(a.limit) and int(a2.posted) == int(a.posted)                                   # [F]
    ok &= set(st2) == set(st) | {r_id} and r_id in st2                                                        # [F][D] exact keys, decided
    ok &= (d.is_Authorized == (st2[r_id] == "AUTH")) and (d.is_Declined == (st2[r_id] == "DECL"))             # [D]
    ok &= all(st2[k] == v for k, v in st.items())                                                             # [P3] earlier decisions preserved
    if amount <= avail: ok &= d.is_Authorized and h2 == {**h, r_id: amount}                                  # [P0]
    else:               ok &= d.is_Declined and h2 == h                                                      # [P1]
    if not ok: raise CorruptCore("Decide result violates its own postconditions")

def check_release_post(a, r_id, a2):
    """Every postcondition of Release on the concrete result (Valid, F, R1, R2)."""
    h, st = core.holds(a), core.status(a)
    ok = _valid(a2) and int(a2.limit) == int(a.limit) and int(a2.posted) == int(a.posted)
    ok &= core.holds(a2) == {k: v for k, v in h.items() if k != r_id}                                          # [R1]
    ok &= core.status(a2) == {**st, r_id: "REL"}                                                              # [R2]
    if not ok: raise CorruptCore("Release result violates its own postconditions")

class Repo:
    def __init__(self, path=None):
        self.path = path or os.path.join(tempfile.mkdtemp(prefix="authrepo-"), "auth.db")
        self.w = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        self.w.execute("PRAGMA journal_mode=WAL")
        self.w.execute("CREATE TABLE IF NOT EXISTS accounts(id INTEGER PRIMARY KEY, state TEXT NOT NULL)")
        self.w.execute("CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER, body TEXT NOT NULL)")
        self.r = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, isolation_level=None, check_same_thread=False)
        self.core = core.Core()
        self._wlock = threading.Lock(); self._rlock = threading.Lock()
        self._oracle = {}
        self._rebuild_oracle()

    def close(self):
        self.w.close(); self.r.close()

    # -- oracle -----------------------------------------------------------
    def _rebuild_oracle(self):
        """Replay the durable event log through the pure core."""
        self._oracle = {}
        for ev in self.events(0):
            t = ev["type"]; a = ev.get("account_id")
            if t == "account.created":      self._oracle[a] = core.fresh_account(ev["limit"])
            elif t == "auth.decided":       _, self._oracle[a] = self.core.Decide(self._oracle[a], core.Request(ev["request_id"], ev["amount"]))
            elif t == "reservation.released": self._oracle[a] = self.core.Release(self._oracle[a], ev["request_id"])

    def verify_replay(self):
        diffs = []
        with self._rlock:
            rows = self.r.execute("SELECT id, state FROM accounts").fetchall()
        for acct_id, state in rows:
            stored = codec.encode(codec.decode(json.loads(state)))
            oracle = codec.encode(self._oracle[acct_id]) if acct_id in self._oracle else None
            if stored != oracle: diffs.append({"account": acct_id, "stored": stored, "oracle": oracle})
        return diffs

    # -- transaction helpers ------------------------------------------------
    def _load(self, acct_id):
        row = self.w.execute("SELECT state FROM accounts WHERE id=?", (acct_id,)).fetchone()
        if row is None: raise core.UnknownAccount(acct_id)
        return codec.decode(json.loads(row[0]))
    def _store(self, acct_id, a):
        self.w.execute("UPDATE accounts SET state=? WHERE id=?", (json.dumps(codec.encode(a)), acct_id))
    def _emit(self, ev):
        ev = dict(ev, producer="auth-service", op_id=self._op)
        prev = self.w.execute("SELECT body FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        ev = seal(ev, json.loads(prev[0])["hash"] if prev else ZERO)
        self.w.execute("INSERT INTO events(account_id, body) VALUES(?, ?)", (ev.get("account_id"), json.dumps(ev)))
    def _committed(self, acct_id, req_id, op, a_after):
        """Closes a write: carries the committed state so a monitor can check continuity, not just atoms."""
        self._emit({"type": "op.committed", "account_id": acct_id, "request_id": req_id, "op": op,
                    "state_after": {"limit": int(a_after.limit), "posted": int(a_after.posted), "reserved": sum(core.holds(a_after).values())}})

    def _tx(self, fn):
        """Run fn inside BEGIN IMMEDIATE; roll back on any exception; oracle updated only after COMMIT."""
        with self._wlock:
            self._op = uuid.uuid4().hex                   # one operation id per transaction; every event of it carries it
            self.w.execute("BEGIN IMMEDIATE")
            try:
                result, oracle_update = fn()
                self.w.execute("COMMIT")
            except Exception:
                self.w.execute("ROLLBACK"); raise
            if oracle_update: oracle_update()
            return result

    # -- operations ---------------------------------------------------------
    def create_account(self, acct_id, limit):
        acct_id, limit = core.validate_id(acct_id, "account_id"), core.validate_limit(limit)
        def body():
            try:
                self.w.execute("INSERT INTO accounts(id, state) VALUES(?, ?)", (acct_id, json.dumps(codec.encode(core.fresh_account(limit)))))
            except sqlite3.IntegrityError:
                raise core.DuplicateAccount(acct_id)
            self._emit({"type": "account.created", "account_id": acct_id, "limit": limit})
            self._committed(acct_id, None, "create_account", core.fresh_account(limit))
            return {"id": acct_id, "limit": limit}, (lambda: self._oracle.__setitem__(acct_id, core.fresh_account(limit)))
        return self._tx(body)

    def authorize(self, acct_id, req_id, amount):
        acct_id, req_id, amount = core.validate_id(acct_id, "account_id"), core.validate_id(req_id, "request_id"), core.validate_amount(amount)
        def body():
            a = self._load(acct_id); st = core.status(a)
            if req_id in st:                                                        # idempotent replay
                prior = self.w.execute("SELECT body FROM events WHERE account_id=? AND body LIKE ? ORDER BY seq", (acct_id, '%"auth.decided"%')).fetchall()
                rec = next(json.loads(b) for (b,) in prior if json.loads(b)["request_id"] == req_id)
                if rec["amount"] != amount: raise core.ConflictingReplay(f"request {req_id} was {rec['amount']}, replay says {amount}")
                return {"request_id": req_id, "decision": rec["decision"], "available_at_decision": rec["available_at_decision"], "replayed": True}, None
            avail = core.available(a)
            d, a2 = self.core.Decide(a, core.Request(req_id, amount))
            check_decide_post(a, req_id, amount, d, a2)
            decision = "AUTHORIZED" if d.is_Authorized else "DECLINED"
            self._store(acct_id, a2)
            self._emit({"type": "auth.decided", "account_id": acct_id, "request_id": req_id, "amount": amount, "available_at_decision": avail, "decision": decision})
            if d.is_Authorized: self._emit({"type": "reservation.created", "account_id": acct_id, "request_id": req_id, "amount": amount})
            self._committed(acct_id, req_id, "authorize", a2)
            def upd(): _, self._oracle[acct_id] = self.core.Decide(self._oracle[acct_id], core.Request(req_id, amount))
            return {"request_id": req_id, "decision": decision, "available_at_decision": avail, "replayed": False}, upd
        return self._tx(body)

    def release(self, acct_id, req_id):
        acct_id, req_id = core.validate_id(acct_id, "account_id"), core.validate_id(req_id, "request_id")
        def body():
            a = self._load(acct_id)
            if req_id not in core.holds(a):
                return {"request_id": req_id, "released": False}, None                 # no-op, no event
            a2 = self.core.Release(a, req_id)
            check_release_post(a, req_id, a2)
            self._store(acct_id, a2)
            self._emit({"type": "reservation.released", "account_id": acct_id, "request_id": req_id})
            self._committed(acct_id, req_id, "release", a2)
            def upd(): self._oracle[acct_id] = self.core.Release(self._oracle[acct_id], req_id)
            return {"request_id": req_id, "released": True}, upd
        return self._tx(body)

    # -- reads (own connection; WAL => never sees an uncommitted write) -------
    def account(self, acct_id):
        acct_id = core.validate_id(acct_id, "account_id")
        with self._rlock:
            row = self.r.execute("SELECT state FROM accounts WHERE id=?", (acct_id,)).fetchone()
        if row is None: raise core.UnknownAccount(acct_id)
        a = codec.decode(json.loads(row[0]))
        return {"id": acct_id, "limit": int(a.limit), "posted": int(a.posted), "available": core.available(a), "holds": core.holds(a), "status": core.status(a)}

    def events(self, since=0):
        with self._rlock:
            rows = self.r.execute("SELECT seq, body FROM events WHERE seq>? ORDER BY seq", (since,)).fetchall()
        return [dict(json.loads(b), seq=s) for s, b in rows]
