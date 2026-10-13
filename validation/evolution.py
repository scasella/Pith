#!/usr/bin/env python3
"""validation/evolution.py OUT — the M5 exit demonstrations, scripted (docs/rfc/0004-safe-evolution.md § 7).

  1. agent handoff        agent A's accepted run is handed to agent B with its task packet; B plans a change before
                          making it (gate/change.py plan), makes it, classifies it (classify), and is judged with A's
                          evidence offered for reuse: only records whose keys are unchanged are reused
  2. substantial rewrite  the same application rewritten on another store: classified, every service-derived record
                          invalidated, judged again; only the model checks carry over
  3. contract upgrade     tally/v1 -> tally/v2 with populated state: the change is behavioral, no v1 evidence is reused
                          under v2, the migration is judged on state the judged v1 artifact produced (basic, and the
                          rewrite), the known-wrong migrations fail for their defect, and a v1 deployment record does not
                          cover the v2 artifact
  4. composed workflow    gate/compose.py on compositions/ledger-receipts: the integration keeps the joint invariant;
                          the known-wrong one keeps each component's rules and breaks it

Writes OUT/evolution-record.json; exit 1 if any expectation fails. Uses the evolution/ packs, which are small, so it
runs in a few minutes."""
import json, pathlib, shutil, subprocess, sys
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent; PY = sys.executable
OUT = pathlib.Path(sys.argv[1]).resolve(); shutil.rmtree(OUT, ignore_errors=True); OUT.mkdir(parents=True)
V1, V2 = ROOT / "evolution/tally-v1", ROOT / "evolution/tally-v2"
rec = {"format": "pith.evolution-record/v1", "demonstrations": {}}; failures = []


def sh(*argv, ok=(0,)):
    r = subprocess.run([str(x) for x in argv], cwd=ROOT, capture_output=True, text=True)
    if r.returncode not in ok: print(r.stdout[-3000:], r.stderr[-3000:]); raise SystemExit(f"FAILED ({r.returncode}): {' '.join(map(str, argv))}")
    return r


def expect(demo, what, cond, detail=""):
    rec["demonstrations"].setdefault(demo, {"expectations": []})["expectations"].append({"what": what, "ok": bool(cond), **({"detail": detail} if detail else {})})
    print(f"[{'ok' if cond else 'FAIL'}] {demo}: {what}" + (f" — {detail}" if detail and not cond else ""))
    if not cond: failures.append(f"{demo}: {what}")


def judge(rel, cand, out, reuse=None):
    r = subprocess.run([PY, "-I", rel / "gate/app_gate.py", "--candidate", cand, "--out", out, "--expected-release", release_id(rel)] + (["--reuse", reuse] if reuse else []),
                       cwd=ROOT, capture_output=True, text=True)
    c = json.loads((out / "app-claims.json").read_text()); E = json.loads((out / "evidence.json").read_text())
    return r.returncode, c, E


def release_id(rel): return sh(PY, rel / "gate/release.py", "id").stdout.strip()


def assembled(rel, example, name):
    d = OUT / "cand" / name; shutil.copytree(example, d); return d


def change(cmd, ev, cand, rel, *extra):
    return json.loads(sh(PY, "gate/change.py", cmd, "--evidence", ev, "--candidate", cand, "--policy-from", rel, "--json", *extra).stdout)


def reused(E): return sorted(r["check"] for r in E["records"] if r.get("reused_from"))


rels = {}
for v, src in (("v1", V1), ("v2", V2)):
    rels[v] = OUT / f"release-{v}"; sh(PY, "gate/release.py", "build", "--pack", src, "--out", rels[v])
rec["releases"] = {v: release_id(r) for v, r in rels.items()}

