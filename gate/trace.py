#!/usr/bin/env python3
"""
gate/trace.py — a divergence a shadow oracle saw, shrunk into a regression trace. FROZEN. Domain-free.

    python3 gate/trace.py harvest LOG --pack DIR --out OUT [--json]
    python3 gate/trace.py replay  TRACE --pack DIR --candidate APP [--json]
    (python3 gate/cli.py trace harvest|replay ... is the same)

A shadow oracle (a pack's own, beside a live service; docs/rfc/0007-autonomous-assurance-and-runtime-composition.md § 7)
writes what it saw as format pith.divergence/v1: the alert, the contract records it bears on, the operations it
reconstructed in the pack's oracle vocabulary (each with what the service was observed to do) and the index of the
operation at which the service and the oracle disagreed. The pack declares (pack.yaml `traces`):

  oracle   a command reading {"steps": [...]} on stdin and printing {"outcomes": [...]}: what the contract says
  render   a command reading a pith.trace/v1 document on stdin and printing the trace in the pack's own form, written
           to `render_file` (a file name); `render_dir` names where in the pack a maintainer adds it (its includes are
           written for that place, not for the harvest directory)
  replay   a command run in a judged workspace of a candidate with PITH_TRACE set: exit 0 iff the candidate answers
           every step as the trace expects

`harvest` keeps the operations up to the diverging one, checks that the oracle really disagrees with what was observed
there, and shrinks them (gate/shrink.py, against the oracle only: nothing live is re-run) to the shortest sequence whose
last step the oracle still answers the same way. It writes trace.yaml (pith.trace/v1: each step with the outcome the
contract requires), the pack's rendering of it, traces.provenance.yaml (unsigned: what it came from and how it was
shrunk) and revocation.draft.yaml (a pith.revocations/v1 entry for evaluator security to consider; GOVERNANCE.md). The
draft is only a draft: a divergence revokes the release only if the deployment was the artifact the evidence accepted
(gate/deploy.py check); otherwise the deployment ran something the evidence never covered, and nothing is revoked.
`replay` runs a trace against a candidate; a shrunk trace is a claim about the oracle until a replay shows the
candidate fails it too.
"""
import argparse, hashlib, json, os, pathlib, shutil, subprocess, sys, tempfile, time
import yaml

HERE = pathlib.Path(__file__).resolve().parent; sys.path.insert(0, str(HERE))
import shrink as SH, workspace as W

DIVERGENCE = "pith.divergence/v1"; TRACE = "pith.trace/v1"; PROVENANCE = "pith.trace-provenance/v1"


def load_divergences(path):
    """Every pith.divergence/v1 record of a JSON document or a JSON-lines log, in order, and the log's digest."""
    text = pathlib.Path(path).read_text()
    try: docs = [json.loads(text)]
    except ValueError: docs = [json.loads(l) for l in text.splitlines() if l.strip()]
    recs = [d for d in docs if isinstance(d, dict) and d.get("format") == DIVERGENCE]
    if not recs: raise SystemExit(f"{path}: no {DIVERGENCE} record")
    return recs, hashlib.sha256(text.encode()).hexdigest()


def commands(pack):
    P = yaml.safe_load((pathlib.Path(pack) / "pack.yaml").read_text())
    T = P.get("traces") or {}
    sub = lambda c: c.replace("{python}", sys.executable) if c else c
    return P, {**{k: sub(T.get(k)) for k in ("oracle", "render", "replay")}, "render_file": T.get("render_file") or "trace.txt", "render_dir": T.get("render_dir")}


