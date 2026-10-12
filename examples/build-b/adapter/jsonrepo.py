"""
adapter/jsonrepo.py — build B's custom integration profile: one JSON document per repository, rewritten
atomically (write temp + fsync + rename) on every committed operation. Single in-process writer lock;
reads parse the last committed file (never a partial write). Event log lives in the same document, so
commit of state and events is one rename. Domain validation reuses the shipped validators; the oracle
is rebuilt from the event log on open. Must pass obligations/adapter/harness.py like any profile.
"""
import json, os, tempfile, threading
from profiles.sqlite import core      # validators and the proven core loader; no storage code is shared
from profiles.sqlite.repo import seal, ZERO, check_decide_post, check_release_post   # chain + runtime post-check helpers (pure functions)
import uuid

def _enc(a): return {"limit": int(a.limit), "posted": int(a.posted), "holds": sorted((int(k), int(v)) for k, v in a.holds.items), "status": sorted((int(k), core.STATUS_NAME[v]) for k, v in a.status.items)}
def _dec(row):
    import _dafny
    limit, posted = core.validate_limit(row["limit"]), core.validate_limit(row["posted"])
    holds = {core.validate_id(k): core.validate_amount(v) for k, v in row["holds"]}
    status = {core.validate_id(k): core.NAME_STATUS[s] for k, s in row["status"]}
    if posted + sum(holds.values()) > limit or set(holds) != {k for k, s in status.items() if s == core.Auth}: raise core.InvalidRequest("stored state invalid")
    return core.Account(limit, posted, _dafny.Map(holds), _dafny.Map(status))

class Repo:
    def __init__(self, path=None):
        self.path = path or os.path.join(tempfile.mkdtemp(prefix="jsonrepo-"), "state.json")
        self.lock = threading.RLock(); self.core = core.Core()
        if not os.path.exists(self.path): self._write({"accounts": {}, "events": []})
        self._oracle = {}; self._rebuild()
    def close(self): pass
    # -- storage ------------------------------------------------------------
    def _read(self):
        with open(self.path) as f: return json.load(f)
    def _write(self, doc):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f: json.dump(doc, f); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, self.path)
    def _emit(self, doc, ev):
        prev = doc["events"][-1]["hash"] if doc["events"] else ZERO
        ev = seal(dict(ev, producer="auth-service", op_id=self._op), prev); ev["seq"] = len(doc["events"]) + 1; doc["events"].append(ev)
    def _done(self, doc, acct_id, req_id, op, a):
        self._emit(doc, {"type": "op.committed", "account_id": acct_id, "request_id": req_id, "op": op,
                         "state_after": {"limit": int(a.limit), "posted": int(a.posted), "reserved": sum(core.holds(a).values())}})
    def _rebuild(self):
        self._oracle = {}
        for ev in self._read()["events"]:
            t, a = ev["type"], ev.get("account_id")
            if t == "account.created": self._oracle[a] = core.fresh_account(ev["limit"])
            elif t == "auth.decided": _, self._oracle[a] = self.core.Decide(self._oracle[a], core.Request(ev["request_id"], ev["amount"]))
            elif t == "reservation.released": self._oracle[a] = self.core.Release(self._oracle[a], ev["request_id"])
    def verify_replay(self):
        doc = self._read(); diffs = []
        for k, row in doc["accounts"].items():
            a = int(k); stored = _enc(_dec(row)); oracle = _enc(self._oracle[a]) if a in self._oracle else None
            if stored != oracle: diffs.append({"account": a, "stored": stored, "oracle": oracle})
        return diffs
    # -- operations -----------------------------------------------------------
    def create_account(self, acct_id, limit):
        acct_id, limit = core.validate_id(acct_id, "account_id"), core.validate_limit(limit)
        with self.lock:
            self._op = uuid.uuid4().hex; doc = self._read()
            if str(acct_id) in doc["accounts"]: raise core.DuplicateAccount(acct_id)
            doc["accounts"][str(acct_id)] = _enc(core.fresh_account(limit))
            self._emit(doc, {"type": "account.created", "account_id": acct_id, "limit": limit}); self._done(doc, acct_id, None, "create_account", core.fresh_account(limit))
            self._write(doc); self._oracle[acct_id] = core.fresh_account(limit)
            return {"id": acct_id, "limit": limit}
    def authorize(self, acct_id, req_id, amount):
        acct_id, req_id, amount = core.validate_id(acct_id, "account_id"), core.validate_id(req_id, "request_id"), core.validate_amount(amount)
        with self.lock:
            self._op = uuid.uuid4().hex; doc = self._read()
            if str(acct_id) not in doc["accounts"]: raise core.UnknownAccount(acct_id)
            a = _dec(doc["accounts"][str(acct_id)])
            if req_id in core.status(a):
                rec = next(e for e in doc["events"] if e["type"] == "auth.decided" and e["account_id"] == acct_id and e["request_id"] == req_id)
                if rec["amount"] != amount: raise core.ConflictingReplay(f"request {req_id} was {rec['amount']}")
                return {"request_id": req_id, "decision": rec["decision"], "available_at_decision": rec["available_at_decision"], "replayed": True}
            avail = core.available(a); d, a2 = self.core.Decide(a, core.Request(req_id, amount)); check_decide_post(a, req_id, amount, d, a2); decision = "AUTHORIZED" if d.is_Authorized else "DECLINED"
            doc["accounts"][str(acct_id)] = _enc(a2)
            self._emit(doc, {"type": "auth.decided", "account_id": acct_id, "request_id": req_id, "amount": amount, "available_at_decision": avail, "decision": decision})
            if d.is_Authorized: self._emit(doc, {"type": "reservation.created", "account_id": acct_id, "request_id": req_id, "amount": amount})
            self._done(doc, acct_id, req_id, "authorize", a2)
            self._write(doc); _, self._oracle[acct_id] = self.core.Decide(self._oracle[acct_id], core.Request(req_id, amount))
            return {"request_id": req_id, "decision": decision, "available_at_decision": avail, "replayed": False}
    def release(self, acct_id, req_id):
        acct_id, req_id = core.validate_id(acct_id, "account_id"), core.validate_id(req_id, "request_id")
        with self.lock:
            self._op = uuid.uuid4().hex; doc = self._read()
            if str(acct_id) not in doc["accounts"]: raise core.UnknownAccount(acct_id)
            a = _dec(doc["accounts"][str(acct_id)])
            if req_id not in core.holds(a): return {"request_id": req_id, "released": False}
            a2 = self.core.Release(a, req_id); check_release_post(a, req_id, a2); doc["accounts"][str(acct_id)] = _enc(a2)
            self._emit(doc, {"type": "reservation.released", "account_id": acct_id, "request_id": req_id}); self._done(doc, acct_id, req_id, "release", a2)
            self._write(doc); self._oracle[acct_id] = self.core.Release(self._oracle[acct_id], req_id)
            return {"request_id": req_id, "released": True}
    # -- reads ----------------------------------------------------------------
    def account(self, acct_id):
        acct_id = core.validate_id(acct_id, "account_id"); doc = self._read()
        if str(acct_id) not in doc["accounts"]: raise core.UnknownAccount(acct_id)
        a = _dec(doc["accounts"][str(acct_id)])
        return {"id": acct_id, "limit": int(a.limit), "posted": int(a.posted), "available": core.available(a), "holds": core.holds(a), "status": core.status(a)}
    def events(self, since=0): return [e for e in self._read()["events"] if e["seq"] > since]
