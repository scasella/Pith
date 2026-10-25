"""
adapter/jsonrepo.py — build B's custom integration profile: one JSON document per repository, rewritten
atomically (write temp + fsync + rename) on every committed operation. Single in-process writer lock;
reads parse the last committed file (never a partial write). Event log lives in the same document, so
commit of state and events is one rename. Domain validation reuses the shipped validators; the oracle
is rebuilt from the event log on open. Must pass obligations/adapter/harness.py like any profile.

Contract authorization-and-posting/v3 (v0.12.0): every write's result is stored as its receipt in the same document
(so in the same rename as its events), and a retry returns it with replayed=true. The document records its schema
(3); a document written for the previous contract (no schema, no receipts) is refused until migrate() has upgraded
it, so an old retry can never miss its receipt.
"""
import json, os, tempfile, threading
from profiles.sqlite import core      # validators and the proven core loader; no storage code is shared
from profiles.sqlite.repo import seal, ZERO, check_decide_post, check_release_post, check_capture_post   # chain + runtime post-check helpers (pure functions)
import uuid

SCHEMA = 3
class UnmigratedState(RuntimeError): pass
class Refused(RuntimeError): pass

def _key(acct_id, req_id, op): return f"{acct_id}:{req_id}:{op}"

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
        self.lock = threading.RLock(); self.core = core.Core(); self.poster = core.Poster()
        if not os.path.exists(self.path): self._write({"schema": SCHEMA, "accounts": {}, "events": [], "receipts": {}})
        if self._read().get("schema") != SCHEMA: raise UnmigratedState(f"{self.path} was written for another contract: migrate it first (python3 -I service/migrate.py --db PATH)")
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
    def _record(self, doc, acct_id, req_id, op, body, amount=None):
        doc["receipts"][_key(acct_id, req_id, op)] = {"amount": amount, "body": body}
        return dict(body, replayed=False)
    def _receipt(self, doc, acct_id, req_id, op): return doc["receipts"].get(_key(acct_id, req_id, op))
    def _rebuild(self):
        self._oracle = {}
        for ev in self._read()["events"]:
            t, a = ev["type"], ev.get("account_id")
            if t == "account.created": self._oracle[a] = core.fresh_account(ev["limit"])
            elif t == "auth.decided": _, self._oracle[a] = self.core.Decide(self._oracle[a], core.Request(ev["request_id"], ev["amount"]))
            elif t == "reservation.released": self._oracle[a] = self.core.Release(self._oracle[a], ev["request_id"])
            elif t == "capture.posted":       self._oracle[a] = self.poster.Capture(self._oracle[a], ev["request_id"])
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
                rec = self._receipt(doc, acct_id, req_id, "authorize")
                if rec["amount"] != amount: raise core.ConflictingReplay(f"request {req_id} was {rec['amount']}")
                return dict(rec["body"], replayed=True)
            avail = core.available(a)
        with self.lock:                                   # DEFECT: the lock was released after reading the availability; the decision is made against that read, not the state at the commit
            self._op = uuid.uuid4().hex; doc = self._read()
            d, a2 = self.core.Decide(a, core.Request(req_id, amount)); check_decide_post(a, req_id, amount, d, a2); decision = "AUTHORIZED" if d.is_Authorized else "DECLINED"
            doc["accounts"][str(acct_id)] = _enc(a2)
            self._emit(doc, {"type": "auth.decided", "account_id": acct_id, "request_id": req_id, "amount": amount, "available_at_decision": avail, "decision": decision})
            if d.is_Authorized: self._emit(doc, {"type": "reservation.created", "account_id": acct_id, "request_id": req_id, "amount": amount})
            self._done(doc, acct_id, req_id, "authorize", a2)
            out = self._record(doc, acct_id, req_id, "authorize", {"request_id": req_id, "decision": decision, "available_at_decision": avail}, amount)
            self._write(doc); _, self._oracle[acct_id] = self.core.Decide(self._oracle[acct_id], core.Request(req_id, amount))
            return out
    def release(self, acct_id, req_id):
        acct_id, req_id = core.validate_id(acct_id, "account_id"), core.validate_id(req_id, "request_id")
        with self.lock:
            self._op = uuid.uuid4().hex; doc = self._read()
            if str(acct_id) not in doc["accounts"]: raise core.UnknownAccount(acct_id)
            a = _dec(doc["accounts"][str(acct_id)])
            if req_id not in core.holds(a):
                rec = self._receipt(doc, acct_id, req_id, "release")
                return dict(rec["body"], replayed=True) if rec else {"request_id": req_id, "released": False, "replayed": False}
            a2 = self.core.Release(a, req_id); check_release_post(a, req_id, a2); doc["accounts"][str(acct_id)] = _enc(a2)
            self._emit(doc, {"type": "reservation.released", "account_id": acct_id, "request_id": req_id}); self._done(doc, acct_id, req_id, "release", a2)
            out = self._record(doc, acct_id, req_id, "release", {"request_id": req_id, "released": True})
            self._write(doc); self._oracle[acct_id] = self.core.Release(self._oracle[acct_id], req_id)
            return out
    def capture(self, acct_id, req_id):
        acct_id, req_id = core.validate_id(acct_id, "account_id"), core.validate_id(req_id, "request_id")
        with self.lock:
            self._op = uuid.uuid4().hex; doc = self._read()
            if str(acct_id) not in doc["accounts"]: raise core.UnknownAccount(acct_id)
            a = _dec(doc["accounts"][str(acct_id)])
            if req_id not in core.holds(a):
                rec = self._receipt(doc, acct_id, req_id, "capture")
                return dict(rec["body"], replayed=True) if rec else {"request_id": req_id, "captured": False, "replayed": False}
            amount = core.holds(a)[req_id]; a2 = self.poster.Capture(a, req_id); check_capture_post(a, req_id, a2); doc["accounts"][str(acct_id)] = _enc(a2)
            self._emit(doc, {"type": "capture.posted", "account_id": acct_id, "request_id": req_id, "amount": amount}); self._done(doc, acct_id, req_id, "capture", a2)
            out = self._record(doc, acct_id, req_id, "capture", {"request_id": req_id, "captured": True, "amount": amount})
            self._write(doc); self._oracle[acct_id] = self.poster.Capture(self._oracle[acct_id], req_id)
            return out

    # -- reads ----------------------------------------------------------------
    def account(self, acct_id):
        acct_id = core.validate_id(acct_id, "account_id"); doc = self._read()
        if str(acct_id) not in doc["accounts"]: raise core.UnknownAccount(acct_id)
        a = _dec(doc["accounts"][str(acct_id)])
        return {"id": acct_id, "limit": int(a.limit), "posted": int(a.posted), "available": core.available(a), "holds": core.holds(a), "status": core.status(a)}
    def events(self, since=0): return [e for e in self._read()["events"] if e["seq"] > since]


