#!/usr/bin/env python3
"""validation/redteam.py OUT — the adequacy ratchet, end to end, on a deliberately under-specified pack
(validation/redteam/underspecified; docs/rfc/0007-autonomous-assurance-and-runtime-composition.md § 4).

The pack is the scaffold of `gate/cli.py pack new` with two gaps an author could leave: T1 says the tally never exceeds
its bound, but model/MC.cfg does not check Bounded, and the harness never tests the bound. Every check passes for its
reference example. The run, on a copy:

  1. the copy is sealed and fit to judge with (`pack check`), with no recorded gap
  2. `gate/redteam.py run` with two saboteur packets (a service that grants one request past the bound; a design that
     lets the tally pass it) and the generated mutants: both packets are confirmed gaps (the gate accepts them, their
     witnesses fail on them and pass on the reference), the generated flip of the bound comparison is not killed, and
     the run exits 1
  3. the pack is refused for release while the gaps are open (`pack check --release` names them)
  4. the tightening (validation/redteam/tighten: Bounded in model/MC.cfg, the bound test back in the harness, the
     adequacy check run against model/MC.cfg) is applied and the pack resealed
  5. the same packets are now killed, each where it should be (the service mutant by the bound test, the design by the
     checked invariants), and the generated flip of the bound comparison is killed too
  6. `gate/redteam.py promote` writes both into the pack's known-wrong suite; after a reseal `pack check` reports no
     open gap, `validation/judge_wrong.py` refuses the promoted application for exactly its defect, and the reference
     example's judgement now includes the adequacy check rejecting the promoted design

Writes OUT/redteam-record.json; exit 1 if any expectation fails."""
import json, pathlib, shutil, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent; PY = sys.executable
OUT = pathlib.Path(sys.argv[1]).resolve(); shutil.rmtree(OUT, ignore_errors=True); OUT.mkdir(parents=True)
SRC = ROOT / "validation/redteam"; PACK = OUT / "pack"
rec = {"format": "pith.redteam-record/v1", "expectations": []}; failures = []


def expect(what, cond, detail=""):
    rec["expectations"].append({"what": what, "ok": bool(cond), **({"detail": detail} if detail else {})})
    print(f"[{'ok' if cond else 'FAIL'}] {what}" + (f" — {detail}" if detail and not cond else ""), flush=True)
    if not cond: failures.append(what)


