"""service/run.py — python -I service/run.py --port P --db PATH (harness/SERVICE.md, version 2), rewritten: no SQLite.
State is an append-only journal of JSON lines at PATH, each decision appended and fsynced before it is answered; the
in-memory index is rebuilt from the journal at start, so an acknowledged result survives SIGKILL. A torn last line
(a crash mid-append, never acknowledged) is discarded on start. service/migrate.py turns a version 1 SQLite database
into a journal."""
import argparse, json, os, re, signal, threading, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

BOUND = 3; NAME = re.compile(r"[a-z0-9-]{1,32}"); HEADER = {"journal": "counters/1"}
ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, required=True); ap.add_argument("--db", required=True); a = ap.parse_args()
lock = threading.Lock(); results = {}; tallies = {}


def load():
    if not os.path.exists(a.db) or os.path.getsize(a.db) == 0:
        with open(a.db, "w") as f: f.write(json.dumps(HEADER) + "\n"); f.flush(); os.fsync(f.fileno())
    with open(a.db, "rb") as f: lines = f.read().split(b"\n")
    if json.loads(lines[0]) != HEADER: raise SystemExit(f"{a.db}: not a counters journal (run service/migrate.py on a version 1 database)")
    good = len(lines[0]) + 1
    for ln in lines[1:]:
        try: r = json.loads(ln)
        except ValueError: break                                   # torn tail: never acknowledged
        results[r["request_id"]] = r; tallies[r["counter"]] = tallies.get(r["counter"], 0) + (r["outcome"] == "OK"); good += len(ln) + 1
    with open(a.db, "r+b") as f: f.truncate(min(good, os.path.getsize(a.db)))


load(); journal = open(a.db, "a")


def request(rq, counter):
    with lock:
        r = results.get(rq)
        if r: return dict(r, replayed=True)
        n = tallies.get(counter, 0); outcome = "OK" if n < BOUND else "REFUSED"; n += outcome == "OK"
        r = {"request_id": rq, "counter": counter, "outcome": outcome, "tally": n}
        journal.write(json.dumps(r) + "\n"); journal.flush(); os.fsync(journal.fileno())
        results[rq] = r; tallies[counter] = n
        return dict(r, replayed=False)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, code, body):
        data = json.dumps(body).encode(); self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        if u.path != "/tally": return self.send(404, {"error": "not found"})
        counter = urllib.parse.parse_qs(u.query, keep_blank_values=True).get("counter", ["default"])[-1]
        if not NAME.fullmatch(counter): return self.send(400, {"error": "bad counter name"})
        with lock: return self.send(200, {"counter": counter, "tally": tallies.get(counter, 0), "bound": BOUND})
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
