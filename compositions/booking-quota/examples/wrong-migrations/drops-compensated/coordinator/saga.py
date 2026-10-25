"""coordinator/saga.py — the reservation saga and its durable log (runtime/RUNTIME.md).

A reservation books the resource, then takes one quota unit for it; if quota refuses, the booking is cancelled. Every step
is logged BEFORE the next call is made, in a SQLite file that survives SIGKILL, so the coordinator can always pick a saga up
where it left it:

    begun   -> book              the booking is called (a repeat returns what booking recorded)
    booked  -> acquire           quota is called with the reservation's request id (a repeat returns the recorded answer)
    denied  -> cancel            quota refused: the cancel is owed. It carries its own request id, derived from the reservation's
    done                         the receipt is written in the same transaction that ends the saga

recover_all() is the recovery duty: it finishes or compensates every saga in the log, without any client retry.
"""
import json, sqlite3, threading, time
from peers import Unavailable

CANCEL_OFFSET = 2 ** 52                      # a reservation's request id is below it; its cancel's is the id plus it, in booking's one namespace


def cancel_id(request_id): return request_id + CANCEL_OFFSET
def quota_key(resource): return f"resource:{resource}"


class Log:
    def __init__(self, path):
        self.mu = threading.RLock()
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.sagas = self.db                     # the saga log and the receipts share one durable store
        self.db.execute("CREATE TABLE IF NOT EXISTS receipts(request_id INTEGER PRIMARY KEY, body TEXT NOT NULL)")
        self.sagas.execute("CREATE TABLE IF NOT EXISTS sagas(request_id INTEGER PRIMARY KEY, resource INTEGER, start INTEGER, end INTEGER, now INTEGER, step TEXT, note TEXT)")

    def get(self, rq):
        with self.mu:
            r = self.sagas.execute("SELECT request_id, resource, start, end, now, step, note FROM sagas WHERE request_id=?", (rq,)).fetchone()
        return dict(zip(("request_id", "resource", "start", "end", "now", "step", "note"), r)) if r else None

    def begin(self, rq, resource, start, end, now):
        with self.mu: self.sagas.execute("INSERT INTO sagas VALUES (?, ?, ?, ?, ?, 'begun', NULL)", (rq, resource, start, end, now))

    def advance(self, rq, step, note=None):
        with self.mu: self.sagas.execute("UPDATE sagas SET step=?, note=? WHERE request_id=?", (step, note, rq))

    def record(self, rq, receipt):
        """A receipt is written once; a later write for the same request is ignored."""
        with self.mu: self.db.execute("INSERT OR IGNORE INTO receipts VALUES (?, ?)", (rq, json.dumps(receipt, sort_keys=True)))

    def finish(self, rq, receipt):
        """Write the receipt and end the saga in one transaction. Returns the receipt the client is told."""
        with self.mu:
            self.db.execute("BEGIN IMMEDIATE")
            self.record(rq, receipt)
            self.sagas.execute("UPDATE sagas SET step='done' WHERE request_id=?", (rq,))
            self.db.execute("COMMIT")
        return receipt

    def forget(self, rq):
        with self.mu: self.sagas.execute("DELETE FROM sagas WHERE request_id=?", (rq,))

    def receipt(self, rq):
        with self.mu: r = self.db.execute("SELECT body FROM receipts WHERE request_id=?", (rq,)).fetchone()
        return json.loads(r[0]) if r else None

    def unfinished(self):
        with self.mu: return [r[0] for r in self.sagas.execute("SELECT request_id FROM sagas WHERE step != 'done' ORDER BY request_id")]


class Coordinator:
    def __init__(self, log, booking, quota, budget=4.0):
        self.log, self.booking, self.quota, self.budget = log, booking, quota, budget
        self.locks = {}; self.mu = threading.Lock()

    def _lock(self, rq):
        with self.mu: return self.locks.setdefault(rq, threading.Lock())

    # ---- the client's call ----
    def reserve(self, rq, resource, start, end, now):
        """Returns (status, body). The body is the receipt with replayed: false when this call decided the reservation, true
        when it was already decided. 409: the request id was used for other parameters. 503: a component could not be reached
        within the budget; the saga stays in the log and the recovery duty finishes it."""
        with self._lock(rq):
            s = self.log.get(rq)
            if s is not None and (s["resource"], s["start"], s["end"], s["now"]) != (resource, start, end, now):
                return 409, {"error": "request id reused with other parameters"}
            if s is None: self.log.begin(rq, resource, start, end, now)
            return self._drive(rq, self.budget)

    # ---- the recovery duty ----
    def recover_all(self, budget=2.0):
        """Finish or compensate every saga in the log; sagas another thread is driving are left to it."""
        for rq in self.log.unfinished():
            lk = self._lock(rq)
            if lk.acquire(blocking=False):
                try: self._drive(rq, budget)
                finally: lk.release()

    # ---- driving one saga (the caller holds its lock) ----
    def _drive(self, rq, budget):
        deadline = time.monotonic() + budget; delay = 0.05
        s = self.log.get(rq)
        if s["step"] == "done": return 200, dict(self.log.receipt(rq), replayed=True)
        while True:
            try: out = self._step(self.log.get(rq))
            except Unavailable as e:
                if time.monotonic() + delay > deadline: return 503, {"error": "in progress", "request_id": rq, "detail": str(e)}
                time.sleep(delay); delay = min(delay * 2, 0.5); continue
            if out[0] == "done": return 200, dict(out[1], replayed=False)
            if out[0] == "error": return out[1], out[2]

    def _step(self, s):
        """One attempt at the saga's current step: ("go",) to continue, ("done", receipt), ("error", status, body); Unavailable when a call cannot be answered."""
        rq, res = s["request_id"], s["resource"]
        if s["step"] == "begun":
            code, b = self.booking.call("POST", f"/resources/{res}/bookings", {"request_id": rq, "start": s["start"], "end": s["end"]})
            if code != 200: self.log.forget(rq); return "error", code, b
            if b["outcome"] == "ACCEPTED": self.log.advance(rq, "booked"); return ("go",)
            r = {"request_id": rq, "outcome": b["outcome"], "resource": res}
            if b["outcome"] == "CONFLICT": r["conflicts_with"] = b["conflicts_with"]
            return "done", self.log.finish(rq, r)
        if s["step"] == "booked":
            code, b = self.quota.call("POST", "/acquire", {"request_id": rq, "key": quota_key(res), "now": s["now"]})
            if code == 200 and b["granted"]:
                return "done", self.log.finish(rq, {"request_id": rq, "outcome": "ACCEPTED", "resource": res, "booking_id": rq, "start": s["start"], "end": s["end"]})
            self.log.advance(rq, "denied", "quota refused" if code == 200 else f"quota: {(b or {}).get('error', code)}")
            return ("go",)
        if s["step"] == "denied":
            code, b = self.booking.call("POST", f"/bookings/{rq}/cancel", {"request_id": cancel_id(rq)})
            if code != 200: raise Unavailable(f"cancel of {rq}: {code}")
            return "done", self.log.finish(rq, {"request_id": rq, "outcome": "QUOTA_EXCEEDED", "resource": res, "booking_id": rq, "reason": s["note"]})
        raise AssertionError(s)