def run(*argv, check=False):
    r = subprocess.run([str(x) for x in argv], cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode != 0: print(r.stdout[-2000:], r.stderr[-2000:]); raise SystemExit(f"FAILED: {' '.join(map(str, argv))}")
    return r


def seal(): run(PY, "gate/release.py", "seal", "--pack", PACK, check=True)
def check(*extra): r = run(PY, "gate/cli.py", "pack", "check", PACK, "--json", *extra); return json.loads(r.stdout)
def redteam(name, *argv):
    r = run(PY, "gate/cli.py", "pack", "redteam", PACK, "--out", OUT / name, "--json", *argv)
    return r.returncode, json.loads(r.stdout)
def verdicts(R): return {m["id"]: m for m in R["mutants"]}


packets = [SRC / "packets/over-grant-by-one.yaml", SRC / "packets/over-bound-design.yaml"]
pk_args = sum((["--packet", str(p)] for p in packets), [])

# 1. the under-specified pack, as its author left it
shutil.copytree(SRC / "underspecified", PACK, ignore=shutil.ignore_patterns("__pycache__", "redteam"))
seal(); C = check()
expect("the under-specified pack is fit to judge with and records no gap", C["ok"] and not any("adequacy gap" in w for w in C["warnings"]), C["errors"])

# 2. red-team it
code, R = redteam("run-before", "--generate", "--max", "40", *pk_args); V = verdicts(R)
rec["before"] = {m["id"]: m["verdict"] for m in R["mutants"]}
expect("the service that grants one request past the bound is a confirmed gap", V.get("over-grant-by-one", {}).get("verdict") == "survivor", V.get("over-grant-by-one"))
expect("the design that lets the tally pass its bound is a confirmed gap", V.get("over-bound-design", {}).get("verdict") == "survivor", V.get("over-bound-design"))
flips = [m for m in R["mutants"] if m["source"] == "generated" and "'<' -> '<='" in m.get("description", "")]   # n < BOUND -> n <= BOUND
expect("the generated flip of the bound comparison is accepted by the under-specified gate (unkilled)",
       any(m["verdict"] == "unkilled" for m in flips), [(m["id"], m["verdict"]) for m in flips])
expect("the run reports the gaps and exits 1", code == 1 and sorted(R["survivors"]) == ["over-bound-design", "over-grant-by-one"], (code, R["survivors"]))
rec["mutation_score_before"] = f"{len(R['killed'])} killed of {sum(1 for m in R['mutants'] if m['source'] == 'generated')} generated"

# 3. refused for release while the gaps are open
C = check("--release")
expect("pack check --release refuses the pack while the gaps are open, and names them",
       not C["ok"] and any("open adequacy gap" in e and "over-grant-by-one" in e and "over-bound-design" in e for e in C["errors"]), C["errors"])

# 4. the maintainers tighten it
shutil.copytree(SRC / "tighten", PACK, dirs_exist_ok=True); seal()

# 5. the same packets, and the generated mutants, against the tightened pack
code, R = redteam("run-after", "--generate", "--max", "40", *pk_args); V = verdicts(R)
rec["after"] = {m["id"]: m["verdict"] for m in R["mutants"]}
g = V.get("over-grant-by-one", {})
expect("the service mutant is now refused by the bound test", g.get("verdict") == "killed" and g.get("refused_at") == "service.lifecycle"
       and "test_the_bound_holds_and_refusals_change_nothing" in g.get("failing_tests", []), g)
d = V.get("over-bound-design", {})
expect("the design is now rejected by the checked invariants", d.get("verdict") == "killed" and d.get("refused_at") == "spec.accepts", d)
flip_ids = {m["id"] for m in flips if m["verdict"] == "unkilled"}
expect("the generated flip of the bound comparison is killed now", flip_ids and all(V.get(i, {}).get("verdict") == "killed" for i in flip_ids),
       {i: V.get(i, {}).get("verdict") for i in flip_ids})
L = R.get("gaps") or {}
expect("the gap record has no open gap and both are waiting to be promoted", L.get("open") == [] and L.get("killed") == ["over-bound-design", "over-grant-by-one"], L)
rec["mutation_score_after"] = f"{len(R['killed'])} killed of {sum(1 for m in R['mutants'] if m['source'] == 'generated')} generated"

# 6. the ratchet: promoted into the known-wrong suite, refused for exactly their defects from now on
r = run(PY, "gate/cli.py", "pack", "redteam", PACK, "--promote", "--json"); P = json.loads(r.stdout)
expect("both gaps are promoted", r.returncode == 0 and sorted(x["id"] for x in P["promoted"]) == ["over-bound-design", "over-grant-by-one"], P)
seal(); C = check()
expect("after promotion the pack records no open gap", C["ok"] and not any("adequacy gap" in w for w in C["warnings"] + C["errors"]), C)
r = run(PY, "validation/judge_wrong.py", "--pack", PACK, OUT / "judge-wrong")
expect("judge_wrong refuses the promoted application (and the pack's own known-wrong) for exactly their defects", r.returncode == 0, r.stdout[-1200:])
rec["judge_wrong"] = r.stdout.strip().splitlines()
r = run("bash", "validation/judge_example.sh", "--pack", PACK, PACK / "examples/basic", OUT / "ev-basic")
E = json.loads((OUT / "ev-basic/evidence.json").read_text()) if (OUT / "ev-basic/evidence.json").exists() else {"records": []}
adq = {x["id"]: x["result"] for x in E["records"] if x["id"].startswith("model.adequacy")}
expect("the reference example is accepted, and the adequacy check now rejects the promoted design against model/MC.cfg",
       r.returncode == 0 and any("OverBound" in i and v == "pass" for i, v in adq.items()), (r.returncode, adq))

rec["ok"] = not failures; rec["failures"] = failures
(OUT / "redteam-record.json").write_text(json.dumps(rec, indent=1))
print(f"redteam: {'every expectation holds' if not failures else f'{len(failures)} FAILED'} ({OUT / 'redteam-record.json'})")
sys.exit(0 if not failures else 1)
