#!/usr/bin/env python3
"""
gate/change.py — change classification and change-impact reports. FROZEN. Domain-free. Advisory: never authoritative.

Every contract record names the route a change to it takes (`change`: presentation | integration | behavioral), and a
pack may name routes for the candidate's own paths (`change_routes`). This tool turns a change into a report of what
it reaches and what must be re-established, before or after it is made:

    python3 gate/change.py plan     --evidence PREV --paths PATH [PATH ...] [--policy-from RELEASE] [--json]
        before implementation: which checks read the paths you intend to change, which contract records those checks
        establish, the route, and what has to be re-established
    python3 gate/change.py classify --evidence PREV [--candidate DIR] [--policy-from RELEASE] [--json] [--out FILE]
        after: the files that changed since PREV was judged (and the contract records that changed, when RELEASE is a
        new release), which evidence still holds, which is invalidated and why, the route, and what to do

The routes, strictest last:
  presentation  re-run the affected delivery and interaction checks
  integration   re-establish the runtime assumptions and the correspondence the affected checks establish
  behavioral    the contract changes: revise and review the contract records, validate intent, update the wrong
                candidates, publish a new release, and judge again (no evidence for the old contract carries over)

    python3 gate/change.py merge --base-candidate DIR --base EVIDENCE --branch NAME=DIR[:EVIDENCE] [--branch ...] --out MERGED
                             [--policy-from RELEASE] [--judge EVIDENCE_OUT] [--json] [--report FILE]
        a fork-join handoff (v0.13.0): several branches made from one accepted base, merged when they touch disjoint
        partitions (pack.yaml `partitions`) and no boundary partition; the merged tree, a digest per partition (the
        compositional seal), which evidence still holds for the merged tree and where from, and, with --judge, the
        judge run on the merged tree with every evidence directory offered for reuse; the merge stands only if that run
        is accepted. Format pith.merge-report/v1, authoritative: false (docs/rfc/0007 § 8)

The report is format pith.change-impact/v1 with `authoritative: false`. A route is an inference from declared paths and
from which checks read which files; where those disagree, or a changed file is read by no check and has no declared
route, the report says `ambiguous` and lists why, and the route given is the strictest candidate. The judge decides
acceptance, never this report; it only says what a fresh run will have to re-establish.
"""
import argparse, fnmatch, json, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent; sys.path.insert(0, str(HERE))
import evidence as EV

FORMAT = "pith.change-impact/v1"
ROUTES = ("presentation", "integration", "behavioral")
REQUIRED = {
    "presentation": "re-run the delivery and interaction checks listed under `rerun`; assurance evidence still holds where the report says so",
    "integration": "re-establish the runtime assumptions and correspondence: re-run every invalidated check (a run with --reuse re-checks only those)",
    "behavioral": "revise the contract: change the records listed under `contract_changes` (or the ones this change needs), validate their intent with "
                  "the pack's maintainers, update the known-wrong candidates, review and publish a new release, then judge against it; evidence for "
                  "the old contract does not carry over",
}


def strictest(routes): return max(routes, key=ROUTES.index) if routes else None


def match(path, globs): return any(fnmatch.fnmatch(path, g) or (g.endswith("/**") and path.startswith(g[:-2])) for g in globs)


def declared_routes(P, path):
    """[(route, why)] from the pack's change_routes for one candidate path."""
    return [(r["route"], r.get("why", "")) for r in P.get("change_routes", []) if match(path, r["paths"])]


def records_by_check(P):
    """{check group id: [contract record]} for every record a check verifies or establishes."""
    out = {}
    for c in P.get("contracts", []):
        for g in c.get("verified_by", []): out.setdefault(g, []).append(c)
    for ch in P.get("checks", []):
        for i in ch.get("establishes", []):
            rec = next((c for c in P.get("contracts", []) if c["id"] == i), None)
            if rec and rec not in out.setdefault(ch["id"], []): out[ch["id"]].append(rec)
    return out


def dependents(concrete, ids):
    """ids plus every concrete check that depends on one of them, transitively."""
    out = set(ids); grew = True
    while grew:
        grew = False
        for c in concrete:
            if c["id"] not in out and set(EV.resolve_deps(c, concrete)) & out: out.add(c["id"]); grew = True
    return out


