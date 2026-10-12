"""
profiles/sqlite/tests/test_profile.py — in-process tests of the SHIPPED sqlite profile. Frozen, and run by the
gate only when profile: sqlite, because importing a module into the judge is acceptable only for frozen code.
Custom profiles are never imported: they are judged black-box through their service by obligations/service/lifecycle.py.

Repo protocol:  Repo(path=None); create_account(id, limit) -> dict; authorize(id, request_id, amount) -> dict;
                release(id, request_id) -> dict; account(id) -> dict; events(since=0) -> list; verify_replay() -> list;
                close(); attribute `path` for reopening. Invalid input raises ValueError (any subclass); unknown account KeyError.
"""
import importlib, pathlib, sys, threading
from concurrent.futures import ThreadPoolExecutor
import pytest
from hypothesis import settings, strategies as st, HealthCheck
from hypothesis.stateful import RuleBasedStateMachine, Bundle, rule, invariant, initialize

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "kernel" / "core" / "py" / "authcore-py"))
Repo = importlib.import_module("profiles.sqlite.repo").Repo
import _dafny, module_, AuthSpec, AuthCore, PostingCore  # noqa: F401
PURE = AuthCore.Core(); POSTER = PostingCore.Poster(); Request = AuthSpec.Request_Request
def fresh(limit): return AuthSpec.Account_Account(limit, 0, _dafny.Map({}), _dafny.Map({}))
def oracle_holds(a): return {int(k): int(v) for k, v in a.holds.items}

def decided(repo, acct=None):
    return [e for e in repo.events() if e["type"] == "auth.decided" and (acct is None or e["account_id"] == acct)]

# ---------------------------------------------------------------- domain / validation
BAD_AMOUNTS = [0, -1, -50, True, False, "60", 60.0, None, 2**53, 2**70]
@pytest.mark.parametrize("bad", BAD_AMOUNTS)
def test_invalid_amount_rejected_without_effect(bad):
    r = Repo(); r.create_account(1, 100)
    before = (r.account(1), len(r.events()))
    with pytest.raises(ValueError):
        r.authorize(1, 7, bad)
    assert (r.account(1), len(r.events())) == before, "invalid input must change nothing and emit nothing"
    assert r.authorize(1, 7, 10)["decision"] == "AUTHORIZED", "the id is still fresh after a rejected request"
    r.close()

@pytest.mark.parametrize("bad", [-1, True, "1", 2**53, None])
def test_invalid_ids_and_limits_rejected(bad):
    r = Repo()
    with pytest.raises(ValueError): r.create_account(bad, 100)
    with pytest.raises(ValueError): r.create_account(2, bad if bad != -1 else -1)
    r.create_account(3, 100)
    with pytest.raises(ValueError): r.authorize(3, bad, 10)
    with pytest.raises(KeyError):   r.authorize(999, 1, 10)
    r.close()

def test_duplicate_create_rejected_and_repo_still_usable():
    r = Repo(); r.create_account(1, 100)
    with pytest.raises(ValueError): r.create_account(1, 5)
    assert r.account(1)["limit"] == 100
    assert r.authorize(1, 1, 100)["decision"] == "AUTHORIZED"          # equality authorizes, after the failed create
    assert r.verify_replay() == []
    r.close()

# ---------------------------------------------------------------- idempotency and conflicts
def test_replay_is_idempotent_and_conflicts_are_rejected():
    r = Repo(); r.create_account(1, 100)
    a = r.authorize(1, 1, 60); n = len(decided(r))
    b = r.authorize(1, 1, 60)
    assert b["replayed"] is True and b["decision"] == a["decision"] and len(decided(r)) == n, "replay: same decision, no new decision event"
    with pytest.raises(ValueError): r.authorize(1, 1, 61)
    assert len(decided(r)) == n and r.account(1)["holds"] == {1: 60}
    r.close()

def test_crash_window_response_lost_then_retry():
    """The client never saw the first response; the retry must return the committed decision and the event log
    must show exactly one decision and one op.committed for the request."""
    r = Repo(); r.create_account(1, 100)
    r.authorize(1, 1, 60)                           # response 'lost'
    again = r.authorize(1, 1, 60)
    assert again["replayed"] and again["decision"] == "AUTHORIZED"
    evs = [e for e in r.events() if e.get("request_id") == 1]
    assert [e["type"] for e in evs].count("auth.decided") == 1
    assert [e["type"] for e in evs].count("op.committed") == 1
    r.close()

# ---------------------------------------------------------------- durability and restart
def test_restart_preserves_state_oracle_and_idempotency():
    r = Repo(); r.create_account(1, 100); r.create_account(2, 50)
    r.authorize(1, 1, 60); r.authorize(2, 2, 50); r.release(2, 2); path = r.path; r.close()
    r2 = Repo(path)
    assert r2.verify_replay() == [], "oracle rebuilt from the durable log must match stored state"
    assert r2.account(1)["holds"] == {1: 60} and r2.account(2)["holds"] == {}
    assert r2.authorize(1, 1, 60)["replayed"] is True, "idempotency survives restart"
    assert r2.authorize(1, 3, 40)["decision"] == "AUTHORIZED" and r2.authorize(1, 4, 1)["decision"] == "DECLINED"
    assert r2.verify_replay() == []
    r2.close()

