"""validation/compare_m1.py — the M2 exit check: the reservation seed judged through the pack and the domain-free
evaluator reaches the same scoped results as the v0.6.0 (M1) judge did.

    python3 validation/compare_m1.py record <evidence-root> > validation/baselines/m1.json     (run once, with the v0.6.0 judge)
    python3 validation/compare_m1.py compare <evidence-root> [validation/baselines/m1.json]

<evidence-root> holds ev-<example> directories (validation/judge_example.sh) and wrong-<fixture> directories
(validation/judge_wrong.py). For each, the comparison covers every check (area, name, result and claim text with
digests masked), every status, the failing delivery obligations, release_ready and release_ready_missing.

Differences that are expected, and why, are listed in EXPECTED below; anything else fails.
"""
import json, pathlib, re, sys

HEX = re.compile(r"\b[0-9a-f]{16,64}\b")
EXPECTED = {
    # gate/ + pack.yaml are policy now, and the release has a different file count; the claim names them
    ("policy", "frozen files intact"): "claim text names the release's policy dirs and file count",
    # the probe now also tries the pack's profiles/ dir (pack.yaml:policy_dirs); README path moved to gate/isolation/
    ("policy", "isolation"): "claim text: probed dirs and README path",
}


def fingerprint(c):
    checks = []
    for x in c["checks"]:
        key = (x["area"], x["check"])
        claim = None if key in EXPECTED else HEX.sub("<hex>", x["claim"])
        checks.append([x["area"], x["check"], x["result"], claim])
    wf = (c.get("delivery_detail") or {}).get("workflows", {})
    return {"checks": checks,
            "statuses": {s: c.get(s) for s in ("behavioral_assurance", "application_delivery", "human_approval")},
            "failing_delivery": sorted(k for k, v in wf.items() if not v["ok"]),
            "release_ready": c.get("release_ready"), "release_ready_missing": c.get("release_ready_missing")}


def collect(root):
    out = {}
    for d in sorted(pathlib.Path(root).iterdir()):
        f = d / ("run/app-claims.json" if (d / "run").exists() else "app-claims.json")
        if d.is_dir() and (d.name.startswith("ev-") or d.name.startswith("wrong-")) and f.exists():
            out[d.name] = fingerprint(json.loads(f.read_text()))
    return out


def main():
    mode, root = sys.argv[1], sys.argv[2]
    if mode == "record":
        print(json.dumps(collect(root), indent=1)); return
    base = json.loads(pathlib.Path(sys.argv[3] if len(sys.argv) > 3 else pathlib.Path(__file__).parent / "baselines/m1.json").read_text())
    now = collect(root); bad = 0
    for name, want in base.items():
        got = now.get(name)
        if got is None: print(f"MISSING {name}: not judged in {root}"); bad += 1; continue
        diffs = [k for k in want if want[k] != got[k]]
        if diffs:
            bad += 1; print(f"DIFF    {name}: {diffs}")
            if "checks" in diffs:
                for i, (a, b) in enumerate(zip(want["checks"], got["checks"] + [None] * len(want["checks"]))):
                    if a != b: print(f"          m1:  {a}\n          now: {b}")
                for b in got["checks"][len(want["checks"]):]: print(f"          now (extra): {b}")
            for k in diffs:
                if k != "checks": print(f"          {k}: m1={want[k]} now={got[k]}")
        else:
            print(f"same    {name}: {len(want['checks'])} checks, statuses, delivery failures {want['failing_delivery'] or 'none'}, release_ready_missing {want['release_ready_missing']}")
    print(f"expected differences (claim text only): {sorted(' · '.join(k) for k in EXPECTED)}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
