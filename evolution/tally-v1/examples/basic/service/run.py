"""service/run.py — python -I service/run.py --port P --db PATH (harness/SERVICE.md). Stdlib only: SQLite, one
transaction per request, so a request is decided against the latest committed tally and survives a crash once acknowledged."""
import argparse, json, signal, sqlite3, threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

BOUND = 3
ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, required=True); ap.add_argument("--db", required=True); a = ap.parse_args()
db = sqlite3.connect(a.db, isolation_level=None, check_same_thread=False); lock = threading.Lock()
db.execute("PRAGMA journal_mode=WAL"); db.execute("PRAGMA synchronous=FULL")
db.execute("CREATE TABLE IF NOT EXISTS results(request_id INTEGER PRIMARY KEY, outcome TEXT, tally INTEGER)")


def tally(): return db.execute("SELECT COUNT(*) FROM results WHERE outcome='OK'").fetchone()[0]


def request(rq):
    with lock:
        db.execute("BEGIN IMMEDIATE")
        try:
            row = db.execute("SELECT outcome, tally FROM results WHERE request_id=?", (rq,)).fetchone()
            if row: db.execute("COMMIT"); return {"request_id": rq, "outcome": row[0], "tally": row[1], "replayed": True}
            n = tally(); outcome = "OK" if n < BOUND else "REFUSED"; n += outcome == "OK"
            db.execute("INSERT INTO results VALUES (?, ?, ?)", (rq, outcome, n)); db.execute("COMMIT")
            return {"request_id": rq, "outcome": outcome, "tally": n, "replayed": False}
        except BaseException: db.execute("ROLLBACK"); raise


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, code, body):
        data = json.dumps(body).encode(); self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        if self.path == "/tally":
            with lock: return self.send(200, {"tally": tally(), "bound": BOUND})
        self.send(404, {"error": "not found"})
    def do_POST(self):
        if self.path != "/requests": return self.send(404, {"error": "not found"})
        try: b = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"null")
        except ValueError: return self.send(400, {"error": "malformed JSON"})
        rq = b.get("request_id") if isinstance(b, dict) else None
        if isinstance(rq, bool) or not isinstance(rq, int) or not 0 <= rq < 2 ** 53: return self.send(400, {"error": "request_id must be an integer in [0, 2^53)"})
        self.send(200, request(rq))


srv = ThreadingHTTPServer(("127.0.0.1", a.port), H); srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
stop = threading.Event(); signal.signal(signal.SIGTERM, lambda *_: stop.set()); stop.wait(); srv.shutdown()
