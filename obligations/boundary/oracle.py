#!/usr/bin/env python3
"""
obligations/boundary/oracle.py — the offline reference oracle of the service contract. FROZEN.

What a conforming service answers to a sequence of operations, computed offline with the verified core (the translation
in kernel/core/py/authcore-py, loaded the way profiles/sqlite/core.py loads it) and nothing else: no server, no database,
no clock, no randomness. The pack declares it as `traces.oracle`; the evaluator uses it to shrink a counterexample to the
fewest operations that still expect the same answer (gate/shrink.py, docs/rfc/0007 § 5) and never runs the candidate to
do it. It is also how a trace harvested from a running service is replayed offline.

    echo '{"steps": [...]}' | python3 obligations/boundary/oracle.py      ->   {"outcomes": [...]}      one outcome per step

A step is {"action", "args"} and nothing else is read from it (a harness may add "step", "observed", "expected"):

    create_account   {account, limit}            outcome {id, limit}
    authorize        {account, request, amount}  outcome {request_id, decision, available_at_decision, replayed}
    release          {account, request}          outcome {request_id, released, replayed}
    capture          {account, request}          outcome {request_id, captured, amount?, replayed}

An answer that is a refusal is {"status": N}: 400 for input outside the proof's domain (profiles/sqlite/core.py), 404 for an
unknown account, 409 for a duplicate account or a replay of a request with a different amount. Every other answer is the
body the generated API (obligations/boundary/generate.py) requires:

  - a decision is the core's, taken against the availability of the same step;
  - every write that changed state is recorded as the receipt of that operation on that request, and a retry of the same
    operation returns it with replayed: true (record Receipts): a release that it released, a capture that it captured
    and the amount, an authorization its decision, declined included;
  - a release or capture with nothing to act on changed nothing: {released|captured: false, replayed: false}, no receipt, so
    it is never "retried" into a receipt it did not earn.
"""
import json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from profiles.sqlite import core as C          # loads the translated verified core and the domain the proof assumes

OPS = ("create_account", "authorize", "release", "capture")


class Oracle:
    def __init__(self):
        self.core, self.poster = C.Core(), C.Poster()
        self.accounts = {}                       # account id -> the core's Account value
        self.receipts = {}                       # (account, request, operation) -> (amount, body)

    # -- receipts ---------------------------------------------------------------------------------------------
    def receipt(self, acct, req, op): return self.receipts.get((acct, req, op))
    def record(self, acct, req, op, body, amount=None):
        self.receipts[(acct, req, op)] = (amount, body)
        return dict(body, replayed=False)

    # -- one step ---------------------------------------------------------------------------------------------
    def step(self, s):
        op, args = s["action"], s["args"]
        if op not in OPS: raise ValueError(f"unknown action {op!r}")
        try: return getattr(self, op)(**args)
        except C.InvalidRequest: return {"status": 400}
        except C.UnknownAccount: return {"status": 404}
        except (C.DuplicateAccount, C.ConflictingReplay): return {"status": 409}

    def _account(self, acct):
        if acct not in self.accounts: raise C.UnknownAccount(acct)
        return self.accounts[acct]

    def create_account(self, account, limit):
        account, limit = C.validate_id(account, "account_id"), C.validate_limit(limit)
        if account in self.accounts: raise C.DuplicateAccount(account)
        self.accounts[account] = C.fresh_account(limit)
        return {"id": account, "limit": limit}

    def authorize(self, account, request, amount):
        account, request, amount = C.validate_id(account, "account_id"), C.validate_id(request, "request_id"), C.validate_amount(amount)
        a = self._account(account)
        if request in C.status(a):                                               # a retry: the recorded receipt, the core is not called
            rec = self.receipt(account, request, "authorize")
            if rec[0] != amount: raise C.ConflictingReplay(request)
            return dict(rec[1], replayed=True)
        avail = C.available(a)
        d, self.accounts[account] = self.core.Decide(a, C.Request(request, amount))
        return self.record(account, request, "authorize",
                           {"request_id": request, "decision": "AUTHORIZED" if d.is_Authorized else "DECLINED", "available_at_decision": avail}, amount)

    def release(self, account, request):
        account, request = C.validate_id(account, "account_id"), C.validate_id(request, "request_id")
        a = self._account(account)
        if request not in C.holds(a):
            rec = self.receipt(account, request, "release")
            return dict(rec[1], replayed=True) if rec else {"request_id": request, "released": False, "replayed": False}
        self.accounts[account] = self.core.Release(a, request)
        return self.record(account, request, "release", {"request_id": request, "released": True})

    def capture(self, account, request):
        account, request = C.validate_id(account, "account_id"), C.validate_id(request, "request_id")
        a = self._account(account)
        if request not in C.holds(a):
            rec = self.receipt(account, request, "capture")
            return dict(rec[1], replayed=True) if rec else {"request_id": request, "captured": False, "replayed": False}
        amount = C.holds(a)[request]
        self.accounts[account] = self.poster.Capture(a, request)
        return self.record(account, request, "capture", {"request_id": request, "captured": True, "amount": amount})


def run(steps, oracle=None):
    """The outcomes of a step sequence, one per step, on a fresh oracle (or the one given)."""
    o = oracle or Oracle()
    return [o.step(s) for s in steps]


def main():
    print(json.dumps({"outcomes": run(json.load(sys.stdin)["steps"])}, sort_keys=True))


if __name__ == "__main__":
    main()
