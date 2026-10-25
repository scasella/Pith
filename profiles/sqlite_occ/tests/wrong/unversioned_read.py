"""Known-wrong OCC store 2/3, `unversioned_read`: profiles/sqlite_occ with ONE defect. The compare-and-swap is intact, but the version
it compares with is not the version of the state the decision was computed from: the state and its version are read by two statements,
and another operation can commit between them, so the swap succeeds against a state that is no longer current.
tests/test_occ.py requires the interleaving explorer to find a violation in it on every run."""
import json
from profiles.sqlite import core, codec
from profiles.sqlite_occ.repo import Repo as Occ


class Repo(Occ):
    def _snapshot(self, db, acct, req, op):
        # DEFECT: two statements. A commit between them leaves this read with the old state and the NEW version.
        row = db.execute("SELECT state FROM accounts WHERE id=?", (acct,)).fetchone()
        if row is None: raise core.UnknownAccount(acct)
        version = db.execute("SELECT version FROM accounts WHERE id=?", (acct,)).fetchone()[0]
        rec = db.execute("SELECT amount, body FROM receipts WHERE account_id=? AND request_id=? AND op=?", (acct, req, op)).fetchone()
        return codec.decode(json.loads(row[0])), version, ((rec[0], json.loads(rec[1])) if rec else None)
