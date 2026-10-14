"""
harness/lifecycle.py — the booking service judged BLACK-BOX, through its HTTP API, as a separate process. FROZEN.
Nothing here imports candidate code. The supervisor (gate/service.py) starts the service from the manifest's
runtime entrypoint, kills it mid-flight (SIGKILL) and restarts it on the same state directory. Resources created
without a buffer have buffer 0 (version 1's convention); the buffer tests create resources with one.
"""
import pathlib, sys, threading
from concurrent.futures import ThreadPoolExecutor
import pytest
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness.supervisor import Service


@pytest.fixture
def svc():
    s = Service(ROOT).start()
    try: yield s
    finally: s.stop()


def active(c, rid): return [(b["id"], b["start"], b["end"]) for b in c.resource(rid)[1]["bookings"] if b["active"]]
def no_overlap(iv, g=0): iv = sorted((s, e) for _, s, e in iv); return all(iv[k][1] + g <= iv[k + 1][0] for k in range(len(iv) - 1))
def near(a, b, g): return a[0] < b[1] + g and b[0] < a[1] + g          # within the buffer g of each other (spec/BookingSpec.dfy Near)


def test_resources_create_list_and_duplicate(svc):
    """Contract: Independence, Turnaround."""
    c = svc.client
    assert c.create(1, "Room A") == (201, {"id": 1, "name": "Room A", "buffer": 0}) and c.create(2, "Room B", 20) == (201, {"id": 2, "name": "Room B", "buffer": 20})
    assert c.create(1, "Again")[0] == 409 and c.resource(1)[1]["name"] == "Room A"
    assert [(r["id"], r["buffer"]) for r in c.resources()[1]["resources"]] == [(1, 0), (2, 20)]
    assert (c.resource(1)[1]["buffer"], c.resource(2)[1]["buffer"]) == (0, 20)
    assert c.resource(99)[0] == 404


def test_the_buffer_separates_bookings_on_its_resource(svc):
    """Contract: B0, B2, B5, HalfOpen, Turnaround, Independence."""
    c = svc.client; c.create(1, "Room A", 15); c.create(2, "Room B")
    assert c.book(1, 1, 600, 660)[1]["outcome"] == "ACCEPTED"
    r = c.book(1, 2, 660, 720)[1]; assert r["outcome"] == "CONFLICT" and r["conflicts_with"] == 1    # touching is within a 15-minute buffer
    r = c.book(1, 3, 674, 720)[1]; assert r["outcome"] == "CONFLICT" and r["conflicts_with"] == 1    # 14 (g - 1) after 1 ends
    assert c.book(1, 4, 675, 735)[1]["outcome"] == "ACCEPTED"                                        # exactly g after 1 ends
    r = c.book(1, 5, 526, 586)[1]; assert r["outcome"] == "CONFLICT" and r["conflicts_with"] == 1    # ends 14 before 1 starts
    assert c.book(1, 6, 525, 585)[1]["outcome"] == "ACCEPTED"                                        # ends exactly g before 1 starts
    r = c.book(1, 7, 740, 800)[1]; assert r["outcome"] == "CONFLICT" and r["conflicts_with"] == 4
    assert c.book(1, 8, 750, 800)[1]["outcome"] == "ACCEPTED"
    assert c.book(2, 9, 600, 660)[1]["outcome"] == "ACCEPTED" and c.book(2, 10, 660, 720)[1]["outcome"] == "ACCEPTED"   # buffer 0: touching is free
    assert active(c, 1) == [(1, 600, 660), (4, 675, 735), (6, 525, 585), (8, 750, 800)] and no_overlap(active(c, 1), 15)
    assert active(c, 2) == [(9, 600, 660), (10, 660, 720)]


