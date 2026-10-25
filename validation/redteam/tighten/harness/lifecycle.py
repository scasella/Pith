"""
harness/lifecycle.py — the service judged BLACK-BOX, through its HTTP API, as a separate process. FROZEN once sealed.
Each test names the contract records it bears on in its docstring, so the task packet can name them.
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


def test_the_bound_holds_and_refusals_change_nothing(svc):
    """Contract: T1, T2."""
    c = svc.client
    outcomes = [c.request(next(RQ))[1]["outcome"] for _ in range(5)]
    assert outcomes == ["OK", "OK", "OK", "REFUSED", "REFUSED"], outcomes
    assert c.tally() == (200, {"tally": 3, "bound": 3})


def test_replays_are_idempotent(svc):
    """Contract: Idempotency, T2."""
    c = svc.client; rq = next(RQ)
    first = c.request(rq)[1]; again = c.request(rq)[1]
    assert first["outcome"] == "OK" and again == dict(first, replayed=True), (first, again)
    assert c.tally()[1]["tally"] == 1


def test_crash_after_acknowledgement_then_restart(svc):
    """Contract: Durability, Idempotency."""
    c = svc.client; rq = next(RQ)
    assert c.request(rq)[1]["outcome"] == "OK"
    svc.kill(); svc.start(); c = svc.client
    assert c.tally()[1]["tally"] == 1 and c.request(rq)[1]["replayed"] is True


def test_concurrent_requests_never_pass_the_bound(svc):
    """Contract: T1, T2."""
    c = svc.client; ids = [next(RQ) for _ in range(12)]
    with ThreadPoolExecutor(8) as ex: res = list(ex.map(lambda r: c.request(r)[1]["outcome"], ids))
    assert res.count("OK") == 3 and c.tally()[1]["tally"] == 3, res


def test_bad_input_is_refused_without_effect(svc):
    """Contract: T2."""
    c = svc.client
    for bad in ({"request_id": -1}, {"request_id": "x"}, {}, {"request_id": 2 ** 53}):
        assert c._req("POST", "/requests", bad)[0] == 400, bad
    assert c.tally()[1]["tally"] == 0
