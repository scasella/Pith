#!/usr/bin/env python3
"""validation/governance.py OUT — the M6 mechanics, scripted (docs/rfc/0005-community-release.md § 6).

  1. the catalog holds: every entry matches its pack (sealed digest, derived stage, listed files, maintainers)
  2. a stage cannot be claimed: an entry that says `released` without an independent review is refused
  3. revocation works end to end: evidence and a deployment record resting on a release revoked in a scratch
     revocations file are reported revoked; the same deployment checks clean without it
  4. the experiment harness runs end to end on scripted agents (plan, records valid against the schema, analysis that
     recomputes the primary outcome, labelled a dry run), and catches a false acceptance the external criteria see

Writes OUT/governance-record.json; exit 1 if any expectation fails."""
import json, pathlib, shutil, subprocess, sys
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent; PY = sys.executable
OUT = pathlib.Path(sys.argv[1]).resolve(); shutil.rmtree(OUT, ignore_errors=True); OUT.mkdir(parents=True)
rec = {"format": "pith.governance-record/v1", "expectations": []}; failures = []


def run(*argv): return subprocess.run([str(a) for a in argv], cwd=ROOT, capture_output=True, text=True)


def expect(what, cond, detail=""):
    rec["expectations"].append({"what": what, "ok": bool(cond), **({"detail": str(detail)[-400:]} if detail and not cond else {})})
    print(f"[{'ok' if cond else 'FAIL'}] {what}" + (f" — {str(detail)[-400:]}" if detail and not cond else ""))
    if not cond: failures.append(what)


r = run(PY, "gate/catalog.py", "check", "--json"); C = json.loads(r.stdout)
expect("the catalog matches every pack it lists", r.returncode == 0 and C["ok"], C["problems"])

cat = yaml.safe_load((ROOT / "catalog.yaml").read_text()); cat["packs"][0]["stage"] = "released"
(OUT / "catalog-claims-released.yaml").write_text(yaml.safe_dump(cat, sort_keys=False))
r = run(PY, "gate/catalog.py", "check", "--catalog", OUT / "catalog-claims-released.yaml", "--json"); C = json.loads(r.stdout)
expect("an entry claiming `released` without an independent review is refused", r.returncode == 1 and any("released" in p["problem"] for p in C["problems"]), C["problems"])

rel = OUT / "release-v2"; run(PY, "gate/release.py", "build", "--pack", "evolution/tally-v2", "--out", rel)
rid = run(PY, rel / "gate/release.py", "id").stdout.strip()
cand = OUT / "candidate"; shutil.copytree(ROOT / "evolution/tally-v2/examples/basic", cand)
r = run(PY, "-I", rel / "gate/app_gate.py", "--candidate", cand, "--out", OUT / "ev", "--expected-release", rid)
expect("the candidate is accepted under the release", r.returncode == 0, r.stdout[-300:])
run(PY, "gate/deploy.py", "record", "--evidence", OUT / "ev", "--release", rel, "--candidate", cand, "--out", OUT / "deployment.json")
revs = {"format": "pith.revocations/v1", "releases": [{"digest": rid, "date": "2026-10-13", "reason": "scratch revocation for validation", "advisory": "none", "effect": "unsound-for: [T1]"}],
        "evaluators": [], "keys": [], "reviews": []}
(OUT / "revocations.yaml").write_text(yaml.safe_dump(revs))
r = run(PY, "gate/catalog.py", "revoked", "--evidence", OUT / "ev", "--revocations", OUT / "revocations.yaml", "--json")
expect("evidence resting on a revoked release is reported revoked", r.returncode == 1 and json.loads(r.stdout)["revoked"], r.stdout)
r = run(PY, "gate/catalog.py", "revoked", "--evidence", OUT / "ev", "--json")
expect("the same evidence is not revoked under the repository's revocations", r.returncode == 0, r.stdout)
r = run(PY, "gate/deploy.py", "check", "--record", OUT / "deployment.json", "--release", rel, "--deployed", cand, "--revocations", OUT / "revocations.yaml", "--json")
expect("a deployment resting on a revoked release is not covered", r.returncode == 1 and any(d["what"] == "revoked release" for d in json.loads(r.stdout)["differences"]), r.stdout)
r = run(PY, "gate/deploy.py", "check", "--record", OUT / "deployment.json", "--release", rel, "--deployed", cand, "--json")
expect("without the revocation the deployment is covered", r.returncode == 0, r.stdout)

r = run(PY, "experiments/harness.py", "dryrun", OUT / "experiment")
A = json.loads((OUT / "experiment/analysis.json").read_text()) if (OUT / "experiment/analysis.json").exists() else {}
expect("the experiment harness runs end to end on scripted agents", r.returncode == 0 and A.get("runs") == 6 and not A.get("invalid") and not A.get("missing"), r.stdout[-600:] + r.stderr[-600:])
expect("the analysis is labelled a dry run", "DRY RUN" in (A.get("note") or ""))
expect("a false acceptance (own acceptance passed, external criteria failed) is counted", (A.get("by_condition", {}).get("core-tests", {}).get("false_acceptance") or 0) >= 1, A.get("by_condition"))
expect("a repair cycle after a refused migration is counted", (A.get("by_condition", {}).get("pith", {}).get("repair_cycles") or 0) >= 1, A.get("by_condition"))
r = run(PY, "experiments/harness.py", "plan", "--models", "model-a", "model-b", "--repeats", "2", "--out", OUT / "plan.json")
P = json.loads((OUT / "plan.json").read_text())
cells = {(x["model"], x["task"], x["condition"], x["repeat"]) for x in P["runs"]}
firsts = {x["condition"] for x in P["runs"] if x["order"] == 1}
expect("the plan crosses every model, task, condition and repeat, and rotates which condition runs first", len(cells) == len(P["runs"]) == 2 * 1 * 3 * 2 and len(firsts) >= 2, (len(P["runs"]), firsts))

rec["ok"] = not failures; rec["failures"] = failures
(OUT / "governance-record.json").write_text(json.dumps(rec, indent=1))
print(f"governance: {'all expectations hold' if not failures else f'{len(failures)} FAILED'} ({OUT / 'governance-record.json'})")
sys.exit(0 if not failures else 1)
