"""
profiles/sqlite_occ/repo.py — the optimistic-concurrency integration profile (docs/rfc/0007 § 6). FROZEN. The only writer of
account state when an application selects `profile: sqlite-occ`. Same Repo API, same events, same receipts and same verified
core as profiles/sqlite/repo.py; what differs is how concurrent operations on one account are kept atomic.

profiles/sqlite takes the write lock BEFORE it reads: read, decide and write all happen inside one BEGIN IMMEDIATE. This profile reads
without a lock and takes the write lock only to commit:

  1. READ     one statement (no lock, no transaction): the account's state, its version and the receipt, if any, of this operation
              on this request. Every operation opens its own connection, so no read ever lands inside another operation's
              transaction, and operations on different threads, Repo objects or processes are all in the same position.
  2. DECIDE   with the verified core (profiles/sqlite/core.py), on that state, outside any lock; the postconditions are re-checked
              on the concrete result, as profiles/sqlite does (CorruptCore on a mismatch).
  3. COMMIT   one short BEGIN IMMEDIATE transaction: (a) the receipt of this request is read again, because a concurrent retry may
              have committed it since step 1: if it is there, the recorded answer is returned and nothing is written;
              (b) the compare-and-swap `UPDATE accounts SET state = ?, version = version + 1 WHERE id = ? AND version = ?`,
              with the version step 1 read; if it changed no row, another operation committed on the account since the read,
              the decision was made against a state that is no longer current, and it is DISCARDED (rollback), never committed;
              (c) the events (hash-chained after the last committed one, ending in op.committed with state_after) and the receipt.
              The whole of (a)-(c) is one transaction, so a crash leaves all of it or none of it.

A lost compare-and-swap retries from step 1: the operation reads the new state and decides again (the request may now be a replay).
The budget is RETRY_BUDGET = 100 attempts per operation, so 99 lost rounds. A lost round means another operation committed a change
to that account after this one read it, and the next read comes after that commit, so the commits that beat one operation are all
different operations, each of which commits once: an operation can lose at most as many rounds as there are OTHER state-changing
operations on its account, and a burst of at most 100 operations on one account cannot exhaust the budget. (The reservation
lifecycle harness puts at most 24 operations on an account, through 8 workers; tests/test_occ.py puts 48 through 16 threads, and
one run of that measured 26 lost rounds in all, nowhere near the budget.) Past the budget the operation raises OccRetriesExhausted,
which says so, and changes nothing.

Atomicity (record Atomicity): a committed decision was computed from the state current at its commit, because the commit is
conditional on that state's version. This is the property profiles/sqlite has by holding the write lock from the read to the commit,
kept while holding it only for the commit's few statements. Reads of account() and events() use read-only connections and see only
committed states (WAL); verify_replay() reads the log and the accounts in one snapshot.

The database records its layout: accounts carries `version`, and a marker table `occ` exists, so a database written by profiles/sqlite
(no version column) is refused with UnmigratedState until profiles/sqlite_occ/migrate.py has upgraded it, and profiles/sqlite refuses
a database written by this profile (a table it does not know): neither profile can write state the other's concurrency control does
not see. The contract version of the state is the same (meta.schema = 3): receipts, events and their chain are exactly profiles/sqlite's.

What this profile does not do: it is not faster in general (a contended account retries; the cost moves from lock waits to repeated
reads), it does not make operations on different accounts independent of each other (the event chain is global, so every commit
takes the one write lock for its few statements), and it relies on SQLite's WAL snapshot reads, on BEGIN IMMEDIATE excluding other writers and on one statement being atomic.
"""
import json, os, sqlite3, tempfile, uuid
from profiles.sqlite import core, codec
from profiles.sqlite.repo import (ZERO, RECEIPTS_DDL, META_DDL, SCHEMA, TABLES as SQLITE_TABLES, seal, tables, CorruptCore,
                                  check_decide_post, check_release_post, check_capture_post)

