"""runtime/migrations/populate.py — produce real composed state by driving the OLD composed candidate (PITH_COMPOSE_MODE=populate).
Composition policy, run by `gate/compose.py stagger` as pytest in the OLD candidate's judged workspace; PITH_COMPOSE_STATE is the
state root (one directory per component: booking/, quota/, coordinator/), PITH_COMPOSE_OBSERVED the file to write.

It starts the old booking (interval-booking-core/v1), quota and coordinator behind their fault proxies and drives reservations:
accepted ones, a conflict, a quota refusal that the coordinator compensated (the booking cancelled), and finally one reservation
IN FLIGHT: the coordinator is killed when its call to quota arrives, after the booking committed and before a unit was taken.
Everything is then stopped (the coordinator stays dead). observed.json holds what the old composition ACKNOWLEDGED: each
receipt the client was given, the bookings and the quota grants as the components themselves served them, and the request in flight."""
import json, os, pathlib, sys, threading
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))      # runtime/: pytest puts only this directory on sys.path
import stack as S

assert os.environ.get("PITH_COMPOSE_MODE") == "populate", "this file populates state: PITH_COMPOSE_MODE=populate"
STATE = pathlib.Path(os.environ["PITH_COMPOSE_STATE"]); OBSERVED = pathlib.Path(os.environ["PITH_COMPOSE_OBSERVED"])

RESERVATIONS = [          # (request id, resource, start, end, the outcome the old composition must give)
    (101, 1, 600, 660, "ACCEPTED"),
    (102, 1, 700, 760, "QUOTA_EXCEEDED"),       # resource 1's one unit is taken: booked, refused by quota, cancelled
    (103, 2, 600, 660, "ACCEPTED"),
    (104, 2, 630, 690, "CONFLICT"),             # overlaps 103: refused by booking, quota never called
]
IN_FLIGHT = (105, 3, 600, 660)


def test_populate():
    st = S.Stack(STATE).start()
    try:
        for rid in (1, 2, 3): st.resource(rid)
        receipts, requests = {}, {}
        for rq, res, start, end, want in RESERVATIONS:
            code, r = st.reserve(rq, res, start, end)
            assert code == 200 and r["outcome"] == want and r["replayed"] is False, (rq, code, r)
            receipts[str(rq)] = r; requests[str(rq)] = {"resource": res, "start": start, "end": end}
        rq, res, start, end = IN_FLIGHT; fired = threading.Event()
        st.proxy["quota"].fault("POST", "/acquire", sever="before", times=1, hook=lambda info: (st.kill("coordinator"), fired.set()))
        S.lost(st.reserve, rq, res, start, end)                    # the coordinator dies when its call to quota arrives; the client never hears
        assert fired.wait(10) and st.active(res) == {rq} and st.grants(res) == [], "the saga must be in flight: booked, no unit taken"
        bookings = {}
        for res_ in (1, 2, 3):
            code, v = st.booking.get(f"/resources/{res_}"); assert code == 200
            for b in v["bookings"]: bookings[str(b["id"])] = dict(b, resource=res_)       # as GET /bookings/{id} serves it
        obs = {"format": "pith.compose-observed/v1", "requests": requests, "receipts": receipts, "bookings": bookings,
               "grants": {str(r): st.grants(r) for r in (1, 2, 3)},
               "in_flight": [{"request_id": rq, "resource": res, "start": start, "end": end}]}
        assert {r["outcome"] for r in receipts.values()} == {"ACCEPTED", "CONFLICT", "QUOTA_EXCEEDED"}
        assert bookings["102"]["active"] is False and "104" not in bookings, bookings          # a compensated booking is kept, cancelled; a conflict never booked
        OBSERVED.write_text(json.dumps(obs, indent=1, sort_keys=True))
    finally:
        st.stop()
