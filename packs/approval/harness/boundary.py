"""harness/boundary.py — the approval API boundary, black-box. FROZEN. Responses match harness/api.schema.json;
invalid, malformed and out-of-domain input is 400 with no effect; unknown documents are 404."""
import json, pathlib, sys
import jsonschema, pytest
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness.supervisor import Service

S = json.loads((ROOT / "harness/api.schema.json").read_text())
def ok(name, body): jsonschema.validate(body, {"$ref": f"#/$defs/{name}", "$defs": S["$defs"]})


@pytest.fixture(scope="module")
def svc():
    s = Service(ROOT).start()
    for a, r in (("alice", ["editor", "approver"]), ("bob", ["approver"]), ("carol", ["approver"]), ("dave", ["publisher"])): s.client.actor(a, r)
    try: yield s
    finally: s.stop()


def test_every_response_matches_its_schema(svc):
    c = svc.client
    ok("actors", c.actors()[1])
    code, r = c.create(1, "d1", "alice"); assert code == 200; ok("result", r)
    code, r = c.create(2, "d2", "bob"); assert code == 200 and r["document"] is None; ok("result", r)
    for args in (("submit", 3, "d1", "alice", 1), ("approve", 4, "d1", "alice", 1), ("approve", 5, "d1", "bob", 1), ("approve", 6, "d1", "carol", 1), ("publish", 7, "d1", "dave", 1)):
        code, r = c.cmd(*args); assert code == 200; ok("result", r)
    code, r = c.edit(8, "d1", "alice"); assert code == 200; ok("result", r)
    ok("document", c.document("d1")[1]); ok("events", c.events()[1])


BAD = [-1, 2 ** 53, 1.5, "1", True, None, [], {}]


@pytest.mark.parametrize("bad", BAD, ids=[repr(b) for b in BAD])
def test_out_of_domain_values_are_refused_without_effect(svc, bad):
    c = svc.client; c.create(900, "b1", "alice"); n = len(c.events()[1]); view = c.document("b1")[1]
    for path, body in (("/documents", {"request_id": bad, "id": "b2", "actor": "alice", "title": "t", "body": "b"}),
                       ("/documents/b1/submit", {"request_id": 901, "actor": "alice", "revision": bad}),
                       ("/documents/b1/edit", {"request_id": bad, "actor": "alice", "body": "b"})):
        assert c._req("POST", path, body)[0] == 400, (path, body)
    assert len(c.events()[1]) == n and c.document("b1")[1] == view


@pytest.mark.parametrize("bad", ["", "UPPER", "has space", "../x", "a" * 65, 7, None, True])
def test_bad_ids_are_refused_without_effect(svc, bad):
    c = svc.client; n = len(c.events()[1])
    assert c._req("POST", "/documents", {"request_id": 950, "id": bad, "actor": "alice", "title": "t", "body": "b"})[0] == 400
    assert c._req("POST", "/actors", {"id": bad, "roles": ["approver"]})[0] == 400
    assert c._req("POST", "/documents", {"request_id": 951, "id": "fine", "actor": bad, "title": "t", "body": "b"})[0] == 400
    assert len(c.events()[1]) == n


def test_malformed_requests_and_unknown_documents(svc):
    c = svc.client; c.create(960, "m1", "alice"); n = len(c.events()[1])
    for path in ("/actors", "/documents", "/documents/m1/edit", "/documents/m1/approve"):
        for raw in ("{", "[]", "null", "3"): assert c.raw_post(path, raw) == 400, (path, raw)
    assert c._req("POST", "/actors", {"id": "zz", "roles": ["admin"]})[0] == 400
    assert c._req("POST", "/documents/m1/approve", {"request_id": 961, "actor": "bob"})[0] == 400
    assert c._req("POST", "/documents", {"request_id": 962, "id": "m2", "actor": "alice", "title": "x" * 10_001, "body": ""})[0] == 400
    assert c.cmd("approve", 963, "missing", "bob", 1)[0] == 404 and c.document("missing")[0] == 404
    assert len(c.events()[1]) == n
