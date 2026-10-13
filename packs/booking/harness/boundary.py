"""
harness/boundary.py — the service's API boundary, black-box. FROZEN.
Every response observed is validated against harness/api.schema.json; invalid, malformed and out-of-domain input is
refused (400) without any effect (no event, no state change); unknown resources and bookings are 404; the UI is served.
"""
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
    try: yield s
    finally: s.stop()


def test_every_response_matches_its_schema(svc):
    """Contract: BoundaryConformance."""
    c = svc.client
    code, r = c.create(1, "Room A"); assert code == 201; ok("resource", r)
    for args in ((1, 1, 600, 660), (1, 2, 630, 690), (1, 3, 700, 700), (1, 1, 600, 660)):
        code, r = c.book(*args); assert code == 200; ok("book_result", r)
    code, r = c.move(1, 4, 610, 650); assert code == 200; ok("move_result", r)
    code, r = c.cancel(1, 5); assert code == 200; ok("cancel_result", r)
    code, r = c.move(1, 6, 0, 10); assert code == 200 and r["outcome"] == "NOT_ACTIVE"; ok("move_result", r)
    ok("resources", c.resources()[1]); ok("resource_view", c.resource(1)[1]); ok("booking", c.booking(1)[1]); ok("events", c.events()[1])


BAD = [-1, 2 ** 53, 1.5, "1", True, None, [], {}]


@pytest.mark.parametrize("bad", BAD, ids=[repr(b) for b in BAD])
def test_out_of_domain_values_are_refused_without_effect(svc, bad):
    """Contract: BoundaryConformance."""
    c = svc.client; c.create(500, "Room")
    before = (len(c.events()[1]), c.resource(500)[1])
    for path, body in (("/resources", {"id": bad, "name": "x"}), ("/resources/500/bookings", {"request_id": bad, "start": 0, "end": 10}),
                       ("/resources/500/bookings", {"request_id": 90001, "start": bad, "end": 10}), ("/resources/500/bookings", {"request_id": 90002, "start": 0, "end": bad})):
        assert c._req("POST", path, body)[0] == 400, f"POST {path} {body}"
    assert (len(c.events()[1]), c.resource(500)[1]) == before


def test_malformed_and_incomplete_requests_are_refused_without_effect(svc):
    """Contract: BoundaryConformance."""
    c = svc.client; c.create(600, "Room"); c.book(600, 60001, 0, 60)
    n = len(c.events()[1])
    for path in ("/resources", "/resources/600/bookings", "/bookings/60001/cancel", "/bookings/60001/reschedule"):
        for raw in ("{", "[]", "null", "42", '"x"'): assert c.raw_post(path, raw) == 400, f"{path} {raw!r}"
    for path, body in (("/resources", {"id": 601}), ("/resources", {"name": "x"}), ("/resources/600/bookings", {"start": 0, "end": 10}),
                       ("/resources/600/bookings", {"request_id": 60002, "end": 10}), ("/bookings/60001/cancel", {}), ("/bookings/60001/reschedule", {"request_id": 60003, "start": 5})):
        assert c._req("POST", path, body)[0] == 400, f"POST {path} {body}"
    assert len(c.events()[1]) == n and c.booking(60001)[1]["active"] is True


def test_unknown_targets_are_404_without_effect(svc):
    """Contract: BoundaryConformance."""
    c = svc.client; n = len(c.events()[1])
    assert c.book(424242, 70001, 0, 10)[0] == 404 and c.cancel(424242, 70002)[0] == 404 and c.move(424242, 70003, 0, 10)[0] == 404
    assert c.resource(424242)[0] == 404 and c.booking(424242)[0] == 404 and len(c.events()[1]) == n


def test_the_application_is_served(svc):
    """Contract: BoundaryConformance."""
    code, body = svc.client.ui(); assert code == 200 and b"<" in body