def test_moves_and_cancels_respect_the_buffer(svc):
    """Contract: M1, M3, B5, X2, Turnaround."""
    c = svc.client; c.create(1, "Room A", 15); c.book(1, 1, 600, 660); c.book(1, 2, 675, 735)
    r = c.move(1, 3, 600, 665)[1]
    assert r["outcome"] == "CONFLICT" and r["conflicts_with"] == 2 and (r["start"], r["end"]) == (600, 660)      # would end 10 before 2 starts
    r = c.move(1, 4, 590, 660)[1]; assert r["outcome"] == "ACCEPTED" and (r["start"], r["end"]) == (590, 660)    # its own buffer does not count
    r = c.move(2, 5, 670, 735)[1]; assert r["outcome"] == "CONFLICT" and r["conflicts_with"] == 1 and (r["start"], r["end"]) == (675, 735)
    assert active(c, 1) == [(1, 590, 660), (2, 675, 735)]
    assert c.cancel(1, 6)[1]["cancelled"] is True
    assert c.move(2, 7, 600, 700)[1]["outcome"] == "ACCEPTED"                         # a cancelled booking frees its buffer too
    r = c.book(1, 8, 714, 730)[1]; assert r["outcome"] == "CONFLICT" and r["conflicts_with"] == 2   # the moved booking keeps its buffer
    assert c.book(1, 9, 715, 730)[1]["outcome"] == "ACCEPTED"
    assert active(c, 1) == [(2, 600, 700), (9, 715, 730)]


def test_the_buffer_is_fixed_at_creation_and_survives_restart(svc):
    """Contract: Turnaround, Durability."""
    c = svc.client
    assert c.create(1, "Room A", 30)[1] == {"id": 1, "name": "Room A", "buffer": 30}
    assert c.create(1, "Room A", 0)[0] == 409 and c.create(1, "Room A")[0] == 409 and c.resource(1)[1]["buffer"] == 30
    assert c.create(2, "Room B", 1440)[0] == 201 and c.create(3, "Room C", 0)[1]["buffer"] == 0
    c.book(1, 1, 600, 660); svc.kill(); c = svc.start().client
    assert [(r["id"], r["buffer"]) for r in c.resources()[1]["resources"]] == [(1, 30), (2, 1440), (3, 0)]
    r = c.book(1, 2, 689, 720)[1]; assert r["outcome"] == "CONFLICT" and r["conflicts_with"] == 1
    assert c.book(1, 3, 690, 720)[1]["outcome"] == "ACCEPTED"


def test_half_open_intervals_conflicts_and_independent_resources(svc):
    """Contract: HalfOpen, B1, B5, Independence."""
    c = svc.client; c.create(1); c.create(2)
    assert c.book(1, 1, 600, 660)[1]["outcome"] == "ACCEPTED"
    assert c.book(1, 2, 660, 720)[1]["outcome"] == "ACCEPTED"                      # starts exactly when 1 ends
    assert c.book(1, 3, 540, 600)[1]["outcome"] == "ACCEPTED"                      # ends exactly when 1 starts
    r = c.book(1, 4, 630, 690)[1]; assert r["outcome"] == "CONFLICT" and r["conflicts_with"] in (1, 2)
    r = c.book(1, 5, 500, 800)[1]; assert r["outcome"] == "CONFLICT"               # contains three bookings
    r = c.book(1, 6, 610, 620)[1]; assert r["outcome"] == "CONFLICT" and r["conflicts_with"] == 1   # inside one
    assert c.book(1, 7, 700, 700)[1]["outcome"] == "INVALID" and c.book(1, 8, 710, 700)[1]["outcome"] == "INVALID"
    assert c.book(2, 9, 600, 660)[1]["outcome"] == "ACCEPTED"                      # another resource is independent
    assert active(c, 1) == [(1, 600, 660), (2, 660, 720), (3, 540, 600)] and active(c, 2) == [(9, 600, 660)]
    r = c.book(2, 11, 659, 720)[1]; assert r["outcome"] == "CONFLICT" and r["conflicts_with"] == 9   # a one-minute overlap conflicts
    r = c.book(2, 12, 540, 601)[1]; assert r["outcome"] == "CONFLICT" and r["conflicts_with"] == 9
    assert c.book(2, 13, 660, 661)[1]["outcome"] == "ACCEPTED"                     # one minute is the shortest booking
    assert c.book(99, 10, 0, 10)[0] == 404


