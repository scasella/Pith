"""validation/judge_wrong.py — judge every known-wrong fixture in examples/wrong/ with the pristine gate and check the
verdict in examples/wrong/expected.yaml: behavioral assurance passes, application delivery fails, and the failing
interaction obligations are exactly the expected ones. Exit 0 iff every fixture is refused for exactly its defects.

    python3 validation/judge_wrong.py <evidence-root> [fixture ...]
"""
import json, pathlib, subprocess, sys
import yaml

SEED = pathlib.Path(__file__).resolve().parent.parent
EXPECT = yaml.safe_load((SEED / "examples/wrong/expected.yaml").read_text())
root = pathlib.Path(sys.argv[1]); names = sys.argv[2:] or list(EXPECT)
bad = 0
for name in names:
    out = root / f"wrong-{name}"
    subprocess.run(["bash", str(SEED / "validation/judge_example.sh"), str(SEED / "examples/wrong" / name), str(out)], capture_output=True, text=True)
    c = json.loads((out / "app-claims.json").read_text())
    wf = c.get("delivery_detail", {}).get("workflows", {})
    failed = sorted(k for k, v in wf.items() if not v["ok"])
    want = sorted(EXPECT[name]["must_fail"])
    ok = str(c["behavioral_assurance"]).startswith("passed") and c["application_delivery"] == "failed" and failed == want
    bad += not ok
    print(f"{'ok  ' if ok else 'FAIL'} {name}: assurance={str(c['behavioral_assurance'])[:6]} delivery={c['application_delivery']} failing={failed} expected={want}")
    for k in failed:
        print(f"       {k}: {wf[k]['evidence'][0][:220]}")
sys.exit(1 if bad else 0)
