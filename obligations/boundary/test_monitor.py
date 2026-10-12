"""Negative suite for the generated monitor, frozen. Each stream must raise exactly the named alert;
the good stream must be silent. These are the reviewer's probes turned into obligations."""
import pathlib, sys, pytest
ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "gen" / "out"))
from monitor import Monitor

P = "auth-service"
import hashlib, json
def chain(events):
    """Seal a raw stream the way a compliant adapter does (op ids assigned per operation: an op ends at op.committed);
    tests mutate AFTER sealing to show the chain catches it."""
    out, prev, op, n = [], "0" * 64, None, 0
    for ev in events:
        if op is None: n += 1; op = f"op{n}"
        ev = dict(ev, op_id=ev.get("op_id", op))
        if ev["type"] == "op.committed": op = None
        body = {k: v for k, v in ev.items() if k not in ("hash", "seq")}; body["prev_hash"] = prev
        h = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        out.append({**body, "hash": h, "seq": ev.get("seq")}); prev = h
    return out
def resealed(events):
    """Rehash a mutated stream so only semantic checks can catch it (hash validity is not semantic correctness)."""
    return chain([{k: v for k, v in e.items() if k not in ("hash", "prev_hash")} for e in events])
def created(a, limit, seq): return [{"type": "account.created", "account_id": a, "limit": limit, "producer": P, "seq": seq},
                                    {"type": "op.committed", "account_id": a, "request_id": None, "op": "create_account", "producer": P, "seq": seq + 1,
                                     "state_after": {"limit": limit, "posted": 0, "reserved": 0}}]
def decided(a, r, amt, avail, dec, seq): return {"type": "auth.decided", "account_id": a, "request_id": r, "amount": amt, "available_at_decision": avail, "decision": dec, "producer": P, "seq": seq}
def hold(a, r, amt, seq):   return {"type": "reservation.created", "account_id": a, "request_id": r, "amount": amt, "producer": P, "seq": seq}
def rel(a, r, seq):         return {"type": "reservation.released", "account_id": a, "request_id": r, "producer": P, "seq": seq}
def done(a, r, op, seq, limit=100, reserved=0): return {"type": "op.committed", "account_id": a, "request_id": r, "op": op, "producer": P, "seq": seq, "state_after": {"limit": limit, "posted": 0, "reserved": reserved}}

GOOD = chain(created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 3), hold(1, 1, 60, 4), done(1, 1, "authorize", 5, reserved=60),
        decided(1, 2, 60, 40, "DECLINED", 6), done(1, 2, "authorize", 7, reserved=60), rel(1, 1, 8), done(1, 1, "release", 9, reserved=0),
        decided(1, 3, 100, 100, "AUTHORIZED", 10), hold(1, 3, 100, 11), done(1, 3, "authorize", 12, reserved=100)] + created(2, 50, 13) +
       [decided(2, 1, 50, 50, "AUTHORIZED", 15), hold(2, 1, 50, 16), done(2, 1, "authorize", 17, limit=50, reserved=50)])   # request id 1 reused in account 2

def codes(stream): return sorted({a["code"] for a in Monitor().run(stream)["alerts"]})

def test_good_stream_is_silent_and_covers_both_branches():
    rep = Monitor().run(GOOD); assert rep["alerts"] == [] and rep["antecedents"]["P0"] >= 2 and rep["antecedents"]["P1"] >= 1

