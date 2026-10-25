#!/usr/bin/env python3
"""validation/compositions.py [OUT] — every composition contract, and the reservation kernels' restatement checked
against the pack's own statement of them (docs/rfc/0006-upgrading-the-main-packs.md § 2).

  1. `gate/compose.py check` on every directory under compositions/: the integration keeps every local invariant,
     permitted effect and joint invariant; every known-wrong integration keeps the local rules and breaks exactly
     the joint invariants it is listed for
  2. compositions/reservation-kernels is a restatement, not a new model: TLC shows that its integration and the frozen
     obligations/design/CoreActions.tla core actions have the same behaviours on the account state (each refines the
     other, with the posting kernel's `captured` read off the requests that are Post)
  3. the correspondence check can fail: the known-wrong integration that ignores what was posted does not refine
     CoreActions
  4. compositions/booking-quota is a RUNTIME composition (docs/rfc/0007 § 3): `gate/compose.py verify --known-wrong` runs three
     processes behind fault proxies (a coordinator killed between the steps of a reservation, lost answers, a severed
     compensating cancel) and every runtime known-wrong candidate must fail exactly its shared invariant; `compose stagger`
     upgrades the booking component from v1 to v2 under a saga in flight; `judge_wrong.py --composition` refuses
     split-saga-leak, orphan-receipt-on-abort, touches-quota-store and drops-compensated for exactly their defects

Writes OUT/compositions-record.json when OUT is given; exit 1 if any expectation fails."""
import json, os, pathlib, re, shutil, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent; PY = sys.executable
OUT = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
K = ROOT / "compositions/reservation-kernels"
rec = {"format": "pith.compositions-record/v1", "checks": []}; failures = []


def expect(what, cond, detail=""):
    rec["checks"].append({"what": what, "ok": bool(cond), **({"detail": detail} if detail else {})})
    print(f"[{'ok' if cond else 'FAIL'}] {what}" + (f" — {detail}" if detail and not cond else ""))
    if not cond: failures.append(what)


def tlc(module, integration=None):
    """Run one correspondence module with TLC; returns (holds, output)."""
    work = pathlib.Path(tempfile.mkdtemp(prefix="correspondence-"))
    try:
        for f in [*(K / "model").glob("*.tla"), *(K / "correspondence").glob("*"), ROOT / "obligations/design/CoreActions.tla"]: shutil.copy(f, work)
        if integration: shutil.copy(integration, work / "Integration.tla")
        jar = os.environ.get("TLA2TOOLS", str(ROOT / ".tools/tla2tools.jar"))
        r = subprocess.run(["java", "-XX:+UseParallelGC", "-cp", jar, "tlc2.TLC", "-nowarning", "-workers", "2", "-deadlock", "-config", f"{module}.cfg", module],
                           cwd=work, capture_output=True, text=True, timeout=900)
        o = r.stdout + r.stderr
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if not re.search(r"TLC2 Version|Starting\.\.\.", o): raise SystemExit("TLC did not run (java or TLA2TOOLS unavailable):\n" + o[-600:])
    return "No error has been found" in o, o


for d in sorted(p for p in (ROOT / "compositions").iterdir() if (p / "composition.yaml").is_file()):
    r = subprocess.run([PY, "gate/compose.py", "check", str(d.relative_to(ROOT)), "--json"], cwd=ROOT, capture_output=True, text=True)
    C = json.loads(r.stdout)
    expect(f"{d.name}: the integration and every known-wrong integration behave as the contract says", r.returncode == 0 and C["ok"],
           [x["run"] for x in C.get("runs", []) if x["result"] != "pass"] or C.get("problems"))
    rec["checks"][-1]["runs"] = [(x["run"], x["result"], x["detail"]) for x in C.get("runs", [])]

