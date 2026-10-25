"""coordinator/peers.py — how the coordinator calls a component: JSON over HTTP, stdlib only. A call that cannot be
answered (connection refused or reset, a timeout, a 5xx) is Unavailable and may be repeated: every call the coordinator
makes carries a request id its component deduplicates. Anything else the component says is an answer, whatever its status."""
import json, http.client, urllib.error, urllib.request


class Unavailable(Exception): pass


class Peer:
    def __init__(self, base, timeout=3.0): self.base = base.rstrip("/"); self.timeout = timeout

    def call(self, method, path, body=None):
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(), method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r: code, raw = r.status, r.read()
        except urllib.error.HTTPError as e: code, raw = e.code, e.read()
        except (OSError, http.client.HTTPException) as e: raise Unavailable(f"{method} {path}: {e}")
        if code >= 500: raise Unavailable(f"{method} {path}: {code}")
        try: return code, json.loads(raw or b"null")
        except ValueError: raise Unavailable(f"{method} {path}: unreadable answer")