def test_replays_are_idempotent_and_conflicting_reuse_is_rejected(svc):
    """Contract: Idempotency."""
    c = svc.client; c.create(1)
    a = c.book(1, 1, 600, 660)[1]; _, ev = c.events(); n = len(ev)
    b = c.book(1, 1, 600, 660)[1]
    assert b["replayed"] is True and b["outcome"] == a["outcome"] and len(c.events()[1]) == n
    assert c.book(1, 1, 600, 661)[0] == 409 and c.cancel(1, 1)[0] == 409             # same request id, other operation
    refused = c.book(1, 2, 630, 690)[1]; c.cancel(1, 3)                              # 1 cancelled: 2's interval is free now
    again = c.book(1, 2, 630, 690)[1]
    assert refused["outcome"] == "CONFLICT" and again["replayed"] is True and again["outcome"] == "CONFLICT"   # a replay is not a retry
    assert c.cancel(1, 3)[1]["replayed"] is True and c.move(1, 4, 0, 10)[1]["outcome"] == "NOT_ACTIVE"


def test_cancel_frees_the_interval_and_is_terminal(svc):
    """Contract: X2."""
    c = svc.client; c.create(1); c.book(1, 1, 600, 660)
    assert c.cancel(1, 2)[1]["cancelled"] is True and c.cancel(1, 3)[1]["cancelled"] is False
    assert c.booking(1)[1]["active"] is False and c.book(1, 4, 600, 660)[1]["outcome"] == "ACCEPTED"
    assert c.move(1, 5, 700, 760)[1]["outcome"] == "NOT_ACTIVE" and c.booking(1)[1]["start"] == 600
    assert c.cancel(99, 6)[0] == 404 and c.move(99, 7, 0, 10)[0] == 404


def test_reschedule_is_atomic(svc):
    """Contract: M3."""
    c = svc.client; c.create(1); c.book(1, 1, 600, 720); c.book(1, 2, 720, 780)
    r = c.move(1, 3, 630, 690)[1]; assert r["outcome"] == "ACCEPTED" and (r["start"], r["end"]) == (630, 690)      # within its own time
    r = c.move(1, 4, 700, 750)[1]
    assert r["outcome"] == "CONFLICT" and r["conflicts_with"] == 2 and (r["start"], r["end"]) == (630, 690)          # refused: kept where it was
    b = c.booking(1)[1]; assert (b["start"], b["end"], b["active"]) == (630, 690, True)
    assert c.move(1, 5, 690, 690)[1]["outcome"] == "INVALID" and c.booking(1)[1]["start"] == 630
    assert c.book(1, 6, 600, 630)[1]["outcome"] == "ACCEPTED"                       # the interval it left is free


def test_crash_after_commit_then_restart_and_retry_replays(svc):
    """Contract: Durability, Idempotency."""
    c = svc.client; c.create(1); c.book(1, 1, 600, 660); c.move(1, 2, 610, 670)
    svc.kill(); c = svc.start().client
    r = c.book(1, 1, 600, 660)[1]; m = c.move(1, 2, 610, 670)[1]
    assert r["replayed"] is True and r["outcome"] == "ACCEPTED" and m["replayed"] is True
    _, evs = c.events()
    assert [e["type"] for e in evs if e.get("request_id") == 1].count("op.committed") == 1
    assert active(c, 1) == [(1, 610, 670)]


def test_restart_preserves_state_and_idempotency(svc):
    """Contract: Durability, Idempotency."""
    c = svc.client; c.create(1, "Room A"); c.create(2, "Room B"); c.book(1, 1, 0, 60); c.book(2, 2, 0, 60); c.cancel(2, 3); c.book(1, 4, 30, 90)
    view1, view2 = c.resource(1)[1], c.resource(2)[1]
    c = svc.restart().client
    assert c.resource(1)[1] == view1 and c.resource(2)[1] == view2
    assert c.book(1, 4, 30, 90)[1]["replayed"] is True and c.book(2, 5, 0, 60)[1]["outcome"] == "ACCEPTED"


