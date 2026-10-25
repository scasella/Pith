"""Tests of the offline oracle (obligations/boundary/oracle.py), frozen. Three questions: does it give the responses the
contract requires, does it agree with the shipped profile over generated programs (a second implementation of the same
contract, so the agreement is not the oracle checking itself), and do the checks have teeth (an oracle that forgets
receipts, or decides without the core, is caught). Needs the Dafny runtime and the translated core, no service."""
import json, pathlib, subprocess, sys
import pytest
from hypothesis import given, settings, strategies as st, HealthCheck
ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from obligations.boundary import oracle as O
from profiles.sqlite import core as C
from profiles.sqlite.repo import Repo

def create(a, limit): return {"action": "create_account", "args": {"account": a, "limit": limit}}
def auth(a, r, amount): return {"action": "authorize", "args": {"account": a, "request": r, "amount": amount}}
def release(a, r): return {"action": "release", "args": {"account": a, "request": r}}
def capture(a, r): return {"action": "capture", "args": {"account": a, "request": r}}


def test_the_responses_the_contract_requires():
    steps = [create(1, 100), create(1, 5), auth(1, 1, 30), auth(1, 2, 80), auth(1, 1, 30), auth(1, 1, 31), auth(9, 1, 1), auth(1, 3, 0),
             release(1, 1), release(1, 1), release(1, 2), release(1, 9), auth(1, 4, 70), capture(1, 4), capture(1, 4), release(1, 4), capture(1, 1),
             auth(1, 5, 30), auth(1, 5, 30), capture(9, 1)]
    assert O.run(steps) == [
        {"id": 1, "limit": 100}, {"status": 409},
        {"request_id": 1, "decision": "AUTHORIZED", "available_at_decision": 100, "replayed": False},
        {"request_id": 2, "decision": "DECLINED", "available_at_decision": 70, "replayed": False},          # strict: 80 > 70
        {"request_id": 1, "decision": "AUTHORIZED", "available_at_decision": 100, "replayed": True},        # the receipt, not a new decision
        {"status": 409}, {"status": 404}, {"status": 400},                                                   # other amount; unknown account; invalid amount
        {"request_id": 1, "released": True, "replayed": False},
        {"request_id": 1, "released": True, "replayed": True},                                               # a retried release is its receipt
        {"request_id": 2, "released": False, "replayed": False},                                             # declined: nothing to release
        {"request_id": 9, "released": False, "replayed": False},
        {"request_id": 4, "decision": "AUTHORIZED", "available_at_decision": 100, "replayed": False},        # the release gave 30 back
        {"request_id": 4, "captured": True, "amount": 70, "replayed": False},
        {"request_id": 4, "captured": True, "amount": 70, "replayed": True},
        {"request_id": 4, "released": False, "replayed": False},                                             # posted is terminal
        {"request_id": 1, "captured": False, "replayed": False},                                             # released: never captured
        {"request_id": 5, "decision": "AUTHORIZED", "available_at_decision": 30, "replayed": False},
        {"request_id": 5, "decision": "AUTHORIZED", "available_at_decision": 30, "replayed": True},
        {"status": 404}]


def test_extra_step_keys_are_ignored_and_the_command_line_speaks_json():
    steps = [dict(create(1, 100), step=1, observed={"id": 1, "limit": 100}), dict(auth(1, 1, 100), step=2, expected={"x": 1}), release(1, 1)]
    r = subprocess.run([sys.executable, str(ROOT / "obligations/boundary/oracle.py")], input=json.dumps({"steps": steps}), capture_output=True, text=True, cwd="/")
    assert r.returncode == 0 and json.loads(r.stdout)["outcomes"] == O.run(steps) and O.run(steps)[2] == {"request_id": 1, "released": True, "replayed": False}
    bad = subprocess.run([sys.executable, str(ROOT / "obligations/boundary/oracle.py")], input=json.dumps({"steps": [{"action": "refund", "args": {}}]}), capture_output=True, text=True)
    assert bad.returncode != 0, "an action outside the vocabulary is an error, not an outcome"


