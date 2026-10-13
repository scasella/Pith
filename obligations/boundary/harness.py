"""
obligations/boundary/harness.py — ring-2 obligations, frozen.

Drives the agent's API through a client protocol, replays every call through the proven core,
validates every request/response/event against the generated schemas with a real JSON Schema
validator, attacks the boundary with invalid inputs, and runs the generated monitor.

The candidate is reached ONLY as a separate process (obligations/service/supervisor.py starts service/run.py)
through the frozen client; no candidate Python is imported. Client methods return (status_code, body):
    client.create(id, limit)                 201 on success; 4xx on duplicate / invalid
    client.account(id)                       200 + AccountView
    client.authorize(id, request_id, amount) 200 + AuthorizeResponse; 4xx on invalid input or conflicting replay; 404 unknown account
    client.release(id, request_id)           200 + ReleaseResponse {"request_id","released","replayed"}
    client.capture(id, request_id)           200 + CaptureResponse {"request_id","captured","amount"?,"replayed"}
    client.events(since=0)                   200 + [event...] in seq order
    client.raw_post(path, json_text)         status for an arbitrary JSON body (used for malformed-input attacks)
"""
import json, os, pathlib, sys
from concurrent.futures import ThreadPoolExecutor
import pytest, yaml, jsonschema
from hypothesis import settings, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, Bundle, rule, invariant, initialize

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "kernel" / "core" / "py" / "authcore-py")); sys.path.insert(0, str(ROOT / "gen" / "out"))
import _dafny, module_, AuthSpec, AuthCore, PostingCore  # noqa: F401  (module_ fixes the translator's import order)
from monitor import Monitor
OPENAPI = yaml.safe_load((ROOT / "gen/out/openapi.yaml").read_text())
EVENTS = json.loads((ROOT / "gen/out/events.schema.json").read_text())
SCHEMAS = OPENAPI["components"]["schemas"]
def schema(name): return {**SCHEMAS[name], "components": {"schemas": SCHEMAS}}
V_EVENT = jsonschema.Draft202012Validator(EVENTS)
V_AUTH  = jsonschema.Draft202012Validator(schema("AuthorizeResponse"))
V_ACCT  = jsonschema.Draft202012Validator(schema("AccountView"))
V_CAP   = jsonschema.Draft202012Validator(schema("CaptureResponse"))
V_REL   = jsonschema.Draft202012Validator(schema("ReleaseResponse"))
ANTECEDENTS = {}

from obligations.service.supervisor import Service
def start():
    s = Service(ROOT).start(); return s.client, s.stop

Request = AuthSpec.Request_Request; NAME = {AuthSpec.Status_Auth(): "AUTH", AuthSpec.Status_Decl(): "DECL", AuthSpec.Status_Rel(): "REL", AuthSpec.Status_Post(): "POST"}
def fresh(limit): return AuthSpec.Account_Account(limit, 0, _dafny.Map({}), _dafny.Map({}))
def holds(a): return {int(k): int(v) for k, v in a.holds.items}
def status(a): return {int(k): NAME[v] for k, v in a.status.items}
def available(a): return int(a.limit) - int(a.posted) - sum(int(v) for _, v in a.holds.items)
def ok(code, body, validator):
    assert code == 200, (code, body); validator.validate(body); return body
def normalize_view(v):  # JSON object keys are strings
    return {"holds": {int(k): x for k, x in v["holds"].items()}, "status": {int(k): x for k, x in v["status"].items()}, "available": v["available"], "limit": v["limit"], "posted": v["posted"]}
POSTER = PostingCore.Poster()

# ------------------------------------------------------------------ invalid-input attacks on the real service
@pytest.fixture
def svc():
    c, stop = start(); yield c; stop()