ok, o = tlc("IntegrationRefinesCore")
expect("reservation-kernels: every behaviour of the integration is a behaviour of CoreActions' core actions", ok, o[-400:])
ok, o = tlc("CoreRefinesIntegration")
expect("reservation-kernels: every behaviour of CoreActions' core actions is a behaviour of the integration", ok, o[-400:])
ok, o = tlc("IntegrationRefinesCore", K / "wrong/ignores-posting/Integration.tla")
expect("the correspondence check can fail: wrong/ignores-posting does not refine CoreActions", not ok and "is violated" in o, o[-400:])

# runtime composition (v0.13.0, docs/rfc/0007-autonomous-assurance-and-runtime-composition.md § 3): compositions/booking-quota is three processes
# (booking, quota, coordinator) behind judge-owned fault proxies; the shared invariants are read from the components' own state after faults that
# land between the steps of a reservation
BQ = ROOT / "compositions/booking-quota"
sandbox = OUT or pathlib.Path(tempfile.mkdtemp(prefix="booking-quota-"))
sandbox.mkdir(parents=True, exist_ok=True)


def run_json(args, out):
    r = subprocess.run([PY, "gate/compose.py", *args, "--out", str(out), "--json"], cwd=ROOT, capture_output=True, text=True)
    return r.returncode, (json.loads(r.stdout) if r.stdout.strip().startswith("{") else {})


code, V = run_json(["verify", str(BQ.relative_to(ROOT)), "--candidate", str(BQ.relative_to(ROOT) / "examples/basic"), "--known-wrong"], sandbox / "booking-quota-verify")
kw = {w["dir"].rsplit("/", 1)[1]: w for w in V.get("known_wrong", [])}
expect("booking-quota: the composed candidate keeps both shared invariants under every injected fault, and every runtime known-wrong candidate fails exactly the invariant it is listed for",
       code == 0 and V.get("ok") and {k: w["result"] for k, w in kw.items()} == {"split-saga-leak": "pass", "orphan-receipt-on-abort": "pass"},
       {"runtime": (V.get("runtime") or {}).get("failing_tests"), "known_wrong": {k: (w["failing_tests"], w["violated"]) for k, w in kw.items()}, "problems": V.get("problems")})
rec["checks"][-1]["known_wrong"] = {k: {"failing_tests": w["failing_tests"], "violated": w["violated"]} for k, w in kw.items()}

code, G = run_json(["stagger", str(BQ.relative_to(ROOT)), "--component", "booking", "--old-candidate", str(BQ.relative_to(ROOT) / "examples/basic-v1"),
                    "--candidate", str(BQ.relative_to(ROOT) / "examples/basic")], sandbox / "booking-quota-stagger")
steps = (G.get("stagger") or {}).get("steps", [])
expect("booking-quota: a staggered upgrade of the booking component (v1 to v2) leaves quota's and the coordinator's state untouched and the composition consistent on the migrated state",
       code == 0 and G.get("ok") and steps and all(s["result"] == "pass" for s in steps), [s["step"] for s in steps if s["result"] != "pass"] or G.get("problems"))
rec["checks"][-1]["steps"] = [(s["step"], s["result"]) for s in steps]

r = subprocess.run([PY, "validation/judge_wrong.py", "--composition", str(BQ.relative_to(ROOT)), str(sandbox / "judge-wrong")], cwd=ROOT, capture_output=True, text=True)
expect("booking-quota: validation/judge_wrong.py refuses every known-wrong runtime candidate and staggered migration for exactly its defect (split-saga-leak, orphan-receipt-on-abort, touches-quota-store, drops-compensated)",
       r.returncode == 0 and sum(ln.startswith("ok  ") for ln in r.stdout.splitlines()) == 4, r.stdout[-800:] + r.stderr[-300:])
rec["checks"][-1]["judged"] = [ln for ln in r.stdout.splitlines() if ln.startswith(("ok", "FAIL"))]

rec["ok"] = not failures; rec["failures"] = failures
if OUT: OUT.mkdir(parents=True, exist_ok=True); (OUT / "compositions-record.json").write_text(json.dumps(rec, indent=1))
print(f"compositions: {'all hold' if not failures else f'{len(failures)} FAILED'}")
sys.exit(0 if not failures else 1)
