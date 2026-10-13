"""
harness/boundary.py — the library's domain, black-box: what it must refuse, and that a refusal changes nothing. FROZEN.

harness/LIBRARY.md § Values. Each malformed call is followed by calls whose results depend on whether it changed
anything (the log or the clock), and all of them are compared with the verified core (harness/oracle.py), which
applies nothing for a refused call.
"""
import pathlib, sys
import pytest
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness import run as R, oracle as O

RT = R.runtime(ROOT)
U31, U53 = 2 ** 31 - 1, 2 ** 53 - 1
NOT_WHOLE = [1.5, "3", True, False, None, [], {}]
if RT == "python": NOT_WHOLE += [2.0]                 # Node.js receives JSON 2.0 as the number 2, which is whole there


def same(steps):
    got, want = R.run(steps, ROOT), O.expected({"steps": steps}, RT)
    for i, (g, w) in enumerate(zip(got, want)):
        assert O.comparable(g) == O.comparable(w), f"step {i} {steps[i]}: library gave {g}, the contract requires {w}"
    return got


def new(limit=2, window=10, id="A"): return {"op": "new", "id": id, "limit": limit, "window": window}
def acq(key, now, cost=1, id="A"): return {"op": "acquire", "id": id, "key": key, "now": now, "cost": cost}


@pytest.mark.parametrize("v", [0, -1, U31 + 1] + NOT_WHOLE, ids=repr)
def test_configuration_is_refused_outside_its_domain(v):
    same([new(limit=v), new(window=v, id="B"), new(limit=1, window=1, id="C"), acq("k", 0, id="C")])


@pytest.mark.parametrize("key", ["", "x" * 65, "a b", "é", "a/b", "a\n", 3, None, ["a"]], ids=repr)
def test_malformed_keys_are_refused_without_effect(key):
    same([new(), acq("k", 5), acq(key, 9), {"op": "peek", "id": "A", "key": key, "now": 9}, acq("k", 6), acq("k", 6),
          acq("x" * 64, 6), acq("a.b:c_d-E9", 6)])


@pytest.mark.parametrize("cost", [0, -1, U31 + 1] + NOT_WHOLE, ids=repr)
def test_malformed_costs_are_refused_without_effect(cost):
    same([new(), acq("k", 5, cost), acq("k", 5, 2), acq("k", 5, 1)])


@pytest.mark.parametrize("now", [-1, U53 + 1] + NOT_WHOLE, ids=repr)
def test_malformed_instants_are_refused_without_effect(now):
    same([new(), acq("k", 5), acq("k", now), {"op": "peek", "id": "A", "key": "k", "now": now}, acq("k", 6), acq("k", 7)])


def test_a_refused_call_does_not_advance_the_clock():
    same([new(), acq("k", 5), acq("bad key", 1000), acq("k", 1000, 0), {"op": "peek", "id": "A", "key": "", "now": 1000}, acq("k", 6)])


def test_arguments_are_checked_before_the_clock():
    same([new(), acq("k", 50), acq("bad key", 1), acq("k", 1, 0), acq("k", 1)])


def test_cost_above_the_limit_is_a_denial_not_an_error():
    same([new(limit=3), acq("k", 0, 4), acq("k", 0, U31), acq("k", 0, 3)])


def test_omitted_cost_is_one():
    same([new(), {"op": "acquire", "id": "A", "key": "k", "now": 0}, {"op": "acquire", "id": "A", "key": "k", "now": 0}, acq("k", 0)])


def test_unknown_keys_have_their_whole_quota():
    same([new(limit=7), {"op": "peek", "id": "A", "key": "never-used", "now": 0}])


@pytest.mark.parametrize("text", ["", "garbage", "{}", "[]", "null", "0", '{"limit": 1}'])
def test_load_refuses_what_dump_did_not_produce(text):
    same([{"op": "load", "id": "B", "text": text}])


def test_load_refuses_a_truncated_dump():
    same([new(), acq("k", 3), acq("j", 4), {"op": "dump", "id": "A"}, {"op": "load", "id": "B", "from": "A", "truncate": True}, acq("k", 4)])


def test_decisions_have_the_contract_types():
    """granted is a boolean, remaining a whole number, retry_after a whole number or None/null (never 0 or undefined)."""
    got = same([new(limit=1), acq("k", 0), acq("k", 1), acq("k", 1, 2)])
    assert got[1]["ok"]["retry_after"] is None and got[2]["ok"]["retry_after"] == 9 and got[3]["ok"]["retry_after"] is None


def test_dump_is_text():
    got = same([new(), acq("k", 0), {"op": "dump", "id": "A"}])
    assert got[2]["ok"]["type"] == "str"
