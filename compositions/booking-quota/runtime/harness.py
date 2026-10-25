"""runtime/harness.py — the driver for the booking-quota composition (composition policy, run by the judge as pytest:
`gate/compose.py verify`; PITH_COMPOSE_WORKSPACE names the judged workspace, PITH_COMPOSE_MODE is `verify`).

Every test starts the three components fresh, each behind its own fault proxy. Faults are programmed per request at a
proxy and fire exactly once (times=1, or a stated count), so they land at the same step on every run: kill the coordinator
when its call to quota arrives, drop a component's answer, kill the coordinator on the response path, sever the
compensating cancel. After a crash the coordinator is restarted and the test waits, with NO client retry, for the
components to reach rest, by polling the components' own state with a bounded timeout (there is no fixed sleep). The
shared invariants are read from booking's listing, quota's grants and the coordinator's stored receipts, never from
anything the coordinator reports about itself.

`checks` in composition.yaml maps each test to the shared invariants it checks; a known-wrong candidate must fail exactly the
tests whose invariants it violates. The runtime check tests the faults it injects; it is not a proof over all crash points."""
import os, pathlib, shutil, threading
import pytest
import stack as S

assert os.environ.get("PITH_COMPOSE_MODE") == "verify", "this driver judges a composed candidate: PITH_COMPOSE_MODE=verify"


@pytest.fixture
def st():
    s = S.Stack(S.fresh_state()); s.start()
    try: yield s
    finally:
        s.stop(); shutil.rmtree(s.root, ignore_errors=True)


def killer(st, cid, fired):
    """A proxy hook that SIGKILLs a process at the instant the faulted request (or its answer) goes by."""
    def hook(info): st.kill(cid); fired.set()
    return hook


def test_accepted_reservation_is_one_booking_and_one_unit(st):
    st.resource(1)
    code, r = st.reserve(1, 1, 600, 660)
    assert code == 200 and r["outcome"] == "ACCEPTED" and r["replayed"] is False, (code, r)
    assert st.active(1) == {1} and st.grants(1) == [1], "an accepted reservation must be exactly one active booking and one granted unit"
    assert st.receipt_problem(1, 1) is None, st.receipt_problem(1, 1)
    code, again = st.reserve(1, 1, 600, 660)
    assert code == 200 and again["outcome"] == "ACCEPTED" and again["replayed"] is True, (code, again)
    assert st.active(1) == {1} and st.grants(1) == [1], "a replayed request must change neither the booking nor the quota"


def test_crash_between_booking_and_quota_is_recovered(st):
    st.resource(1); fired = threading.Event()
    st.proxy["quota"].fault("POST", "/acquire", sever="before", times=1, hook=killer(st, "coordinator", fired))
    S.lost(st.reserve, 1, 1, 600, 660)                         # the coordinator dies when its call to quota arrives; this client's answer is lost
    assert fired.wait(10), "the fault never landed: the coordinator never called quota"
    assert st.active(1) == {1} and st.grants(1) == [], "the fault must land after the booking committed and before quota was called"
    st.restart("coordinator")                                   # NO client retry from here on
    assert st.wait_rest(1), f"after the restart the coordinator left booking {sorted(st.active(1))} and quota grants {st.grants(1)} apart"
    assert len(st.grants(1)) == len(set(st.grants(1))), "a unit was granted twice"


def test_lost_quota_answer_is_retried_without_a_second_grant(st):
    st.resource(1)
    st.proxy["quota"].fault("POST", "/acquire", sever="after", times=1)    # quota commits the grant; the coordinator never hears
    S.lost(st.reserve, 1, 1, 600, 660)
    assert any(r["status"] is None and r["upstream_status"] == 200 for r in st.proxy["quota"].requests("POST")), "the fault never landed on quota's answer"
    assert st.wait_rest(1), f"booking {sorted(st.active(1))} and quota grants {st.grants(1)} stayed apart after a lost answer"
    assert st.grants(1) == [1] and st.active(1) == {1}, "the request must hold exactly one unit and one booking"
    assert S.acquires_reaching_quota(st, 1) >= 2, "the coordinator did not repeat the call whose answer was lost"


def test_crash_on_the_quota_response_path_recovers(st):
    st.resource(1); fired = threading.Event()
    st.proxy["quota"].fault("POST", "/acquire", sever="after", times=1, hook=killer(st, "coordinator", fired), hook_at="response")
    S.lost(st.reserve, 1, 1, 600, 660)                         # quota granted; the coordinator dies before it reads the answer
    assert fired.wait(10), "the fault never landed: the coordinator never called quota"
    assert st.grants(1) == [1] and st.active(1) == {1}, "the fault must land after quota granted the unit"
    st.restart("coordinator")                                   # no client retry yet
    assert st.wait_rest(1), f"after the restart booking {sorted(st.active(1))} and quota grants {st.grants(1)} are apart"
    code, r = st.reserve(1, 1, 600, 660)                        # now the client retries
    assert code == 200 and r["outcome"] == "ACCEPTED", (code, r)
    assert st.grants(1) == [1] and st.active(1) == {1}, "the retry must not take a second unit or a second booking"


