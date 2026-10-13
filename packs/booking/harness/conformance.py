"""
harness/conformance.py — the running service agrees with the verified core, operation by operation. FROZEN.

Hypothesis generates sequences of book / cancel / reschedule requests (dense, small integer times, so touching
endpoints, containment and exact repeats are common). Each sequence is sent to the candidate's service AND applied
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

IDS = itertools.count(1)
op = st.tuples(st.sampled_from(["book", "book", "cancel", "move"]), st.integers(0, 5), st.integers(0, 12), st.integers(0, 12))


@pytest.fixture(scope="module")
def svc():
    s = Service(ROOT).start()
    try: yield s
    finally: s.stop()


@settings(max_examples=80, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.lists(op, min_size=1, max_size=24))
def test_service_agrees_with_the_verified_core(svc, seq):
    """Contract: CoreConformance."""
    c = svc.client; k = core.Core(); rid = 10_000 + next(IDS); assert c.create(rid)[0] == 201
    model, booked = [], []                                  # the core's calendar; booking ids sent so far (accepted or not)
    for kind, pick, a, b in seq:
        s, e = a * 10, b * 10; rq = rid * 1000 + next(IDS) % 1000
        if kind == "book":
            code, r = c.book(rid, rq, s, e); o, cal = k.Book(core.calendar(model), rq, s, e); booked.append(rq)
            assert code == 200 and (r["outcome"], r["conflicts_with"]) == core.outcome(o), f"book [{s},{e}) on {core.rows(core.calendar(model))}: service {r}, core {core.outcome(o)}"
        elif booked and any(x[0] == booked[pick % len(booked)] for x in model):
            bid = booked[pick % len(booked)]
            if kind == "cancel":
                code, r = c.cancel(bid, rq); ok, cal = k.Cancel(core.calendar(model), bid)
                assert code == 200 and r["cancelled"] == ok, f"cancel {bid} on {model}: service {r}, core {ok}"
            else:
                code, r = c.move(bid, rq, s, e); o, cal = k.Reschedule(core.calendar(model), bid, s, e)
                assert code == 200 and (r["outcome"], r["conflicts_with"]) == core.outcome(o), f"move {bid} to [{s},{e}) on {model}: service {r}, core {core.outcome(o)}"
        else:
            continue
        model = sorted(core.rows(cal))
        got = [(x["id"], x["start"], x["end"], x["active"]) for x in c.resource(rid)[1]["bookings"]]
        assert got == model, f"calendar after {kind}: service {got}, core {model}"
