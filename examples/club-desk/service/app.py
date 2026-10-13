"""service/app.py — ring 2 HTTP boundary. Standard library + jsonschema. No logic: validate the body against the
generated OpenAPI schema, call the adapter, map its errors to status codes, serve the UI at /."""
import json, pathlib, threading, yaml, jsonschema
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from profiles.sqlite.repo import Repo
from profiles.sqlite.core import InvalidRequest, DuplicateAccount, ConflictingReplay, UnknownAccount

ROOT = pathlib.Path(__file__).resolve().parent.parent
OPENAPI = yaml.safe_load((ROOT / "gen/out/openapi.yaml").read_text())
S = OPENAPI["components"]["schemas"]
def validator(schema): return jsonschema.Draft202012Validator({**schema, "components": {"schemas": S}})
V_CREATE  = validator(OPENAPI["paths"]["/accounts"]["post"]["requestBody"]["content"]["application/json"]["schema"])
V_AUTH    = validator(S["AuthorizeRequest"])
V_RELEASE = validator(OPENAPI["paths"]["/accounts/{id}/release"]["post"]["requestBody"]["content"]["application/json"]["schema"])
V_CAPTURE = validator(OPENAPI["paths"]["/accounts/{id}/capture"]["post"]["requestBody"]["content"]["application/json"]["schema"])
UI = ROOT / (yaml.safe_load((ROOT / "app.manifest.yaml").read_text()).get("ui_entry") or "ui/index.html")

class APIHTTPServer(ThreadingHTTPServer):
    # The lifecycle harness overlaps eight writers with three paced readers. Keep
    # transient bursts in the accept queue while the threaded handlers start.
    request_queue_size = 64

def make_handler(repo):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        def _json(self, validator):
            n = int(self.headers.get("Content-Length") or 0); raw = self.rfile.read(n)
            try: body = json.loads(raw)
            except Exception: raise InvalidRequest("body is not JSON")
            err = next(validator.iter_errors(body), None)
            if err: raise InvalidRequest(f"schema: {err.message}")
            for k, v in body.items():
                if isinstance(v, bool): raise InvalidRequest(f"{k}: boolean is not an integer")
            return body
        def do_GET(self):
            u = urlparse(self.path); parts = u.path.strip("/").split("/")
            try:
                if u.path == "/": return self._send(200, UI.read_bytes(), "text/html; charset=utf-8")
                if parts == ["openapi.yaml"]: return self._send(200, (ROOT / "gen/out/openapi.yaml").read_bytes(), "text/yaml")
                if parts == ["events"]: return self._send(200, repo.events(int(parse_qs(u.query).get("since", ["0"])[0])))
                if len(parts) == 2 and parts[0] == "accounts": return self._send(200, repo.account(int(parts[1])))
                self._send(404, {"error": "not found"})
            except UnknownAccount: self._send(404, {"error": "no such account"})
            except (InvalidRequest, ValueError) as e: self._send(400, {"error": str(e)})
        def do_POST(self):
            parts = urlparse(self.path).path.strip("/").split("/")
            try:
                if parts == ["accounts"]:
                    b = self._json(V_CREATE); return self._send(201, repo.create_account(b["id"], b["limit"]))
                if len(parts) == 3 and parts[0] == "accounts" and parts[2] == "authorize":
                    b = self._json(V_AUTH); return self._send(200, repo.authorize(int(parts[1]), b["request_id"], b["amount"]))
                if len(parts) == 3 and parts[0] == "accounts" and parts[2] == "release":
                    b = self._json(V_RELEASE); return self._send(200, repo.release(int(parts[1]), b["request_id"]))
                if len(parts) == 3 and parts[0] == "accounts" and parts[2] == "capture":
                    b = self._json(V_CAPTURE); return self._send(200, repo.capture(int(parts[1]), b["request_id"]))
                self._send(404, {"error": "not found"})
            except UnknownAccount: self._send(404, {"error": "no such account"})
            except DuplicateAccount: self._send(409, {"error": "account exists"})
            except ConflictingReplay as e: self._send(409, {"error": str(e)})
            except (InvalidRequest, ValueError) as e: self._send(400, {"error": str(e)})
    return H

def serve(repo, port=0):
    srv = APIHTTPServer(("127.0.0.1", port), make_handler(repo))
    threading.Thread(target=srv.serve_forever, daemon=True).start(); return srv

if __name__ == "__main__":
    import sys
    srv = serve(Repo(sys.argv[1] if len(sys.argv) > 1 else None), 8080); print("auth-service on http://127.0.0.1:8080")
    try: threading.Event().wait()
    except KeyboardInterrupt: srv.shutdown()