# ---------------------------------------------------------------- events contract
def test_every_write_ends_with_op_committed_in_order():
    r = Repo(); r.create_account(1, 100); r.authorize(1, 1, 60); r.authorize(1, 2, 60); r.release(1, 1)
    evs = r.events(); types = [e["type"] for e in evs]
    assert types == ["account.created", "op.committed", "auth.decided", "reservation.created", "op.committed",
                     "auth.decided", "op.committed", "reservation.released", "op.committed"]
    assert [e["seq"] for e in evs] == sorted(e["seq"] for e in evs)
    assert all(e["producer"] == "auth-service" for e in evs)
    import hashlib, json
    prev = "0" * 64
    for e in evs:                                                       # hash chain
        body = {k: v for k, v in e.items() if k not in ("hash", "seq")}
        assert e["prev_hash"] == prev and e["hash"] == hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), "event chain broken"
        prev = e["hash"]
    commits = [e for e in evs if e["type"] == "op.committed"]
    assert [c["state_after"]["reserved"] for c in commits] == [0, 60, 60, 0], "state_after must carry the committed state"
    assert commits[-1]["state_after"] == {"limit": 100, "posted": 0, "reserved": 0}
    r.close()

# ---------------------------------------------------------------- concurrency and isolation
def test_concurrent_bursts_never_exceed_and_readers_see_only_committed_states():
    r = Repo(); r.create_account(1, 100); stop = threading.Event(); bad = []
    def reader():
        while not stop.is_set():
            try:
                v = r.account(1)
                if v["posted"] + sum(v["holds"].values()) > v["limit"] or set(v["holds"]) != {k for k, s in v["status"].items() if s == "AUTH"}:
                    bad.append(v)
            except Exception as e: bad.append(repr(e))
    threads = [threading.Thread(target=reader, daemon=True) for _ in range(3)]; [t.start() for t in threads]
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda i: r.authorize(1, 100 + i, 30), range(16)))
        list(ex.map(lambda i: r.release(1, 100 + i), range(0, 16, 2)))
        list(ex.map(lambda i: r.authorize(1, 200 + i, 30), range(8)))
    stop.set(); [t.join(timeout=2) for t in threads]
    assert bad == [], f"readers observed an inconsistent or uncommitted state: {bad[:2]}"
    assert len(decided(r)) == 24 and r.verify_replay() == []
    v = r.account(1); assert sum(v["holds"].values()) <= 100
    r.close()

# ---------------------------------------------------------------- posting kernel
def test_capture_posts_exactly_and_is_terminal():
    r = Repo(); r.create_account(1, 100); r.authorize(1, 1, 60)
    assert r.capture(1, 1) == {"request_id": 1, "captured": True, "amount": 60, "replayed": False}
    v = r.account(1); assert v["posted"] == 60 and v["holds"] == {} and v["status"][1] == "POST" and v["available"] == 40
    assert r.capture(1, 1)["replayed"] is True and r.account(1)["posted"] == 60          # idempotent, no double post
    assert r.release(1, 1) == {"request_id": 1, "released": False}                        # cannot release a posted request
    assert r.authorize(1, 2, 40)["decision"] == "AUTHORIZED" and r.authorize(1, 3, 1)["decision"] == "DECLINED"
    assert r.capture(1, 9) == {"request_id": 9, "captured": False} and r.verify_replay() == []
    r.close()

# ---------------------------------------------------------------- stateful replay against the proven core
class Machine(RuleBasedStateMachine):
    accounts = Bundle("accounts")
    def __init__(self):
        super().__init__(); self.r = Repo(); self.o = {}; self.na = 1; self.nr = 1
    def teardown(self):
        assert self.r.verify_replay() == []; self.r.close()
    @initialize(target=accounts, limit=st.integers(0, 300))
    def create(self, limit):
        a = self.na; self.na += 1; self.r.create_account(a, limit); self.o[a] = fresh(limit); return a
    @rule(acct=accounts, amount=st.integers(1, 400))
    def authorize(self, acct, amount):
        rid = self.nr; self.nr += 1
        before = self.r.account(acct)["available"]
        res = self.r.authorize(acct, rid, amount)
        d, self.o[acct] = PURE.Decide(self.o[acct], Request(rid, amount))
        assert res["decision"] == ("AUTHORIZED" if d.is_Authorized else "DECLINED")
        assert (amount > before) == (res["decision"] == "DECLINED") and res["available_at_decision"] == before
    @rule(acct=accounts)
    def release(self, acct):
        h = self.r.account(acct)["holds"]
        if h:
            rid = min(h); assert self.r.release(acct, rid)["released"]; self.o[acct] = PURE.Release(self.o[acct], rid)
    @rule(acct=accounts)
    def capture(self, acct):
        h = self.r.account(acct)["holds"]
        if h:
            rid = max(h); assert self.r.capture(acct, rid)["captured"]; self.o[acct] = POSTER.Capture(self.o[acct], rid)
    @invariant()
    def matches(self):
        for a, o in self.o.items():
            v = self.r.account(a); assert v["holds"] == oracle_holds(o) and v["posted"] == int(o.posted) and v["posted"] + sum(v["holds"].values()) <= v["limit"]

TestMachine = Machine.TestCase
TestMachine.settings = settings(max_examples=40, stateful_step_count=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])
