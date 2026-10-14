"""harness/client.py — the frozen HTTP client for harness/SERVICE.md. Every method returns (status, body); bodies are
parsed JSON or None. raw_post sends arbitrary bytes for malformed-input checks. Stdlib only."""
import json, urllib.request, urllib.error


class Client:
    def __init__(self, base): self.base = base
    def _req(self, method, path, body=None, raw=None, timeout=10):
        data = raw.encode() if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                b = r.read()
                try: return r.status, json.loads(b) if b else None
                except ValueError: return r.status, None
        except urllib.error.HTTPError as e:
            try: return e.code, json.loads(e.read() or b"null")
            except ValueError: return e.code, None
    def create(self, rid, name="Room", buffer=None):                       # buffer None: omitted (the service's default, 0)
        return self._req("POST", "/resources", {"id": rid, "name": name, **({} if buffer is None else {"buffer": buffer})})
    def resources(self):                            return self._req("GET", "/resources")
    def resource(self, rid):                        return self._req("GET", f"/resources/{rid}")
    def book(self, rid, request_id, start, end):    return self._req("POST", f"/resources/{rid}/bookings", {"request_id": request_id, "start": start, "end": end})
    def booking(self, bid):                         return self._req("GET", f"/bookings/{bid}")
    def cancel(self, bid, request_id):              return self._req("POST", f"/bookings/{bid}/cancel", {"request_id": request_id})
    def move(self, bid, request_id, start, end):    return self._req("POST", f"/bookings/{bid}/reschedule", {"request_id": request_id, "start": start, "end": end})
    def events(self, since=0):                      return self._req("GET", f"/events?since={since}")
    def raw_post(self, path, text):                 return self._req("POST", path, raw=text)[0]
    def ui(self):
        try:
            with urllib.request.urlopen(self.base + "/", timeout=10) as r: return r.status, r.read()
        except urllib.error.HTTPError as e: return e.code, b""
