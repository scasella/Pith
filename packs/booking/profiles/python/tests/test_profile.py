"""profiles/python/tests/test_profile.py — in-process tests of the shipped Python profile (SQLite store). FROZEN.

They establish what the proof assumes of its surroundings (spec/tcb.yaml): each operation executes atomically against
the latest committed calendar and its resource's buffer, committed operations survive reopening, replays never reach
the core, invalid input changes nothing, and version 1 state is upgraded by migrate() and refused until it is.
Judged only when app.manifest.yaml says runtime: python, profile: shipped.
"""
import json, pathlib, sqlite3, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
import pytest
from hypothesis import given, settings, strategies as st
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from profiles.python import core
from profiles.python.store import Store, ConflictingReplay, Duplicate, InvalidRequest, Unknown, Unrecognised, migrate

BUFFER = {1: 0, 2: 10}                                    # resource 1 keeps version 1's convention; resource 2 has a turnaround buffer


def fresh():
    s = Store(str(pathlib.Path(tempfile.mkdtemp()) / "b.db")); s.create_resource(1, "Room"); s.create_resource(2, "Other", BUFFER[2]); return s


def test_concurrent_requests_for_one_interval_accept_exactly_one():
    s = fresh()
    with ThreadPoolExecutor(16) as ex: res = list(ex.map(lambda i: s.book(100 + i, 1, 600, 660), range(32)))
    assert [r["outcome"] for r in res].count("ACCEPTED") == 1
    assert core.valid([(b["id"], b["start"], b["end"], b["active"]) for b in s.resource(1)["bookings"]])


def test_concurrent_requests_within_the_buffer_accept_exactly_one():
    s = fresh()                                           # [600, 660) and [665, 700) are 5 apart: one of them, with buffer 10
    with ThreadPoolExecutor(16) as ex: res = list(ex.map(lambda i: s.book(100 + i, 2, *((600, 660) if i % 2 else (665, 700))), range(32)))
    assert [r["outcome"] for r in res].count("ACCEPTED") == 1
    assert core.valid([(b["id"], b["start"], b["end"], b["active"]) for b in s.resource(2)["bookings"]], BUFFER[2])


def test_concurrent_moves_into_one_gap_accept_exactly_one():
    s = fresh()
    for i in range(8): s.book(i + 1, 1, i * 100, i * 100 + 50)
    with ThreadPoolExecutor(8) as ex: res = list(ex.map(lambda i: s.reschedule(200 + i, i + 1, 2000, 2050), range(8)))
    assert [r["outcome"] for r in res].count("ACCEPTED") == 1


def test_reopen_preserves_state_ops_events_and_buffers():
    d = pathlib.Path(tempfile.mkdtemp()) / "b.db"; s = Store(str(d)); s.create_resource(1, "Room"); s.create_resource(2, "Other", 15)
    s.book(1, 1, 600, 660); s.book(2, 1, 630, 700); s.cancel(3, 1); s.book(4, 1, 630, 700); s.book(5, 2, 600, 660)
    view, evs, res = s.resource(1), s.events(), s.resources(); s = Store(str(d))
    assert s.resource(1) == view and s.events() == evs and s.resources() == res == [{"id": 1, "name": "Room", "buffer": 0}, {"id": 2, "name": "Other", "buffer": 15}]
    assert s.book(1, 1, 600, 660)["replayed"] is True and s.book(4, 1, 630, 700)["outcome"] == "ACCEPTED"
    assert s.book(6, 2, 674, 700)["outcome"] == "CONFLICT" and s.book(7, 2, 675, 700)["outcome"] == "ACCEPTED"


def test_the_buffer_is_fixed_at_creation():
    s = fresh()
    with pytest.raises(Duplicate): s.create_resource(2, "Other", 0)
    assert s.resource(2)["buffer"] == BUFFER[2] and s.create_resource(3, "Third") == {"id": 3, "name": "Third", "buffer": 0}


def test_replay_never_reaches_the_core():
    s = fresh(); s.book(1, 1, 600, 660)
    s.k = None                                            # a replay that called the core would raise here
    assert s.book(1, 1, 600, 660)["replayed"] is True
    with pytest.raises(ConflictingReplay): s.book(1, 1, 600, 661)
    with pytest.raises(ConflictingReplay): s.cancel(1, 1)


@pytest.mark.parametrize("bad", [-1, 2 ** 53, 1.5, "1", True, None])
def test_invalid_input_changes_nothing(bad):
    s = fresh(); n = len(s.events())
    for call in (lambda: s.book(bad, 1, 0, 10), lambda: s.book(9, 1, bad, 10), lambda: s.book(9, 1, 0, bad), lambda: s.reschedule(9, bad, 0, 10),
                 lambda: s.create_resource(9, "x", bad)):
        with pytest.raises(InvalidRequest): call()
    with pytest.raises(InvalidRequest): s.create_resource(9, "x", 1441)
    assert len(s.events()) == n and s.resource(9) is None


