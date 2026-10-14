"""service/app.py — HTTP layer (harness/SERVICE.md). Stdlib only."""
import json, re, threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from service.store import Invalid, Conflict, Missing
from service import workflow as W

OPS = ("edit", "submit", "approve", "reject", "publish")


def serve(store, port):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def send(self, code, body):
            data = json.dumps(body).encode(); self.send_response(code); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        def guarded(self, fn):
            try: self.send(*fn())
            except Conflict as e: self.send(409, {"error": str(e)})
            except Missing as e: self.send(404, {"error": f"unknown document {e}"})
            except (Invalid, ValueError, TypeError) as e: self.send(400, {"error": str(e)})
        def do_GET(self):
            path, _, q = self.path.partition("?")
            def fn():
                if path == "/actors": return 200, {"actors": store.actors()}
                if path == "/events": return 200, store.events(int((re.search(r"since=(\d+)", q) or [0, 0])[1]))
                if m := re.fullmatch(r"/documents/([^/]+)", path):
                    d = store.document(m[1]); return (200, d) if d else (404, {"error": "unknown document"})
                return 404, {"error": "not found"}
            self.guarded(fn)
        def do_POST(self):
            def fn():
                b = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"null")
                if not isinstance(b, dict): raise Invalid("body must be a JSON object")
                if self.path == "/actors": return 201, store.add_actor(b.get("id"), b.get("roles"))
                if self.path == "/documents": return 200, store.create(b.get("request_id"), b.get("id"), b.get("actor"), b.get("title"), b.get("body"), b["quorum"] if "quorum" in b else W.DEFAULT_QUORUM)
                if (m := re.fullmatch(r"/documents/([^/]+)/(\w+)", self.path)) and m[2] in OPS:
                    return 200, store.command(m[2], b.get("request_id"), m[1], b.get("actor"), b.get("revision"), b.get("body"))
                return 404, {"error": "not found"}
            self.guarded(fn)
    srv = ThreadingHTTPServer(("127.0.0.1", port), H); srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
