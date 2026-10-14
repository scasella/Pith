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

rec["ok"] = not failures; rec["failures"] = failures
if OUT: OUT.mkdir(parents=True, exist_ok=True); (OUT / "compositions-record.json").write_text(json.dumps(rec, indent=1))
print(f"compositions: {'all hold' if not failures else f'{len(failures)} FAILED'}")
sys.exit(0 if not failures else 1)