def test_unknown_resource_and_booking():
    s = fresh()
    with pytest.raises(Unknown): s.book(1, 99, 0, 10)
    with pytest.raises(Unknown): s.cancel(2, 99)


V1_DDL = ("CREATE TABLE resources(id INTEGER PRIMARY KEY, name TEXT NOT NULL)",
          "CREATE TABLE slots(id INTEGER PRIMARY KEY, resource INTEGER NOT NULL, start INTEGER NOT NULL, end INTEGER NOT NULL, active INTEGER NOT NULL)",
          "CREATE TABLE ops(request_id INTEGER PRIMARY KEY, kind TEXT NOT NULL, params TEXT NOT NULL, result TEXT NOT NULL)",
          "CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT NOT NULL)")


def v1_state():
    """What the version 1 profile wrote: two touching bookings (free at buffer 0), a refusal, a cancellation."""
    d = pathlib.Path(tempfile.mkdtemp()) / "b.db"; db = sqlite3.connect(d, isolation_level=None)
    for ddl in V1_DDL: db.execute(ddl)
    db.execute("INSERT INTO resources VALUES (1, 'Room')")
    for row in ((1, 1, 600, 660, 1), (2, 1, 660, 720, 1), (3, 1, 500, 560, 0)): db.execute("INSERT INTO slots VALUES (?, ?, ?, ?, ?)", row)
    for rq, kind, params, result in ((1, "book", {"resource": 1, "start": 600, "end": 660}, {"request_id": 1, "booking_id": 1, "resource": 1, "outcome": "ACCEPTED", "conflicts_with": None}),
                                     (4, "book", {"resource": 1, "start": 630, "end": 690}, {"request_id": 4, "booking_id": 4, "resource": 1, "outcome": "CONFLICT", "conflicts_with": 1}),
                                     (5, "cancel", {"booking_id": 3}, {"request_id": 5, "booking_id": 3, "cancelled": True})):
        db.execute("INSERT INTO ops VALUES (?, ?, ?, ?)", (rq, kind, json.dumps(params), json.dumps(result)))
    db.execute("INSERT INTO events(body) VALUES (?)", (json.dumps({"type": "resource.created", "resource": 1, "name": "Room"}),)); db.close()
    return d


def test_version_1_state_is_refused_until_migrated_then_kept_with_buffer_0():
    d = v1_state()
    with pytest.raises(Unrecognised): Store(str(d))
    assert migrate(str(d)).startswith("migrated 1 ") and migrate(str(d)).startswith("already version 2")
    s = Store(str(d))
    assert s.resources() == [{"id": 1, "name": "Room", "buffer": 0}] and s.booking(3)["active"] is False
    assert [(b["id"], b["start"], b["end"], b["active"]) for b in s.resource(1)["bookings"]] == [(1, 600, 660, True), (2, 660, 720, True), (3, 500, 560, False)]
    assert s.book(1, 1, 600, 660)["replayed"] is True and s.book(4, 1, 630, 690) == {"request_id": 4, "booking_id": 4, "resource": 1, "outcome": "CONFLICT", "conflicts_with": 1, "replayed": True}
    assert s.cancel(5, 3)["replayed"] is True and s.book(6, 1, 720, 780)["outcome"] == "ACCEPTED"      # touching at buffer 0
    assert s.events()[0] == {"type": "resource.created", "resource": 1, "name": "Room", "seq": 1}


def test_migrate_refuses_state_it_does_not_recognise():
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "text.db").write_text("this is not a booking database\n")
    with pytest.raises(Unrecognised): migrate(str(d / "text.db"))
    assert (d / "text.db").read_text() == "this is not a booking database\n"
    db = sqlite3.connect(d / "other.db"); db.execute("CREATE TABLE things(x)"); db.close()
    with pytest.raises(Unrecognised): migrate(str(d / "other.db"))
    assert migrate(str(d / "missing.db")).startswith("no state") and not (d / "missing.db").exists()


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
            o, c = k.Book(core.calendar(model[rid]), BUFFER[rid], bid, a * 10, b * 10); model[rid] = core.rows(c); owner.setdefault(bid, rid)
            assert (r["outcome"], r["conflicts_with"]) == core.outcome(o)
        elif bid in owner and any(x[0] == bid for x in model[owner[bid]]):
            rid = owner[bid]
            if op == "cancel":
                r = s.cancel(rq, bid); ok, c = k.Cancel(core.calendar(model[rid]), BUFFER[rid], bid); assert r["cancelled"] == ok
            else:
                r = s.reschedule(rq, bid, a * 10, b * 10); o, c = k.Reschedule(core.calendar(model[rid]), BUFFER[rid], bid, a * 10, b * 10); assert r["outcome"] == core.outcome(o)[0]
            model[rid] = core.rows(c)
        for rid in (1, 2):
            got = [(x["id"], x["start"], x["end"], x["active"]) for x in s.resource(rid)["bookings"]]
            assert got == sorted(model[rid]) and core.valid(got, BUFFER[rid])        # the store keeps calendars in booking-id order
