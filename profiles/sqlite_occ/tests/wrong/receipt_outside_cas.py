"""Known-wrong OCC store 3/3, `receipt_outside_cas`: profiles/sqlite_occ with ONE defect. The idempotency question (is this request
already decided? is there a receipt?) is asked once, before the commit transaction, and not again: not inside the transaction, and not
when a lost compare-and-swap sends the operation back to read. A retry that raced its own original therefore decides the request a
second time instead of returning the receipt the other commit recorded.
tests/test_occ.py requires the interleaving explorer to find a violation in it on every run."""
from profiles.sqlite_occ.repo import Repo as Occ, RETRY_BUDGET, OccRetriesExhausted


class Repo(Occ):
    def _recheck(self, db, acct, req, op):
        return None                                           # DEFECT (1 of 2): no receipt check inside the commit transaction

    def _run(self, acct, req, op, check, compute, replay):
        db = self._connect()
        try:
            a, version, rec = self._snapshot(db, acct, req, op)
            done = check(a, rec)                              # DEFECT (2 of 2): the idempotency check, made here once, before the transaction
            if done is not None: return done
            for attempt in range(RETRY_BUDGET):
                done = self._commit(db, acct, req, op, version, compute(a), replay)
                if done is not None: return done[0]
                a, version, rec = self._snapshot(db, acct, req, op)       # a lost compare-and-swap reads again, but never asks the question again
        finally: db.close()
        raise OccRetriesExhausted("retry budget exhausted")
