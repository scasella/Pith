#!/usr/bin/env python3
"""
experiments/harness.py — plan, record, check and analyse the conditions experiment (docs/EXPERIMENTS.md).

    python3 experiments/harness.py plan     --models ID [ID ...] [--repeats N] --out runs/plan.json
        the run list: every model x task x repeat, the condition rotated (latin square) so every model meets every
        condition and every task is run under every condition; each run gets an id and an order
    python3 experiments/harness.py validate RUN.json [...]
        a run record against experiments/schemas/run.schema.json and the protocol (the budget it ran under, the
        condition it was planned for, interventions named)
    python3 experiments/harness.py analyze  RUNS_DIR [--plan PLAN] [--json]
        the primary outcome per condition (and per model x condition), with Wilson 95% intervals, and the supporting
        measures; recomputed from the stages, never taken from a record's own summary. Planned runs without a record
        are reported as missing, abandoned runs as failures, excluded runs with their reason
    python3 experiments/harness.py dryrun   OUT
        the whole pipeline with two scripted agents instead of models, to show the harness works end to end. Its numbers
        measure the harness, not the conditions: the scripted agents were written to exercise each path. Between turns the
        agents are handed only the distilled packet of the refusal (below), never the full task packet or the judge's log
    python3 experiments/harness.py feedback EVIDENCE [--policy-from RELEASE] [--json]
        what an agent is shown for its next turn (docs/rfc/0007-autonomous-assurance-and-runtime-composition.md § 5): the
        distilled task packet of a judge run (task-packet.distilled.json: redacted, a structured counterexample), or, for a
        refused migration (a directory holding migration-report.json), the packet distilled from the failing step with
        --policy-from, the release the candidate was judged under. TASK.distilled.md, or the JSON. A run record keeps only
        each turn's `feedback`: the packet's digest and its first failure's check

Run records: format pith.experiment-run/v1 (the schema). Nothing here talks to a model provider; a run is executed by
whoever runs the agent, and recorded with what actually happened, failures included.
"""
import argparse, hashlib, json, math, pathlib, re, shutil, subprocess, sys, time
import yaml

HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from gate import packet as PT                      # the evaluator's own redaction and packet shape: the feedback is never written here
PROTOCOL = yaml.safe_load((HERE / "protocol.yaml").read_text())
SCHEMA = json.loads((HERE / "schemas/run.schema.json").read_text())
CONDITIONS = list(PROTOCOL["conditions"])


def plan(models, repeats, tasks=None):
    tasks = tasks or list(PROTOCOL["tasks"]); runs = []
    for r in range(repeats):
        for i, m in enumerate(models):
            for j, t in enumerate(tasks):
                for k in range(len(CONDITIONS)):                     # every condition once per cell, in rotated order
                    c = CONDITIONS[(i + j + r + k) % len(CONDITIONS)]
                    runs.append({"run_id": f"{t}-{c}-{_slug(m)}-r{r + 1}", "model": m, "task": t, "condition": c, "repeat": r + 1, "order": k + 1})
    return {"format": "pith.experiment-plan/v1", "protocol": PROTOCOL["id"], "planned": time.strftime("%Y-%m-%d"), "runs": runs}


def _slug(s): return "".join(ch if ch.isalnum() or ch in "-." else "-" for ch in s)[:48]


def validate(rec):
    import jsonschema
    errs = [e.message for e in jsonschema.Draft202012Validator(SCHEMA).iter_errors(rec)]
    if rec.get("protocol") != PROTOCOL["id"]: errs.append(f"protocol {rec.get('protocol')} is not {PROTOCOL['id']}")
    if rec.get("planned", {}).get("condition") not in CONDITIONS: errs.append("planned.condition is not a protocol condition")
    for st in (rec.get("stages") or {}).values():
        for iv in st.get("interventions", []):
            if iv.get("who") != "none" and not iv.get("why_instructions_were_not_enough"): errs.append("an intervention must say why the instructions were not enough")
    return errs