RETRY_BUDGET = 100                    # attempts per operation; see the module docstring for why a burst of at most 100 operations on one account cannot exhaust it
BUSY_TIMEOUT = 30.0                   # seconds a BEGIN IMMEDIATE waits for the write lock held by another connection's commit
TABLES = SQLITE_TABLES | {"occ"}
ACCOUNTS_DDL = "CREATE TABLE IF NOT EXISTS accounts(id INTEGER PRIMARY KEY, state TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 0)"
EVENTS_DDL = "CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER, body TEXT NOT NULL)"
OCC_DDL = "CREATE TABLE IF NOT EXISTS occ(layout INTEGER PRIMARY KEY CHECK (layout = 1))"
SNAPSHOT = ("SELECT a.state, a.version, r.amount, r.body FROM accounts a "
            "LEFT JOIN receipts r ON r.account_id = a.id AND r.request_id = ? AND r.op = ? WHERE a.id = ?")


class UnmigratedState(RuntimeError): pass
class OccRetriesExhausted(RuntimeError): pass


class Write:
    """What one operation commits: the account's state after, its events (before op.committed), its receipt."""
    def __init__(self, after, events, op, body, amount=None): self.after, self.events, self.op, self.body, self.amount = after, events, op, body, amount


def layout_current(db, have):
    return (have == TABLES and db.execute("SELECT value FROM meta WHERE key='schema'").fetchone() == (SCHEMA,)
            and "version" in {r[1] for r in db.execute("PRAGMA table_info(accounts)")})


