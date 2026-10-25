"""
profiles/sqlite_occ/tests/test_occ.py — in-process tests of the SHIPPED sqlite-occ profile (docs/rfc/0007 § 6). Frozen, and run by the
gate only when profile: sqlite-occ, for the reason test_profile.py is run only for sqlite: importing a module into the judge is acceptable
only for frozen code. Custom profiles are never imported: they are judged black-box through their service.

Three kinds of test:
  - the profile is the shipped profile in everything but how concurrent operations on one account are kept atomic: the same outcomes,
    events and receipts as profiles/sqlite on a long operation sequence, the same refusals, the same contract tests on its own layout;
  - its concurrency control, EXPLORED, not sampled: gate/interleave.py runs every interleaving, with at most two preemptions, of two and
    of three concurrent operations over a real SQLite file, and every schedule must be linearizable against the verified core and keep INV1
    (tests/scenarios.py says exactly what is checked);
  - the explorer can fail: three known-wrong stores (tests/wrong/), each the profile with one defect, must each have a violating schedule,
    the same one on every run.
"""
import itertools, json, pathlib, sqlite3, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
import pytest
ROOT = pathlib.Path(__file__).resolve().parents[3]
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(HERE))
import scenarios as S
from gate import interleave as IL
from profiles.sqlite import core
from profiles.sqlite.repo import Repo as SqliteRepo, UnmigratedState as SqliteUnmigrated
from profiles.sqlite_occ import repo as occ
from profiles.sqlite_occ.repo import Repo, UnmigratedState, OccRetriesExhausted, RETRY_BUDGET
from profiles.sqlite_occ.migrate import migrate, Refused


@pytest.fixture
def controller():
    """The cooperative controller installed for ONE test (it replaces threading.Lock, time.sleep and sqlite3.connect for what follows) and
    removed afterwards, so the real-thread tests in this module, and any other module in the session, run on the standard library."""
    saved = (threading.Lock, threading.RLock, time.sleep, sqlite3.connect, dict(IL._installed))
    try: yield
    finally:
        threading.Lock, threading.RLock, time.sleep, sqlite3.connect = saved[:4]
        IL._installed.clear(); IL._installed.update(saved[4])


def decided(r, acct=None): return [e for e in r.events() if e["type"] == "auth.decided" and (acct is None or e["account_id"] == acct)]
def strip(evs): return [{k: v for k, v in e.items() if k not in ("op_id", "prev_hash", "hash", "seq")} for e in evs]


# ---------------------------------------------------------------- the same profile, as far as outcomes go
def test_same_outcomes_events_and_refusals_as_the_shipped_profile_on_a_long_operation_sequence():
    """600 pseudo-random operations (valid, invalid, replays, conflicts, unknown accounts, declines) through this profile and through
    profiles/sqlite: every outcome or refusal, every account, and every event (apart from operation ids and hashes) equal."""
    import random
    rng = random.Random(7); o, s = Repo(), SqliteRepo()
    def both(name, *a):
        def call(r):
            try: return ("ok", getattr(r, name)(*a))
            except Exception as e: return ("refused", type(e).__name__)
        x, y = call(o), call(s); assert x == y, f"{name}{a}: sqlite-occ gave {x}, sqlite gave {y}"
    for acct, limit in ((1, 100), (2, 50), (3, 0)): both("create_account", acct, limit)
    both("create_account", 1, 5); both("create_account", -1, 5); both("authorize", 1, 1, True)
    for _ in range(600):
        acct, req, k = rng.choice([1, 2, 3, 9]), rng.randint(1, 40), rng.random()
        if k < .5: both("authorize", acct, req, rng.choice([1, 10, 30, 60, 100, 120]))
        elif k < .7: both("release", acct, req)
        elif k < .9: both("capture", acct, req)
        else: both("authorize", acct, req, rng.randint(1, 5))
    assert all(o.account(a) == s.account(a) for a in (1, 2, 3)) and strip(o.events()) == strip(s.events())
    assert o.verify_replay() == [] and s.verify_replay() == []


