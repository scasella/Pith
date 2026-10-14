import json, urllib.request, urllib.error
class Client:
    def __init__(self, base): self.base = base
    def _req(self, method, path, body=None, raw=None):
        data = raw.encode() if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r: return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            try: return e.code, json.loads(e.read() or b"null")
            except Exception: return e.code, None
    def create(self, id, limit):                 return self._req("POST", "/accounts", {"id": id, "limit": limit})
    def account(self, id):                       return self._req("GET", f"/accounts/{id}")
    def authorize(self, id, request_id, amount): return self._req("POST", f"/accounts/{id}/authorize", {"request_id": request_id, "amount": amount})
    def release(self, id, request_id):           return self._req("POST", f"/accounts/{id}/release", {"request_id": request_id})
    def events(self, since=0):                   return self._req("GET", f"/events?since={since}")
    def raw_post(self, path, text):              return self._req("POST", path, raw=text)[0]
