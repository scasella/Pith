"""runtime/migrations/verify.py — the NEW composed candidate judged BLACK-BOX on state migrated by one component's upgrade
(PITH_COMPOSE_MODE=verify-migrated). Composition policy, run by `gate/compose.py stagger` as pytest in the new candidate's
judged workspace; PITH_COMPOSE_STATE is the migrated state root, PITH_COMPOSE_OBSERVED what populate.py saw the OLD composition
acknowledge. Each test starts all three components fresh on its own COPY of the migrated state, each behind a fault proxy; the
coordinator's recovery runs on start, with no client retry, and the shared invariants are read from the components' own state.
`checks` in migrations/booking-v1-to-v2.yaml maps each test to the shared invariants it checks."""
import json, os, pathlib, shutil, sys, tempfile
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))      # runtime/
import stack as S

assert os.environ.get("PITH_COMPOSE_MODE") == "verify-migrated", "this file judges migrated state: PITH_COMPOSE_MODE=verify-migrated"
STATE = pathlib.Path(os.environ["PITH_COMPOSE_STATE"]); OBS = json.loads(pathlib.Path(os.environ["PITH_COMPOSE_OBSERVED"]).read_text())
RECEIPTS = {int(k): v for k, v in OBS["receipts"].items()}


@pytest.fixture
def st():
    d = pathlib.Path(tempfile.mkdtemp(prefix="migrated-")) / "state"; shutil.copytree(STATE, d)
    ident = S.SB.candidate_identity()
    if ident:
        for p in [d, *d.rglob("*")]: os.chown(p, *ident)
    s = S.Stack(d); s.start()
    try: yield s
    finally: s.stop(); shutil.rmtree(d.parent, ignore_errors=True)


def resources(): return sorted({b["resource"] for b in OBS["bookings"].values()})
def same(receipt, observed): return {k: v for k, v in receipt.items() if k != "replayed"} == {k: v for k, v in observed.items() if k != "replayed"}


def test_the_saga_in_flight_at_the_upgrade_completes_without_a_retry(st):
    for f in OBS["in_flight"]:
        assert st.wait_rest(f["resource"]), (f"booking {sorted(st.active(f['resource']))} and quota grants {st.grants(f['resource'])} stayed apart: "
                                              f"the coordinator did not finish the reservation it was killed in the middle of")
        assert st.active(f["resource"]) == {f["request_id"]} == set(st.grants(f["resource"])), "the booking made before the upgrade must hold its unit"


def test_the_migrated_components_agree(st):
    for f in OBS["in_flight"]: assert st.wait_rest(f["resource"])
    for res in resources():
        assert st.at_rest(res), f"resource {res}: booking {sorted(st.active(res))} and quota grants {st.grants(res)} name different requests"
    for res, g in OBS["grants"].items():                       # quota was not touched by booking's upgrade: what it had granted it still has
        assert set(g) <= set(st.grants(int(res))), f"resource {res}: quota lost grants {g}"
    for rq, b in OBS["bookings"].items():
        if b["active"]: assert rq and int(rq) in st.active(b["resource"]), f"booking {rq} was active and is not"


def test_observed_receipts_replay_identically(st):
    for f in OBS["in_flight"]: assert st.wait_rest(f["resource"])
    for rq, r in RECEIPTS.items():
        q = OBS["requests"][str(rq)]
        code, body = st.reserve(rq, q["resource"], q["start"], q["end"])
        assert code == 200 and body["replayed"] is True and same(body, r), f"the receipt acknowledged for {rq} was {r}; its replay is {code} {body}"
        code, stored = st.coord.get(f"/reservations/{rq}")
        assert code == 200 and same(stored, r), f"the stored receipt for {rq} was {r} and is {code} {stored}"


def test_observed_receipts_agree_with_the_migrated_components(st):
    for f in OBS["in_flight"]: assert st.wait_rest(f["resource"])
    for rq, r in RECEIPTS.items():
        assert st.receipt_problem(rq, r["resource"]) is None, st.receipt_problem(rq, r["resource"])
        if str(rq) in OBS["bookings"]:                          # the booking a receipt names is served as it was (a compensated one still cancelled)
            assert st.booking.get(f"/bookings/{rq}") == (200, OBS["bookings"][str(rq)]), f"the booking named by receipt {rq} was {OBS['bookings'][str(rq)]}, now {st.booking.get(f'/bookings/{rq}')}"
    for f in OBS["in_flight"]:
        assert S.wait_for(lambda: st.coord.get(f"/reservations/{f['request_id']}")[0] == 200), "the recovered reservation has no receipt"
        assert st.receipt_problem(f["request_id"], f["resource"]) is None, st.receipt_problem(f["request_id"], f["resource"])


def test_new_reservations_on_the_upgraded_composition(st):
    for f in OBS["in_flight"]: assert st.wait_rest(f["resource"])
    code, r = st.reserve(9001, 1, 800, 860)                    # resource 1's unit was taken before the upgrade: it must still be
    assert code == 200 and r["outcome"] == "QUOTA_EXCEEDED", (code, r)
    assert st.booking_is_active(9001) is False and st.at_rest(1)
    code, b = st.booking.post("/resources", {"id": 7, "name": "buffered", "buffer": 30}); assert code == 201 and b["buffer"] == 30, "booking is not version 2"
    assert st.reserve(9002, 7, 0, 60)[1]["outcome"] == "ACCEPTED"
    code, r = st.reserve(9003, 7, 70, 100)                     # inside the 30-minute turnaround: version 2's buffer, then no unit is taken
    assert r["outcome"] == "CONFLICT" and S.acquires_reaching_quota(st, 9003) == 0, (code, r)
    assert st.at_rest(7) and st.receipt_problem(9002, 7) is None and st.receipt_problem(9003, 7) is None