# ---- 1. agent handoff
D = "agent handoff"
a_cand = assembled(rels["v2"], V2 / "examples/basic", "agent-a")
code, ca, EA = judge(rels["v2"], a_cand, OUT / "ev-agent-a")
expect(D, "agent A's application is accepted", code == 0 and str(ca["behavioral_assurance"]).startswith("passed"))
packet = json.loads((OUT / "ev-agent-a/task-packet.json").read_text())
expect(D, "agent B starts from A's task packet: done, with the rerun and impact commands", packet["state"] == "done" and packet["rerun"].get("impact"))
plan = change("plan", OUT / "ev-agent-a", a_cand, rels["v2"], "--paths", "service/run.py")
expect(D, "B's plan, before editing service/run.py: integration route, re-run the checks that read it", plan["route"] == "integration" and "lifecycle harness (black-box)" in plan["rerun"], plan["rerun"])
b_cand = OUT / "cand/agent-b"; shutil.copytree(a_cand, b_cand)
p = b_cand / "service/run.py"; p.write_text(p.read_text().replace("def tally(counter):", "def tally(counter):                    # accepted requests of one counter, from the committed state\n    \"\"\"accepted requests of one counter\"\"\"\n   ", 1))
cls = change("classify", OUT / "ev-agent-a", b_cand, rels["v2"])
expect(D, "B's change, classified after: the same route and the same checks to re-run as planned", cls["route"] == plan["route"] and set(cls["rerun"]) <= set(plan["rerun"]), (cls["route"], cls["rerun"]))
code, cb, EB = judge(rels["v2"], b_cand, OUT / "ev-agent-b", reuse=OUT / "ev-agent-a")
expect(D, "B is judged with A's evidence offered: accepted, and only unaffected records reused", code == 0 and set(reused(EB)) <= set(cls["evidence"]["holds"]) and reused(EB), reused(EB))
expect(D, "nothing the change invalidated was reused", not set(reused(EB)) & set(cls["rerun"]))
rec["demonstrations"][D].update({"plan": plan, "classify": {k: cls[k] for k in ("route", "rerun", "ambiguous")}, "reused": reused(EB)})

# ---- 2. substantial rewrite
D = "substantial rewrite"
r_cand = assembled(rels["v2"], V2 / "examples/journal", "rewrite")
cls = change("classify", OUT / "ev-agent-a", r_cand, rels["v2"])
expect(D, "the rewrite is an integration change with every service file changed", cls["route"] == "integration" and {"service/run.py", "service/migrate.py"} <= {f["path"] for f in cls["files"]})
expect(D, "every record that ran or read the service is invalidated", {"lifecycle harness (black-box)", "service entrypoint", "migration entrypoint"} <= set(cls["rerun"]), cls["rerun"])
code, cr, ER = judge(rels["v2"], r_cand, OUT / "ev-rewrite", reuse=OUT / "ev-agent-a")
expect(D, "the rewrite is accepted on its own evidence; only the model checks carry over", code == 0 and set(reused(ER)) == {"model checked", "the model rejects a bound checked on counter default only"}, reused(ER))
rec["demonstrations"][D].update({"classify": {k: cls[k] for k in ("route", "rerun")}, "reused": reused(ER)})