@pytest.mark.parametrize("amount", [0, -1, -50, True, "60", 60.5, None, 2**53, 2**70])
def test_invalid_amount_rejected_at_boundary(svc, amount):
    """Contract: BoundaryConformance."""
    assert svc.create(1, 100)[0] == 201
    code, body = svc.authorize(1, 7, amount)
    assert 400 <= code < 500, f"invalid amount {amount!r} must be rejected, got {code} {body}"
    _, evs = svc.events(); assert not any(e.get("request_id") == 7 for e in evs), "no event for a rejected request"
    assert svc.authorize(1, 7, 10)[1]["decision"] == "AUTHORIZED"

@pytest.mark.parametrize("body", ['{"request_id": 1}', '{"amount": 5}', '{"request_id": 1, "amount": 5, "extra": 1}', '{"request_id": "1", "amount": 5}',
                                  'not json', '[]', '{"request_id": 1, "amount": 1e3}'])
def test_malformed_request_rejected(svc, body):
    """Contract: BoundaryConformance."""
    assert svc.create(1, 100)[0] == 201
    assert 400 <= svc.raw_post("/accounts/1/authorize", body) < 500
    assert svc.account(1)[1]["holds"] == {} and len(svc.events()[1]) == 2        # account.created + op.committed only

def test_conflicting_replay_rejected_and_unknown_account_404(svc):
    """Contract: BoundaryConformance."""
    assert svc.create(1, 100)[0] == 201
    assert svc.authorize(1, 1, 60)[1]["decision"] == "AUTHORIZED"
    code, _ = svc.authorize(1, 1, 61); assert code in (400, 409)
    assert svc.account(1)[1]["holds"] == {"1": 60}
    assert svc.authorize(42, 1, 1)[0] == 404 and svc.account(42)[0] == 404
    assert svc.create(1, 5)[0] in (400, 409)

def test_every_event_and_response_validates_against_schema(svc):
    """Contract: BoundaryConformance."""
    assert svc.create(1, 100)[0] == 201
    V_AUTH.validate(svc.authorize(1, 1, 100)[1]); V_AUTH.validate(svc.authorize(1, 2, 1)[1]); V_ACCT.validate(svc.account(1)[1])
    _, evs = svc.events(); [V_EVENT.validate(e) for e in evs]
    assert [e["type"] for e in evs] == ["account.created", "op.committed", "auth.decided", "reservation.created", "op.committed", "auth.decided", "op.committed"]
    assert len({e["op_id"] for e in evs}) == 3

def test_release_and_capture_answer_with_receipts(svc):
    """Contract: Receipts, BoundaryConformance."""
    assert svc.create(1, 100)[0] == 201
    svc.authorize(1, 1, 30); svc.authorize(1, 2, 40)
    assert ok(*svc.release(1, 1), V_REL) == {"request_id": 1, "released": True, "replayed": False}
    assert ok(*svc.release(1, 1), V_REL) == {"request_id": 1, "released": True, "replayed": True}          # the receipt, not a no-op
    assert ok(*svc.capture(1, 2), V_CAP) == {"request_id": 2, "captured": True, "amount": 40, "replayed": False}
    assert ok(*svc.capture(1, 2), V_CAP) == {"request_id": 2, "captured": True, "amount": 40, "replayed": True}
    assert ok(*svc.release(1, 2), V_REL) == {"request_id": 2, "released": False, "replayed": False}        # posted: never released
    assert ok(*svc.capture(1, 1), V_CAP) == {"request_id": 1, "captured": False, "replayed": False}        # released: never captured
    assert ok(*svc.release(1, 9), V_REL) == {"request_id": 9, "released": False, "replayed": False}
    _, evs = svc.events(); [V_EVENT.validate(e) for e in evs]
    assert [e["type"] for e in evs].count("reservation.released") == 1 and [e["type"] for e in evs].count("capture.posted") == 1

