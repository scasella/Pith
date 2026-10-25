#!/usr/bin/env python3
"""validation/interleavings.py [OUT] — deterministic interleavings (docs/rfc/0007-autonomous-assurance-and-runtime-composition.md § 6).

A concurrency defect found by timing is found sometimes. The interleaving explorer (gate/interleave.py) runs every schedule of the
concurrent operations within a preemption bound, one thread at a time, so a defect reachable within the bound is found on EVERY run
and the schedule that shows it is the same one. This runner holds the claim to account: every known-wrong case is run FIVE times,
each in a fresh process, and must give

  - the identical failing set (the pack's deterministic test, and nothing else: the tests selected are the deterministic ones)
  - the identical number of schedules, of violating schedules, and the identical FIRST violating schedule

and each correct counterpart must pass five times with zero violating schedules and the identical number of schedules:

  booking      examples/wrong/check-then-insert  against examples/custom-py, calendar-py         (a service, drives packs/booking's test)
  quota        examples/wrong/unlocked           against examples/sliding-log-py                 (a library, drives packs/quota's test)
  reservation  examples/wrong/split-decision     against examples/build-a, build-b, build-occ    (a service, drives obligations/service/lifecycle.py)
  OCC profile  profiles/sqlite_occ/tests/wrong/{blind_write, unversioned_read, receipt_outside_cas} against the real profile on every
               scenario of two and of three concurrent operations (bound 2; linearizable against the verified core)

and, as a CONTROL, examples/wrong/retry-not-released: a receipt defect after a lost response, not a race. The whole reservation lifecycle
harness is run five times on it and fails the identical test every time, and the deterministic test passes: the new test does not
mistake a receipt defect for a race, and the receipt test was deterministic already.

For contrast (recorded, not asserted: a timing test's outcome is up to the machine) the timing-based burst test of each service or
library fixture is run five times too.

Writes OUT/interleavings-record.json when OUT is given; exit 1 if any expectation fails."""
import concurrent.futures, json, os, pathlib, re, shutil, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent; PY = sys.executable; RUNS = 5
OUT = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
WORK = pathlib.Path(tempfile.mkdtemp(prefix="interleavings-"))
rec = {"format": "pith.interleavings-record/v1", "runs_each": RUNS, "checks": [], "cases": {}}; failures = []
PYTEST = [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--noconftest", "-c", "/dev/null", "--rootdir=.", "-rA"]


def expect(what, cond, detail=""):
    rec["checks"].append({"what": what, "ok": bool(cond), **({"detail": detail} if detail else {})})
    print(f"[{'ok' if cond else 'FAIL'}] {what}" + (f" — {detail}" if detail and not cond else ""), flush=True)
    if not cond: failures.append(what)


def run(args, cwd, timeout=900):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def workspace(release, example, name):
    """The pristine release with the candidate's files laid over it, as validation/judge_example.sh assembles it."""
    ws = WORK / name
    if ws.exists(): shutil.rmtree(ws)
    if isinstance(release, pathlib.Path): shutil.copytree(release, ws)
    else:                                                               # the reservation pack: the repository root's release dirs
        ws.mkdir()
        for d in run([PY, "gate/release.py", "dirs"], ROOT).stdout.split(): shutil.copytree(ROOT / d, ws / d, ignore=shutil.ignore_patterns("__pycache__"))
        for f in ("pack.yaml", "release.seal.json"): shutil.copy(ROOT / f, ws / f)
    shutil.copytree(example, ws, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "claims-from-release.json", "*.example"))
    return ws


def pytest_run(ws, target, select=None):
    """One run of a harness file (optionally only the tests whose names match `select`) in a workspace: what failed, passed, was
    skipped, and what the interleaving tests printed (`pith-interleave {...}` lines)."""
    r = run([*PYTEST, target, *(["-k", select] if select else [])], ws)
    out = r.stdout + r.stderr
    return {"failed": sorted(set(re.findall(r"^FAILED \S+?::(\w+)", out, re.M))), "passed": sorted(set(re.findall(r"^PASSED \S+?::(\w+)", out, re.M))),
            "skipped": len(re.findall(r"^SKIPPED", out, re.M)),
            "interleave": [json.loads(l.split(" ", 1)[1]) for l in out.splitlines() if l.startswith("pith-interleave ")], "exit": r.returncode, "tail": out[-600:]}


def shape(x):
    """What must be identical from run to run: the failing set and every exploration's size, violation count and first violating schedule."""
    return {"failed": x["failed"], "passed": x["passed"], "interleave": x["interleave"]}


