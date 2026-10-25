"""
obligations/app/faultproxy.py — a judge-owned HTTP proxy between the browser and the candidate service. FROZEN.

The interaction obligations (UI-CONTRACT.md § Interaction obligations) need responses that are delayed, lost or
failed, with every other request reaching the real service unchanged. The browser loads the application through
this proxy, so the page under test runs unmodified: no injected script, no mocked fetch. Faults are programmed only
from the judge's process (Python calls on FaultProxy), never over HTTP, so the page cannot switch them off.

A fault matches one (method, path) pair and can:
  * delay      — hold the request this many seconds before forwarding it (reordering of responses)
  * status     — answer with this status instead of the service's response
  * forward    — with status: still forward the request first, so the service commits and the response is lost
  * times      — apply to this many matching requests, then expire (None: until cleared)
Every request is logged with whether a fault touched it; the log is evidence, the page never sees it.

v0.13.0 (docs/rfc/0007-autonomous-assurance-and-runtime-composition.md § 3): the same proxy stands in front of each
component of a runtime composition, where a fault must land between the steps of a cross-component operation. Added,
all optional, so the interaction obligations above are unchanged:
  * a path may contain `*` (matched with fnmatch); an exact path is still looked up first
  * sever      — "before": close the connection without forwarding or answering (the call never arrives);
                 "after": forward, let the service commit, then close without answering (the answer is lost)
  * hook, hook_at — a judge callable run when a matching request arrives ("request") or after the service answered
                 and before the answer is relayed ("response"); the driver uses it to kill a process at that instant
PUT, DELETE and PATCH are proxied like GET and POST.
"""
import fnmatch, http.client, json, socket, threading, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FaultProxy:
    def __init__(self, upstream: str):
        self.upstream = upstream.rstrip("/")
        self.faults = {}; self.log = []; self._lock = threading.Lock(); self.srv = None

    # ---- programming (judge only) ----
    def fault(self, method, path, status=None, delay=0.0, forward=False, times=None, message="judge-injected fault", sever=None, hook=None, hook_at="request"):
        if sever not in (None, "before", "after"): raise ValueError("sever must be None, 'before' or 'after'")
        if hook_at not in ("request", "response"): raise ValueError("hook_at must be 'request' or 'response'")
        with self._lock:
            self.faults[(method, path)] = {"status": status, "delay": delay, "forward": forward, "times": times, "message": message,
                                           "sever": sever, "hook": hook, "hook_at": hook_at}

    def clear(self):
        with self._lock: self.faults.clear()

    def requests(self, method=None):
        with self._lock: return [r for r in self.log if method is None or r["method"] == method]

    def _take(self, method, path):
        with self._lock:
            key = (method, path) if (method, path) in self.faults else \
                  next((k for k in self.faults if k[0] == method and "*" in k[1] and fnmatch.fnmatchcase(path, k[1])), None)
            f = self.faults.get(key) if key else None
            if f is None: return None
            if f["times"] is not None:
                f["times"] -= 1
                if f["times"] <= 0: self.faults.pop(key)
            return dict(f)

    # ---- serving ----
    def start(self):
        proxy = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def _handle(self, method):
                n = int(self.headers.get("Content-Length") or 0); body = self.rfile.read(n) if n else None
                path = self.path.split("?", 1)[0]
                f = proxy._take(method, path)
                if f and f["delay"]: time.sleep(f["delay"])
                if f and f.get("hook") and f.get("hook_at") == "request": f["hook"]({"method": method, "path": self.path})
                status, data, ctype = None, b"", "application/json"
                if f and f.get("sever") == "before": return self._sever(method, body, f, None)
                if not f or f["status"] is None or f["forward"] or f.get("sever") == "after":
                    req = urllib.request.Request(proxy.upstream + self.path, data=body, method=method,
                                                 headers={"Content-Type": self.headers.get("Content-Type") or "application/json"})
                    try:
                        with urllib.request.urlopen(req, timeout=15) as r: status, data, ctype = r.status, r.read(), r.headers.get("Content-Type") or ctype
                    except urllib.error.HTTPError as e: status, data, ctype = e.code, e.read(), e.headers.get("Content-Type") or ctype
                    except (urllib.error.URLError, http.client.HTTPException, OSError):
                        # the service died or dropped the call (a crash the judge caused, for instance): the client sees what it
                        # would have seen without the proxy, a connection closed without an answer; the log records it
                        return self._sever(method, body, f or {"upstream": "no answer"}, None)
                upstream_status = status
                if f and f.get("hook") and f.get("hook_at") == "response": f["hook"]({"method": method, "path": self.path, "status": status})
                if f and f.get("sever") == "after": return self._sever(method, body, f, upstream_status)
                if f and f["status"] is not None:
                    status, data, ctype = f["status"], json.dumps({"error": f["message"]}).encode(), "application/json"
                with proxy._lock:
                    proxy.log.append({"method": method, "path": self.path, "body": body.decode(errors="replace") if body else None,
                                      "status": status, "upstream_status": upstream_status, "fault": f and {k: v for k, v in f.items() if k != "hook"}})
                self.send_response(status); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(data)

            def _sever(self, method, body, f, upstream_status):
                with proxy._lock:
                    proxy.log.append({"method": method, "path": self.path, "body": body.decode(errors="replace") if body else None,
                                      "status": None, "upstream_status": upstream_status, "fault": {k: v for k, v in f.items() if k != "hook"}})
                self.close_connection = True
                try: self.connection.shutdown(socket.SHUT_RDWR)
                except OSError: pass

            def do_GET(self): self._handle("GET")
            def do_POST(self): self._handle("POST")
            def do_PUT(self): self._handle("PUT")
            def do_DELETE(self): self._handle("DELETE")
            def do_PATCH(self): self._handle("PATCH")

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H); self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        return self

    def stop(self):
        if self.srv: self.srv.shutdown(); self.srv.server_close()
