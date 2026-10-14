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


def main():
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("plan", "classify"):
        s = sub.add_parser(n); s.add_argument("--evidence", required=True); s.add_argument("--policy-from", default=None)
        s.add_argument("--candidate", default=None); s.add_argument("--json", action="store_true"); s.add_argument("--out", default=None)
        if n == "plan": s.add_argument("--paths", nargs="+", required=True)
    a = ap.parse_args()
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
