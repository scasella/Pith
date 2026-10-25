"""
profiles/sqlite_occ/tests/scenarios.py — concurrent operations on one account, explored schedule by schedule. FROZEN.

Shared by test_occ.py (which asserts the real Repo has no violating schedule and each known-wrong store has one) and
validation/interleavings.py (which runs a scenario in a fresh interpreter, five times, and asserts the identical result).

A scenario is a limit, the operations already done, and the operations to run concurrently on account 1. `explore_scenario` runs EVERY
interleaving of them (gate/interleave.py: threads run one at a time and switch at each SQL statement the store issues, each lock and
sleep; at most `bound` preemptions) over a real SQLite file, and holds each schedule to LINEARIZABILITY against the verified core: the
outcomes of the operations, the account's final state and the events appended must be exactly those of SOME sequential order of the same
operations run through the core alone (obligations/boundary/oracle.py), and INV1 and P2 must hold, the event log must replay to the stored
state and its hash chain and operation ids must be intact. A schedule is a violation if any of that fails or an operation raises.

    python3 -I profiles/sqlite_occ/tests/scenarios.py STORE SCENARIO [BOUND]      prints one JSON line (STORE: real | blind_write | ...)
"""
import hashlib, importlib, itertools, json, os, pathlib, shutil, sys, tempfile
ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from gate import interleave as IL
from obligations.boundary import oracle as O

ACCT = 1
SCENARIOS = {                                           # name -> limit, operations done first, operations run concurrently: (op, request[, amount])
    "authorize/authorize": dict(limit=100, setup=[], ops=[("authorize", 1, 60), ("authorize", 2, 60)]),                       # room for one
    "authorize/release": dict(limit=100, setup=[("authorize", 1, 60)], ops=[("authorize", 2, 60), ("release", 1)]),          # the decision depends on the order
    "authorize/capture": dict(limit=100, setup=[("authorize", 1, 60)], ops=[("authorize", 2, 60), ("capture", 1)]),
    "replay/replay": dict(limit=100, setup=[], ops=[("authorize", 1, 60), ("authorize", 1, 60)]),                             # one request twice at once
    "authorize/authorize/release": dict(limit=100, setup=[("authorize", 1, 60)], ops=[("authorize", 2, 60), ("authorize", 3, 40), ("release", 1)]),
    "authorize/capture/release": dict(limit=100, setup=[("authorize", 1, 60), ("authorize", 2, 40)], ops=[("authorize", 3, 10), ("capture", 1), ("release", 2)]),
    "replay/replay/authorize": dict(limit=100, setup=[], ops=[("authorize", 1, 60), ("authorize", 1, 60), ("authorize", 2, 60)]),
}
STORES = ("blind_write", "receipt_outside_cas", "unversioned_read")


def store(name):
    """The Repo class of the real profile ("real") or of one known-wrong store (tests/wrong/NAME.py)."""
    return importlib.import_module("profiles.sqlite_occ.repo" if name == "real" else f"profiles.sqlite_occ.tests.wrong.{name}").Repo


def call(repo, op): return getattr(repo, op[0])(ACCT, op[1], *op[2:])
def step(op): return {"action": op[0], "args": {"account": ACCT, "request": op[1], **({"amount": op[2]} if len(op) > 2 else {})}}
def view(a): return {"id": ACCT, "limit": int(a.limit), "posted": int(a.posted), "available": O.C.available(a), "holds": O.C.holds(a), "status": O.C.status(a)}


def expected_events(op, r, o):
    """What a sequential run appends for one operation, in the form sig() gives a stored event."""
    a = o.accounts[ACCT]; after = ("op.committed", op[1], (int(a.limit), int(a.posted), sum(O.C.holds(a).values())))
    if op[0] == "authorize" and r.get("replayed") is False:
        return [("auth.decided", op[1], r["decision"], r["available_at_decision"])] + ([("reservation.created", op[1])] if r["decision"] == "AUTHORIZED" else []) + [after]
    if op[0] == "release" and r.get("released") and r["replayed"] is False: return [("reservation.released", op[1]), after]
    if op[0] == "capture" and r.get("captured") and r["replayed"] is False: return [("capture.posted", op[1], r["amount"]), after]
    return []


def sig(e):
    t = e["type"]
    if t == "auth.decided": return (t, e["request_id"], e["decision"], e["available_at_decision"])
    if t == "capture.posted": return (t, e["request_id"], e["amount"])
    if t == "op.committed": s = e["state_after"]; return (t, e["request_id"], (s["limit"], s["posted"], s["reserved"]))
    return (t, e.get("request_id"))