def test_quota_refusal_cancels_the_booking(st):
    st.resource(1)
    assert st.reserve(1, 1, 600, 660)[1]["outcome"] == "ACCEPTED"
    code, r = st.reserve(2, 1, 700, 760)                        # a non-conflicting interval; the resource's one unit is taken
    assert code == 200 and r["outcome"] == "QUOTA_EXCEEDED", (code, r)
    assert st.booking_is_active(2) is False, f"the refused reservation's booking must be cancelled, not {st.booking_is_active(2)}"
    assert st.grants(1) == [1] and st.active(1) == {1}, "a refused reservation must burn no unit and leave no active booking"
    assert S.acquires_reaching_quota(st, 2) == 1, "quota must have been asked exactly once"


def test_severed_cancel_is_retried_until_done(st):
    st.resource(1)
    assert st.reserve(1, 1, 600, 660)[1]["outcome"] == "ACCEPTED"
    st.proxy["booking"].fault("POST", "/bookings/*/cancel", sever="before", times=3)     # the compensating cancel never arrives, three times
    code, r = S.lost(st.reserve, 2, 1, 700, 760) or (None, None)
    severed = lambda: [x for x in st.proxy["booking"].requests("POST") if "/cancel" in x["path"] and x["status"] is None]
    assert S.wait_for(lambda: len(severed()) == 3), f"the fault must sever three cancels, it severed {len(severed())}"
    assert S.wait_for(lambda: st.booking_is_active(2) is False), "the compensating cancel was not retried until done"
    assert st.wait_rest(1) and st.grants(1) == [1] and st.active(1) == {1}, "the refused reservation left a booking or a unit behind"
    assert r is None or code != 200 or r["outcome"] == "QUOTA_EXCEEDED", (code, r)


def test_receipt_of_a_compensated_reservation_says_quota_exceeded(st):
    st.resource(1)
    assert st.reserve(1, 1, 600, 660)[1]["outcome"] == "ACCEPTED"
    assert st.reserve(2, 1, 700, 760)[1]["outcome"] == "QUOTA_EXCEEDED"
    code, rc = st.coord.get("/reservations/2")
    assert code == 200 and rc["outcome"] == "QUOTA_EXCEEDED", f"the stored receipt of a compensated reservation says {rc and rc['outcome']}"
    code, again = st.reserve(2, 1, 700, 760)
    assert code == 200 and again["outcome"] == "QUOTA_EXCEEDED" and again["replayed"] is True, f"the replay of a compensated reservation says {again}"
    assert st.receipt_problem(2, 1) is None, st.receipt_problem(2, 1)
    assert st.receipt_problem(1, 1) is None, st.receipt_problem(1, 1)


def test_conflict_burns_no_quota_and_receipts_replay(st):
    st.resource(1); st.resource(2)
    assert st.reserve(1, 1, 600, 660)[1]["outcome"] == "ACCEPTED"
    code, r = st.reserve(2, 1, 630, 690)                        # overlaps booking 1
    assert code == 200 and r["outcome"] == "CONFLICT" and r["conflicts_with"] == 1, (code, r)
    assert S.acquires_reaching_quota(st, 2) == 0, "a conflicting booking must not reach quota"
    assert st.grants(1) == [1] and st.active(1) == {1}, "a conflicting reservation must burn no unit"
    st.proxy["coordinator"].fault("POST", "/reservations", sever="after", times=1)         # the client never hears its answer
    S.lost(st.reserve, 3, 2, 600, 660)
    code, r3 = st.reserve(3, 2, 600, 660)
    assert code == 200 and r3["outcome"] == "ACCEPTED" and r3["replayed"] is True, f"the retry after a lost answer must replay the receipt: {code} {r3}"
    for rq, res, outcome in ((1, 1, "ACCEPTED"), (2, 1, "CONFLICT"), (3, 2, "ACCEPTED")):
        code, rep = st.reserve(rq, res, *{1: (600, 660), 2: (630, 690), 3: (600, 660)}[rq])
        assert code == 200 and rep["outcome"] == outcome and rep["replayed"] is True, (rq, code, rep)
        assert st.receipt_problem(rq, res) is None, st.receipt_problem(rq, res)
    assert st.grants(2) == [3] and st.active(2) == {3}, "the replays must not change either component"