def primary(rec):
    """The primary outcome, recomputed from the stages (protocol.yaml primary_outcome)."""
    if rec["outcome"].get("excluded"): return None
    b, c = rec["stages"].get("build", {}), rec["stages"].get("change", {})
    repaired = any(iv.get("who") == "maintainer" for st in (b, c) for iv in st.get("interventions", []))
    return bool((b.get("external") or {}).get("passed") and (c.get("external") or {}).get("passed") and not repaired and not b.get("abandoned") and not c.get("abandoned"))


def wilson(k, n, z=1.96):
    if n == 0: return None
    p = k / n; d = 1 + z * z / n; c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0, c - h), 3), round(min(1, c + h), 3)]


def analyze(runs_dir, plan_path=None):
    recs = [json.loads(p.read_text()) for p in sorted(pathlib.Path(runs_dir).glob("*.json")) if p.name != "plan.json"]
    recs = [r for r in recs if r.get("format") == "pith.experiment-run/v1"]
    invalid = {r["run_id"]: validate(r) for r in recs if validate(r)}
    out = {"format": "pith.experiment-analysis/v1", "protocol": PROTOCOL["id"], "runs": len(recs), "invalid": invalid,
           "dry_run": any(r.get("dry_run") for r in recs), "by_condition": {}, "by_model_condition": {}, "excluded": [], "abandoned": []}
    if plan_path:
        P = json.loads(pathlib.Path(plan_path).read_text()); have = {r["run_id"] for r in recs}
        out["missing"] = [r["run_id"] for r in P["runs"] if r["run_id"] not in have]
    for r in recs:
        if r["outcome"].get("excluded"): out["excluded"].append({"run_id": r["run_id"], "reason": r["outcome"].get("exclusion_reason")})
        if any(st.get("abandoned") for st in r["stages"].values()): out["abandoned"].append(r["run_id"])

    def measures(rs):
        ok = [primary(r) for r in rs]; n = sum(x is not None for x in ok); k = sum(bool(x) for x in ok)
        fa = sum(1 for r in rs for s in r["stages"].values() if (s.get("own_acceptance") or {}).get("result") == "accepted" and not (s.get("external") or {}).get("passed"))
        fr = sum(1 for r in rs for s in r["stages"].values() if (s.get("own_acceptance") or {}).get("result") == "refused" and (s.get("external") or {}).get("passed"))
        regress = sum(1 for r in rs for k_, v in ((r["stages"].get("change", {}).get("external") or {}).get("criteria") or {}).items() if k_.startswith("regression") and not v)
        return {"n": n, "primary": k, "proportion": round(k / n, 3) if n else None, "wilson95": wilson(k, n),
                "false_acceptance": fa, "false_rejection": fr, "semantic_regressions": regress,
                "maintainer_interventions": sum(1 for r in rs for s in r["stages"].values() for iv in s.get("interventions", []) if iv.get("who") == "maintainer"),
                "setup_failures": sum(len(s.get("setup_failures", [])) for r in rs for s in r["stages"].values()),
                "repair_cycles": sum(max(0, s.get("attempts", 1) - 1) for r in rs for s in r["stages"].values()),
                "abandoned": sum(1 for r in rs if any(s.get("abandoned") for s in r["stages"].values())),
                "median_wall_clock_minutes": _median([(r.get("usage") or {}).get("wall_clock_minutes") for r in rs])}
    for c in CONDITIONS: out["by_condition"][c] = measures([r for r in recs if r["planned"]["condition"] == c])
    for m in sorted({r["planned"]["model"] for r in recs}):
        for c in CONDITIONS: out["by_model_condition"][f"{m} / {c}"] = measures([r for r in recs if r["planned"]["model"] == m and r["planned"]["condition"] == c])
    if out["dry_run"]: out["note"] = "DRY RUN with scripted agents: these numbers measure the harness, not the conditions or any model"
    return out