@pytest.mark.parametrize("bad", [0, -1, True, "60", 60.0, None, 2 ** 53])
def test_invalid_amount_rejected_without_effect(bad):
    r = Repo(); r.create_account(1, 100); before = (r.account(1), len(r.events()))
    with pytest.raises(ValueError): r.authorize(1, 7, bad)
    assert (r.account(1), len(r.events())) == before and r.authorize(1, 7, 10)["decision"] == "AUTHORIZED"


def test_replay_conflict_unknown_account_and_duplicate_create():
    r = Repo(); r.create_account(1, 100); a = r.authorize(1, 1, 60); n = len(decided(r))
    b = r.authorize(1, 1, 60)
    assert b == dict(a, replayed=True) and len(decided(r)) == n
    with pytest.raises(ValueError): r.authorize(1, 1, 61)
    with pytest.raises(KeyError): r.authorize(9, 1, 10)
    with pytest.raises(ValueError): r.create_account(1, 5)
    assert r.account(1)["limit"] == 100 and r.account(1)["holds"] == {1: 60} and r.verify_replay() == []


def test_receipts_survive_a_reopen_and_the_event_contract_holds():
    r = Repo(); r.create_account(1, 100); r.authorize(1, 1, 30); r.authorize(1, 2, 50); r.authorize(1, 3, 60)
    assert r.release(1, 1) == {"request_id": 1, "released": True, "replayed": False}
    assert r.capture(1, 2) == {"request_id": 2, "captured": True, "amount": 50, "replayed": False}
    n = len(r.events()); path = r.path; r = Repo(path)
    assert r.release(1, 1) == {"request_id": 1, "released": True, "replayed": True}
    assert r.capture(1, 2) == {"request_id": 2, "captured": True, "amount": 50, "replayed": True}
    assert r.authorize(1, 3, 60) == {"request_id": 3, "decision": "DECLINED", "available_at_decision": 20, "replayed": True}
    assert r.release(1, 2) == {"request_id": 2, "released": False, "replayed": False} and len(r.events()) == n and r.verify_replay() == []
    types = [e["type"] for e in r.events()]
    assert types == ["account.created", "op.committed", "auth.decided", "reservation.created", "op.committed", "auth.decided", "reservation.created", "op.committed",
                     "auth.decided", "op.committed", "reservation.released", "op.committed", "capture.posted", "op.committed"]
    commits = [e["state_after"] for e in r.events() if e["type"] == "op.committed"]
    assert [c["reserved"] for c in commits] == [0, 30, 80, 80, 50, 0] and [c["posted"] for c in commits] == [0, 0, 0, 0, 0, 50]


# ---------------------------------------------------------------- the layout: versions, and refusal of the other profile's state
def test_every_committed_change_bumps_the_accounts_version_once_and_nothing_else_does():
    r = Repo(); r.create_account(1, 100); r.create_account(2, 100)
    def version(a): return sqlite3.connect(r.path).execute("SELECT version FROM accounts WHERE id=?", (a,)).fetchone()[0]
    assert (version(1), version(2)) == (0, 0)
    r.authorize(1, 1, 30); r.authorize(1, 2, 90); r.release(1, 1); r.capture(1, 2); r.authorize(2, 1, 10)
    assert (version(1), version(2)) == (3, 1), "a decline changes the state (it records the decision), a release, a capture likewise"
    r.authorize(1, 1, 30); r.release(1, 1); r.release(1, 77); r.capture(1, 88); r.account(1); r.events(); r.verify_replay()
    assert (version(1), version(2)) == (3, 1), "replays, no-ops and reads change no version"


def test_reads_take_no_write_lock():
    """While another connection holds the write lock (BEGIN IMMEDIATE), the optimistic read of an operation, account(), events() and
    verify_replay() all answer: only the commit waits for the lock."""
    r = Repo(); r.create_account(1, 100); r.authorize(1, 1, 30)
    w = sqlite3.connect(r.path, isolation_level=None); w.execute("BEGIN IMMEDIATE")
    try:
        db = r._connect(); db.execute("PRAGMA busy_timeout=0")
        try: a, version, rec = r._snapshot(db, 1, 1, "authorize")
        finally: db.close()
        assert version == 1 and rec[1]["decision"] == "AUTHORIZED" and core.holds(a) == {1: 30}
        assert r.account(1)["holds"] == {1: 30} and len(r.events()) == 5 and r.verify_replay() == []
    finally: w.execute("ROLLBACK"); w.close()


