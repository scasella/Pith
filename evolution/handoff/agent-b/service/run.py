"""service/run.py — tally/v2 HTTP service (harness/SERVICE.md). Stdlib only.
Every request is decided and committed inside one SQLite transaction under a process-wide lock, so the bound holds under
concurrency and an acknowledged result survives SIGKILL."""
import argparse, json, os, re, signal, sqlite3, sys, threading, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store

NAME = re.compile(r"[a-z0-9-]{1,32}")
MAX_ID = 2 ** 53


def valid_name(c): return isinstance(c, str) and NAME.fullmatch(c) is not None


LOG_LOCK = threading.Lock()


def log_request(rq, counter, outcome, replayed, error=None):
    """Operator log: one JSON line on stderr per POST /requests. Never affects the answer."""
    rec = {"request_id": rq, "counter": counter, "outcome": outcome, "replayed": replayed}
    if error is not None: rec["error"] = error
    try:
        line = json.dumps(rec, separators=(",", ":")) + "\n"
        with LOG_LOCK:
            sys.stderr.write(line); sys.stderr.flush()
    except Exception:
        pass


class Tally:
    def __init__(self, path):
        self.con = store.connect(path); self.lock = threading.Lock()
        v = store.schema_version(self.con)
        if v not in (None, store.SCHEMA_VERSION):
            raise SystemExit(f"state at {path} is schema version {v!r}; run service/migrate.py")
        if v is None:
            tables = {r[0] for r in self.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables: raise SystemExit(f"state at {path} is not tally/v2 state (tables {sorted(tables)}); run service/migrate.py")
        store.init(self.con)

    def tally(self, counter):
        with self.lock:
            row = self.con.execute("SELECT tally FROM counters WHERE name=?", (counter,)).fetchone()
        return row[0] if row else 0

    def request(self, rq, counter):
        with self.lock:
            con = self.con; con.execute("BEGIN IMMEDIATE")
            try:
                row = con.execute("SELECT counter, outcome, tally FROM results WHERE request_id=?", (rq,)).fetchone()
                if row:
                    con.execute("ROLLBACK")
                    return {"request_id": rq, "counter": row[0], "outcome": row[1], "tally": row[2], "replayed": True}
                cur = con.execute("SELECT tally FROM counters WHERE name=?", (counter,)).fetchone()
                t = cur[0] if cur else 0
                if t < store.BOUND:
                    t += 1; outcome = "OK"
                    con.execute("INSERT INTO counters(name, tally) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET tally=excluded.tally", (counter, t))
                else:
                    outcome = "REFUSED"
                con.execute("INSERT INTO results(request_id, counter, outcome, tally) VALUES (?, ?, ?, ?)", (rq, counter, outcome, t))
                con.execute("COMMIT")
            except BaseException:
                try: con.execute("ROLLBACK")
                except sqlite3.Error: pass
                raise
            return {"request_id": rq, "counter": counter, "outcome": outcome, "tally": t, "replayed": False}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass

    def send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data)))
        self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        if u.path != "/tally": return self.send(404, {"error": "not found"})
        q = urllib.parse.parse_qs(u.query, keep_blank_values=True)
        if set(q) - {"counter"} or len(q.get("counter", [None])) != 1: return self.send(400, {"error": "bad query"})
        c = q.get("counter", [store.DEFAULT])[0]
        if not valid_name(c): return self.send(400, {"error": "bad counter"})
        self.send(200, {"counter": c, "tally": self.server.tally.tally(c), "bound": store.BOUND})

    def do_POST(self):
        if urllib.parse.urlsplit(self.path).path != "/requests": return self.send(404, {"error": "not found"})
        rq = c = None
        def bad(err):
            log_request(rq, c, None, None, err)
            return self.send(400, {"error": err})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n)) if n > 0 else None
        except (ValueError, UnicodeDecodeError):
            return bad("bad json")
        if not isinstance(body, dict) or set(body) - {"request_id", "counter"}: return bad("bad body")
        rq = body.get("request_id")
        if type(rq) is not int or not 0 <= rq < MAX_ID: rq = None; return bad("bad request_id")
        c = body.get("counter", store.DEFAULT)
        if not valid_name(c): c = None; return bad("bad counter")
        r = self.server.tally.request(rq, c)
        log_request(r["request_id"], r["counter"], r["outcome"], r["replayed"])
        self.send(200, r)

    def do_PUT(self): self.send(405, {"error": "method not allowed"})
    do_DELETE = do_PATCH = do_PUT


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, required=True); ap.add_argument("--db", required=True)
    a = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler); srv.daemon_threads = True
    srv.tally = Tally(a.db)
    def term(*_): threading.Thread(target=srv.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, term)
    try: srv.serve_forever()
    finally: srv.server_close()


if __name__ == "__main__":
    main()