def where(P, manifest, path):
    """'artifact' (judged), 'release' (frozen: only a new release changes it) or 'outside' (never judged)."""
    top = path.split("/")[0]
    if top in P.get("policy_dirs", []) or top in ("gate", "pack.yaml", "release.seal.json"): return "release"
    inc = [str(i).rstrip("/") for i in (manifest or {}).get("include") or []] if "include" in P["candidate"].get("manifest_allowlist", []) else []
    if top in P["candidate"]["owned_dirs"] or path == "app.manifest.yaml" or any(path == i or path.startswith(i + "/") for i in inc): return "artifact"
    return "outside"


def route_files(P, paths, reads, manifest=None):
    """Per changed path: declared routes, routes implied by the contract records of the checks that read it, the route
    and any ambiguity. `reads` is {path: [check group ids that read it]}."""
    by_check = records_by_check(P); rows = []; ambiguous = []
    for p in sorted(paths):
        loc = where(P, manifest, p)
        if loc == "outside":
            rows.append({"path": p, "route": None, "where": "outside the judged artifact: no evidence rests on it, and none covers it"}); continue
        if loc == "release":
            why = ["frozen release content: a new release is needed; whether the contract's meaning changes (behavioral) or only how it is checked is the maintainers' call"]
            rows.append({"path": p, "route": "behavioral", "where": "frozen release content", "ambiguous": why}); ambiguous.append({"path": p, "why": why}); continue
        decl = declared_routes(P, p)
        recs = {c["id"]: c.get("change") for g in reads.get(p, []) for c in by_check.get(g, [])}
        # an implementation change to a path that feeds behavioral records re-establishes them (integration route);
        # only a change to the records themselves is a behavioral change
        implied = sorted({("presentation" if r == "presentation" else "integration") for r in recs.values() if r}, key=ROUTES.index)
        d_routes = sorted({r for r, _ in decl}, key=ROUTES.index)
        why = []
        if len(d_routes) > 1: why.append(f"declared routes disagree: {d_routes}")
        if d_routes and implied and ROUTES.index(strictest(implied)) > ROUTES.index(strictest(d_routes)):
            why.append(f"declared {strictest(d_routes)}, but checks reading it establish records that need {strictest(implied)}")
        if not d_routes and not reads.get(p): why.append("no declared route and no check reads it: its effect on the contract is unknown")
        route = strictest(d_routes + implied) or "integration"
        rows.append({"path": p, "route": route, "declared": [{"route": r, "why": w} for r, w in decl], "read_by": sorted(reads.get(p, [])),
                     "records": sorted(recs), **({"ambiguous": why} if why else {})})
        if why: ambiguous.append({"path": p, "why": why})
    return rows, ambiguous


def report(prior, now, files, reads, rows_impact):
    P = now["pack"]
    cc = EV.contract_changes(prior, P.get("contracts"))
    frows, amb = route_files(P, files, reads, now.get("manifest"))
    rec_routes = {**{i: v.get("change") for i, v in (prior.get("contracts") or {}).items()}, **{c["id"]: c.get("change") for c in P.get("contracts", [])}}
    # a changed contract record takes its own route (a record without one is behavioral); a new release is needed either way
    route = strictest([rec_routes.get(i) or "behavioral" for i in cc] + [r["route"] for r in frows if r["route"]])
    inval = [r for r in rows_impact if r["state"] != "holds" and not r["state"].startswith("unchanged")]
    return {"format": FORMAT, "authoritative": False,
            "note": "advisory: an inference from declared routes and from which checks read which files; the judge decides acceptance",
            "from": {k: prior.get(k) for k in ("release_digest", "evaluator_digest", "artifact_digest", "digest")} | {"pack": prior.get("pack")},
            "to": {"pack": {"id": P["pack"]["id"], "version": P["pack"].get("version")}},
            "route": route, "ambiguous": amb, "required": REQUIRED.get(route) if route else "nothing changed",
            "contract_changes": [{"id": i, "change": c, "route": rec_routes.get(i)} for i, c in cc.items()],
            "files": frows,
            "evidence": {"holds": sorted(r["check"] for r in rows_impact if r["state"] == "holds"),
                         "invalidated": [{"check": r["check"], "why": r.get("why", r["state"])} for r in inval]},
            "rerun": sorted({r["check"] for r in inval})}