# ---- 3. contract upgrade with populated state
D = "contract upgrade"
o_cand = assembled(rels["v1"], V1 / "examples/basic", "v1")
code, c1, E1 = judge(rels["v1"], o_cand, OUT / "ev-v1")
expect(D, "the v1 application is accepted under tally/v1", code == 0)
sh(PY, "gate/deploy.py", "record", "--evidence", OUT / "ev-v1", "--release", rels["v1"], "--candidate", o_cand, "--out", OUT / "deploy-v1.json")
cls = change("classify", OUT / "ev-v1", a_cand, rels["v2"])
cc = {c["id"]: c["change"] for c in cls["contract_changes"]}
expect(D, "upgrading to tally/v2 is classified behavioral, naming the changed records", cls["route"] == "behavioral" and cc.get("T1") == "version 1 -> 2" and cc.get("M1") == "added", cc)
expect(D, "no v1 evidence holds for the v2 contract", not cls["evidence"]["holds"], cls["evidence"]["holds"])
code, c2, E2 = judge(rels["v2"], a_cand, OUT / "ev-v2-reuse-v1", reuse=OUT / "ev-v1")
expect(D, "judged under v2 with v1's evidence offered, nothing is reused", code == 0 and not reused(E2), reused(E2))
r = subprocess.run([PY, "gate/deploy.py", "check", "--record", OUT / "deploy-v1.json", "--release", rels["v2"], "--deployed", a_cand, "--json"], cwd=ROOT, capture_output=True, text=True)
expect(D, "the v1 deployment record does not cover the v2 artifact", r.returncode == 1 and {d["what"] for d in json.loads(r.stdout)["differences"]} >= {"release", "artifact"})
migs = {}
for name, cand, want in (("basic", V2 / "examples/basic", True), ("rewrite", V2 / "examples/journal", True)):
    r = subprocess.run([PY, "gate/migrate.py", "run", "--release", rels["v2"], "--candidate", cand, "--old-release", rels["v1"], "--old-candidate", o_cand,
                        "--old-evidence", OUT / "ev-v1", "--out", OUT / f"migration-{name}"], cwd=ROOT, capture_output=True, text=True)
    M = json.loads((OUT / f"migration-{name}/migration-report.json").read_text()); migs[name] = M
    expect(D, f"migration of populated v1 state to the {name} application: every step passes, history kept", r.returncode == 0 and M["ok"], [s["step"] for s in M["steps"] if s["result"] != "pass"])
W = yaml.safe_load((V2 / "examples/wrong-migrations/expected.yaml").read_text())
for name, want in W.items():
    r = subprocess.run([PY, "gate/migrate.py", "run", "--release", rels["v2"], "--candidate", V2 / "examples/wrong-migrations" / name, "--old-release", rels["v1"],
                        "--old-candidate", o_cand, "--old-evidence", OUT / "ev-v1", "--out", OUT / f"migration-wrong-{name}"], cwd=ROOT, capture_output=True, text=True)
    M = json.loads((OUT / f"migration-wrong-{name}/migration-report.json").read_text()); migs["wrong-" + name] = M
    v = next((s for s in M["steps"] if s["step"].startswith("verify")), {})
    got = set(v.get("failing_tests") or []); need = set(want["failing_tests"]); may = set(want.get("may_also_fail") or [])
    expect(D, f"known-wrong migration {name} is refused at verify for exactly its defect", r.returncode == 1 and v.get("result") == "fail" and need <= got <= need | may, sorted(got))
code, c2b, _ = judge(rels["v2"], V2 / "examples/wrong-migrations/drops-refused", OUT / "ev-wrong-migration-judged")
expect(D, "the same known-wrong migration passes the ordinary judge: only the migration run with populated state catches it", code == 0)
rec["demonstrations"][D].update({"classify": {k: cls[k] for k in ("route", "contract_changes")}, "migrations": {k: {"ok": m["ok"], "steps": [(s["step"], s["result"]) for s in m["steps"]]} for k, m in migs.items()}})

# ---- 4. composed workflow
D = "composed workflow"
r = subprocess.run([PY, "gate/compose.py", "check", "compositions/ledger-receipts", "--json"], cwd=ROOT, capture_output=True, text=True)
C = json.loads(r.stdout)
expect(D, "the integration keeps every local invariant, permitted effect and the joint invariant", r.returncode == 0 and C["runs"][0]["result"] == "pass")
expect(D, "the known-wrong integration keeps each component's rules and violates exactly the joint invariant",
       all(x["result"] == "pass" for x in C["runs"][1:]) and any("is violated" in x["run"] for x in C["runs"]))
rec["demonstrations"][D].update({"runs": [(x["run"], x["result"], x["detail"]) for x in C["runs"]]})

rec["ok"] = not failures; rec["failures"] = failures
(OUT / "evolution-record.json").write_text(json.dumps(rec, indent=1, default=str))
print(f"evolution: {'all demonstrations hold' if not failures else f'{len(failures)} FAILED'} ({OUT / 'evolution-record.json'})")
sys.exit(0 if not failures else 1)
