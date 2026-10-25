"""service/app.py — the quota component's HTTP API (coordinator contract: runtime/RUNTIME.md). Stdlib only."""
import json, threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlsplit, parse_qs
from limiter import InvalidArgument, ClockRegression
from service.ledger import Mismatch, KEY


def serve(ledger, port):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def send(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        def do_GET(self):
            u = urlsplit(self.path)
            if u.path == "/health": return self.send(200, {"ok": True})
            if u.path == "/grants":
                key = (parse_qs(u.query).get("key") or [""])[0]
                if not KEY.fullmatch(key): return self.send(400, {"error": "key"})
                return self.send(200, {"key": key, "grants": ledger.grants(key)})
            self.send(404, {"error": "not found"})
        def do_POST(self):
            if urlsplit(self.path).path != "/acquire": return self.send(404, {"error": "not found"})
            try:
                n = int(self.headers.get("Content-Length") or 0); b = json.loads(self.rfile.read(n) or b"null")
                if not isinstance(b, dict): raise InvalidArgument("body", "must be a JSON object")
                self.send(200, ledger.acquire(b.get("request_id"), b.get("key"), b.get("now")))
            except Mismatch as e: self.send(409, {"error": str(e)})
            except ClockRegression as e: self.send(409, {"error": "clock regression", "clock": e.clock})
            except (InvalidArgument, ValueError) as e: self.send(400, {"error": str(e)})
    srv = ThreadingHTTPServer(("127.0.0.1", port), H); srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