# ---------------------------------------------------------------- agreement with the shipped profile
def profile_outcomes(steps):
    """The same steps through the shipped sqlite profile (frozen, in process): its bodies and exceptions in the oracle's terms."""
    repo, out = Repo(), []
    try:
        for s in steps:
            a = s["args"]
            try:
                out.append({"create_account": lambda: repo.create_account(a["account"], a["limit"]), "authorize": lambda: repo.authorize(a["account"], a["request"], a["amount"]),
                            "release": lambda: repo.release(a["account"], a["request"]), "capture": lambda: repo.capture(a["account"], a["request"])}[s["action"]]())
            except C.UnknownAccount: out.append({"status": 404})
            except (C.DuplicateAccount, C.ConflictingReplay): out.append({"status": 409})
            except C.InvalidRequest: out.append({"status": 400})
    finally: repo.close()
    return out

amounts = st.sampled_from([0, 1, 10, 30, 30, 50, 70, 100, 101, True, "5"])
step = st.one_of(st.builds(create, st.sampled_from([1, 1, 2]), st.sampled_from([0, 60, 100, 100])),
                 st.builds(auth, st.sampled_from([1, 1, 2, 3]), st.integers(1, 5), amounts),
                 st.builds(release, st.sampled_from([1, 1, 2, 3]), st.integers(1, 5)), st.builds(capture, st.sampled_from([1, 1, 2, 3]), st.integers(1, 5)))
programs = st.lists(step, min_size=1, max_size=30)


@settings(max_examples=120, deadline=None, derandomize=True, database=None, suppress_health_check=[HealthCheck.too_slow])
@given(programs)
def test_the_oracle_agrees_with_the_shipped_profile(steps):
    assert O.run(steps) == profile_outcomes(steps)


class Forgetful(O.Oracle):
    """Known-wrong: answers a retried release with what that call did, as the retry-not-released fixture does."""
    def receipt(self, acct, req, op): return None if op == "release" else super().receipt(acct, req, op)

class AmountLess(O.Oracle):
    """Known-wrong: a retried capture's receipt forgets the amount."""
    def record(self, acct, req, op, body, amount=None): return super().record(acct, req, op, {k: v for k, v in body.items() if k != "amount"} if op == "capture" else body, amount)


@pytest.mark.parametrize("wrong", [Forgetful, AmountLess])
def test_the_agreement_check_has_teeth(wrong):
    steps = [create(1, 100), auth(1, 1, 30), auth(1, 2, 40), release(1, 1), release(1, 1), capture(1, 2), capture(1, 2), auth(1, 1, 30)]
    assert O.run(steps, wrong()) != profile_outcomes(steps), "the shipped profile must disagree with an oracle that forgets receipts"
    assert O.run(steps) == profile_outcomes(steps)


def test_decisions_are_the_cores():
    """A decision comes from the compiled core's Decide against the availability of the same step; a retry and a refusal never call it."""
    calls = []
    class Counting(O.Oracle):
        def __init__(self):
            super().__init__(); decide = self.core.Decide
            self.core = type("Counted", (), {"Decide": lambda s, a, r: calls.append((int(r.id_), int(r.amount))) or decide(a, r), "Release": self.core.Release})()
    out = O.run([create(1, 100), auth(1, 1, 60), auth(1, 1, 60), auth(1, 1, 61), auth(1, 2, 40), auth(1, 3, 1), auth(2, 1, 5), auth(1, 4, 0)], Counting())
    assert calls == [(1, 60), (2, 40), (3, 1)], "only fresh, valid requests on a known account reach the core"
    assert [o.get("decision") for o in out] == [None, "AUTHORIZED", "AUTHORIZED", None, "AUTHORIZED", "DECLINED", None, None]
    class Declines(O.Oracle):
        def __init__(self):
            super().__init__(); self.core = type("Stub", (), {"Decide": lambda s, a, r: (C.AuthSpec.Decision_Declined(), a), "Release": self.core.Release})()
    assert O.run([create(1, 100), auth(1, 1, 60)], Declines())[1]["decision"] == "DECLINED" != O.run([create(1, 100), auth(1, 1, 60)])[1]["decision"]
