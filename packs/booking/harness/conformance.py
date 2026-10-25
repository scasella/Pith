"""
harness/conformance.py — the running service agrees with the verified core, operation by operation. FROZEN.

Hypothesis generates a resource buffer and sequences of book / cancel / reschedule requests on that resource (dense,
small integer times, so touching endpoints, containment, exact repeats and gaps of exactly the buffer, one minute
less and one minute more are common). Each sequence is sent to the candidate's service AND applied
to the verified core (profiles/python/bookingcore-py, translated from spec/BookingCore.dfy) in the same order; every
outcome, every named conflict and the resulting calendar must be the same. Each example uses fresh resource and
request ids on one running service, so examples do not interfere. This is how a custom profile, which does not run
the verified core, is held to it; for the shipped profiles it checks the integration end to end. A test, not a proof.
"""
import itertools, pathlib, sys
import pytest
from hypothesis import given, settings, strategies as st, HealthCheck
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness.supervisor import Service
from profiles.python import core
from gate.packet import cx_line

IDS = itertools.count(1)
# buffers: 0 (version 1's convention) in three draws of eight; otherwise around the 10-minute grid, so the gaps the generated
# endpoints leave are often exactly the buffer, one minute under it or one minute over it
buffers = st.sampled_from([0, 0, 0, 1, 9, 10, 11, 20])
# endpoints on a 10-minute grid, each nudged by up to one minute, so one-minute overlaps and gaps are generated too
op = st.tuples(st.sampled_from(["book", "book", "cancel", "move"]), st.integers(0, 5), st.integers(0, 12), st.integers(0, 12),
               st.integers(-1, 1), st.integers(-1, 1))


def seen(code, r, *keys):
    """What the service answered, in the contract's words (a refusal is its status alone, whatever its body says)."""
    return {k: r.get(k) for k in keys} if code == 200 and isinstance(r, dict) else {"status": code}


def cx(sent, expected, observed=None):
    """The one-line counterexample the task packet carries (gate/packet.py): every operation sent so far with the answer the
    service gave and, on the last one, where service and verified core part, the answer the core gives."""
    sent[-1]["expected"] = expected
    return cx_line(sent, expected=expected, observed=sent[-1]["observed"] if observed is None else observed, violated=["CoreConformance"],
                   diverged_at=len(sent) - 1, replayable=False, source="oracle discrepancy")


@pytest.fixture(scope="module")
def svc():
    s = Service(ROOT).start()
    try: yield s
    finally: s.stop()


@settings(max_examples=80, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(buffers, st.lists(op, min_size=1, max_size=24))
def test_service_agrees_with_the_verified_core(svc, g, seq):
    """Contract: CoreConformance, Turnaround."""
    c = svc.client; k = core.Core(); rid = 10_000 + next(IDS)
    assert c.create(rid, buffer=g)[0] == 201 and c.resource(rid)[1]["buffer"] == g
    model, booked = [], []                                  # the core's calendar; booking ids sent so far (accepted or not)
    sent = [{"step": 1, "action": "create", "args": {"resource": rid, "buffer": g}, "observed": {"status": 201}}]
    for kind, pick, a, b, da, db in seq:
        s, e = max(0, a * 10 + da), max(0, b * 10 + db); rq = rid * 1000 + next(IDS) % 1000
        if kind == "book":
            code, r = c.book(rid, rq, s, e); o, cal = k.Book(core.calendar(model), g, rq, s, e); booked.append(rq)
            sent.append({"step": len(sent) + 1, "action": "book", "args": {"resource": rid, "request": rq, "start": s, "end": e}, "observed": seen(code, r, "outcome", "conflicts_with")})
            assert code == 200 and (r["outcome"], r["conflicts_with"]) == core.outcome(o), \
                f"book [{s},{e}) at buffer {g} on {core.rows(core.calendar(model))}: service {r}, core {core.outcome(o)} " + cx(sent, dict(zip(("outcome", "conflicts_with"), core.outcome(o))))
        elif booked and any(x[0] == booked[pick % len(booked)] for x in model):
            bid = booked[pick % len(booked)]
            if kind == "cancel":
                code, r = c.cancel(bid, rq); ok, cal = k.Cancel(core.calendar(model), g, bid)
                sent.append({"step": len(sent) + 1, "action": "cancel", "args": {"booking": bid, "request": rq}, "observed": seen(code, r, "cancelled")})
                assert code == 200 and r["cancelled"] == ok, f"cancel {bid} on {model}: service {r}, core {ok} " + cx(sent, {"cancelled": ok})
            else:
                code, r = c.move(bid, rq, s, e); o, cal = k.Reschedule(core.calendar(model), g, bid, s, e)
                sent.append({"step": len(sent) + 1, "action": "move", "args": {"booking": bid, "request": rq, "start": s, "end": e}, "observed": seen(code, r, "outcome", "conflicts_with")})
                assert code == 200 and (r["outcome"], r["conflicts_with"]) == core.outcome(o), \
                    f"move {bid} to [{s},{e}) at buffer {g} on {model}: service {r}, core {core.outcome(o)} " + cx(sent, dict(zip(("outcome", "conflicts_with"), core.outcome(o))))
        else:
            continue
        model = sorted(core.rows(cal))
        got = [(x["id"], x["start"], x["end"], x["active"]) for x in c.resource(rid)[1]["bookings"]]
        rows = lambda cal: [{"booking": b, "start": st_, "end": en, "active": act} for b, st_, en, act in cal]
        assert got == model, f"calendar after {kind}: service {got}, core {model} " + cx(
            sent + [{"step": len(sent) + 1, "action": "read_calendar", "args": {"resource": rid}, "observed": {"bookings": rows(got)}}], {"bookings": rows(model)})