# ------------------------------------------------------------------ stateful: API vs proven core, with the monitor
class Boundary(RuleBasedStateMachine):
    accounts = Bundle("accounts")
    def __init__(self):
        super().__init__(); self.c, self.stop = start(); self.core = AuthCore.Core(); self.oracle = {}; self.na = 1; self.nr = 1
    def teardown(self):
        try:
            _, evs = self.c.events(); [V_EVENT.validate(e) for e in evs]
            assert all("hash" in e and "prev_hash" in e and "op_id" in e for e in evs), "events must carry op_id and be hash-chained"
            rep = Monitor().run(evs); assert rep["alerts"] == [], rep["alerts"]
            for k, v in rep["antecedents"].items(): ANTECEDENTS[k] = ANTECEDENTS.get(k, 0) + v
        finally: self.stop()
    @initialize(target=accounts, limit=st.integers(0, 300))
    def new_account(self, limit):
        aid = self.na; self.na += 1; assert self.c.create(aid, limit)[0] == 201; self.oracle[aid] = fresh(limit); return aid
    @rule(acct=accounts, amount=st.integers(1, 400))
    def authorize(self, acct, amount):
        rid = self.nr; self.nr += 1
        before = ok(*self.c.account(acct), V_ACCT)["available"]
        r = ok(*self.c.authorize(acct, rid, amount), V_AUTH)
        d, self.oracle[acct] = self.core.Decide(self.oracle[acct], Request(rid, amount))
        assert r["decision"] == ("AUTHORIZED" if d.is_Authorized else "DECLINED"), "disagrees with the proven core"
        assert (amount > before) == (r["decision"] == "DECLINED") and r["available_at_decision"] == before
        again = ok(*self.c.authorize(acct, rid, amount), V_AUTH); assert again["replayed"] is True and again["decision"] == r["decision"]
    @rule(acct=accounts, amount=st.integers(1, 150))
    def burst(self, acct, amount):
        base = self.nr; self.nr += 6
        with ThreadPoolExecutor(6) as ex: rs = list(ex.map(lambda i: ok(*self.c.authorize(acct, base + i, amount), V_AUTH), range(6)))
        _, evs = self.c.events(); order = [e["request_id"] for e in evs if e["type"] == "auth.decided" and e["account_id"] == acct and base <= e["request_id"] < base + 6]
        assert len(order) == 6
        for rid in order:
            d, self.oracle[acct] = self.core.Decide(self.oracle[acct], Request(rid, amount))
            assert next(r for r in rs if r["request_id"] == rid)["decision"] == ("AUTHORIZED" if d.is_Authorized else "DECLINED")
    @rule(acct=accounts)
    def release_one(self, acct):
        h = ok(*self.c.account(acct), V_ACCT)["holds"]
        if h:
            rid = int(sorted(h, key=int)[0]); r = ok(*self.c.release(acct, rid), V_REL)
            assert r["released"] and r["replayed"] is False; self.oracle[acct] = self.core.Release(self.oracle[acct], rid)
            assert ok(*self.c.release(acct, rid), V_REL) == dict(r, replayed=True)              # a retry returns the receipt
    @rule(acct=accounts)
    def capture_one(self, acct):
        h = ok(*self.c.account(acct), V_ACCT)["holds"]
        if h:
            rid = int(sorted(h, key=int)[-1]); r = ok(*self.c.capture(acct, rid), V_CAP)
            assert r["captured"] and r["amount"] == h[str(rid)] and r["replayed"] is False; self.oracle[acct] = POSTER.Capture(self.oracle[acct], rid)
            assert ok(*self.c.capture(acct, rid), V_CAP) == dict(r, replayed=True)              # a retry returns the receipt, amount included
    @invariant()
    def equals_oracle(self):
        for aid, o in self.oracle.items():
            v = normalize_view(ok(*self.c.account(aid), V_ACCT))
            assert v["holds"] == holds(o) and v["status"] == status(o) and v["available"] == available(o) and v["posted"] == int(o.posted)
            assert v["posted"] + sum(v["holds"].values()) <= v["limit"]

TestBoundary = Boundary.TestCase
TestBoundary.settings = settings(max_examples=int(os.environ.get("BOUNDARY_EXAMPLES", "30")), stateful_step_count=15, deadline=None)

def test_both_decision_branches_exercised():
    """Contract: BoundaryConformance."""
    assert ANTECEDENTS.get("P0", 0) > 0 and ANTECEDENTS.get("P1", 0) > 0, ANTECEDENTS
