"""harness/client.py — the frozen HTTP client for harness/SERVICE.md. Every method returns (status, body). Stdlib only."""
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
    def actor(self, aid, roles):                        return self._req("POST", "/actors", {"id": aid, "roles": list(roles)})
    def actors(self):                                   return self._req("GET", "/actors")
    def create(self, rq, doc, actor, title="T", body="v1"): return self._req("POST", "/documents", {"request_id": rq, "id": doc, "actor": actor, "title": title, "body": body})
    def edit(self, rq, doc, actor, body="next"):        return self._req("POST", f"/documents/{doc}/edit", {"request_id": rq, "actor": actor, "body": body})
    def cmd(self, op, rq, doc, actor, revision):        return self._req("POST", f"/documents/{doc}/{op}", {"request_id": rq, "actor": actor, "revision": revision})
    def document(self, doc):                            return self._req("GET", f"/documents/{doc}")
    def events(self, since=0):                          return self._req("GET", f"/events?since={since}")
    def raw_post(self, path, text):                     return self._req("POST", path, raw=text)[0]