class Repo:
    def __init__(self, path=None):
        self.path = path or os.path.join(tempfile.mkdtemp(prefix="occrepo-"), "auth.db")
        self.retries = 0                                  # lost compare-and-swaps so far (a diagnostic; not synchronised)
        db = self._connect()
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("BEGIN IMMEDIATE")
            have = tables(db)
            if have and not layout_current(db, have):
                db.execute("ROLLBACK")
                raise UnmigratedState(f"{self.path} holds state written for another profile or contract (tables {sorted(have)}): migrate it first "
                                      f"(python3 -I service/migrate.py --db PATH; profiles/sqlite_occ/migrate.py)")
            for ddl in (ACCOUNTS_DDL, EVENTS_DDL, RECEIPTS_DDL, META_DDL, OCC_DDL): db.execute(ddl)
            db.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('schema', ?)", (SCHEMA,))
            db.execute("INSERT OR IGNORE INTO occ(layout) VALUES(1)")
            db.execute("COMMIT")
        finally: db.close()
        self.core = core.Core(); self.poster = core.Poster()

    def close(self): pass                                 # every operation opens and closes its own connection

    def _connect(self, readonly=False):
        if readonly: return sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, isolation_level=None, check_same_thread=False, timeout=BUSY_TIMEOUT)
        return sqlite3.connect(self.path, isolation_level=None, check_same_thread=False, timeout=BUSY_TIMEOUT)

    # -- the three steps ----------------------------------------------------------------------------------
    def _snapshot(self, db, acct, req, op):
        """Step 1: the account's state with the version it had, and this request's receipt for this operation, from ONE statement."""
        row = db.execute(SNAPSHOT, (req, op, acct)).fetchone()
        if row is None: raise core.UnknownAccount(acct)
        return codec.decode(json.loads(row[0])), row[1], ((row[2], json.loads(row[3])) if row[3] is not None else None)

    def _recheck(self, db, acct, req, op):
        """Step 3a, inside the commit transaction: the receipt of this request, if a concurrent retry committed it since step 1."""
        row = db.execute("SELECT amount, body FROM receipts WHERE account_id=? AND request_id=? AND op=?", (acct, req, op)).fetchone()
        return (row[0], json.loads(row[1])) if row else None

    def _cas(self, db, acct, version, state):
        """Step 3b: replace the state only if its version is still the one the decision was computed from."""
        return db.execute("UPDATE accounts SET state=?, version=version+1 WHERE id=? AND version=?", (state, acct, version)).rowcount == 1

    def _append(self, db, acct, req, op, op_id, events, after, receipt=None, amount=None):
        """Step 3c: the operation's events, chained after the last committed one, closed by op.committed carrying the committed state;
        its receipt."""
        prev = db.execute("SELECT body FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        h, rows = (json.loads(prev[0])["hash"] if prev else ZERO), []
        done = {"type": "op.committed", "account_id": acct, "request_id": req, "op": op,
                "state_after": {"limit": int(after.limit), "posted": int(after.posted), "reserved": sum(core.holds(after).values())}}
        for ev in events + [done]:
            ev = seal(dict(ev, producer="auth-service", op_id=op_id), h); h = ev["hash"]; rows.append((ev.get("account_id"), json.dumps(ev)))
        db.executemany("INSERT INTO events(account_id, body) VALUES(?, ?)", rows)
        if receipt is not None:
            db.execute("INSERT INTO receipts(account_id, request_id, op, amount, body) VALUES(?, ?, ?, ?, ?)", (acct, req, op, amount, json.dumps(receipt)))

    def _commit(self, db, acct, req, op, version, w, replay):
        """One short write transaction. Returns (result,) when the operation is answered, None when the compare-and-swap was lost."""
        op_id = uuid.uuid4().hex
        db.execute("BEGIN IMMEDIATE")
        try:
            rec = self._recheck(db, acct, req, op)
            if rec is not None: db.execute("ROLLBACK"); return (replay(rec),)
            if not self._cas(db, acct, version, json.dumps(codec.encode(w.after))): db.execute("ROLLBACK"); return None
            self._append(db, acct, req, op, op_id, w.events, w.after, w.body, w.amount)
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction: db.execute("ROLLBACK")
            raise
        return (dict(w.body, replayed=False),)

    def _run(self, acct, req, op, check, compute, replay):
        """read, check, decide, commit; a lost compare-and-swap starts again from the read. check(a, receipt) is the idempotency question,
        asked of every state the operation reads: it returns the answer that changes nothing (a replay, a no-op) or None; compute(a)
        decides with the core and returns what to commit (a Write)."""
        for attempt in range(RETRY_BUDGET):
            db = self._connect()
            try:
                a, version, rec = self._snapshot(db, acct, req, op)
                done = check(a, rec)
                if done is not None: return done
                done = self._commit(db, acct, req, op, version, compute(a), replay)
                if done is not None: return done[0]
            finally: db.close()
            self.retries += 1
        raise OccRetriesExhausted(f"{op} of request {req} on account {acct} lost the compare-and-swap {RETRY_BUDGET} times in a row: "
                                  f"contention on the account exceeds the retry budget; nothing was changed, retry the request")

    # -- operations ---------------------------------------------------------------------------------------
    def create_account(self, acct_id, limit):
        acct_id, limit = core.validate_id(acct_id, "account_id"), core.validate_limit(limit)
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            try: db.execute("INSERT INTO accounts(id, state, version) VALUES(?, ?, 0)", (acct_id, json.dumps(codec.encode(core.fresh_account(limit)))))
            except sqlite3.IntegrityError: db.execute("ROLLBACK"); raise core.DuplicateAccount(acct_id)
            self._append(db, acct_id, None, "create_account", uuid.uuid4().hex, [{"type": "account.created", "account_id": acct_id, "limit": limit}], core.fresh_account(limit))
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction: db.execute("ROLLBACK")
            raise
        finally: db.close()
        return {"id": acct_id, "limit": limit}

    def authorize(self, acct_id, req_id, amount):
        acct_id, req_id, amount = core.validate_id(acct_id, "account_id"), core.validate_id(req_id, "request_id"), core.validate_amount(amount)
        def replay(rec):
            if rec[0] != amount: raise core.ConflictingReplay(f"request {req_id} was {rec[0]}, replay says {amount}")
            return dict(rec[1], replayed=True)
        def check(a, rec):
            if req_id not in core.status(a): return None
            if rec is None: raise CorruptCore(f"request {req_id} was decided but has no receipt")
            return replay(rec)                                                     # a replay: the recorded receipt, the core is not called
        def compute(a):
            avail = core.available(a)
            d, a2 = self.core.Decide(a, core.Request(req_id, amount))
            check_decide_post(a, req_id, amount, d, a2)
            decision = "AUTHORIZED" if d.is_Authorized else "DECLINED"
            evs = [{"type": "auth.decided", "account_id": acct_id, "request_id": req_id, "amount": amount, "available_at_decision": avail, "decision": decision}]
            if d.is_Authorized: evs.append({"type": "reservation.created", "account_id": acct_id, "request_id": req_id, "amount": amount})
            return Write(a2, evs, "authorize", {"request_id": req_id, "decision": decision, "available_at_decision": avail}, amount)
        return self._run(acct_id, req_id, "authorize", check, compute, replay)

    def release(self, acct_id, req_id):
        acct_id, req_id = core.validate_id(acct_id, "account_id"), core.validate_id(req_id, "request_id")
        def replay(rec): return dict(rec[1], replayed=True)
        def check(a, rec):
            if req_id in core.holds(a): return None
            return replay(rec) if rec else {"request_id": req_id, "released": False, "replayed": False}   # a retry: its receipt; else a no-op
        def compute(a):
            a2 = self.core.Release(a, req_id)
            check_release_post(a, req_id, a2)
            return Write(a2, [{"type": "reservation.released", "account_id": acct_id, "request_id": req_id}], "release", {"request_id": req_id, "released": True})
        return self._run(acct_id, req_id, "release", check, compute, replay)

    def capture(self, acct_id, req_id):
        """Posting kernel: move an authorized hold into posted, in full. Idempotent: a captured request replays."""
        acct_id, req_id = core.validate_id(acct_id, "account_id"), core.validate_id(req_id, "request_id")
        def replay(rec): return dict(rec[1], replayed=True)
        def check(a, rec):
            if req_id in core.holds(a): return None
            if rec: return replay(rec)
            if core.status(a).get(req_id) == "POST": raise CorruptCore(f"request {req_id} was captured but has no receipt")
            return {"request_id": req_id, "captured": False, "replayed": False}
        def compute(a):
            amount = core.holds(a)[req_id]
            a2 = self.poster.Capture(a, req_id)
            check_capture_post(a, req_id, a2)
            return Write(a2, [{"type": "capture.posted", "account_id": acct_id, "request_id": req_id, "amount": amount}], "capture",
                         {"request_id": req_id, "captured": True, "amount": amount})
        return self._run(acct_id, req_id, "capture", check, compute, replay)

    # -- reads (own read-only connections; WAL => never sees an uncommitted write) ----------------------------------
    def account(self, acct_id):
        acct_id = core.validate_id(acct_id, "account_id")
        db = self._connect(readonly=True)
        try: row = db.execute("SELECT state FROM accounts WHERE id=?", (acct_id,)).fetchone()
        finally: db.close()
        if row is None: raise core.UnknownAccount(acct_id)
        a = codec.decode(json.loads(row[0]))
        return {"id": acct_id, "limit": int(a.limit), "posted": int(a.posted), "available": core.available(a), "holds": core.holds(a), "status": core.status(a)}

    def events(self, since=0):
        db = self._connect(readonly=True)
        try: rows = db.execute("SELECT seq, body FROM events WHERE seq>? ORDER BY seq", (since,)).fetchall()
        finally: db.close()
        return [dict(json.loads(b), seq=s) for s, b in rows]

    def verify_replay(self):
        """Replay the durable event log through the pure core and compare with every stored account, both read in ONE snapshot."""
        db = self._connect(readonly=True)
        try:
            db.execute("BEGIN")
            rows = db.execute("SELECT body FROM events ORDER BY seq").fetchall(); accts = db.execute("SELECT id, state FROM accounts").fetchall()
            db.execute("COMMIT")
        finally: db.close()
        oracle = {}
        for (b,) in rows:
            ev = json.loads(b); t = ev["type"]; a = ev.get("account_id")
            if t == "account.created":        oracle[a] = core.fresh_account(ev["limit"])
            elif t == "auth.decided":         _, oracle[a] = self.core.Decide(oracle[a], core.Request(ev["request_id"], ev["amount"]))
            elif t == "reservation.released": oracle[a] = self.core.Release(oracle[a], ev["request_id"])
            elif t == "capture.posted":       oracle[a] = self.poster.Capture(oracle[a], ev["request_id"])
        diffs = []
        for acct_id, state in accts:
            stored = codec.encode(codec.decode(json.loads(state))); want = codec.encode(oracle[acct_id]) if acct_id in oracle else None
            if stored != want: diffs.append({"account": acct_id, "stored": stored, "oracle": want})
        return diffs