def test_concurrent_requests_for_one_interval_accept_exactly_one_per_resource(svc):
    """Contract: Atomicity, B0, Independence."""
    c = svc.client; c.create(1); c.create(2)
    with ThreadPoolExecutor(16) as ex:
        res = list(ex.map(lambda i: c.book(1 + i % 2, 100 + i, 600, 660)[1], range(40)))
    for rid in (1, 2):
        assert [r["outcome"] for r in res if r["resource"] == rid].count("ACCEPTED") == 1, "double booking under concurrency"
        assert len(active(c, rid)) == 1


def test_concurrent_overlapping_bursts_keep_calendars_conflict_free(svc):
    """Contract: Atomicity, B0."""
    c = svc.client; c.create(1)
    reqs = [(200 + i, (i * 37) % 300, (i * 37) % 300 + 45) for i in range(48)]
    with ThreadPoolExecutor(16) as ex: res = list(ex.map(lambda q: c.book(1, *q)[1], reqs))
    acc = active(c, 1); ids = {i for i, *_ in acc}
    assert no_overlap(acc), f"overlapping accepted intervals: {acc}"
    assert ids == {r["booking_id"] for r in res if r["outcome"] == "ACCEPTED"}
    span = {r[0]: (r[1], r[2]) for r in reqs}
    for r in res:                                                           # every conflict names an accepted, overlapping booking
        if r["outcome"] == "CONFLICT":
            (s, e), (s2, e2) = span[r["request_id"]], span[r["conflicts_with"]]
            assert r["conflicts_with"] in ids and s < e2 and s2 < e


def test_concurrent_bursts_keep_the_buffer(svc):
    """Contract: Atomicity, B0, B5, Turnaround."""
    c = svc.client; c.create(1, "Room A", 10)
    reqs = [(300 + i, (i * 37) % 300, (i * 37) % 300 + 45) for i in range(48)]
    with ThreadPoolExecutor(16) as ex: res = list(ex.map(lambda q: c.book(1, *q)[1], reqs))
    acc = active(c, 1); ids = {i for i, *_ in acc}
    assert no_overlap(acc, 10), f"accepted intervals closer than the buffer: {acc}"
    assert ids == {r["booking_id"] for r in res if r["outcome"] == "ACCEPTED"}
    span = {r[0]: (r[1], r[2]) for r in reqs}
    for r in res:                                                           # every conflict names an accepted booking within the buffer
        if r["outcome"] == "CONFLICT": assert r["conflicts_with"] in ids and near(span[r["request_id"]], span[r["conflicts_with"]], 10)


def test_concurrent_moves_into_one_gap_accept_exactly_one(svc):
    """Contract: Atomicity, B0, M3."""
    c = svc.client; c.create(1)
    for i in range(8): c.book(1, i + 1, i * 100, i * 100 + 50)
    with ThreadPoolExecutor(8) as ex: res = list(ex.map(lambda i: c.move(i + 1, 300 + i, 2000, 2050)[1], range(8)))
    assert [r["outcome"] for r in res].count("ACCEPTED") == 1 and no_overlap(active(c, 1))


def test_every_operation_commits_once_with_the_resulting_calendar(svc):
    """Contract: Atomicity."""
    c = svc.client; c.create(1); c.book(1, 1, 0, 60); c.book(1, 2, 30, 90); c.move(1, 3, 60, 120); c.cancel(1, 4); c.book(1, 5, 0, 30)
    _, evs = c.events()
    assert [e["seq"] for e in evs] == sorted(e["seq"] for e in evs) and len({e["seq"] for e in evs}) == len(evs)
    commits = [e for e in evs if e["type"] == "op.committed"]
    assert [e["request_id"] for e in commits] == [1, 2, 3, 4, 5]
    assert [sorted(map(tuple, e["active"])) for e in commits] == [[(1, 0, 60)], [(1, 0, 60)], [(1, 60, 120)], [], [(5, 0, 30)]]
    assert commits[-1]["active"] == [list(x) for x in active(c, 1)]
