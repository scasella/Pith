"""service/drifted_repo.py — what a brownfield desk's own code looked like after somebody "optimised" it (validation/shadow.py).

The accepted club desk serves the shipped profile (profiles/sqlite/repo.py). This is the same store with ONE change in `authorize`:
the availability it reports (in the auth.decided event and in the receipt returned to the client) is read from a small cache that
keeps the account's availability as it was before the newest hold, once the account has three or more live holds ("busy accounts
are read from the cache"). The core still decides on the true state, so every decision, every hold and every account view is the
one the contract requires: with a few holds per account nothing differs at all, and the drift shows only as a stale figure in a
receipt and an event. A figure that crosses the amount makes the receipt contradict itself (DECLINED with more available than was
asked for).

The trigger is a property of the account's state (how many holds are live), not of a counter: a counter ("after the 20th
authorization") cannot survive shrinking, because a trace shrunk against the oracle keeps only the steps its last answer depends on,
and the replay would pass on the drifted service. This is the limit gate/trace.py states: a shrunk trace is a claim about the
oracle until a replay shows the candidate fails it too.

It is candidate code (service/), not a patch of profiles/: profiles/ is release policy, which the judge and the replay always take
from the release, so a patch there would be replaced by the pristine file the moment the candidate is assembled. A drift in the
deployment's own code is also how a deployment really drifts, and it is the honest case for the revocation draft: the deployed
artifact is not the one the evidence accepted (gate/deploy.py), so nothing about the release is revoked by it.
"""
from profiles.sqlite import core
from profiles.sqlite.repo import Repo as ShippedRepo, CorruptCore, check_decide_post

BUSY = 3                                           # live holds from which the cache is read


class Repo(ShippedRepo):
    def __init__(self, path=None):
        self._newest = {}                          # account -> the request of its newest hold (the cache's memory)
        super().__init__(path)

    def _cached_available(self, acct_id, a):
        true, holds = core.available(a), core.holds(a)
        newest = self._newest.get(acct_id)
        return true + holds[newest] if len(holds) >= BUSY and newest in holds else true       # the cache ignores the newest hold

    def authorize(self, acct_id, req_id, amount):                                              # the shipped authorize; the changed lines are marked
        acct_id, req_id, amount = core.validate_id(acct_id, "account_id"), core.validate_id(req_id, "request_id"), core.validate_amount(amount)
        def body():
            a = self._load(acct_id); st = core.status(a)
            if req_id in st:
                rec = self._receipt(acct_id, req_id, "authorize")
                if rec is None: raise CorruptCore(f"request {req_id} was decided but has no receipt")
                if rec[0] != amount: raise core.ConflictingReplay(f"request {req_id} was {rec[0]}, replay says {amount}")
                return dict(rec[1], replayed=True), None
            avail = self._cached_available(acct_id, a)                                         # CHANGED: was core.available(a)
            d, a2 = self.core.Decide(a, core.Request(req_id, amount))
            check_decide_post(a, req_id, amount, d, a2)
            decision = "AUTHORIZED" if d.is_Authorized else "DECLINED"
            if d.is_Authorized: self._newest[acct_id] = req_id                                 # CHANGED: the cache's memory
            self._store(acct_id, a2)
            self._emit({"type": "auth.decided", "account_id": acct_id, "request_id": req_id, "amount": amount, "available_at_decision": avail, "decision": decision})
            if d.is_Authorized: self._emit({"type": "reservation.created", "account_id": acct_id, "request_id": req_id, "amount": amount})
            self._committed(acct_id, req_id, "authorize", a2)
            def upd(): _, self._oracle[acct_id] = self.core.Decide(self._oracle[acct_id], core.Request(req_id, amount))
            return self._record(acct_id, req_id, "authorize", {"request_id": req_id, "decision": decision, "available_at_decision": avail}, amount), upd
        return self._tx(body)
