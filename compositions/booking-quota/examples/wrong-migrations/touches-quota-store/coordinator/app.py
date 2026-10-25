"""coordinator/app.py — the coordinator's HTTP API (runtime/RUNTIME.md). Stdlib only."""
import json, re, threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from saga import CANCEL_OFFSET

MAX53 = 2 ** 53


def whole(x, hi): return type(x) is int and 0 <= x < hi


def serve(coord, port):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def send(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        def do_GET(self):
            if self.path == "/health": return self.send(200, {"ok": True})
            if m := re.fullmatch(r"/reservations/(\d+)", self.path):
                r = coord.log.receipt(int(m[1]))
                return self.send(200, r) if r else self.send(404, {"error": "no receipt"})
            self.send(404, {"error": "not found"})
        def do_POST(self):
            if self.path != "/reservations": return self.send(404, {"error": "not found"})
            try:
                n = int(self.headers.get("Content-Length") or 0); b = json.loads(self.rfile.read(n) or b"null")
            except ValueError: return self.send(400, {"error": "body must be JSON"})
            if not isinstance(b, dict) or not (whole(b.get("request_id"), CANCEL_OFFSET) and all(whole(b.get(k), MAX53) for k in ("resource", "start", "end", "now"))):
                return self.send(400, {"error": "request_id (below 2^52), resource, start, end and now must be integers in [0, 2^53)"})
            self.send(*coord.reserve(b["request_id"], b["resource"], b["start"], b["end"], b["now"]))
    srv = ThreadingHTTPServer(("127.0.0.1", port), H); srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
