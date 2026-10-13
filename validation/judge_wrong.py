"""validation/judge_wrong.py — judge every known-wrong fixture of a pack with the pristine gate and check the verdict
its expected.yaml names. Exit 0 iff every fixture is refused for exactly its defects.

    python3 validation/judge_wrong.py <evidence-root> [fixture ...]                         the reservation pack (examples/wrong/)
    python3 validation/judge_wrong.py --pack packs/booking <evidence-root> [fixture ...]    another pack (<pack>/examples/wrong/)

Two kinds of expectation:
  must_fail: [obligation ids]            behavioral assurance passes, application delivery fails on EXACTLY these obligations
  refused_at: <check id>                 the run is refused at exactly that check (the first blocking failure), and
  failing_tests: [names]                 the failing tests named in its output are exactly these, plus at most
  may_also_fail: [names]                 these, where whether a concurrent test observes the defect depends on scheduling
"""
import json, pathlib, re, subprocess, sys
import yaml

SEED = pathlib.Path(__file__).resolve().parent.parent
args = sys.argv[1:]; pack = None
if args[:1] == ["--pack"]: pack = (SEED / args[1]).resolve(); args = args[2:]
WRONG = (pack / "examples/wrong") if pack else SEED / "examples/wrong"
EXPECT = yaml.safe_load((WRONG / "expected.yaml").read_text())
root = pathlib.Path(args[0]); names = args[1:] or list(EXPECT)
prefix = f"wrong-{pack.name}-" if pack else "wrong-"
bad = 0
for name in names:
    out = root / f"{prefix}{name}"; want = EXPECT[name]
    subprocess.run(["bash", str(SEED / "validation/judge_example.sh"), *(["--pack", str(pack)] if pack else []), str(WRONG / name), str(out)], capture_output=True, text=True)
    c = json.loads((out / "app-claims.json").read_text())
    if "must_fail" in want:
        wf = c.get("delivery_detail", {}).get("workflows", {})
        failed = sorted(k for k, v in wf.items() if not v["ok"])
        ok = str(c["behavioral_assurance"]).startswith("passed") and c["application_delivery"] == "failed" and failed == sorted(want["must_fail"])
        print(f"{'ok  ' if ok else 'FAIL'} {name}: assurance={str(c['behavioral_assurance'])[:6]} delivery={c['application_delivery']} failing={failed} expected={sorted(want['must_fail'])}")
        for k in failed: print(f"       {k}: {wf[k]['evidence'][0][:220]}")
    else:
        fails = [x for x in c["checks"] if x["result"] == "fail"]
        first = fails[0] if fails else {}
        tests = sorted(set(re.findall(r"FAILED \S+::(\w+)", first.get("why", ""))))
        need = set(want.get("failing_tests", tests)); extra = set(tests) - need
        ok = c["behavioral_assurance"] == "refused" and first.get("id") == want["refused_at"] and need <= set(tests) and extra <= set(want.get("may_also_fail", []))
        print(f"{'ok  ' if ok else 'FAIL'} {name}: assurance={c['behavioral_assurance']} refused at {first.get('id')} (expected {want['refused_at']}); failing tests {tests}")
        if not ok and want.get("failing_tests"): print(f"       expected tests {sorted(want['failing_tests'])}" + (f", possibly also {sorted(want['may_also_fail'])}" if want.get("may_also_fail") else ""))
    bad += not ok
sys.exit(1 if bad else 0)