def reusable(R, prior, policy):
    """`holds` says which results this change did not reach; `reusable` says which of them the judge's --reuse can
    actually take. Evidence is bound to the release and evaluator it was produced under (evidence.reusable), so across
    a release every result is produced again, including the ones that hold."""
    import release as REL
    now = REL.release_digest(policy if (policy / "gate").is_dir() else HERE.parent, policy); same = prior.get("release_digest") == now
    R["evidence"]["reusable"] = list(R["evidence"]["holds"]) if same else []
    if not same:
        R["evidence"]["reusable_note"] = ("the previous evidence is for another release: what holds was not reached by the change, "
                                          "but --reuse never crosses releases, so the judge produces every result again")


def reads_from(prior, now, paths):
    """{path: [check groups]} — which checks read each path: the previous run's recorded inputs and the release's
    declared `inputs` globs (so a path that does not exist yet is still placed)."""
    out = {}
    for r in prior["records"]:
        for p in r.get("files") or {}:
            if p in paths: out.setdefault(p, set()).add(r["id"].split("/")[0])
    for c in now["concrete"]:
        for p in paths:
            if match(p, c.get("inputs", [])): out.setdefault(p, set()).add(c["group"])
    return {p: sorted(v) for p, v in out.items()}


# ---------------------------------------------------------------- fork-join merge (v0.13.0)
def partition_of(parts, path):
    return next((x["id"] for x in parts if match(path, x["paths"])), None)


