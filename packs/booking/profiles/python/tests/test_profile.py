"""profiles/python/tests/test_profile.py — in-process tests of the shipped Python profile (SQLite store). FROZEN.

They establish what the proof assumes of its surroundings (spec/tcb.yaml): each operation executes atomically against
the latest committed calendar, committed operations survive reopening, replays never reach the core, invalid input
changes nothing. Judged only when app.manifest.yaml says runtime: python, profile: shipped.
"""
import pathlib, sys, tempfile, threading
from concurrent.futures import ThreadPoolExecutor
import pytest
from hypothesis import given, settings, strategies as st
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from profiles.python import core
from profiles.python.store import Store, ConflictingReplay, InvalidRequest, Unknown


def fresh():
    s = Store(str(pathlib.Path(tempfile.mkdtemp()) / "b.db")); s.create_resource(1, "Room"); s.create_resource(2, "Other"); return s


def test_concurrent_requests_for_one_interval_accept_exactly_one():
    s = fresh()
    with ThreadPoolExecutor(16) as ex: res = list(ex.map(lambda i: s.book(100 + i, 1, 600, 660), range(32)))
    assert [r["outcome"] for r in res].count("ACCEPTED") == 1
    assert core.valid([(b["id"], b["start"], b["end"], b["active"]) for b in s.resource(1)["bookings"]])


def test_concurrent_moves_into_one_gap_accept_exactly_one():
    s = fresh()
    for i in range(8): s.book(i + 1, 1, i * 100, i * 100 + 50)
    with ThreadPoolExecutor(8) as ex: res = list(ex.map(lambda i: s.reschedule(200 + i, i + 1, 2000, 2050), range(8)))
    assert [r["outcome"] for r in res].count("ACCEPTED") == 1


def test_reopen_preserves_state_ops_and_events():
    d = pathlib.Path(tempfile.mkdtemp()) / "b.db"; s = Store(str(d)); s.create_resource(1, "Room")
    s.book(1, 1, 600, 660); s.book(2, 1, 630, 700); s.cancel(3, 1); s.book(4, 1, 630, 700)
    view, evs = s.resource(1), s.events(); s = Store(str(d))
    assert s.resource(1) == view and s.events() == evs
    assert s.book(1, 1, 600, 660)["replayed"] is True and s.book(4, 1, 630, 700)["outcome"] == "ACCEPTED"


def test_replay_never_reaches_the_core():
    s = fresh(); s.book(1, 1, 600, 660)
    s.k = None                                            # a replay that called the core would raise here
    assert s.book(1, 1, 600, 660)["replayed"] is True
    with pytest.raises(ConflictingReplay): s.book(1, 1, 600, 661)
    with pytest.raises(ConflictingReplay): s.cancel(1, 1)


@pytest.mark.parametrize("bad", [-1, 2 ** 53, 1.5, "1", True, None])
def test_invalid_input_changes_nothing(bad):
    s = fresh(); n = len(s.events())
    for call in (lambda: s.book(bad, 1, 0, 10), lambda: s.book(9, 1, bad, 10), lambda: s.book(9, 1, 0, bad), lambda: s.reschedule(9, bad, 0, 10)):
        with pytest.raises(InvalidRequest): call()
    assert len(s.events()) == n


def test_unknown_resource_and_booking():
    s = fresh()
    with pytest.raises(Unknown): s.book(1, 99, 0, 10)
    with pytest.raises(Unknown): s.cancel(2, 99)


ops = st.lists(st.tuples(st.sampled_from(["book", "cancel", "move"]), st.integers(1, 2), st.integers(1, 12), st.integers(0, 20), st.integers(0, 20)), max_size=40)


@settings(max_examples=60, deadline=None)
@given(ops)
def test_store_agrees_with_the_core_applied_in_order(seq):
    """Differential: the store's committed calendars equal the verified core applied to the same operations in order."""
    s = fresh(); k = core.Core(); model = {1: [], 2: []}; owner = {}
    for n, (op, rid, bid, a, b) in enumerate(seq):
        rq = 1000 + n
        if op == "book":
            if bid in owner: continue                     # a booking id is used once (a second use would be a replay)
            r = s.book(bid, rid, a * 10, b * 10)
            o, c = k.Book(core.calendar(model[rid]), bid, a * 10, b * 10); model[rid] = core.rows(c); owner.setdefault(bid, rid)
            assert (r["outcome"], r["conflicts_with"]) == core.outcome(o)
        elif bid in owner and any(x[0] == bid for x in model[owner[bid]]):
            rid = owner[bid]
            if op == "cancel":
                r = s.cancel(rq, bid); ok, c = k.Cancel(core.calendar(model[rid]), bid); assert r["cancelled"] == ok
            else:
                r = s.reschedule(rq, bid, a * 10, b * 10); o, c = k.Reschedule(core.calendar(model[rid]), bid, a * 10, b * 10); assert r["outcome"] == core.outcome(o)[0]
            model[rid] = core.rows(c)
        for rid in (1, 2):
            got = [(x["id"], x["start"], x["end"], x["active"]) for x in s.resource(rid)["bookings"]]
            assert got == sorted(model[rid]) and core.valid(got)        # the store keeps calendars in booking-id order
