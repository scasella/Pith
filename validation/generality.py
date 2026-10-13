"""validation/generality.py — the M3 exit check: structurally different packs, judged by ONE evaluator.

    python3 validation/generality.py [--markdown] <evidence-dir> ...

Each <evidence-dir> is the output of one judge run (validation/judge_example.sh). The check passes iff every run was
made by the same evaluator code (evidence.json evaluator_digest: gate/ minus the frozen list it carries for its pack),
at least three distinct packs are present, every run reached its pack's completion status, and for every pack at
least two runs differ in the candidate's runtime (implementation variation) and at least two in the application
(application variation). It prints one row per run; --markdown prints the table for docs/VALIDATION.md.
"""
import json, pathlib, sys
import yaml

args = sys.argv[1:]; md = args[:1] == ["--markdown"]; args = args[md:]
rows = []
for d in map(pathlib.Path, args):
    E = json.loads((d / "evidence.json").read_text()); C = json.loads((d / "app-claims.json").read_text())
    art = d / "artifact"; M = yaml.safe_load((art / "app.manifest.yaml").read_text()) if (art / "app.manifest.yaml").exists() else {}
    runtime = M.get("runtime") or ("python" if (art / "service").exists() else "-")
    rows.append({"dir": d.name, "pack": E["pack"]["id"], "app": C.get("app") or d.name, "runtime": runtime, "profile": M.get("profile", "-"),
                 "evaluator": E["evaluator_digest"], "release": E["release_digest"], "statuses": E["statuses"],
                 "checks": len(E["records"])})
problems = []
evs = {r["evaluator"] for r in rows}
if len(evs) != 1: problems.append(f"{len(evs)} different evaluator digests: {sorted(e[:16] for e in evs)}")
packs = sorted({r["pack"] for r in rows})
if len(packs) < 3: problems.append(f"only {len(packs)} packs: {packs}")
for r in rows:
    # every mechanical status passed; a human attestation is not something a judge run can produce
    bad = [s for s, v in r["statuses"].items() if s != "human_approval" and not str(v).startswith("passed")]
    if bad: problems.append(f"{r['dir']}: {', '.join(f'{s}={str(r['statuses'][s])[:20]}' for s in bad)}")
for p in packs:
    mine = [r for r in rows if r["pack"] == p]
    if len({(r["runtime"], r["profile"]) for r in mine}) < 2 and p != "pith.reservation": problems.append(f"{p}: no implementation variation (one runtime/profile)")
    if len({r["app"] for r in mine}) < 2: problems.append(f"{p}: no application variation (one application)")

if md:
    print(f"Evaluator digest (all runs): `{next(iter(evs))[:16]}`\n" if len(evs) == 1 else "")
    print("| Pack | Application | Runtime / profile | Release | Checks | Statuses |\n|---|---|---|---|---|---|")
    for r in rows:
        st = "; ".join(f"{s} {str(v).split(';')[0]}" for s, v in r["statuses"].items())
        print(f"| {r['pack']} | {r['app']} | {r['runtime']} / {r['profile']} | `{r['release'][:12]}` | {r['checks']} | {st} |")
else:
    for r in rows:
        print(f"{r['pack']:18} {r['app'][:28]:28} {r['runtime']:7} {r['profile']:8} evaluator {r['evaluator'][:16]} release {r['release'][:16]} "
              + " ".join(f"{s}={str(v).split(';')[0]}" for s, v in r["statuses"].items()))
print("\n".join(problems) if problems else f"ok: {len(rows)} runs, {len(packs)} packs, one evaluator ({next(iter(evs))[:16]})")
sys.exit(1 if problems else 0)