def migrate(path):
    """Upgrade a document written under authorization-and-posting-core/v2 in place: one receipt per acknowledged write,
    from the event log (the only place version 2 kept them); accounts and events unchanged. A version 3 document is
    left as it is; anything else is refused and left untouched. Written with the same temp + fsync + rename."""
    if not os.path.isfile(path): raise Refused(f"{path} does not exist")
    try:
        with open(path) as f: doc = json.load(f)
    except (ValueError, UnicodeDecodeError) as e: raise Refused(f"{path} is not a document this adapter wrote ({e})")
    if not isinstance(doc, dict): raise Refused("unrecognised state")
    if doc.get("schema") == SCHEMA and set(doc) == {"schema", "accounts", "events", "receipts"}: return "already version 3: nothing to do"
    if set(doc) != {"accounts", "events"}: raise Refused(f"unrecognised state: keys {sorted(doc)}")
    prev = ZERO
    for e in doc["events"]:                                                         # the history the receipts come from must verify
        body = {k: v for k, v in e.items() if k not in ("hash", "seq")}
        if e.get("prev_hash") != prev or seal({k: v for k, v in body.items() if k != "prev_hash"}, prev)["hash"] != e.get("hash"): raise Refused(f"event {e.get('seq')}: the hash chain does not verify")
        prev = e["hash"]
    receipts = {}
    for e in doc["events"]:
        t, a, r = e["type"], e.get("account_id"), e.get("request_id")
        if t == "auth.decided": receipts[_key(a, r, "authorize")] = {"amount": e["amount"], "body": {"request_id": r, "decision": e["decision"], "available_at_decision": e["available_at_decision"]}}
        elif t == "reservation.released": receipts[_key(a, r, "release")] = {"amount": None, "body": {"request_id": r, "released": True}}
        elif t == "capture.posted": receipts[_key(a, r, "capture")] = {"amount": None, "body": {"request_id": r, "captured": True, "amount": e["amount"]}}
    for k, row in doc["accounts"].items():
        for r, s in row["status"]:
            for op in {"AUTH": ["authorize"], "DECL": ["authorize"], "REL": ["authorize", "release"], "POST": ["authorize", "capture"]}[s]:
                if _key(int(k), r, op) not in receipts: raise Refused(f"account {k} request {r} is {s} without the events that acknowledged it")
    doc = {"schema": SCHEMA, "accounts": doc["accounts"], "events": doc["events"], "receipts": receipts}
    tmp = path + ".tmp"
    with open(tmp, "w") as f: json.dump(doc, f); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)
    return f"migrated to version 3: {len(receipts)} receipts from {len(doc['events'])} events; history unchanged"
