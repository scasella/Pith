"""harness/client.py — the frozen HTTP client for harness/SERVICE.md (version 2). Every method returns (status, body). Stdlib only."""
import json, urllib.parse, urllib.request, urllib.error


class Client:
    def __init__(self, base): self.base = base
    def _req(self, method, path, body=None, timeout=10):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r: return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            try: return e.code, json.loads(e.read() or b"null")
            except ValueError: return e.code, None
    def request(self, rq, counter=None):
        return self._req("POST", "/requests", {"request_id": rq} if counter is None else {"request_id": rq, "counter": counter})
    def tally(self, counter=None): return self._req("GET", "/tally" + ("" if counter is None else "?counter=" + urllib.parse.quote(counter)))
