#!/usr/bin/env python3
"""
gate/deploy.py — bind evidence to a deployment. FROZEN. Domain-free.

Evidence says what was checked about one artifact under one release. A deployment record carries that identity to
where the artifact runs, so an operator (or a later run of `check`) can tell whether what is deployed is what was judged:

    python3 gate/deploy.py record --evidence EV --release RELEASE --candidate DIR [--config KEY=VALUE ...] --out deployment.json
    python3 gate/deploy.py check  --record deployment.json --release RELEASE --deployed DIR [--config KEY=VALUE ...] [--revocations FILE] [--json]

`record` refuses unless the evidence verifies, the release is the one the evidence names, the candidate is the judged
artifact (same artifact digest), and every status the pack declares is at its ready value (or --allow-not-ready, which
the record then says). It records (format pith.deployment/v1): the artifact and release digests, the evidence digest,
the contract identity (pack, version, contract version, each contract record's version), the toolchain and runtime the
evidence was produced under, the dependency versions the evaluator recorded, and the runtime configuration as SHA-256
digests of each value (configuration values may be secrets; the record proves equality, never discloses them).

`check` recomputes the deployed artifact's digest under the same release and compares it, the release, the runtime
(Python version and platform) and any configuration given again. A mismatch is reported with what differs; the
deployment is then running something the evidence does not cover.

What a record does not do: it does not observe the running system. Runtime monitoring is scoped to what it can
observe: a complete-looking event stream is not independent proof that no side effect bypassed it. The record says so.
"""
import argparse, hashlib, json, pathlib, platform, shutil, sys, tempfile, time

HERE = pathlib.Path(__file__).resolve().parent; sys.path.insert(0, str(HERE))
import workspace as W, evidence as EV, release as REL
import yaml

FORMAT = "pith.deployment/v1"
MONITORING = ("the record binds evidence to the deployed artifact and its configuration; it does not observe the running system. "
              "Runtime monitoring covers only what the service emits: a complete-looking event stream is not proof that no side effect bypassed it.")


def artifact_digest(candidate, release):
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="deploy-")); ws = None
    try:
        ws = W.assemble(pathlib.Path(candidate).resolve(), pathlib.Path(release).resolve(), tmp / "artifact")
        return W.digest_dir(tmp / "artifact")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if ws: shutil.rmtree(ws, ignore_errors=True)


def config(pairs):
    out = {}
    for p in pairs or []:
        if "=" not in p: sys.exit(f"--config {p}: expected KEY=VALUE")
        k, v = p.split("=", 1); out[k] = "sha256:" + hashlib.sha256(v.encode()).hexdigest()
    return dict(sorted(out.items()))


def runtime(): return {"python": platform.python_version(), "implementation": platform.python_implementation(), "platform": f"{platform.system()}-{platform.machine()}"}


def ready(P, name, value):
    cond = P["statuses"][name]["ready"]
    return isinstance(value, str) and (value.startswith(cond["startswith"]) if "startswith" in cond else value == cond["equals"])


def record(a):
    E = EV.load(a.evidence); problems = []
    S = json.loads((pathlib.Path(a.evidence) / "statement.intoto.json").read_text())
    if S["predicate"]["evidence_digest"] != E["digest"] or S["subject"][0]["digest"]["pith-tree-sha256"] != E["artifact_digest"]:
        problems.append("the in-toto statement does not bind this evidence")
    rel = REL.release_digest(pathlib.Path(a.release).resolve())
    if rel != E["release_digest"]: problems.append(f"release {rel[:16]} is not the release the evidence names ({str(E.get('release_digest'))[:16]})")
    art = artifact_digest(a.candidate, a.release)
    if art != E["artifact_digest"]: problems.append(f"artifact {art[:16]} is not the judged artifact ({str(E.get('artifact_digest'))[:16]})")
    P = yaml.safe_load((pathlib.Path(a.release) / W.PACK_FILE).read_text())
    not_ready = [n for n, v in (E.get("statuses") or {}).items() if n in P["statuses"] and not ready(P, n, v)]
    if not_ready and not a.allow_not_ready: problems.append(f"statuses not at their ready value: {not_ready} (--allow-not-ready records it anyway)")
    if E.get("gate_mode") != "authoritative": problems.append(f"evidence is from a {E.get('gate_mode')} run, not an authoritative one")
    if problems:
        for p in problems: print(f"[REFUSED] {p}")
        sys.exit(1)
    D = {"format": FORMAT, "recorded": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
         "artifact_digest": art, "release_digest": rel, "evidence_digest": E["digest"], "evaluator_digest": E["evaluator_digest"],
         "contract": {"pack": E["pack"], "records": {i: c.get("version") for i, c in (E.get("contracts") or {}).items()}},
         "statuses": E.get("statuses"), "not_ready": not_ready, "release_ready": E.get("release_ready"), "isolation": E.get("isolation"),
         "toolchain": E.get("toolchain"), "runtime": runtime(), "config": config(a.config), "monitoring": MONITORING}
    D["digest"] = EV.h(D)
    pathlib.Path(a.out).write_text(json.dumps(D, indent=1))
    print(f"deployment record {a.out}: artifact {art[:16]}, release {rel[:16]}, evidence {E['digest'][:16]}" + (f"; NOT READY: {not_ready}" if not_ready else ""))