def explore_n(name, ws, target, test, select=None):
    runs = [pytest_run(ws, target, select or test) for _ in range(RUNS)]
    rec["cases"][name] = {"runs": [shape(x) for x in runs]}
    return runs


def wrong_case(label, ws, target, test):
    runs = explore_n(label, ws, target, test)
    same = all(shape(x) == shape(runs[0]) for x in runs)
    il = runs[0]["interleave"]; first = next((x["first"] for x in il if x.get("first")), None)
    expect(f"{label}: the deterministic test fails on all {RUNS} runs, and it is the only test that fails", all(x["failed"] == [test] for x in runs), [x["failed"] for x in runs])
    expect(f"{label}: all {RUNS} runs give the identical exploration: {il[0]['schedules'] if il else '?'} schedules, {il[0]['violations'] if il else '?'} violating, "
           f"the same first violating schedule", same and il and il[0]["violations"] > 0 and first, [x["interleave"] for x in runs])
    rec["cases"][label]["first_violating_schedule"] = first
    return runs


def right_case(label, ws, target, test):
    runs = explore_n(label, ws, target, test)
    il = runs[0]["interleave"]
    expect(f"{label}: the deterministic test passes on all {RUNS} runs with zero violating schedules out of {il[0]['schedules'] if il else '?'}",
           all(x["failed"] == [] and x["passed"] == [test] and x["interleave"] and all(i["violations"] == 0 and i["schedules"] > 0 for i in x["interleave"]) for x in runs), [x["tail"] for x in runs][:1])
    expect(f"{label}: all {RUNS} runs explore the identical schedules", all(shape(x) == shape(runs[0]) for x in runs))


def contrast(label, ws, target, test):
    runs = [pytest_run(ws, target, test) for _ in range(RUNS)]
    rec["cases"][label + " (timing-based)"] = {"test": test, "failed_in_runs": sum(1 for x in runs if test in x["failed"]), "of": RUNS}
    print(f"[..] {label}: the timing-based {test} failed in {rec['cases'][label + ' (timing-based)']['failed_in_runs']} of {RUNS} runs", flush=True)


# ---- booking ---------------------------------------------------------------------------------------------------------------------------
BK = ROOT / "packs/booking"; B_TEST = "test_interleaved_bookings_of_one_interval_accept_exactly_one"
run([PY, "gate/release.py", "build", "--pack", str(BK), "--out", str(WORK / "booking-release")], ROOT)
wrong_case("booking check-then-insert", workspace(WORK / "booking-release", BK / "examples/wrong/check-then-insert", "bk-cti"), "harness/lifecycle.py", B_TEST)
contrast("booking check-then-insert", WORK / "bk-cti", "harness/lifecycle.py", "test_concurrent_requests_for_one_interval_accept_exactly_one_per_resource")
for ex in ("custom-py", "calendar-py"): right_case(f"booking {ex}", workspace(WORK / "booking-release", BK / "examples" / ex, f"bk-{ex}"), "harness/lifecycle.py", B_TEST)

# ---- quota -----------------------------------------------------------------------------------------------------------------------------
QU = ROOT / "packs/quota"; Q_TEST = "test_interleaved_acquires_of_the_last_unit_grant_exactly_once"
run([PY, "gate/release.py", "build", "--pack", str(QU), "--out", str(WORK / "quota-release")], ROOT)
wrong_case("quota unlocked", workspace(WORK / "quota-release", QU / "examples/wrong/unlocked", "qu-unlocked"), "harness/lifecycle.py", Q_TEST)
contrast("quota unlocked", WORK / "qu-unlocked", "harness/lifecycle.py", "test_one_limiter_shared_by_threads_grants_exactly_the_limit")
right_case("quota sliding-log-py", workspace(WORK / "quota-release", QU / "examples/sliding-log-py", "qu-sliding"), "harness/lifecycle.py", Q_TEST)
node = pytest_run(workspace(WORK / "quota-release", QU / "examples/tally-node", "qu-tally"), "harness/lifecycle.py", Q_TEST)
expect("quota tally-node (Node.js): the deterministic test is skipped, with its reason, not passed", node["skipped"] == 1 and node["failed"] == [] and node["passed"] == [], node["tail"])

