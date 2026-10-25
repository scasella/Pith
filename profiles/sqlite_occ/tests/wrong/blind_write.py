"""Known-wrong OCC store 1/3, `blind_write`: profiles/sqlite_occ with ONE defect. The commit replaces the account's state without
asking whether it is still the state the decision was computed from, so an operation that read before another committed overwrites
that commit: a lost update (a hold released and then back, a decision made against availability that no longer exists).
tests/test_occ.py requires the interleaving explorer to find a violation in it on every run."""
from profiles.sqlite_occ.repo import Repo as Occ


class Repo(Occ):
    def _cas(self, db, acct, version, state):
        # DEFECT: no `AND version = ?`: the update always lands, whatever committed since the read
        return db.execute("UPDATE accounts SET state=?, version=version+1 WHERE id=?", (state, acct)).rowcount == 1