CASES = {
  "P1-obs":  created(1, 100, 1) + [decided(1, 1, 150, 100, "AUTHORIZED", 3), hold(1, 1, 150, 4), done(1, 1, "authorize", 5)],
  "P0-obs":  created(1, 100, 1) + [decided(1, 1, 100, 100, "DECLINED", 3), done(1, 1, "authorize", 4)],
  "P2-amount": created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 3), hold(1, 1, 1, 4), done(1, 1, "authorize", 5)],
  "COMPLETE-missing-reservation": created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 3), done(1, 1, "authorize", 4)],
  "P2-obs|reservation-on-decline": created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 3), hold(1, 1, 60, 4), done(1, 1, "authorize", 5),
                                     decided(1, 2, 60, 40, "DECLINED", 6), hold(1, 2, 60, 7), done(1, 2, "authorize", 8)],
  "R1-terminal": created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 3), hold(1, 1, 60, 4), done(1, 1, "authorize", 5),
                 rel(1, 1, 6), done(1, 1, "release", 7), hold(1, 1, 60, 8)],
  "P2-obs":  created(1, 100, 1) + [hold(1, 9, 10, 3)],
  "P3-obs":  created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 3), hold(1, 1, 60, 4), done(1, 1, "authorize", 5), decided(1, 1, 60, 40, "DECLINED", 6)],
  "AVAIL-MISMATCH": created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 3), hold(1, 1, 60, 4), done(1, 1, "authorize", 5), decided(1, 2, 10, 100, "AUTHORIZED", 6), hold(1, 2, 10, 7), done(1, 2, "authorize", 8)],
  "INV1-obs": created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 3), hold(1, 1, 60, 4), done(1, 1, "authorize", 5), decided(1, 2, 60, 40, "AUTHORIZED", 6), hold(1, 2, 60, 7), done(1, 2, "authorize", 8)],
  "R1-unknown": created(1, 100, 1) + [rel(1, 5, 3), done(1, 5, "release", 4)],
  "COMPLETE-unterminated": created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 3), hold(1, 1, 60, 4)],
  # reviewer's streams
  "OP-composition|create-without-commit": [{"type": "account.created", "account_id": 1, "limit": 100, "producer": P, "seq": 1},
                                           decided(1, 1, 60, 100, "AUTHORIZED", 2), hold(1, 1, 60, 3), done(1, 1, "authorize", 4, reserved=60)],
  "OP-after-commit|duplicate-decline-commit": created(1, 100, 1) + [decided(1, 1, 150, 100, "DECLINED", 3), done(1, 1, "authorize", 4), dict(done(1, 1, "authorize", 5), op_id="op2")],
  "OP-composition|release-absorbed": created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 3), hold(1, 1, 60, 4), rel(1, 1, 5), done(1, 1, "authorize", 6, reserved=0)],
  "OP-interleaved": created(1, 100, 1) + [dict(decided(1, 1, 60, 100, "AUTHORIZED", 3), op_id="opA"), dict(decided(1, 2, 10, 100, "AUTHORIZED", 4), op_id="opB"),
                    dict(hold(1, 1, 60, 5), op_id="opA"), dict(done(1, 1, "authorize", 6, reserved=60), op_id="opA"), dict(hold(1, 2, 10, 7), op_id="opB"), dict(done(1, 2, "authorize", 8, reserved=70), op_id="opB")],
  "PRODUCER": created(1, 100, 1) + [dict(decided(1, 1, 60, 100, "AUTHORIZED", 3), producer="other"), hold(1, 1, 60, 4), done(1, 1, "authorize", 5)],
  "ORDER": created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 2), hold(1, 1, 60, 4), done(1, 1, "authorize", 5)],
  "DUP-ACCOUNT": created(1, 100, 1) + created(1, 100, 3),
  "P2-duplicate-hold": created(1, 100, 1) + [decided(1, 1, 30, 100, "AUTHORIZED", 3), hold(1, 1, 30, 4), hold(1, 1, 30, 5), done(1, 1, "authorize", 6)],
}
@pytest.mark.parametrize("code,stream", CASES.items())
def test_named_violation_is_detected(code, stream):
    code = code.split("|")[0]
    got = codes(resealed(stream))                     # rehashed: a valid chain must not hide a semantic violation
    assert code in got, f"expected {code}, got {got}"

def test_altered_event_breaks_the_chain():
    evs = [dict(e) for e in GOOD]; evs[2]["amount"] = 61
    assert "CHAIN" in codes(evs)

def test_state_after_must_match_reconstruction():
    bad = created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 3), hold(1, 1, 60, 4), done(1, 1, "authorize", 5, reserved=0)]
    assert "STATE" in codes(resealed(bad))

def test_truncated_tail_is_not_detected_by_chain_alone():
    """A valid prefix ending inside an operation is caught by COMPLETE-unterminated; a prefix ending AT a commit boundary
    is only caught with a watermark."""
    assert "COMPLETE-unterminated" in codes(GOOD[:4])
    assert codes(GOOD[:5]) == []                                                   # ends at a commit: silent without a watermark
    assert "INCOMPLETE" in sorted({a["code"] for a in Monitor().run(GOOD[:5], expected_last_seq=GOOD[-1]["seq"])["alerts"]})

def test_same_request_id_in_two_accounts_is_not_a_duplicate():
    assert "P3-obs" not in codes(GOOD)
