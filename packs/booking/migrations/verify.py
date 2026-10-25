"""
migrations/verify.py — the version 2 service judged BLACK-BOX on state migrated from version 1. FROZEN.
gate/migrate.py runs it in the new release's workspace with PITH_MIGRATION_STATE (the migrated state directory) and
PITH_MIGRATION_OBSERVED (what migrations/populate.py saw the old service acknowledge). Each test starts the new
service on its own copy of the migrated state, so the tests are independent. Nothing here imports candidate code.
"""
import json, os, pathlib, shutil, sys, tempfile
import pytest
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness.supervisor import Service
from gate import sandbox as SB
from gate.packet import cx_line

STATE = pathlib.Path(os.environ["PITH_MIGRATION_STATE"]); OBS = json.loads(pathlib.Path(os.environ["PITH_MIGRATION_OBSERVED"]).read_text())


@pytest.fixture
def svc():
    d = pathlib.Path(tempfile.mkdtemp(prefix="migrated-")) / "state"; shutil.copytree(STATE, d)
    ident = SB.candidate_identity()
    if ident:
        for p in [d, *d.rglob("*")]: os.chown(p, *ident)
    s = Service(ROOT, state=d).start()
    try: yield s
    finally: s.stop()


def call(c, op, args): return getattr(c, op)(*args)
def with_buffer_0(x): return dict(x, buffer=0)


ARGS = {"book": ("resource", "request", "start", "end"), "cancel": ("booking", "request"), "move": ("booking", "request", "start", "end")}


def sent(steps, op, args, code, got):
    """Record one operation sent to the migrated service, in the contract's words, with what it answered."""
    steps.append({"step": len(steps) + 1, "action": op, "args": dict(zip(ARGS[op], args)), "observed": got if code == 200 and isinstance(got, dict) else {"status": code}})


def cx(steps, expected, violated=("MIG1",), at=None):
    """The one-line counterexample the task packet carries (gate/packet.py): the operations sent up to step `at` (the last one by
    default) with the answers the migrated service gave and, on that step, the answer the contract requires."""
    steps = steps[:len(steps) if at is None else at + 1]; steps[-1]["expected"] = expected
    return cx_line(steps, expected=expected, observed=steps[-1]["observed"], violated=violated, diverged_at=len(steps) - 1, replayable=False, source="migration")


def test_every_recorded_result_is_kept_and_replayed(svc):
    """Contract: MIG1, Idempotency."""
    c = svc.client; steps = []
    for rq, r in OBS["results"].items():
        code, got = call(c, r["op"], r["args"]); sent(steps, r["op"], r["args"], code, got)
        assert code == 200 and got == dict(r["result"], replayed=True), cx(steps, dict(r["result"], replayed=True), ("MIG1", "Idempotency"))


def test_history_is_intact(svc):
    """Contract: MIG1, X3, Durability."""
    c = svc.client
    assert c.resources()[1]["resources"] == [with_buffer_0(r) for r in OBS["resources"]]
    for rid, v in OBS["views"].items(): assert c.resource(int(rid))[1] == with_buffer_0(v), rid
    for bid, b in OBS["bookings"].items(): assert c.booking(int(bid)) == (200, b), bid
    evs = c.events()[1]
    assert evs[:len(OBS["events"])] == OBS["events"], "the event history version 1 served is not kept"


def test_version_1_resources_keep_buffer_0_and_touching_bookings_stay_valid(svc):
    """Contract: MIG1, HalfOpen, B0, Turnaround."""
    c = svc.client
    assert [r["buffer"] for r in c.resources()[1]["resources"]] == [0] * len(OBS["resources"])
    act = [(b["id"], b["start"], b["end"]) for b in c.resource(1)[1]["bookings"] if b["active"]]
    assert act == [(b["id"], b["start"], b["end"]) for b in OBS["views"]["1"]["bookings"] if b["active"]] and (102, 660, 720) in act
    assert c.book(1, 9001, 720, 780)[1]["outcome"] == "ACCEPTED"                   # touching 102 from above, at buffer 0
    r = c.move(101, 9002, 600, 660)[1]; assert r["outcome"] == "ACCEPTED", r       # touching 103 and 102 on both sides
    r = c.book(1, 9003, 659, 700)[1]; assert r["outcome"] == "CONFLICT" and r["conflicts_with"] in (101, 102), r


def test_old_request_ids_stay_bound_to_their_operation(svc):
    """Contract: MIG1, Idempotency."""
    c = svc.client
    assert c.book(1, 101, 0, 10)[0] == 409                      # an accepted book's id, other parameters
    assert c.cancel(102, 101)[0] == 409                          # ... for another operation
    assert c.move(103, 104, 0, 10)[0] == 409                     # a refused book's id is bound too
    assert c.book(2, 107, 0, 10)[0] == 409                       # and a cancel's
    assert c.booking(102)[1]["active"] is True and c.booking(103)[1]["start"] == 540


def test_cancelled_bookings_stay_cancelled(svc):
    """Contract: MIG1, X3, M0."""
    c = svc.client
    assert c.booking(106)[1]["active"] is False
    assert c.cancel(106, 9101)[1]["cancelled"] is False and c.move(106, 9102, 0, 60)[1]["outcome"] == "NOT_ACTIVE"
    assert c.book(2, 9103, 600, 660)[1]["outcome"] == "ACCEPTED"                   # its interval stays free


def test_in_flight_request_is_decided_once(svc):
    """Contract: MIG1, Durability, Idempotency."""
    c = svc.client; steps = []
    for f in OBS["in_flight"]:
        code, first = call(c, f["op"], f["args"]); sent(steps, f["op"], f["args"], code, first)
        code2, again = call(c, f["op"], f["args"]); sent(steps, f["op"], f["args"], code2, again)
        assert code == 200 and first["outcome"] == "ACCEPTED" and again == dict(first, replayed=True), (
            cx(steps, {"outcome": "ACCEPTED"}, ("MIG1", "Durability"), at=len(steps) - 2) if not (code == 200 and first["outcome"] == "ACCEPTED")
            else cx(steps, dict(first, replayed=True), ("MIG1", "Idempotency", "Durability")))
        rq = f["args"][1]
        assert [e["type"] for e in c.events()[1] if e.get("request_id") == rq].count("op.committed") == 1, "decided more than once"
        assert c.booking(rq)[1]["active"] is True


def test_buffers_work_on_migrated_state(svc):
    """Contract: MIG1, Turnaround, B0, B2."""
    c = svc.client
    assert c.create(3, "Room C", 15)[1] == {"id": 3, "name": "Room C", "buffer": 15}
    assert c.create(2, "Room B", 15)[0] == 409                                      # an old resource's buffer is fixed too
    assert c.book(3, 9201, 600, 660)[1]["outcome"] == "ACCEPTED"
    r = c.book(3, 9202, 674, 735)[1]; assert r["outcome"] == "CONFLICT" and r["conflicts_with"] == 9201
    assert c.book(3, 9203, 675, 735)[1]["outcome"] == "ACCEPTED"