def reference(sc):
    """Every sequential order of the scenario's operations, through the verified core: outcomes by operation, final account, events appended."""
    out = []
    for order in itertools.permutations(range(len(sc["ops"]))):
        o = O.Oracle(); o.step({"action": "create_account", "args": {"account": ACCT, "limit": sc["limit"]}})
        for op in sc["setup"]: o.step(step(op))
        res, log = [None] * len(sc["ops"]), []
        for i in order:
            res[i] = o.step(step(sc["ops"][i])); log += expected_events(sc["ops"][i], res[i], o)
        out.append({"order": order, "outcomes": res, "final": view(o.accounts[ACCT]), "log": log})
    return out


def canonical(o): return json.dumps(o, sort_keys=True, separators=(",", ":"))


def invariants(final):
    """INV1 and P2 on the stored account."""
    if final["posted"] + sum(final["holds"].values()) > final["limit"]: return f"INV1 broken: posted {final['posted']} + holds {final['holds']} > limit {final['limit']}"
    if set(final["holds"]) != {k for k, s in final["status"].items() if s == "AUTH"}: return f"P2 broken: holds {final['holds']} vs status {final['status']}"


def log_integrity(repo, evs):
    """The event log replays to the stored state, its hash chain verifies and every operation id ends in exactly one op.committed."""
    d = repo.verify_replay()
    if d: return f"the event log does not replay to the stored state: {d}"
    prev, ops = "0" * 64, {}
    for e in evs:
        body = {k: v for k, v in e.items() if k not in ("hash", "seq")}
        if e["prev_hash"] != prev or e["hash"] != hashlib.sha256(canonical(body).encode()).hexdigest(): return f"the hash chain breaks at event {e['seq']}"
        prev = e["hash"]; ops.setdefault(e["op_id"], []).append(e["type"])
    bad = [k for k, v in ops.items() if v[-1] != "op.committed" or v.count("op.committed") != 1]
    if bad: return f"operation(s) {bad} do not end in exactly one op.committed"


def explore_scenario(repo_cls, name, bound=2, max_schedules=20000):
    """The report of gate/interleave.py explore for one scenario on one store: {"schedules", "violations", "first", ...}."""
    IL.install(dbapi=["sqlite3"])                       # before any connection of the code under test is opened
    sc = SCENARIOS[name]; ref = reference(sc)
    with tempfile.TemporaryDirectory(prefix="occ-scenario-") as d:
        d = pathlib.Path(d); template = d / "template.db"; r = repo_cls(str(template)); r.create_account(ACCT, sc["limit"])
        for op in sc["setup"]: call(r, op)
        n_setup, k = len(r.events()), itertools.count()
        def setup():
            p = d / f"s{next(k)}.db"; shutil.copyfile(template, p); return repo_cls(str(p)), p
        def check(state, results):
            repo, p = state
            try:
                if any(x[0] != "ok" for x in results): return f"an operation raised {next(x[1] for x in results if x[0] != 'ok')}"
                got, final, evs = [x[1] for x in results], repo.account(ACCT), repo.events()
                log = [sig(e) for e in evs[n_setup:]]
                if invariants(final): return invariants(final)
                if not any(got == x["outcomes"] and final == x["final"] and log == x["log"] for x in ref):
                    return (f"not linearizable: outcomes {[g.get('decision', g.get('released', g.get('captured'))) for g in got]}, final holds {final['holds']} "
                            f"posted {final['posted']}, events {[e[:2] for e in log]} match no sequential order of the operations (orders {[x['order'] for x in ref]})")
                return log_integrity(repo, evs)
            finally:
                for f in d.glob(p.name + "*"): f.unlink()
        return IL.explore(setup, [lambda st, op=op: call(st[0], op) for op in sc["ops"]], check, bound=bound, max_schedules=max_schedules)


if __name__ == "__main__":
    which, name = sys.argv[1], sys.argv[2]; rep = explore_scenario(store(which), name, int(sys.argv[3]) if len(sys.argv) > 3 else 2)
    first = rep["first"] and {"schedule": rep["first"]["schedule"], "violation": rep["first"]["violation"]}
    print(json.dumps({"store": which, "scenario": name, "bound": rep["bound"], "schedules": rep["schedules"], "violations": len(rep["violations"]), "complete": rep["complete"],
                      "inconclusive": len(rep["inconclusive"]), "deadlocks": len(rep["deadlocks"]), "first": first}, sort_keys=True))
