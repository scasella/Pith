"""
obligations/service/lifecycle.py — ring-1 obligations judged BLACK-BOX through the candidate's service, frozen.
Nothing here imports candidate code. The supervisor starts the service from service/run.py, drives it over HTTP
with the frozen client, kills it mid-flight (SIGKILL) and restarts it on the same database.
"""
import hashlib, itertools, json, pathlib, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
import pytest
ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from obligations.service.supervisor import Service
from obligations.service.trace import Trace
from gate import interleave as IL

def canonical(o): return json.dumps(o, sort_keys=True, separators=(",", ":"))

@pytest.fixture
def svc():
    s = Service(ROOT).start()
    try: yield s
    finally: s.stop()

def decided(c, acct=None):
    _, evs = c.events(); return [e for e in evs if e["type"] == "auth.decided" and (acct is None or e["account_id"] == acct)]

def test_duplicate_create_rejected_and_service_still_usable(svc):
    c = svc.client; assert c.create(1, 100)[0] == 201
    assert c.create(1, 5)[0] in (400, 409) and c.account(1)[1]["limit"] == 100
    assert c.authorize(1, 1, 100)[1]["decision"] == "AUTHORIZED"

def test_replay_is_idempotent_and_conflicts_are_rejected(svc):
    """Contract: Idempotency, Idempotent."""
    c = Trace(svc.client); c.create(1, 100)
    a = c.authorize(1, 1, 60)[1]; n = len(decided(c))
    b = c.authorize(1, 1, 60)[1]
    want = {"request_id": 1, "decision": "AUTHORIZED", "available_at_decision": 100, "replayed": True}       # the receipt (the oracle's answer)
    assert b["replayed"] is True and b["decision"] == a["decision"], c.cx(want, ["Idempotency", "Idempotent"])
    assert len(decided(c)) == n, f"the replay emitted {len(decided(c)) - n} more auth.decided event(s)"
    assert c.authorize(1, 1, 61)[0] in (400, 409), c.cx({"status": 409}, ["Idempotency"])
    assert c.account(1)[1]["holds"] == {"1": 60}

def test_crash_after_commit_then_restart_retry_replays(svc):
    """Contract: Durability, Idempotency."""
    c = Trace(svc.client); c.create(1, 100); c.authorize(1, 1, 60)
    svc.kill()
    c.on(svc.start().client)
    again = c.authorize(1, 1, 60)[1]
    want = {"request_id": 1, "decision": "AUTHORIZED", "available_at_decision": 100, "replayed": True}
    assert again["replayed"] is True and again["decision"] == "AUTHORIZED", c.cx(want, ["Durability", "Idempotency"])
    _, evs = c.events(); mine = [e for e in evs if e.get("request_id") == 1]
    assert [e["type"] for e in mine].count("auth.decided") == 1 and len([e for e in mine if e["type"] == "op.committed"]) == 1

def test_restart_preserves_state_and_idempotency(svc):
    """Contract: Durability, Idempotency."""
    c = svc.client; c.create(1, 100); c.create(2, 50); c.authorize(1, 1, 60); c.authorize(2, 2, 50); c.release(2, 2)
    c = svc.restart().client
    assert c.account(1)[1]["holds"] == {"1": 60} and c.account(2)[1]["holds"] == {}
    assert c.authorize(1, 1, 60)[1]["replayed"] is True
    assert c.authorize(1, 3, 40)[1]["decision"] == "AUTHORIZED" and c.authorize(1, 4, 1)[1]["decision"] == "DECLINED"

