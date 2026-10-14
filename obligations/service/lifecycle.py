"""
obligations/service/lifecycle.py — ring-1 obligations judged BLACK-BOX through the candidate's service, frozen.
Nothing here imports candidate code. The supervisor starts the service from service/run.py, drives it over HTTP
with the frozen client, kills it mid-flight (SIGKILL) and restarts it on the same database.
"""
import hashlib, json, pathlib, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
import pytest
ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from obligations.service.supervisor import Service

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
    c = svc.client; c.create(1, 100)
    a = c.authorize(1, 1, 60)[1]; n = len(decided(c))
    b = c.authorize(1, 1, 60)[1]
    assert b["replayed"] is True and b["decision"] == a["decision"] and len(decided(c)) == n
    assert c.authorize(1, 1, 61)[0] in (400, 409) and c.account(1)[1]["holds"] == {"1": 60}

def test_crash_after_commit_then_restart_retry_replays(svc):
    """Contract: Durability, Idempotency."""
    c = svc.client; c.create(1, 100); c.authorize(1, 1, 60)
    svc.kill()
    c = svc.start().client
    again = c.authorize(1, 1, 60)[1]
    assert again["replayed"] is True and again["decision"] == "AUTHORIZED"
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
    c = svc.client; c.create(1, 100); c.authorize(1, 1, 30); c.authorize(1, 2, 50)
    assert c.release(1, 1)[1] == {"request_id": 1, "released": True, "replayed": False}
    assert c.capture(1, 2)[1] == {"request_id": 2, "captured": True, "amount": 50, "replayed": False}
    svc.kill(); c = svc.start().client                                                             # the responses were lost
    assert c.release(1, 1)[1] == {"request_id": 1, "released": True, "replayed": True}             # the receipt, not "not released"
    assert c.capture(1, 2)[1] == {"request_id": 2, "captured": True, "amount": 50, "replayed": True}
    assert c.authorize(1, 1, 30)[1] == {"request_id": 1, "decision": "AUTHORIZED", "available_at_decision": 100, "replayed": True}
    assert c.release(1, 2)[1]["released"] is False and c.capture(1, 1)[1]["captured"] is False      # a receipt answers only its own operation
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