def merge(a):
    import shutil, subprocess, workspace as W, release as REL
    policy = pathlib.Path(a.policy_from).resolve() if a.policy_from else HERE.parent
    out = pathlib.Path(a.out).resolve()
    R = {"format": "pith.merge-report/v1", "authoritative": False,
         "note": "advisory: disjoint partitions say which evidence carries over, never that the merged application works; the judge run on the merged tree decides",
         "conflicts": [], "problems": [], "branches": []}
    def done(ok):
        R["ok"] = ok and not R["conflicts"] and not R["problems"]; return R
    if out.exists(): R["problems"].append(f"{out} exists; use a fresh directory"); return done(False)
    base_E = EV.load(a.base); base = EV.current(pathlib.Path(a.base_candidate).resolve(), policy); P = base["pack"]
    parts = P.get("partitions") or []; boundary = {x["id"] for x in parts if x.get("boundary")}
    if not parts: R["problems"].append("the pack declares no partitions (pack.yaml `partitions`): a merge cannot say which branch owns what")
    if base_E.get("artifact_files") != base["artifact_files"]:
        R["problems"].append("the base candidate is not the artifact the base evidence judged"); return done(False)
    R["base"] = {"evidence_digest": base_E["digest"], "artifact_digest": base_E["artifact_digest"], "release_digest": base_E["release_digest"]}
    sources = {"base": base_E}; paths = {"base": a.base}; owner = {}; touched = {}
    for spec in a.branch:
        name, rest = spec.split("=", 1); bdir, _, bev = rest.partition(":")
        now = EV.current(pathlib.Path(bdir).resolve(), policy); bf = now["artifact_files"]; f0 = base["artifact_files"]
        changed = sorted(p for p in set(f0) | set(bf) if f0.get(p) != bf.get(p))
        pmap = {p: partition_of(parts, p) or f"unpartitioned:{p}" for p in changed}
        b = {"name": name, "dir": str(pathlib.Path(bdir).resolve()), "changed": [{"path": p, "partition": pmap[p], "deleted": p not in bf} for p in changed],
             "partitions": sorted(set(pmap.values()))}
        if bev:
            E = EV.load(bev)
            if E.get("artifact_files") == bf: sources[name] = E; paths[name] = bev; b["evidence_digest"] = E["digest"]
            else: b["evidence_note"] = "this evidence judged another artifact than the branch as it is: not offered for reuse"
        for p in changed:
            if p in owner and owner[p][1] != bf.get(p): R["conflicts"].append({"kind": "textual", "path": p, "branches": [owner[p][0], name]})
            owner[p] = (name, bf.get(p))
        for q in b["partitions"]:
            if q in boundary: R["conflicts"].append({"kind": "boundary", "partition": q, "branch": name,
                                                     "why": "a boundary partition changed inside a fork: every other branch was made against the old boundary"})
            if q in touched and touched[q] != name: R["conflicts"].append({"kind": "partition", "partition": q, "branches": [touched[q], name]})
            touched.setdefault(q, name)
        R["branches"].append(b)
    if R["conflicts"] or R["problems"]: return done(False)
    # the merged tree: the base artifact plus every branch's changes (disjoint by now)
    tmp = out.parent / (out.name + ".base-artifact")
    W.copy_artifact(pathlib.Path(a.base_candidate).resolve(), tmp, W.load_pack_policy(policy)[0], P["candidate"]["owned_dirs"],
                    (base["manifest"] or {}).get("include") or [])
    shutil.copytree(tmp, out); shutil.rmtree(tmp, ignore_errors=True)
    for b in R["branches"]:
        for c in b["changed"]:
            dst = out / c["path"]
            if c["deleted"]: dst.unlink(missing_ok=True)
            else: dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(pathlib.Path(b["dir"]) / c["path"], dst)
    merged = EV.current(out, policy)
    seal = {}
    for x in parts + [{"id": "unpartitioned", "paths": []}]:
        files = {p: d for p, d in merged["artifact_files"].items() if (partition_of(parts, p) or "unpartitioned") == x["id"]}
        seal[x["id"]] = EV.h(files)
    R["merged"] = {"dir": str(out), "partitions": seal, "seal": EV.h(seal)}
    # which evidence still holds for the merged tree, and where from
    holds, rerun, cross = [], [], []
    cacheable = {c["id"]: bool(c.get("cacheable")) for c in merged["concrete"]}
    for c in merged["concrete"]:
        k = merged["keys"][c["id"]]["key"]
        src = next((n for n, E in sources.items() for r in E["records"] if r["id"] == c["id"] and r.get("key") == k and r["result"] == "pass"), None)
        (holds if src else rerun).append({"check": c["id"], "source": src, "cacheable": cacheable[c["id"]],
                                          **({"reused_by_judge": cacheable[c["id"]]} if src else {})})
    for b in R["branches"]:
        E = sources.get(b["name"]); others = {q for o in R["branches"] if o is not b for q in o["partitions"]}
        for r in (E or {}).get("records", []):
            hit = sorted({partition_of(parts, p) or "unpartitioned" for p in (r.get("files") or {})} & others)
            if hit and r["result"] == "pass": cross.append({"branch": b["name"], "check": r["id"], "rests_on": hit,
                                                            "why": "this branch's result read files in a partition another branch changed: it does not carry over"})
    R["evidence"] = {"holds": holds, "rerun": rerun, "cross_partition": cross,
                     "rule": "only cacheable results (proofs, model checks) are reused by the judge; every check that starts the service runs again on the merged tree"}
    if a.judge:
        rel = REL.release_digest(policy if (policy / "gate").is_dir() else HERE.parent, policy)
        cmd = [sys.executable, "-I", str(policy / "gate" / "app_gate.py"), "--candidate", str(out), "--out", str(pathlib.Path(a.judge).resolve()), "--expected-release", rel]
        for n in sources: cmd += ["--reuse", str(pathlib.Path(paths[n]).resolve())]
        r = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        jd = pathlib.Path(a.judge)
        C = json.loads((jd / "app-claims.json").read_text()) if (jd / "app-claims.json").exists() else {}
        review = {x.get("status") for x in P.get("checks", []) if x.get("method") == "review"}
        unready = [s for s in P.get("statuses", {}) if s not in review and not _ready(P, s, C.get(s))]
        J = json.loads((jd / "evidence.json").read_text()) if (jd / "evidence.json").exists() else {"records": []}
        pk = json.loads((jd / "task-packet.json").read_text()) if (jd / "task-packet.json").exists() else {}
        R["judge"] = {"evidence": str(jd.resolve()), "exit": r.returncode, "statuses": {s: C.get(s) for s in P.get("statuses", {})}, "unready": unready,
                      "reused": sorted(x["id"] for x in J["records"] if x.get("reused_from")),
                      "first_failure": (pk.get("first_failure") or {}).get("check"), "accepted": not unready and bool(C)}
        return done(R["judge"]["accepted"])
    return done(True)


def _ready(P, name, value):
    cond = P["statuses"][name]["ready"]
    return isinstance(value, str) and (value.startswith(cond["startswith"]) if "startswith" in cond else value == cond["equals"])