def test_state_written_by_the_shipped_sqlite_profile_is_refused_until_migrated():
    s = SqliteRepo(); s.create_account(1, 100); s.authorize(1, 1, 30); s.authorize(1, 2, 90); s.authorize(1, 3, 20); s.release(1, 1); s.capture(1, 3)
    before = s.events(); path = s.path; s.close()
    with pytest.raises(UnmigratedState): Repo(path)
    note = migrate(path); assert "migrated 1 account(s)" in note and "nothing to do" in migrate(path)                        # re-runnable
    r = Repo(path)
    assert r.events() == before and r.verify_replay() == [], "events, receipts and the chain are kept byte for byte"
    assert r.authorize(1, 2, 90) == {"request_id": 2, "decision": "DECLINED", "available_at_decision": 70, "replayed": True}
    assert r.release(1, 1) == {"request_id": 1, "released": True, "replayed": True} and r.capture(1, 3) == {"request_id": 3, "captured": True, "amount": 20, "replayed": True}
    with pytest.raises(ValueError): r.authorize(1, 1, 31)
    assert r.authorize(1, 4, 10)["decision"] == "AUTHORIZED" and r.verify_replay() == []
    with pytest.raises(SqliteUnmigrated): SqliteRepo(path)                                                                   # and the other way round


def test_previous_contract_state_is_migrated_in_one_step_and_junk_is_refused(tmp_path):
    from profiles.sqlite.migrate import migrate as previous
    s = SqliteRepo(); s.create_account(1, 100); s.authorize(1, 1, 30); s.release(1, 1); path = s.path; s.close()
    db = sqlite3.connect(path, isolation_level=None); db.execute("DROP TABLE receipts"); db.execute("DROP TABLE meta"); db.close()      # as the previous contract wrote it
    with pytest.raises(UnmigratedState): Repo(path)
    assert "receipts" in migrate(path) and Repo(path).release(1, 1) == {"request_id": 1, "released": True, "replayed": True}
    junk = tmp_path / "x.db"; junk.write_text("not a database\n")
    with pytest.raises(Refused): migrate(str(junk))
    assert junk.read_text() == "not a database\n"
    with pytest.raises(Refused): migrate(str(tmp_path / "missing.db"))
    other = sqlite3.connect(tmp_path / "other.db", isolation_level=None); other.execute("CREATE TABLE t(x)"); other.close()
    with pytest.raises(Refused): migrate(str(tmp_path / "other.db"))


# ---------------------------------------------------------------- real threads: bursts, two Repo objects, the retry budget
def test_bursts_of_sixteen_threads_decide_each_request_once_and_never_exhaust_the_budget():
    """16 threads (the frozen lifecycle harness's widest burst), 48 authorizations of 30 on one account of 100, then releases and
    more authorizations: exactly the requests that fit are authorized, every request decided once, the log intact, no operation
    raised OccRetriesExhausted. Real threads, so which operations collide varies; the scenarios below are what is exhaustive."""
    r = Repo(); r.create_account(1, 100); stop = threading.Event(); bad = []
    def reader():
        while not stop.is_set():
            v = r.account(1)
            if v["posted"] + sum(v["holds"].values()) > v["limit"] or set(v["holds"]) != {k for k, s in v["status"].items() if s == "AUTH"}: bad.append(v)
            time.sleep(0.002)
    ts = [threading.Thread(target=reader, daemon=True) for _ in range(3)]; [t.start() for t in ts]
    with ThreadPoolExecutor(16) as ex:
        res = list(ex.map(lambda i: r.authorize(1, 100 + i, 30)["decision"], range(48)))
        assert res.count("AUTHORIZED") == 3 and r.account(1)["available"] == 10
        list(ex.map(lambda i: r.release(1, 100 + i), [i for i in range(48) if res[i] == "AUTHORIZED"]))
        res2 = list(ex.map(lambda i: r.authorize(1, 200 + i, 30)["decision"], range(32)))
    stop.set(); [t.join(timeout=2) for t in ts]
    assert bad == [] and res2.count("AUTHORIZED") == 3 and len(decided(r)) == 80 and r.verify_replay() == []
    assert len({e["request_id"] for e in decided(r)}) == 80 and r.retries < 48 * RETRY_BUDGET


