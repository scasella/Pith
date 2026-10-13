"""service/store.py — SQLite persistence. One transaction (BEGIN IMMEDIATE) per command: load, decide, write, record."""
import json, re, sqlite3, threading
from service import workflow as W

NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
ROLES = {"editor", "approver", "publisher"}
class Invalid(ValueError): pass
class Conflict(ValueError): pass
class Missing(KeyError): pass


def name(x, what):
    if not isinstance(x, str) or not NAME.match(x): raise Invalid(f"{what} must match {NAME.pattern}")
    return x
def integer(x, what):
    if isinstance(x, bool) or not isinstance(x, int) or not 0 <= x < 2 ** 53: raise Invalid(f"{what} must be an integer in [0, 2^53)")
    return x
def quorum(x):
    if isinstance(x, bool) or not isinstance(x, int) or x not in W.QUORUMS: raise Invalid("quorum must be an integer in [2, 5]")
    return x
def text(x, what):
    if not isinstance(x, str) or len(x) > 10_000: raise Invalid(f"{what} must be a string of at most 10000 characters")
    return x


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL"); self.db.execute("PRAGMA synchronous=FULL")
        tables = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "docs" in tables and "meta" not in tables: raise SystemExit(f"{path} holds version 1 state: run service/migrate.py --db {path} first")
        for ddl in ("CREATE TABLE IF NOT EXISTS actors(id TEXT PRIMARY KEY, roles TEXT)", "CREATE TABLE IF NOT EXISTS docs(id TEXT PRIMARY KEY, body TEXT)",
                    "CREATE TABLE IF NOT EXISTS ops(request_id INTEGER PRIMARY KEY, params TEXT, result TEXT)", "CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT)",
                    "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)", "INSERT OR IGNORE INTO meta VALUES ('schema', '2')"):
            self.db.execute(ddl)
        self.lock = threading.Lock()

    def tx(self, fn):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try: r = fn(); self.db.execute("COMMIT"); return r
            except BaseException: self.db.execute("ROLLBACK"); raise
    def read(self, sql, *a):
        with self.lock: return self.db.execute(sql, a).fetchall()
    def emit(self, **b): self.db.execute("INSERT INTO events(body) VALUES (?)", (json.dumps(b),))

    def add_actor(self, aid, roles):
        name(aid, "id")
        if not isinstance(roles, list) or not all(r in ROLES for r in roles): raise Invalid("roles must be a list of editor, approver, publisher")
        def fn():
            if self.db.execute("SELECT 1 FROM actors WHERE id=?", (aid,)).fetchone(): raise Conflict(f"actor {aid} exists")
            self.db.execute("INSERT INTO actors VALUES (?, ?)", (aid, json.dumps(sorted(set(roles))))); self.emit(type="actor.registered", actor=aid, roles=sorted(set(roles)))
            return {"id": aid, "roles": sorted(set(roles))}
        return self.tx(fn)
    def actors(self): return [{"id": i, "roles": json.loads(r)} for i, r in self.read("SELECT id, roles FROM actors ORDER BY id")]
    def roles(self, aid):
        r = self.db.execute("SELECT roles FROM actors WHERE id=?", (aid,)).fetchone(); return set(json.loads(r[0])) if r else set()
    def document(self, did):
        name(did, "document id"); r = self.read("SELECT body FROM docs WHERE id=?", did)
        return W.view(json.loads(r[0][0])) if r else None
    def events(self, since=0): return [dict(json.loads(b), seq=s) for s, b in self.read("SELECT seq, body FROM events WHERE seq > ? ORDER BY seq", since)]

    def _cmd(self, rq, params, decide):
        integer(rq, "request_id")
        def fn():
            row = self.db.execute("SELECT params, result FROM ops WHERE request_id=?", (rq,)).fetchone()
            if row:
                if json.loads(row[0]) != params: raise Conflict(f"request_id {rq} was used for another command")
                return dict(json.loads(row[1]), replayed=True)
            reason, doc = decide()
            result = {"request_id": rq, "outcome": "OK" if reason is None else "REFUSED", "reason": reason, "document": W.view(doc)}
            self.db.execute("INSERT INTO ops VALUES (?, ?, ?)", (rq, json.dumps(params), json.dumps(result)))
            self.emit(type="command.decided", request_id=rq, command=params["op"], document=params["id"], actor=params["actor"], outcome=result["outcome"], reason=reason)
            self.emit(type="op.committed", request_id=rq, document=params["id"], status=doc and doc["status"], revision=doc and len(doc["revisions"]))
            return dict(result, replayed=False)
        return self.tx(fn)

    def create(self, rq, did, actor, title, body, q=W.DEFAULT_QUORUM):
        name(did, "id"); name(actor, "actor"); text(title, "title"); text(body, "body"); quorum(q)
        params = {"op": "create", "id": did, "actor": actor, "title": title, "body": body, "quorum": q}
        def decide():
            if self.db.execute("SELECT 1 FROM docs WHERE id=?", (did,)).fetchone(): raise Conflict(f"document {did} exists")
            reason, doc = W.create(self.roles(actor), actor, did, title, body, q)
            if doc: self.db.execute("INSERT INTO docs VALUES (?, ?)", (did, json.dumps(doc)))
            return reason, doc
        return self._cmd(rq, params, decide)

    def command(self, op, rq, did, actor, revision=None, body=None):
        name(did, "document id"); name(actor, "actor")
        if op == "edit": text(body, "body")
        else: integer(revision, "revision")
        params = {"op": op, "id": did, "actor": actor, **({"body": body} if op == "edit" else {"revision": revision})}
        def decide():
            row = self.db.execute("SELECT body FROM docs WHERE id=?", (did,)).fetchone()
            if row is None: raise Missing(did)
            reason, doc = W.apply(json.loads(row[0]), op, actor, self.roles(actor), revision, body)
            if reason is None: self.db.execute("UPDATE docs SET body=? WHERE id=?", (json.dumps(doc), did))
            return reason, doc
        return self._cmd(rq, params, decide)
