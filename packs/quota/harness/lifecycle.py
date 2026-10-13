"""
harness/lifecycle.py — the candidate's library, black-box, on the cases a reader can check by hand. FROZEN.

Every program runs in a fresh driver process started as the candidate (harness/run.py); expectations are the reviewed
traces (spec/TraceData.dfy), the verified core (harness/oracle.py) or, where the core is too slow to ask (a window of
2^31 - 1 instants), arithmetic written out in the test.
"""
import pathlib, sys
import pytest
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness import run as R, oracle as O, tracedata as T

RT = R.runtime(ROOT)


def same(steps):
    """Run on the candidate and on the oracle; assert they agree step by step."""
    got, want = R.run(steps, ROOT), O.expected({"steps": steps}, RT)
    for i, (g, w) in enumerate(zip(got, want)):
        assert O.comparable(g) == O.comparable(w), f"step {i} {steps[i]}: library gave {g}, the contract requires {w}"
    return got


def acq(key, now, cost=1, id="A"): return {"op": "acquire", "id": id, "key": key, "now": now, "cost": cost}


@pytest.mark.parametrize("trace", T.traces(), ids=lambda t: t[0])
def test_reviewed_traces(trace):
    """The reviewed traces, step by step, through the library (the same data the Dafny checks run against the core)."""
    name, limit, window, steps = trace
    got = R.run(T.program(limit, window, steps), ROOT)
    assert got[0] == {"ok": None}, f"{name}: Limiter(limit={limit}, window={window}) failed: {got[0]}"
    for i, ((k, c, n, want), g) in enumerate(zip(steps, got[1:])):
        assert O.comparable(g) == O.comparable(want), f"{name} step {i + 1} acquire({k!r}, now={n}, cost={c}): library gave {g}, the reviewed trace requires {want}"


def test_window_is_half_open_at_every_boundary():
    """For several windows: a grant at t counts at t + window - 1 and not at t + window."""
    for w in (1, 2, 7, 30):
        steps = [{"op": "new", "id": "A", "limit": 1, "window": w}, acq("k", 100), acq("k", 100 + w - 1), acq("k", 100 + w)]
        got = same(steps)
        assert got[3]["ok"]["granted"] is True


def test_no_window_ever_holds_more_than_the_limit():
    """A greedy client asks at every instant; in every window of the configured length the grants stay within the limit."""
    limit, window = 4, 9
    steps = [{"op": "new", "id": "A", "limit": limit, "window": window}] + [acq("k", t, 1 + t % 3) for t in range(60)]
    got = same(steps)
    grants = [(t, 1 + t % 3) for t, g in zip(range(60), got[1:]) if g["ok"]["granted"]]
    for end in range(60 + window):
        assert sum(c for t, c in grants if end - window < t <= end) <= limit, f"window ending at {end} holds more than {limit}"


def test_limiters_are_independent():
    """Two limiters in one process, same keys, different configurations: neither sees the other's grants or clock."""
    steps = [{"op": "new", "id": "A", "limit": 1, "window": 10}, {"op": "new", "id": "B", "limit": 2, "window": 5},
             acq("k", 50, id="A"), acq("k", 50, id="B"), acq("k", 50, id="B"), acq("k", 51, id="A"), acq("k", 51, id="B"),
             acq("k", 3, id="B"),                                         # B's clock is 51, A's too: both regress
             {"op": "new", "id": "C", "limit": 1, "window": 10}, acq("k", 3, id="C"), acq("k", 3, id="C")]
    got = same(steps)
    assert got[9]["ok"]["granted"] is True, "a new limiter starts with no grants and its clock at 0"


def test_dump_and_load_carry_the_whole_state():
    """A loaded limiter decides like the original: configuration, clock and every grant that can still count."""
    steps = [{"op": "new", "id": "A", "limit": 3, "window": 10}, acq("a", 0), acq("a", 4, 2), acq("b", 6), {"op": "peek", "id": "A", "key": "a", "now": 7},
             {"op": "dump", "id": "A"}, {"op": "load", "id": "B", "from": "A"},
             acq("a", 6, id="B"),                                          # the clock (7) came along: regressed
             acq("a", 9, id="B"), acq("a", 10, id="B"), acq("a", 13, id="B"), acq("b", 15, id="B"), acq("a", 14, 2, id="B"),
             acq("a", 9, id="A"), acq("a", 14, 3, id="A")]                # the original is untouched by B's calls
    same(steps)