def harvest(log, pack, out, record=None):
    pack, out = pathlib.Path(pack).resolve(), pathlib.Path(out).resolve()
    P, T = commands(pack); recs, digest = load_divergences(log)
    rep = {"format": "pith.trace-harvest/v1", "pack": P["pack"]["id"], "source": {"log": str(log), "sha256": digest, "records": len(recs)}, "problems": []}
    if not T["oracle"]: rep["problems"].append("the pack declares no traces.oracle"); rep["ok"] = False; return rep
    # the first record (or the one asked for) at which the oracle disagrees with an answer the service gave: a record
    # whose only symptom is in the stream itself (a broken chain, a disputed state) has no answer to disagree with
    chosen, why_not = None, []
    for i, D in ([(record, recs[record])] if record is not None else enumerate(recs)):
        ops = D.get("operations") or []; k = D.get("diverged_at", len(ops) - 1)
        if not ops or not isinstance(k, int) or not 0 <= k < len(ops): why_not.append(f"record {i}: names no operation at which it diverged"); continue
        steps = [{"action": o["action"], "args": o.get("args", {})} for o in ops[:k + 1]]
        observed = ops[k].get("observed"); expected = SH.oracle(T["oracle"], steps, cwd=pack)[-1]
        if expected == observed: why_not.append(f"record {i} ({D.get('alert')}): the oracle agrees with the answer the service gave"); continue
        chosen = (i, D, steps, observed, expected); break
    if chosen is None:
        rep["problems"] += why_not or ["no record to harvest"]; rep["problems"].append("nothing to harvest: no record shows the service answering otherwise than the contract requires")
        rep["ok"] = False; return rep
    i, D, steps, observed, expected = chosen; rep["source"]["record"] = i
    small, calls = SH.ddmin(steps, lambda s: SH.oracle(T["oracle"], s, cwd=pack)[-1] == expected, keep_last=True)
    outcomes = SH.oracle(T["oracle"], small, cwd=pack)
    out.mkdir(parents=True, exist_ok=True)
    trace = {"format": TRACE, "pack": P["pack"]["id"], "contract_version": P["pack"].get("contract_version"),
             "records": D.get("records", []), "alert": D.get("alert"),
             "steps": [{"step": i + 1, **s, "expected": o} for i, (s, o) in enumerate(zip(small, outcomes))],
             "observed_at_divergence": observed}
    (out / "trace.yaml").write_text("# A regression trace harvested from a shadow divergence (gate/trace.py). Each step's `expected` is what the\n"
                                   "# contract (the pack's oracle) requires; the last step is where the live service answered differently.\n"
                                   + yaml.safe_dump(trace, sort_keys=False, width=1000))
    rendered = None
    if T["render"]:
        r = subprocess.run(T["render"], shell=True, cwd=pack, input=json.dumps(trace), capture_output=True, text=True, timeout=120)
        if r.returncode == 0 and r.stdout.strip():
            rendered = out / pathlib.PurePosixPath(T["render_file"]).name; rendered.write_text(r.stdout)
        else: rep["problems"].append(f"traces.render failed ({r.returncode}): {(r.stderr or r.stdout)[-300:]}")
    today = time.strftime("%Y-%m-%d")
    prov = {"format": PROVENANCE, "status": "unsigned", "reviewers": [], "harvested": today,
            "source": {"sha256": digest, "detected_at": D.get("detected_at"), "release_digest": D.get("release_digest"),
                       "artifact_digest": D.get("artifact_digest"), "alert": D.get("alert")},
            "shrink": {"from_steps": len(steps), "to_steps": len(small), "against": "oracle", "oracle_calls": calls},
            "note": "shrunk against the oracle only; a replay against the service shows whether it fails the shrunk trace too (gate/trace.py replay), "
                    "possibly at an earlier step than the one it was harvested at, since the shrunk history differs",
            **({"place_in": T["render_dir"]} if T["render_dir"] else {})}
    (out / "traces.provenance.yaml").write_text(yaml.safe_dump(prov, sort_keys=False, width=1000))
    draft = {"format": "pith.revocations/v1", "status": "DRAFT, not filed",
             "releases": [{"digest": D.get("release_digest") or "<the release the deployment was judged under>", "date": today,
                           "reason": f"shadow divergence ({D.get('alert')}): the deployed service answered {json.dumps(observed, sort_keys=True)} where the contract requires {json.dumps(expected, sort_keys=True)}; trace.yaml",
                           "advisory": "draft for evaluator security (GOVERNANCE.md § Keys, attestations and revocation). File it only if gate/deploy.py check shows the "
                                       "deployment was the artifact the evidence accepted; otherwise the deployment ran something the evidence never covered and nothing is revoked.",
                           "effect": f"unsound-for: {D.get('records', [])}"}]}
    (out / "revocation.draft.yaml").write_text(yaml.safe_dump(draft, sort_keys=False, width=1000))
    rep.update({"ok": not rep["problems"], "out": str(out), "steps": {"from": len(steps), "to": len(small)}, "expected": expected, "observed": observed,
                "files": sorted(p.name for p in out.iterdir())})
    return rep


def replay(trace, pack, candidate):
    pack = pathlib.Path(pack).resolve(); P, T = commands(pack)
    if not T["replay"]: return {"format": "pith.trace-replay/v1", "ok": False, "problems": ["the pack declares no traces.replay"]}
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="replay-"))
    try:
        ws = W.assemble(pathlib.Path(candidate).resolve(), pack, tmp / "artifact")
        pytest = (P.get("pytest") or "{python} -m pytest -q").replace("{python}", sys.executable).replace("{root}", str(ws))
        r = subprocess.run(T["replay"].replace("{pytest}", pytest), shell=True, cwd=ws, capture_output=True, text=True, timeout=900,
                           env={**os.environ, "PITH_TRACE": str(pathlib.Path(trace).resolve())})
        return {"format": "pith.trace-replay/v1", "ok": r.returncode == 0, "exit": r.returncode, "artifact_digest": W.digest_dir(tmp / "artifact"),
                "output": (r.stdout + r.stderr)[-6000:], "problems": []}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("harvest"); h.add_argument("log"); h.add_argument("--pack", default=str(HERE.parent)); h.add_argument("--out", required=True); h.add_argument("--json", action="store_true")
    h.add_argument("--record", type=int, default=None, help="the index of the record to harvest (default: the first the oracle disagrees with)")
    r = sub.add_parser("replay"); r.add_argument("trace"); r.add_argument("--pack", default=str(HERE.parent)); r.add_argument("--candidate", required=True); r.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rep = harvest(a.log, a.pack, a.out, a.record) if a.cmd == "harvest" else replay(a.trace, a.pack, a.candidate)
    if a.json: print(json.dumps(rep, indent=1, default=str))
    else:
        for p in rep.get("problems", []): print(f"PROBLEM {p}")
        if a.cmd == "harvest" and rep.get("steps"): print(f"harvested: {rep['steps']['from']} operations shrunk to {rep['steps']['to']} against the oracle; wrote {rep['files']} in {rep['out']}")
        if a.cmd == "replay": print(f"replay: {'the candidate answers every step as the trace expects' if rep['ok'] else 'the candidate does NOT answer as the trace expects'}")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