def test_two_repo_objects_on_one_file_are_as_safe_as_one():
    """Operations arrive through two Repo objects (two processes would be the same to the database): still one winner."""
    a = Repo(); b = Repo(a.path); a.create_account(1, 100)
    with ThreadPoolExecutor(8) as ex: res = list(ex.map(lambda i: (a if i % 2 else b).authorize(1, i, 60)["decision"], range(24)))
    assert res.count("AUTHORIZED") == 1 and a.account(1)["holds"] == b.account(1)["holds"] and len(a.account(1)["holds"]) == 1 and a.verify_replay() == []


def test_a_contended_operation_that_exhausts_the_retry_budget_says_so_and_changes_nothing():
    class Starved(Repo):
        def _cas(self, db, acct, version, state): return False                  # every compare-and-swap is lost, as under unending contention
    r = Starved(); r.create_account(1, 100); n = len(r.events())
    with pytest.raises(OccRetriesExhausted, match=rf"lost the compare-and-swap {RETRY_BUDGET} times"): r.authorize(1, 1, 60)
    assert r.retries == RETRY_BUDGET and len(r.events()) == n and r.account(1)["holds"] == {} and Repo(r.path).authorize(1, 1, 60)["decision"] == "AUTHORIZED"


# ---------------------------------------------------------------- the interleavings, explored
TWO = ["authorize/authorize", "authorize/release", "authorize/capture", "replay/replay"]
THREE = ["authorize/authorize/release", "authorize/capture/release", "replay/replay/authorize"]


@pytest.mark.parametrize("scenario", TWO + THREE)
def test_every_interleaving_within_two_preemptions_is_linearizable_and_keeps_inv1(controller, scenario):
    """Every schedule of the operations (at most two preemptions, switching at every SQL statement) gives the outcomes, final state and
    events of some sequential order through the verified core; INV1 and P2 hold; the log replays and chains. Deterministic: a violation
    reachable within the bound is found on every run, and none exists in this profile."""
    rep = S.explore_scenario(Repo, scenario, bound=2)
    first = rep["first"] and f"first violating schedule {rep['first']['schedule']}: {rep['first']['violation']}"
    assert not rep["violations"], f"Atomicity: {len(rep['violations'])} of {rep['schedules']} schedules of {scenario} are not linearizable; {first}"
    assert rep["schedules"] > 2 and rep["complete"] and not rep["inconclusive"] and not rep["deadlocks"], \
        f"Atomicity: {scenario}: the exploration did not finish ({rep['schedules']} schedules, complete={rep['complete']}, inconclusive={rep['inconclusive']}, deadlocks={rep['deadlocks']})"


WRONG = [("blind_write", "authorize/authorize"), ("blind_write", "authorize/release"), ("unversioned_read", "authorize/authorize"),
         ("receipt_outside_cas", "replay/replay")]


@pytest.mark.parametrize("name,scenario", WRONG)
def test_the_explorer_finds_a_violation_in_each_known_wrong_store_every_time(controller, name, scenario):
    """Each store in tests/wrong/ is the profile with one defect (a blind write, a version read apart from its state, an idempotency
    check made once before the transaction). The scenario that exercises it has violating schedules, and a second exploration finds
    exactly the same ones: the first violating schedule, the number of schedules and of violations are identical."""
    runs = [S.explore_scenario(S.store(name), scenario, bound=2) for _ in range(2)]
    key = lambda rep: (rep["schedules"], len(rep["violations"]), rep["first"] and rep["first"]["schedule"])
    assert runs[0]["violations"], f"{name} on {scenario}: no violating schedule among {runs[0]['schedules']}: the explorer cannot see this defect"
    assert key(runs[0]) == key(runs[1]), f"{name} on {scenario}: two explorations differ: {key(runs[0])} vs {key(runs[1])}"
    assert runs[0]["complete"] and not runs[0]["inconclusive"]


def test_the_correct_profile_is_not_flagged_where_a_wrong_store_is(controller):
    """The same scenarios, the real store: no violation, so what the wrong stores trip on is their defect and not the check."""
    for name, scenario in WRONG:
        assert not S.explore_scenario(Repo, scenario, bound=2)["violations"], scenario
