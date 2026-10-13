"""service/app.py — HTTP layer over the shipped Python profile (profiles/python/store.py). Stdlib only."""
import json, pathlib, re, threading, yaml
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from profiles.python.store import InvalidRequest, ConflictingReplay, Duplicate, Unknown

ROOT = pathlib.Path(__file__).resolve().parent.parent
UI = ROOT / (yaml.safe_load((ROOT / "app.manifest.yaml").read_text()).get("ui_entry") or "ui/index.html")


def serve(store, port):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        def body(self):
            n = int(self.headers.get("Content-Length") or 0); b = json.loads(self.rfile.read(n) or b"null")
            if not isinstance(b, dict): raise InvalidRequest("body must be a JSON object")
            return b
        def handle_errors(self, fn):
            try: self.send(*fn())
            except (InvalidRequest, ValueError, KeyError, TypeError) as e:
                if isinstance(e, ConflictingReplay) or isinstance(e, Duplicate): return self.send(409, {"error": str(e)})
                if isinstance(e, Unknown): return self.send(404, {"error": str(e)})
                self.send(400, {"error": str(e)})
        def do_GET(self):
            path, _, q = self.path.partition("?")
            def fn():
                if path == "/": return 200, UI.read_bytes(), "text/html; charset=utf-8"
                if path == "/resources": return 200, {"resources": store.resources()}
                if m := re.fullmatch(r"/resources/(\d+)", path):
                    r = store.resource(int(m[1])); return (200, r) if r else (404, {"error": "unknown resource"})
                if m := re.fullmatch(r"/bookings/(\d+)", path):
                    b = store.booking(int(m[1])); return (200, b) if b else (404, {"error": "unknown booking"})
                if path == "/events":
                    since = int((re.search(r"since=(\d+)", q) or [0, 0])[1]); return 200, store.events(since)
                return 404, {"error": "not found"}
            self.handle_errors(fn)
        def do_POST(self):
            def fn():
                b = self.body()
                if self.path == "/resources": return 201, store.create_resource(b.get("id"), b.get("name"), b.get("buffer", 0))
                if m := re.fullmatch(r"/resources/(\d+)/bookings", self.path): return 200, store.book(b.get("request_id"), int(m[1]), b.get("start"), b.get("end"))
                if m := re.fullmatch(r"/bookings/(\d+)/cancel", self.path): return 200, store.cancel(b.get("request_id"), int(m[1]))
                if m := re.fullmatch(r"/bookings/(\d+)/reschedule", self.path): return 200, store.reschedule(b.get("request_id"), int(m[1]), b.get("start"), b.get("end"))
                return 404, {"error": "not found"}
            self.handle_errors(fn)
    srv = ThreadingHTTPServer(("127.0.0.1", port), H); srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