def main():
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("merge"); m.add_argument("--base-candidate", required=True); m.add_argument("--base", required=True)
    m.add_argument("--branch", action="append", required=True); m.add_argument("--out", required=True); m.add_argument("--policy-from", default=None)
    m.add_argument("--judge", default=None); m.add_argument("--json", action="store_true"); m.add_argument("--report", default=None)
    for n in ("plan", "classify"):
        s = sub.add_parser(n); s.add_argument("--evidence", required=True); s.add_argument("--policy-from", default=None)
        s.add_argument("--candidate", default=None); s.add_argument("--json", action="store_true"); s.add_argument("--out", default=None)
        if n == "plan": s.add_argument("--paths", nargs="+", required=True)
    a = ap.parse_args()
    if a.cmd == "merge":
        R = merge(a)
        if a.report: pathlib.Path(a.report).write_text(json.dumps(R, indent=1))
        if a.json: print(json.dumps(R, indent=1))
        else:
            for x in R["problems"]: print(f"PROBLEM {x}")
            for x in R["conflicts"]: print(f"CONFLICT {x}")
            for b in R["branches"]: print(f"branch {b['name']}: partitions {b['partitions']} ({len(b['changed'])} files)")
            if R.get("evidence"):
                print(f"evidence: {len(R['evidence']['holds'])} hold ({sum(1 for x in R['evidence']['holds'] if x['cacheable'])} reusable), {len(R['evidence']['rerun'])} re-run; "
                      f"{len(R['evidence']['cross_partition'])} branch results rest on another branch's partition")
            if R.get("judge"): print(f"judge on the merged tree: {'accepted' if R['judge']['accepted'] else 'REFUSED'} (first failure {R['judge']['first_failure']}); reused {R['judge']['reused']}")
            print(f"merge: {'ok' if R['ok'] else 'REFUSED'} (advisory report; the judge decides)")
        sys.exit(0 if R["ok"] else 1)
    prior = EV.load(a.evidence)
    policy = pathlib.Path(a.policy_from).resolve() if a.policy_from else HERE.parent
    cand = pathlib.Path(a.candidate).resolve() if a.candidate else HERE.parent
    now = EV.current(cand, policy)
    if a.cmd == "plan":
        files = set(a.paths); reads = reads_from(prior, now, files)
        hit = dependents(now["concrete"], {c["id"] for c in now["concrete"] if any(g == c["group"] for p in files for g in reads.get(p, []))})
        rows = [{"id": i, "check": next(c["name"] for c in now["concrete"] if c["id"] == i), "state": "invalidated", "why": "reads a planned path, or rests on a check that does"} for i in sorted(hit)]
        rows += [{"id": c["id"], "check": c["name"], "state": "holds"} for c in now["concrete"] if c["id"] not in hit]
        R = report(prior, now, files, reads, rows); R["planned"] = sorted(files)
    else:
        before = prior.get("artifact_files")
        if before is None:
            files = {p for r in prior["records"] for p in (r.get("files") or {})} | {p for k in now["keys"].values() for p in k["files"]}
            files = {p for p in files if (r := [x for x in prior["records"] if p in (x.get("files") or {})]) and any((now["keys"].get(x["id"]) or {}).get("files", {}).get(p) != x["files"][p] for x in r)}
        else:
            nowf = now["artifact_files"]; files = {p for p in set(before) | set(nowf) if before.get(p) != nowf.get(p)}
        reads = reads_from(prior, now, files)
        R = report(prior, now, files, reads, EV.impact(prior, now["keys"], now["pack"].get("contracts")))
        reusable(R, prior, policy)
        if before is None: R["ambiguous"].append({"why": ["the previous evidence predates recorded artifact files: only files some check reads were compared"]})
    if a.out: pathlib.Path(a.out).write_text(json.dumps(R, indent=1))
    if a.json: print(json.dumps(R, indent=1)); return
    print(f"route: {R['route'] or 'none'} (advisory){' — AMBIGUOUS' if R['ambiguous'] else ''}")
    for c in R["contract_changes"]: print(f"  contract {c['id']}: {c['change']}")
    for f in R["files"]: print(f"  {f['route'] or '-':>12}  {f['path']}" + (f"  [ambiguous: {'; '.join(f['ambiguous'])}]" if f.get("ambiguous") else "") + (f"  ({f['where']})" if f.get("where") else ""))
    for x in R["ambiguous"]:
        if "path" not in x: print(f"  ambiguous: {'; '.join(x['why'])}")
    print(f"evidence: {len(R['evidence']['holds'])} hold, {len(R['evidence']['invalidated'])} invalidated; re-run: {', '.join(R['rerun']) or 'nothing'}")
    if R["evidence"].get("reusable") is not None and len(R["evidence"]["reusable"]) != len(R["evidence"]["holds"]):
        print(f"  {R['evidence']['reusable_note']}")
    print(f"required: {R['required']}")


if __name__ == "__main__":
    main()
