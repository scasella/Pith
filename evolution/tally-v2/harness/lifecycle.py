"""
harness/lifecycle.py — the version 2 service judged BLACK-BOX, through its HTTP API, as a separate process. FROZEN once
sealed. Each test names the contract records it bears on in its docstring, so the task packet can name them.
"""
import itertools, pathlib, sys
from concurrent.futures import ThreadPoolExecutor
import pytest
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness.supervisor import Service

RQ = itertools.count(1)


@pytest.fixture
def svc():
    s = Service(ROOT).start()
    try: yield s
    finally: s.stop()


def test_each_counter_has_its_own_bound(svc):
    """Contract: T1, T2."""
    c = svc.client
    a = [c.request(next(RQ), "a")[1]["outcome"] for _ in range(4)]
    b = [c.request(next(RQ), "b")[1]["outcome"] for _ in range(2)]
    assert a == ["OK", "OK", "OK", "REFUSED"] and b == ["OK", "OK"], (a, b)
    assert c.tally("a") == (200, {"counter": "a", "tally": 3, "bound": 3}) and c.tally("b")[1]["tally"] == 2


def test_absent_counter_is_default(svc):
    """Contract: T1, T2."""
    c = svc.client; rq = next(RQ)
    assert c.request(rq)[1] == {"request_id": rq, "counter": "default", "outcome": "OK", "tally": 1, "replayed": False}
    assert c.tally() == (200, {"counter": "default", "tally": 1, "bound": 3}) == c.tally("default")


def test_replays_are_idempotent_across_counters(svc):
    """Contract: Idempotency, T2."""
    c = svc.client; rq = next(RQ)
    first = c.request(rq, "a")[1]; again = c.request(rq, "b")[1]
    assert first["outcome"] == "OK" and again == dict(first, replayed=True), (first, again)
    assert c.tally("a")[1]["tally"] == 1 and c.tally("b")[1]["tally"] == 0


def test_crash_after_acknowledgement_then_restart(svc):
    """Contract: Durability, Idempotency."""
    c = svc.client; rq = next(RQ)
    assert c.request(rq, "a")[1]["outcome"] == "OK"
    svc.kill(); svc.start(); c = svc.client
    assert c.tally("a")[1]["tally"] == 1 and c.request(rq)[1] == {"request_id": rq, "counter": "a", "outcome": "OK", "tally": 1, "replayed": True}


def test_concurrent_requests_never_pass_a_bound(svc):
    """Contract: T1, T2."""
    c = svc.client; ids = [(next(RQ), "ab"[i % 2]) for i in range(16)]
    with ThreadPoolExecutor(8) as ex: res = list(ex.map(lambda x: c.request(*x)[1], ids))
    for k in "ab": assert sum(r["outcome"] == "OK" and r["counter"] == k for r in res) == 3 and c.tally(k)[1]["tally"] == 3, res


def test_bad_input_is_refused_without_effect(svc):
    """Contract: T2."""
    c = svc.client
    for bad in ({"request_id": -1}, {"request_id": "x"}, {}, {"request_id": 2 ** 53}, {"request_id": 1, "counter": ""},
                {"request_id": 1, "counter": "UPPER"}, {"request_id": 1, "counter": "x" * 33}, {"request_id": 1, "counter": 7}):
        assert c._req("POST", "/requests", bad)[0] == 400, bad
    assert c.tally("bad name")[0] == 400 and c.tally()[1]["tally"] == 0