def test_capture_is_exact_terminal_and_idempotent(svc):
    """Contract: Idempotency."""
    c = svc.client; c.create(1, 100); c.authorize(1, 1, 60)
    r = c.capture(1, 1)[1]; assert r["captured"] is True and r["amount"] == 60 and r["replayed"] is False
    v = c.account(1)[1]; assert v["posted"] == 60 and v["holds"] == {} and v["status"]["1"] == "POST" and v["available"] == 40
    assert c.capture(1, 1)[1]["replayed"] is True and c.account(1)[1]["posted"] == 60          # no double posting
    assert c.release(1, 1)[1]["released"] is False                                                 # posted is terminal
    assert c.authorize(1, 2, 40)[1]["decision"] == "AUTHORIZED" and c.authorize(1, 3, 1)[1]["decision"] == "DECLINED"
    svc.kill(); c = svc.start().client
    assert c.account(1)[1]["posted"] == 60 and c.capture(1, 1)[1]["replayed"] is True             # survives restart

def test_receipts_are_returned_on_retry_across_a_crash(svc):
    """Contract: Receipts, Durability."""
    c = Trace(svc.client); c.create(1, 100); c.authorize(1, 1, 30); c.authorize(1, 2, 50)
    want = {"request_id": 1, "released": True, "replayed": False}
    assert c.release(1, 1)[1] == want, c.cx(want, ["Receipts"])
    want = {"request_id": 2, "captured": True, "amount": 50, "replayed": False}
    assert c.capture(1, 2)[1] == want, c.cx(want, ["Receipts"])
    svc.kill(); c.on(svc.start().client)                                                           # the responses were lost
    want = {"request_id": 1, "released": True, "replayed": True}                                   # the receipt, not "not released"
    assert c.release(1, 1)[1] == want, c.cx(want, ["Receipts"])
    want = {"request_id": 2, "captured": True, "amount": 50, "replayed": True}
    assert c.capture(1, 2)[1] == want, c.cx(want, ["Receipts"])
    want = {"request_id": 1, "decision": "AUTHORIZED", "available_at_decision": 100, "replayed": True}
    assert c.authorize(1, 1, 30)[1] == want, c.cx(want, ["Receipts"])
    want = {"request_id": 2, "released": False, "replayed": False}                                 # a receipt answers only its own operation
    assert c.release(1, 2)[1]["released"] is False, c.cx(want, ["Receipts"])
    want = {"request_id": 1, "captured": False, "replayed": False}
    assert c.capture(1, 1)[1]["captured"] is False, c.cx(want, ["Receipts"])
    _, evs = c.events(); types = [e["type"] for e in evs]
    assert types.count("reservation.released") == 1 and types.count("capture.posted") == 1 and c.account(1)[1]["posted"] == 50

def test_event_contract(svc):
    """Contract: EventContract."""
    c = svc.client; c.create(1, 100); c.authorize(1, 1, 60); c.authorize(1, 2, 60); c.release(1, 1); c.authorize(1, 3, 40); c.capture(1, 3)
    _, evs = c.events(); types = [e["type"] for e in evs]
    assert types == ["account.created", "op.committed", "auth.decided", "reservation.created", "op.committed",
                     "auth.decided", "op.committed", "reservation.released", "op.committed",
                     "auth.decided", "reservation.created", "op.committed", "capture.posted", "op.committed"]
    assert [e["seq"] for e in evs] == sorted(e["seq"] for e in evs) and all(e["producer"] == "auth-service" for e in evs)
    prev = "0" * 64
    for e in evs:
        body = {k: v for k, v in e.items() if k not in ("hash", "seq")}
        assert e["prev_hash"] == prev and e["hash"] == hashlib.sha256(canonical(body).encode()).hexdigest(), "chain broken"
        prev = e["hash"]
    ops = {}
    for e in evs: ops.setdefault(e["op_id"], []).append(e["type"])
    assert len(ops) == 6 and all(v[-1] == "op.committed" and v.count("op.committed") == 1 for v in ops.values())
    commits = [x["state_after"] for x in evs if x["type"] == "op.committed"]
    assert [x["reserved"] for x in commits] == [0, 60, 60, 0, 40, 0] and [x["posted"] for x in commits] == [0, 0, 0, 0, 0, 40]

