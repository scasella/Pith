"""handbook/reviews.py — the review workflow for policy documents: people with roles write revisions, approvers other
than the author approve the current revision until the document's quorum (chosen when it is created, 2 by default) is
reached, a publisher publishes. This is the workflow the project protects
with Pith (PITH.md); its rules are the pack's (pith.approval INTENT.md), and service/ exposes it to the judge.

Storage is the handbook's one database, normalised: people, review_docs (with each document's quorum), review_revisions, review_votes (each vote
bound to the revision it approved), review_requests (the idempotency record of every command) and review_log."""
import json, re

NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
ROLES = ("editor", "approver", "publisher")
DEFAULT_QUORUM = 2                 # a create without `quorum`; every document reviewed before quorums (service/migrate.py)
QUORUMS = range(2, 6)
NEEDS = {"submit": None, "approve": "approver", "reject": "approver", "publish": "publisher"}
FROM = {"submit": "draft", "approve": "in_review", "reject": "in_review", "publish": "approved"}
COMMANDS = ("edit",) + tuple(NEEDS)


class Invalid(ValueError): pass
class Conflict(ValueError): pass
class Unknown(KeyError): pass


def _name(x, what):
    if not isinstance(x, str) or not NAME.match(x): raise Invalid(f"{what} must match {NAME.pattern}")
    return x
def _int(x, what):
    if isinstance(x, bool) or not isinstance(x, int) or not 0 <= x < 2 ** 53: raise Invalid(f"{what} must be an integer in [0, 2^53)")
    return x
def _quorum(x):
    if isinstance(x, bool) or not isinstance(x, int) or x not in QUORUMS: raise Invalid("quorum must be an integer in [2, 5]")
    return x
def _text(x, what):
    if not isinstance(x, str) or len(x) > 10_000: raise Invalid(f"{what} must be a string of at most 10000 characters")
    return x