def test_dump_is_a_snapshot():
    """Later calls on the original do not change what an earlier dump loads to; loading twice gives two independent limiters."""
    steps = [{"op": "new", "id": "A", "limit": 2, "window": 10}, acq("a", 1), {"op": "dump", "id": "A"}, acq("a", 2), acq("a", 3),
             {"op": "load", "id": "B", "from": "A"}, {"op": "load", "id": "C", "from": "A"},
             acq("a", 3, id="B"), acq("a", 3, id="B"), acq("a", 3, id="C"), acq("a", 3, id="C")]
    same(steps)


def test_clock_regression_changes_nothing():
    steps = [{"op": "new", "id": "A", "limit": 2, "window": 10}, acq("a", 5), acq("a", 4), acq("b", 0), {"op": "peek", "id": "A", "key": "a", "now": 4},
             {"op": "peek", "id": "A", "key": "a", "now": 5}, acq("a", 5), acq("a", 5)]
    same(steps)


def test_decisions_do_not_depend_on_the_wall_clock():
    """The same calls give the same decisions whether they are made at once or with real time passing in between."""
    base = [{"op": "new", "id": "A", "limit": 2, "window": 3}, acq("a", 0), acq("a", 1), acq("a", 2), acq("a", 3), acq("a", 4)]
    fast = R.run(base, ROOT)
    slow = R.run([base[0], base[1], {"op": "sleep", "ms": 1100}, base[2], {"op": "sleep", "ms": 1100}] + base[3:], ROOT)
    assert [O.comparable(x) for x in fast] == [O.comparable(x) for i, x in enumerate(slow) if i not in (2, 4)]
    same(base)


def test_one_limiter_shared_by_threads_grants_exactly_the_limit():
    """Python: 8 threads share one fresh limiter and call it at one instant, all on the same key at the same moment, over
    5000 keys (each key is one chance for two threads to both see room for its last unit); exactly `limit` granted
    per key. Node.js: the same calls in turn. Expectation by hand ([Q1] [Q2]: at one instant on a fresh limiter, a key
    is granted until its limit and denied after); the core would be slow on a 10 000-entry log."""
    for limit, keys, calls in ((37, None, 150), (1, 5000, 10000), (3, 2000, 8000)):
        steps = [{"op": "new", "id": "A", "limit": limit, "window": 1000},
                 {"op": "burst", "id": "A", "key": "hot", "now": 5, "cost": 1, "threads": 8, "calls": calls, **({"keys": keys} if keys else {})},
                 {"op": "peek", "id": "A", "key": "hot0" if keys else "hot", "now": 5}]
        got = R.run(steps, ROOT)
        assert got[1] == {"ok": {"granted": limit * (keys or 1), "errors": []}}, f"{8 * calls} calls over {keys or 1} key(s) with limit {limit}: {got[1]}"
        assert got[2] == {"ok": 0}, f"after the burst, peek gave {got[2]}"


def test_extreme_values():
    """The largest window, limit and instant. Expectations by hand: the core's retry search is linear in the window."""
    W, L, N = 2 ** 31 - 1, 2 ** 31 - 1, 2 ** 53 - 1
    t0 = N - W
    steps = [{"op": "new", "id": "A", "limit": L, "window": W}, acq("k", t0, L), acq("k", t0 + 1, 1), acq("k", N, 1),
             {"op": "peek", "id": "A", "key": "k", "now": N}, acq("j", N, L), acq("j", N, 1)]
    got = R.run(steps, ROOT)
    want = [{"ok": None},
            {"ok": {"granted": True, "remaining": 0, "retry_after": None}},
            {"ok": {"granted": False, "remaining": 0, "retry_after": W - 1}},       # the grant at t0 expires at t0 + W = N
            {"ok": {"granted": True, "remaining": L - 1, "retry_after": None}},
            {"ok": L - 1},
            {"ok": {"granted": True, "remaining": 0, "retry_after": None}},
            {"ok": {"granted": False, "remaining": 0, "retry_after": W}}]           # nothing more until the whole window passes
    for i, (g, w) in enumerate(zip(got, want)):
        assert O.comparable(g) == O.comparable(w), f"step {i} {steps[i]}: library gave {g}, the contract requires {w}"