def test_concurrent_bursts_and_readers(svc):
    """Contract: Durability, EventContract."""
    c = svc.client; c.create(1, 100); stop = threading.Event(); bad = []
    def reader():
        while not stop.is_set():
            time.sleep(0.005)              # paced: three readers at full speed exhaust ephemeral ports on some hosts (macOS); the check is unchanged
            code, v = c.account(1)
            if code != 200: bad.append(code); continue
            holds = {int(k): x for k, x in v["holds"].items()}
            if v["posted"] + sum(holds.values()) > v["limit"] or set(holds) != {int(k) for k, s in v["status"].items() if s == "AUTH"}: bad.append(v)
    ts = [threading.Thread(target=reader, daemon=True) for _ in range(3)]; [t.start() for t in ts]
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda i: c.authorize(1, 100 + i, 30), range(16)))
        list(ex.map(lambda i: c.release(1, 100 + i), range(0, 16, 2)))
        list(ex.map(lambda i: c.authorize(1, 200 + i, 30), range(8)))
    stop.set(); [t.join(timeout=2) for t in ts]
    assert bad == [], f"inconsistent reads: {bad[:2]}"
    assert len(decided(c)) == 24 and sum(c.account(1)[1]["holds"].values()) <= 100


def test_interleaved_authorizations_with_room_for_one_decide_exactly_one():
    """Contract: Atomicity. Every schedule of two requests authorizing 60 on a fresh account with limit 100, with at most one
    preemption (gate/interleave.py: the requests are held at their first line in service/, run one at a time and switch at every lock,
    sleep and SQL statement), authorizes exactly one, declines the other against the 40 the first left, and leaves one hold: not a
    timing test, so the same defect is found on every run. Python services only (this pack runs Python). A service whose request
    threads the controller never sees, or whose code has no lock, sleep or SQL statement to switch at, is refused as inconclusive,
    never passed: the burst tests remain its check."""
    with Service(ROOT, interleave=True) as svc:
        c, E, ids = svc.client, IL.ServiceEpisodes(svc.control), itertools.count(1)
        def setup():
            acct = next(ids); c.create(acct, 100); return acct, (1000 + 2 * acct, 1001 + 2 * acct)
        def authorize(i): return lambda ctx: c.authorize(ctx[0], ctx[1][i], 60)
        def check(ctx, results):
            acct, _ = ctx
            if any(r[0] != "ok" or r[1][0] != 200 for r in results): return f"a request failed: {results}"
            dec = sorted(r[1][1]["decision"] for r in results); v = c.account(acct)[1]; avail = sorted(e["available_at_decision"] for e in decided(c, acct))
            if dec != ["AUTHORIZED", "DECLINED"]: return f"decisions {dec}, not one AUTHORIZED and one DECLINED; holds {v['holds']}"
            if avail != [40, 100]: return f"decided against availability {avail}, not 100 for the first and the 40 it left for the second"
            if v["holds"] != {str(r[1][1]["request_id"]): 60 for r in results if r[1][1]["decision"] == "AUTHORIZED"} or v["available"] != 40:
                return f"after one authorization the account holds {v['holds']} with {v['available']} available"
        rep = E.explore(setup, [authorize(0), authorize(1)], check, bound=1)
    first = rep["first"]
    print("pith-interleave " + json.dumps({"schedules": rep["schedules"], "violations": len(rep["violations"]), "complete": rep["complete"], "first": first and first["schedule"]}, sort_keys=True))
    assert not rep["violations"], f"Atomicity: {len(rep['violations'])} of {rep['schedules']} schedules decide against stale availability; first violating schedule {first['schedule']}: {first['violation']}"
    assert rep["schedules"] > 2 and rep["complete"] and not rep["inconclusive"] and not rep["deadlocks"], \
        f"Atomicity: the exploration did not finish ({rep['schedules']} schedules; 2 are the serial orders and nothing else can run if no lock, sleep or SQL statement is reached; complete={rep['complete']}, inconclusive={rep['inconclusive']}, deadlocks={rep['deadlocks']})"