# ---- reservation -----------------------------------------------------------------------------------------------------------------------
R_TEST = "test_interleaved_authorizations_with_room_for_one_decide_exactly_one"; R_FILE = "obligations/service/lifecycle.py"
EX = ROOT / "examples"
wrong_case("reservation split-decision", workspace(None, EX / "wrong/split-decision", "res-split"), R_FILE, R_TEST)
contrast("reservation split-decision", WORK / "res-split", R_FILE, "test_concurrent_bursts_and_readers")
for ex in ("build-a", "build-b", "build-occ"): right_case(f"reservation {ex}", workspace(None, EX / ex, f"res-{ex}"), R_FILE, R_TEST)

# CONTROL: a receipt defect is not a race. The WHOLE lifecycle harness, five times: the same single test fails every time; the new one passes.
ctl = workspace(None, EX / "wrong/retry-not-released", "res-control")
runs = [pytest_run(ctl, R_FILE) for _ in range(RUNS)]
rec["cases"]["control retry-not-released"] = {"runs": [shape(x) for x in runs]}
expect(f"control retry-not-released: the whole lifecycle harness fails the identical test on all {RUNS} runs, and not the deterministic interleaving test",
       all(x["failed"] == ["test_receipts_are_returned_on_retry_across_a_crash"] and R_TEST in x["passed"] for x in runs), [x["failed"] for x in runs])
expect("control retry-not-released: the deterministic interleaving test explores the identical schedules on every run, with zero violating",
       all(x["interleave"] == runs[0]["interleave"] and x["interleave"] and x["interleave"][0]["violations"] == 0 for x in runs), [x["interleave"] for x in runs])

# ---- the OCC profile -------------------------------------------------------------------------------------------------------------------
sys.path.insert(0, str(ROOT / "profiles/sqlite_occ/tests"))
import scenarios as SC
TWO = [n for n in SC.SCENARIOS if n.count("/") == 1]; THREE = [n for n in SC.SCENARIOS if n.count("/") == 2]
FOUND_BY = {"blind_write": ["authorize/authorize", "authorize/release", "authorize/capture"], "unversioned_read": ["authorize/authorize", "authorize/release", "authorize/capture"],
            "receipt_outside_cas": ["replay/replay"]}


def scenario_run(store, scenario):
    r = run([PY, "-I", "profiles/sqlite_occ/tests/scenarios.py", store, scenario], ROOT)
    lines = [l for l in r.stdout.splitlines() if l.startswith("{")]
    return json.loads(lines[0]) if lines else {"error": (r.stdout + r.stderr)[-400:]}


jobs = [(s, sc) for s, scs in FOUND_BY.items() for sc in scs] + [("real", sc) for sc in TWO + THREE]
with concurrent.futures.ThreadPoolExecutor(4) as ex:             # independent processes, one interpreter each; the schedule set does not depend on load
    futs = {(s, sc): [ex.submit(scenario_run, s, sc) for _ in range(RUNS)] for s, sc in jobs}
    results = {k: [f.result() for f in v] for k, v in futs.items()}
for (store, scenario), rs in results.items():
    key = lambda r: (r.get("schedules"), r.get("violations"), json.dumps(r.get("first"), sort_keys=True), r.get("complete"), r.get("inconclusive"), r.get("deadlocks"))
    same = all(key(r) == key(rs[0]) for r in rs); r0 = rs[0]
    rec["cases"][f"occ {store} {scenario}"] = {"runs": rs}
    if store == "real":
        expect(f"sqlite-occ {scenario}: all {RUNS} runs explore the identical {r0.get('schedules')} schedules (bound {r0.get('bound')}), none violating, complete",
               same and r0.get("violations") == 0 and r0.get("complete") is True and not r0.get("inconclusive") and not r0.get("deadlocks") and (r0.get("schedules") or 0) > 2, rs[:1])
    else:
        expect(f"{store} on {scenario}: all {RUNS} runs find the identical {r0.get('violations')} violating schedules of {r0.get('schedules')}, the same first one "
               f"{(r0.get('first') or {}).get('schedule')}", same and (r0.get("violations") or 0) > 0 and r0.get("complete") is True, rs[:1])

rec["ok"] = not failures
if OUT: OUT.mkdir(parents=True, exist_ok=True); (OUT / "interleavings-record.json").write_text(json.dumps(rec, indent=1, sort_keys=True))
shutil.rmtree(WORK, ignore_errors=True)
print(f"\n{len(rec['checks']) - len(failures)} of {len(rec['checks'])} expectations hold" + (f"; FAILED: {failures}" if failures else ""))
sys.exit(1 if failures else 0)
