"""Conventional tests of the HTTP contract (core-tests condition). Run with SERVICE_URL=http://127.0.0.1:PORT against a
service you started on a fresh database."""
import json, os, urllib.request
URL = os.environ.get("SERVICE_URL", "http://127.0.0.1:8080")


def post(rq):
    r = urllib.request.Request(URL + "/requests", data=json.dumps({"request_id": rq}).encode(), method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r) as x: return json.loads(x.read())


def test_first_request_is_accepted(): assert post(1)["outcome"] == "OK"
def test_repeat_is_replayed(): assert post(1)["replayed"] is True