def _median(xs):
    xs = sorted(x for x in xs if isinstance(x, (int, float)))
    return None if not xs else (xs[len(xs) // 2] if len(xs) % 2 else (xs[len(xs) // 2 - 1] + xs[len(xs) // 2]) / 2)


# ------------------------------------------------------------------ feedback: what an agent reads between turns
HOST_PATH = re.compile(r"(?:file://)?/(?:Users|home|private|var/folders|tmp|opt|root|mnt|srv|Library)/|[A-Za-z]:\\")   # a path into the machine that ran the judge
def feedback(ev, policy=None):
    """The packet an agent is shown after a refused turn, and nothing else: {packet, markdown, digest, check, disclosure}.
    `ev` is a judge's evidence directory (its task-packet.distilled.json) or a migration's output directory (the packet is
    distilled from the failing step of its migration-report.json, under the release `policy`). Refuses, rather than hands over,
    anything that is not redacted or still holds a host path or a stack frame: an agent never sees the full packet."""
    ev = pathlib.Path(ev)
    if (ev / "task-packet.distilled.json").is_file():
        D = json.loads((ev / "task-packet.distilled.json").read_text()); md = (ev / "TASK.distilled.md").read_text() if (ev / "TASK.distilled.md").is_file() else PT.markdown(D)
    elif (ev / "migration-report.json").is_file():
        if not policy: raise SystemExit("a migration report is distilled under the release it was judged by: pass --policy-from RELEASE")
        D = migration_packet(json.loads((ev / "migration-report.json").read_text()), pathlib.Path(policy)); md = PT.markdown(D)
    else:
        raise SystemExit(f"{ev}: no distilled packet (task-packet.distilled.json) and no migration report; `python3 gate/cli.py packet distill {ev}` writes the former")
    leak = D.get("disclosure") != "redacted" or HOST_PATH.search(md) or any(p.search(l) for l in md.splitlines() for p in PT.FRAME_LINES)
    if leak: raise SystemExit(f"{ev}: the packet is not distilled (disclosure {D.get('disclosure')!r}, or it still holds a host path or a stack frame); an agent is not handed it")
    return {"packet": D, "markdown": md, "digest": hashlib.sha256(json.dumps(D, sort_keys=True).encode()).hexdigest(),
            "check": (D.get("first_failure") or {}).get("check"), "disclosure": D["disclosure"]}


def migration_packet(rep, policy):
    """The distilled packet of a refused migration: its first failing step, in the evaluator's packet shape (gate/packet.py), under
    the new release's pack and redaction vocabulary. A step's output is what the harness printed, a counterexample line included."""
    P = yaml.safe_load((policy / "pack.yaml").read_text()); fail = next((x for x in rep["steps"] if x["result"] == "fail"), None)
    if fail is None: raise SystemExit("the migration report has no failing step")
    rec = {"id": "migration." + re.split(r"[:\s]", fail["step"])[0], "check": fail["step"], "kind": "command", "result": "fail", "blocking": True, "why": fail.get("detail") or "", "area": "migration", "method": "test",
           "category": fail.get("category", "violation"), "category_basis": "reported by the migration report", "establishes": list(rep.get("records") or [])}
    claims = {"pack": {"id": rep["to"]["pack"], "version": rep["to"].get("version")}, "artifact_digest": rep["to"]["artifact_digest"], "release_ready_missing": [], "checks": [rec]}
    pk = PT.build(claims, [rec], P, "migration", "<candidate>", "<release>", "<evidence>", {}, rep["to"]["release_digest"])
    D = PT.distill(pk, claims, P, policy); D["gate_mode"] = "migration"
    return D


def _turn(attempts, fb): return {"turn": attempts, "digest": fb["digest"], "check": fb["check"], "disclosure": fb["disclosure"]}


# ------------------------------------------------------------------ dry run
SCRIPTED = {   # what each scripted agent submits at each stage, in order of attempts (paths under the repository)
    "scripted:careful": {"build": ["evolution/tally-v1/examples/basic"], "change": ["evolution/tally-v2/examples/basic"]},
    "scripted:naive": {"build": ["evolution/tally-v1/examples/basic"],
                       "change": ["evolution/tally-v2/examples/wrong-migrations/drops-refused", "evolution/tally-v2/examples/basic"]},
}
RUN_JSON = {"build": {"start": "python -I service/run.py --port {port} --db {db}"},
            "change": {"start": "python -I service/run.py --port {port} --db {db}", "migrate": "python -I service/migrate.py --db {db}"}}


def sh(argv, cwd=ROOT, **kw): return subprocess.run([str(a) for a in argv], cwd=cwd, capture_output=True, text=True, **kw)


def tree_digest(d):
    h = hashlib.sha256()
    for p in sorted(pathlib.Path(d).rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts: h.update(str(p.relative_to(d)).encode()); h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def dryrun(out):
    out = pathlib.Path(out).resolve(); shutil.rmtree(out, ignore_errors=True); (out / "runs").mkdir(parents=True)
    rel = {}
    for v in ("v1", "v2"):
        rel[v] = out / f"release-{v}"; sh([sys.executable, "gate/release.py", "build", "--pack", f"evolution/tally-{v}", "--out", rel[v]])
    rid = {v: sh([sys.executable, r / "gate/release.py", "id"]).stdout.strip() for v, r in rel.items()}
    P = plan(list(SCRIPTED), 1); (out / "runs/plan.json").write_text(json.dumps(P, indent=1))
    for run in P["runs"]:
        t0 = time.time(); agent = SCRIPTED[run["model"]]; base = out / "work" / run["run_id"]; stages = {}; prev = None
        for stage in ("build", "change"):
            attempts = 0; own = {"result": "none"}; ws = base / stage; turns = []
            for src in agent[stage]:
                attempts += 1
                if ws.exists(): shutil.rmtree(ws)
                shutil.copytree(prev, ws) if prev else ws.mkdir(parents=True)
                shutil.copytree(ROOT / src, ws, dirs_exist_ok=True); (ws / "run.json").write_text(json.dumps(RUN_JSON[stage]))
                if run["condition"] == "core-tests":
                    shutil.copytree(HERE / "tasks/counters/core-tests", ws, dirs_exist_ok=True)
                own = acceptance(run["condition"], stage, ws, prev, rel, rid, out / "evidence" / f"{run['run_id']}-{stage}-{attempts}")
                if own["result"] != "refused": break                 # the agent stops when its own acceptance stops refusing
                if run["condition"] == "pith":                       # it repairs from the distilled packet it was handed, which is all it was handed
                    if "feedback" not in own: raise SystemExit(f"{run['run_id']}: a refused turn handed the agent no distilled packet")
                    turns.append(_turn(attempts, own["feedback"]))
            ext = json.loads(sh([sys.executable, HERE / "external/counters_check.py", "--workspace", ws, "--stage", stage, "--json"] + (["--previous", prev] if prev else [])).stdout)
            stages[stage] = {"attempts": attempts, "own_acceptance": {k: v for k, v in own.items() if k != "feedback"}, "external": {"passed": ext["passed"], "criteria": ext["criteria"], **({"error": ext["error"]} if ext.get("error") else {})},
                             "interventions": [], "setup_failures": [], "abandoned": False, "workspace_digest": tree_digest(ws), "transcript_sha256": None,
                             **({"feedback": turns} if turns else {})}
            prev = ws
        rec = {"format": "pith.experiment-run/v1", "protocol": PROTOCOL["id"], "run_id": run["run_id"], "dry_run": True,
               "planned": {k: run[k] for k in ("model", "task", "condition", "repeat", "order")},
               "agent": {"model": run["model"], "provider": "none (scripted)", "harness": "experiments/harness.py dryrun"},
               "budget": PROTOCOL["budget"], "usage": {"turns": None, "tokens_in": None, "tokens_out": None, "wall_clock_minutes": round((time.time() - t0) / 60, 2), "cost_usd": 0},
               "stages": stages, "outcome": {"excluded": False}}
        rec["outcome"]["primary"] = primary(rec)
        errs = validate(rec)
        if errs: raise SystemExit(f"{run['run_id']}: invalid record: {errs}")
        (out / "runs" / f"{run['run_id']}.json").write_text(json.dumps(rec, indent=1))
        print(f"{run['run_id']:<44} own: {stages['build']['own_acceptance']['result']}/{stages['change']['own_acceptance']['result']}  external: "
              f"{stages['build']['external']['passed']}/{stages['change']['external']['passed']}  attempts {stages['change']['attempts']}  primary {rec['outcome']['primary']}")
    A = analyze(out / "runs", out / "runs/plan.json"); (out / "analysis.json").write_text(json.dumps(A, indent=1))
    return A


def acceptance(condition, stage, ws, prev, rel, rid, ev):
    """The condition's own acceptance: what the agent would see before it stops."""
    if condition == "prose": return {"result": "none", "detail": "no acceptance procedure: the agent declares itself done"}
    if condition == "core-tests":
        r = sh([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_core.py"], cwd=ws)
        return {"result": "accepted" if r.returncode == 0 else "refused", "detail": (r.stdout.strip().splitlines() or [""])[-1]}
    v = "v1" if stage == "build" else "v2"
    ev.parent.mkdir(parents=True, exist_ok=True)
    r = sh([sys.executable, "-I", rel[v] / "gate/app_gate.py", "--candidate", ws, "--out", ev, "--expected-release", rid[v]])
    if r.returncode != 0:
        fb = feedback(ev, rel[v]); return {"result": "refused", "detail": f"judge exit {r.returncode}; first failure {fb['check']} (the distilled packet is the agent's only feedback)", "feedback": fb}
    if stage == "change":
        old_ev = sorted(ev.parent.glob(ev.name.rsplit("-change-", 1)[0] + "-build-*"))[-1]
        m = sh([sys.executable, "gate/migrate.py", "run", "--release", rel["v2"], "--candidate", ws, "--old-release", rel["v1"], "--old-candidate", prev,
                "--old-evidence", old_ev, "--out", str(ev) + "-migration"])
        if m.returncode != 0:
            fb = feedback(str(ev) + "-migration", rel["v2"])
            return {"result": "refused", "detail": f"judge accepted; migration refused at {fb['packet']['first_failure']['name']!r} (the distilled packet is the agent's only feedback)", "feedback": fb}
    return {"result": "accepted", "detail": f"judge exit 0 ({ev})"}


def main():
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan"); p.add_argument("--models", nargs="+", required=True); p.add_argument("--repeats", type=int, default=PROTOCOL["repeats"]); p.add_argument("--out", required=True)
    v = sub.add_parser("validate"); v.add_argument("records", nargs="+")
    a = sub.add_parser("analyze"); a.add_argument("runs"); a.add_argument("--plan"); a.add_argument("--json", action="store_true")
    d = sub.add_parser("dryrun"); d.add_argument("out")
    f = sub.add_parser("feedback"); f.add_argument("evidence"); f.add_argument("--policy-from"); f.add_argument("--json", action="store_true")
    x = ap.parse_args()
    if x.cmd == "plan":
        P = plan(x.models, x.repeats); pathlib.Path(x.out).parent.mkdir(parents=True, exist_ok=True); pathlib.Path(x.out).write_text(json.dumps(P, indent=1))
        print(f"{len(P['runs'])} runs planned ({x.out})")
    elif x.cmd == "validate":
        bad = 0
        for f in x.records:
            errs = validate(json.loads(pathlib.Path(f).read_text())); bad += bool(errs)
            print(f"{'ok' if not errs else 'INVALID'}  {f}" + "".join(f"\n  - {e}" for e in errs))
        sys.exit(1 if bad else 0)
    elif x.cmd == "feedback":
        fb = feedback(x.evidence, x.policy_from); print(json.dumps(fb["packet"], indent=1) if x.json else fb["markdown"])
    else:
        A = analyze(x.runs, x.plan) if x.cmd == "analyze" else dryrun(x.out)
        if getattr(x, "json", False): print(json.dumps(A, indent=1)); return
        if A.get("note"): print(A["note"])
        for c, m in A["by_condition"].items():
            print(f"{c:<11} primary {m['primary']}/{m['n']} {m['wilson95']}  false accept {m['false_acceptance']}  false reject {m['false_rejection']}  "
                  f"regressions {m['semantic_regressions']}  repair cycles {m['repair_cycles']}  maintainer interventions {m['maintainer_interventions']}  abandoned {m['abandoned']}")
        if A.get("missing"): print(f"missing records: {A['missing']}")
        if A["invalid"]: print(f"INVALID records: {A['invalid']}"); sys.exit(1)


if __name__ == "__main__":
    main()
