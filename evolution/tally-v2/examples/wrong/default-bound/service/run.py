"""service/run.py — python -I service/run.py --port P --db PATH (harness/SERVICE.md, version 2). Stdlib only: SQLite, one
transaction per request, so a request is decided against the latest committed tally of its counter and survives a crash
once acknowledged. service/migrate.py upgrades a version 1 database in place."""
import argparse, json, re, signal, sqlite3, sys, threading, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

BOUND = 3; NAME = re.compile(r"[a-z0-9-]{1,32}")
ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, required=True); ap.add_argument("--db", required=True); a = ap.parse_args()
db = sqlite3.connect(a.db, isolation_level=None, check_same_thread=False); lock = threading.Lock()
db.execute("PRAGMA journal_mode=WAL"); db.execute("PRAGMA synchronous=FULL")
cols = [r[1] for r in db.execute("PRAGMA table_info(results)")]
if cols and "counter" not in cols: sys.exit("version 1 database: run service/migrate.py first")
db.execute("CREATE TABLE IF NOT EXISTS results(request_id INTEGER PRIMARY KEY, outcome TEXT, tally INTEGER, counter TEXT NOT NULL DEFAULT 'default')")


def tally(counter): return db.execute("SELECT COUNT(*) FROM results WHERE outcome='OK' AND counter=?", (counter,)).fetchone()[0]


def request(rq, counter):
    with lock:
        db.execute("BEGIN IMMEDIATE")
        try:
            row = db.execute("SELECT outcome, tally, counter FROM results WHERE request_id=?", (rq,)).fetchone()
            if row: db.execute("COMMIT"); return {"request_id": rq, "counter": row[2], "outcome": row[0], "tally": row[1], "replayed": True}
            n = tally(counter); outcome = "OK" if tally("default") < BOUND else "REFUSED"; n += outcome == "OK"   # DEFECT: a version 1 leftover, only counter "default" is bounded
            db.execute("INSERT INTO results(request_id, outcome, tally, counter) VALUES (?, ?, ?, ?)", (rq, outcome, n, counter)); db.execute("COMMIT")
            return {"request_id": rq, "counter": counter, "outcome": outcome, "tally": n, "replayed": False}
        except BaseException: db.execute("ROLLBACK"); raise


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, code, body):
        data = json.dumps(body).encode(); self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        if u.path != "/tally": return self.send(404, {"error": "not found"})
        q = urllib.parse.parse_qs(u.query, keep_blank_values=True); counter = q.get("counter", ["default"])[-1]
        if not NAME.fullmatch(counter): return self.send(400, {"error": "bad counter name"})
        with lock: return self.send(200, {"counter": counter, "tally": tally(counter), "bound": BOUND})
    def do_POST(self):
        if self.path != "/requests": return self.send(404, {"error": "not found"})
        try: b = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"null")
        except ValueError: return self.send(400, {"error": "malformed JSON"})
        rq = b.get("request_id") if isinstance(b, dict) else None
        if isinstance(rq, bool) or not isinstance(rq, int) or not 0 <= rq < 2 ** 53: return self.send(400, {"error": "request_id must be an integer in [0, 2^53)"})
        counter = b.get("counter", "default")
        if not isinstance(counter, str) or not NAME.fullmatch(counter): return self.send(400, {"error": "bad counter name"})
        self.send(200, request(rq, counter))


srv = ThreadingHTTPServer(("127.0.0.1", a.port), H); srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
stop = threading.Event(); signal.signal(signal.SIGTERM, lambda *_: stop.set()); stop.wait(); srv.shutdown()