class Reviews:
    def __init__(self, db):
        self.db = db
        cols = [r[1] for r in db.query("PRAGMA table_info(review_docs)")]
        if cols and "quorum" not in cols: raise SystemExit("this database holds reviews from before per-document quorums: run service/migrate.py first")
        db.schema("CREATE TABLE IF NOT EXISTS people(id TEXT PRIMARY KEY, roles TEXT)",
                  "CREATE TABLE IF NOT EXISTS review_docs(id TEXT PRIMARY KEY, title TEXT, status TEXT, quorum INTEGER NOT NULL)",
                  "CREATE TABLE IF NOT EXISTS review_revisions(doc TEXT, rev INTEGER, author TEXT, body TEXT, PRIMARY KEY(doc, rev))",
                  "CREATE TABLE IF NOT EXISTS review_votes(doc TEXT, rev INTEGER, actor TEXT, PRIMARY KEY(doc, rev, actor))",
                  "CREATE TABLE IF NOT EXISTS review_requests(request_id INTEGER PRIMARY KEY, params TEXT, result TEXT)",
                  "CREATE TABLE IF NOT EXISTS review_log(seq INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT)")

    # ---- people
    def add_person(self, pid, roles):
        _name(pid, "id")
        if not isinstance(roles, list) or not all(r in ROLES for r in roles): raise Invalid("roles must be a list of editor, approver, publisher")
        roles = sorted(set(roles))
        with self.db.transaction() as c:
            if c.execute("SELECT 1 FROM people WHERE id=?", (pid,)).fetchone(): raise Conflict(f"person {pid} exists")
            c.execute("INSERT INTO people VALUES (?, ?)", (pid, json.dumps(roles))); self._log(c, type="actor.registered", actor=pid, roles=roles)
        return {"id": pid, "roles": roles}

    def people(self): return [{"id": i, "roles": json.loads(r)} for i, r in self.db.query("SELECT id, roles FROM people ORDER BY id")]

    # ---- reading
    def document(self, did):
        _name(did, "document id")
        with self.db.lock: return self._view(self.db.conn, did)

    def log(self, since=0): return [dict(json.loads(b), seq=s) for s, b in self.db.query("SELECT seq, body FROM review_log WHERE seq > ? ORDER BY seq", since)]

    def _view(self, c, did):
        d = c.execute("SELECT title, status, quorum FROM review_docs WHERE id=?", (did,)).fetchone()
        if not d: return None
        revs = [{"revision": r, "author": a, "body": b} for r, a, b in c.execute("SELECT rev, author, body FROM review_revisions WHERE doc=? ORDER BY rev", (did,))]
        votes = [{"revision": r, "actor": a} for r, a in c.execute("SELECT rev, actor FROM review_votes WHERE doc=? ORDER BY rev, actor", (did,))]
        cur = len(revs)
        return {"id": did, "title": d[0], "status": d[1], "revision": cur, "quorum": d[2], "revisions": revs, "approvals": votes,
                "current_votes": [v["actor"] for v in votes if v["revision"] == cur]}

    # ---- commands: each one transaction; a request id is recorded with its result and replayed
    def create(self, rq, did, actor, title, body, quorum=DEFAULT_QUORUM):
        _name(did, "id"); _name(actor, "actor"); _text(title, "title"); _text(body, "body"); _quorum(quorum)
        def decide(c):
            if c.execute("SELECT 1 FROM review_docs WHERE id=?", (did,)).fetchone(): raise Conflict(f"document {did} exists")
            if "editor" not in self._roles(c, actor): return "ROLE"
            c.execute("INSERT INTO review_docs VALUES (?, ?, 'draft', ?)", (did, title, quorum)); c.execute("INSERT INTO review_revisions VALUES (?, 1, ?, ?)", (did, actor, body))
        return self._command(rq, {"op": "create", "id": did, "actor": actor, "title": title, "body": body, "quorum": quorum}, did, decide)

    def command(self, op, rq, did, actor, revision=None, body=None):
        if op not in COMMANDS: raise Invalid(f"unknown command {op}")
        _name(did, "document id"); _name(actor, "actor")
        if op == "edit": _text(body, "body")
        else: _int(revision, "revision")
        params = {"op": op, "id": did, "actor": actor, **({"body": body} if op == "edit" else {"revision": revision})}
        return self._command(rq, params, did, lambda c: self._decide(c, op, did, actor, revision, body))

    def _decide(self, c, op, did, actor, revision, body):
        d = c.execute("SELECT status, quorum FROM review_docs WHERE id=?", (did,)).fetchone()
        if d is None: raise Unknown(did)
        status, quorum = d; roles = self._roles(c, actor)
        cur, author = c.execute("SELECT rev, author FROM review_revisions WHERE doc=? ORDER BY rev DESC LIMIT 1", (did,)).fetchone()
        if op == "edit":
            if "editor" not in roles: return "ROLE"
            if status == "published": return "WRONG_STATE"
            c.execute("INSERT INTO review_revisions VALUES (?, ?, ?, ?)", (did, cur + 1, actor, body)); return self._set(c, did, "draft")
        if NEEDS[op] and NEEDS[op] not in roles: return "ROLE"
        if revision != cur: return "STALE_REVISION"
        if status != FROM[op]: return "WRONG_STATE"
        if op == "submit": return "NOT_AUTHOR" if actor != author else self._set(c, did, "in_review")
        if op == "publish": return self._set(c, did, "published")
        if actor == author: return "SEPARATION_OF_DUTIES"                                  # approve and reject
        if op == "reject": return self._set(c, did, "rejected")
        if c.execute("SELECT 1 FROM review_votes WHERE doc=? AND rev=? AND actor=?", (did, cur, actor)).fetchone(): return "ALREADY_APPROVED"
        c.execute("INSERT INTO review_votes VALUES (?, ?, ?)", (did, cur, actor))
        votes = c.execute("SELECT COUNT(*) FROM review_votes WHERE doc=? AND rev=?", (did, cur)).fetchone()[0]     # this revision's votes only
        if votes >= quorum: self._set(c, did, "approved")

    def _command(self, rq, params, did, decide):
        _int(rq, "request_id")
        with self.db.transaction() as c:
            row = c.execute("SELECT params, result FROM review_requests WHERE request_id=?", (rq,)).fetchone()
            if row:
                if json.loads(row[0]) != params: raise Conflict(f"request_id {rq} was used for another command")
                return dict(json.loads(row[1]), replayed=True)
            reason = decide(c); view = self._view(c, did)
            result = {"request_id": rq, "outcome": "OK" if reason is None else "REFUSED", "reason": reason, "document": view}
            c.execute("INSERT INTO review_requests VALUES (?, ?, ?)", (rq, json.dumps(params), json.dumps(result)))
            self._log(c, type="command.decided", request_id=rq, command=params["op"], document=did, actor=params["actor"], outcome=result["outcome"], reason=reason)
            self._log(c, type="op.committed", request_id=rq, document=did, status=view and view["status"], revision=view and view["revision"])
            return dict(result, replayed=False)

    def _roles(self, c, pid):
        r = c.execute("SELECT roles FROM people WHERE id=?", (pid,)).fetchone(); return set(json.loads(r[0])) if r else set()
    def _set(self, c, did, status): c.execute("UPDATE review_docs SET status=? WHERE id=?", (status, did))
    def _log(self, c, **body): c.execute("INSERT INTO review_log(body) VALUES (?)", (json.dumps(body),))