def check(a):
    D = json.loads(pathlib.Path(a.record).read_text()); diffs = []
    if D.get("format") != FORMAT or D.get("digest") != EV.h({k: v for k, v in D.items() if k != "digest"}): diffs.append({"what": "record", "detail": "not a pith.deployment/v1 record, or its digest does not match its content"})
    rel = REL.release_digest(pathlib.Path(a.release).resolve())
    if rel != D.get("release_digest"): diffs.append({"what": "release", "recorded": D.get("release_digest"), "deployed": rel})
    art = artifact_digest(a.deployed, a.release)
    if art != D.get("artifact_digest"): diffs.append({"what": "artifact", "recorded": D.get("artifact_digest"), "deployed": art})
    rt = runtime()
    for k, v in rt.items():
        if (D.get("runtime") or {}).get(k) != v: diffs.append({"what": f"runtime.{k}", "recorded": (D.get("runtime") or {}).get(k), "deployed": v})
    if a.config is not None:
        now = config(a.config)
        for k in sorted(set(now) | set(D.get("config") or {})):
            if now.get(k) != (D.get("config") or {}).get(k): diffs.append({"what": f"config.{k}", "detail": "missing" if k not in now else ("not recorded" if k not in (D.get("config") or {}) else "value differs")})
    if a.revocations:
        import catalog as CAT
        R = CAT.load_revocations(a.revocations)
        for kind, d in (("releases", D.get("release_digest")), ("evaluators", D.get("evaluator_digest"))):
            e = CAT.revoked_digests(R, kind).get(d)
            if e: diffs.append({"what": f"revoked {kind[:-1]}", "detail": f"{e.get('reason')} ({e.get('advisory')}); effect: {e.get('effect')}"})
    rep = {"format": "pith.deployment-check/v1", "ok": not diffs, "record": D.get("digest"), "differences": diffs, "monitoring": MONITORING,
           "covered": "the deployed artifact is the judged one under the recorded release" if not diffs else "the deployment runs something the evidence does not cover"}
    if a.json: print(json.dumps(rep, indent=1))
    else:
        for d in diffs: print(f"[DIFFERS] {d['what']}: " + (d.get("detail") or f"recorded {str(d.get('recorded'))[:16]}, deployed {str(d.get('deployed'))[:16]}"))
        print(("ok: " if rep["ok"] else "NOT ok: ") + rep["covered"])
    sys.exit(0 if rep["ok"] else 1)


def main():
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    for k in ("--evidence", "--release", "--candidate", "--out"): r.add_argument(k, required=True)
    r.add_argument("--config", action="append"); r.add_argument("--allow-not-ready", action="store_true")
    c = sub.add_parser("check")
    for k in ("--record", "--release", "--deployed"): c.add_argument(k, required=True)
    c.add_argument("--config", action="append"); c.add_argument("--json", action="store_true")
    c.add_argument("--revocations", default=None, help="revocations.yaml: a deployment resting on a revoked release or evaluator is not covered")
    a = ap.parse_args()
    (record if a.cmd == "record" else check)(a)


if __name__ == "__main__":
    main()
