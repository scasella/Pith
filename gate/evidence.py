#!/usr/bin/env python3
"""
gate/evidence.py — structured, dependency-aware evidence. FROZEN. Domain-free.

Every check the evaluator runs produces one evidence record: what was claimed, by which method, for which contract
records, resting on which other records, under which toolchain, and computed from exactly which input files.
A record's key is a digest over the check's own definition, the digests of the files its `inputs` globs match in
the judged workspace, the toolchain entries it names, the evaluator's code, and the keys of the records it
depends on. So a changed input invalidates the record AND everything that rests on it, and an unchanged record
can be recognised without re-running it.

    python3 gate/evidence.py impact --evidence PREV_EVIDENCE_DIR [--candidate DIR] [--policy-from DIR]
        which records of a previous run still hold for the candidate as it is now, and which are invalidated and why
    python3 gate/evidence.py verify PREV_EVIDENCE_DIR
        check evidence.json's self-digest and that statement.intoto.json binds the same artifact and records

Reuse (app_gate.py --reuse DIR) is allowed only for checks the pack marks `cacheable`, only from a run of the same
release and evaluator, only for records that passed, and only when the key is identical. Reused records say so.
Format: docs/rfc/0001-contract-packs-and-evidence.md § Evidence.
"""
import argparse, hashlib, json, pathlib, platform, shutil, sys, tempfile

FORMAT = "pith.evidence/v1"
STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
PREDICATE_TYPE = "https://github.com/scasella/Pith/blob/main/docs/rfc/0001-contract-packs-and-evidence.md#predicate-v1"
SPEC_FIELDS_NOT_KEYED = {"claim", "why", "name", "establishes", "assumptions", "area"}   # report text: changing it does not change the result


def canonical(o): return json.dumps(o, sort_keys=True, separators=(",", ":"), default=str).encode()
def h(o): return hashlib.sha256(canonical(o)).hexdigest()


def evaluator_digest(root):
    """Digest of the evaluator's own code (gate/), excluding the frozen list it carries for the pack."""
    d = pathlib.Path(root) / "gate"; x = hashlib.sha256()
    for p in sorted(d.rglob("*")):
        if p.is_file() and p.name != "frozen.sha256" and "__pycache__" not in p.parts:
            x.update(str(p.relative_to(d)).encode()); x.update(hashlib.sha256(p.read_bytes()).digest())
    return x.hexdigest()


def resolve_deps(check, concrete):
    """depends_on names declared check ids; a declared id that expanded (coverage lists etc.) stands for all of its expansions."""
    out = []
    for d in check.get("depends_on", []):
        out += [c["id"] for c in concrete if c["group"] == d]
    return out


def keys(concrete, root, toolchain, evaluator):
    """{concrete id: {"key", "own_key", "files", "tools", "deps"}} computed BEFORE any check runs, so outputs a check
    writes into the workspace never change a key, and `impact` on a fresh workspace computes the same keys."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent)); from workspace import files_matching
    out = {}
    for c in concrete:
        files = files_matching(root, c.get("inputs", []))
        tools = {t: toolchain.get(t) for t in c.get("tools", [])}
        spec = {k: v for k, v in c.items() if k not in SPEC_FIELDS_NOT_KEYED}
        own = h({"spec": spec, "files": files, "tools": tools, "python": platform.python_version(), "evaluator": evaluator})
        deps = resolve_deps(c, concrete)
        out[c["id"]] = {"own_key": own, "key": h({"own": own, "deps": [out[d]["key"] for d in deps if d in out]}), "files": files, "tools": tools, "deps": deps}
    return out


def load(evidence_dir):
    p = pathlib.Path(evidence_dir) / "evidence.json"
    E = json.loads(p.read_text())
    body = {k: v for k, v in E.items() if k != "digest"}
    if E.get("format") != FORMAT or E.get("digest") != h(body): raise ValueError(f"{p}: not {FORMAT} evidence or its digest does not match its content")
    return E


def reusable(prior, check, key, release_digest, evaluator):
    """The prior record for this check if its evidence may stand in for a fresh run, else None (with the reason)."""
    if not check.get("cacheable"): return None, "not cacheable"
    if prior is None: return None, "no prior evidence"
    if prior.get("release_digest") != release_digest: return None, "prior evidence is for another release"
    if prior.get("evaluator_digest") != evaluator: return None, "prior evidence is from another evaluator"
    r = next((r for r in prior["records"] if r["id"] == check["id"]), None)
    if r is None: return None, "no prior record"
    if r["result"] != "pass": return None, "prior record did not pass"
    if r["key"] != key: return None, "inputs changed"
    return r, None


def statement(E):
    """An in-toto v1 Statement binding the behavioural-evidence predicate to the judged artifact. Unsigned: signing
    and distribution are the operator's (provenance does not prove behaviour; this predicate says what was checked)."""
    return {"_type": STATEMENT_TYPE,
            "subject": [{"name": "artifact/", "digest": {"pith-tree-sha256": E["artifact_digest"]}}],
            "predicateType": PREDICATE_TYPE,
            "predicate": {"pack": E["pack"], "release_digest": E["release_digest"], "evaluator_digest": E["evaluator_digest"],
                          "gate_mode": E["gate_mode"], "authority": E["authority"], "isolation": E["isolation"],
                          "statuses": E["statuses"], "release_ready": E["release_ready"], "evidence_digest": E["digest"],
                          "records": [{k: r[k] for k in ("id", "check", "result", "method", "establishes", "key") if k in r} for r in E["records"]]}}


def write(out, E):
    E = {k: v for k, v in E.items() if k != "digest"}; E["digest"] = h(E)
    (pathlib.Path(out) / "evidence.json").write_text(json.dumps(E, indent=1))
    (pathlib.Path(out) / "statement.intoto.json").write_text(json.dumps(statement(E), indent=1))
    return E


def contract_changes(prior, now_contracts):
    """{record id: "how it changed"} between the contract records a previous run was judged against and the release's
    now. Empty when the previous evidence predates recorded contract versions (it cannot say)."""
    before = prior.get("contracts")
    if before is None or now_contracts is None: return {}
    now = {c["id"]: {"version": c.get("version"), "change": c.get("change")} for c in now_contracts}
    out = {}
    for i in sorted(set(before) | set(now)):
        if i not in now: out[i] = "removed"
        elif i not in before: out[i] = "added"
        elif before[i].get("version") != now[i]["version"]: out[i] = f"version {before[i].get('version')} -> {now[i]['version']}"
    return out


def impact(prior, now_keys, now_contracts=None):
    """Classify every prior record against keys computed for the workspace as it is now. With the release's contract
    records, a record that establishes a contract record whose version changed is invalidated even if its inputs did
    not change: it is evidence for the old contract."""
    rows = []; changed = contract_changes(prior, now_contracts)
    for r in prior["records"]:
        if r.get("key") is None: continue                 # evaluator built-ins carry no inputs
        k = now_keys.get(r["id"])
        if k is None: rows.append({"id": r["id"], "check": r["check"], "state": "no longer applies"}); continue
        stale = [f"{c} {changed[c]}" for c in r.get("establishes") or [] if c in changed]
        if k["key"] == r["key"] and stale: rows.append({"id": r["id"], "check": r["check"], "state": "invalidated", "why": "contract changed: " + ", ".join(stale)}); continue
        if k["key"] == r["key"]: rows.append({"id": r["id"], "check": r["check"], "state": "holds" if r["result"] == "pass" else f"unchanged ({r['result']})"}); continue
        changed = sorted(p for p in set(k["files"]) | set(r["files"]) if k["files"].get(p) != r["files"].get(p))
        why = []
        if changed: why.append(f"inputs changed: {changed[:8]}" + (f" (+{len(changed) - 8})" if len(changed) > 8 else ""))
        if k["tools"] != r.get("tools"): why.append("toolchain changed")
        if k["own_key"] != r.get("own_key") and not why: why.append("check definition or evaluator changed")
        if k["own_key"] == r.get("own_key"): why.append("rests on invalidated evidence: " + ", ".join(d for d in k["deps"] if now_keys[d]["key"] != next((x["key"] for x in prior["records"] if x["id"] == d), None)))
        if stale: why.append("contract changed: " + ", ".join(stale))
        rows.append({"id": r["id"], "check": r["check"], "state": "invalidated", "why": "; ".join(why)})
    return rows


def current(cand, policy):
    """Keys, checks, contract records and artifact files for `cand` judged by the release at `policy`, computed in a
    throwaway workspace without running anything: what `impact` and gate/change.py compare a previous run against."""
    here = pathlib.Path(__file__).resolve().parent; sys.path.insert(0, str(here))
    import workspace as W, pack as PK, app_gate as G
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="impact-")); ws = None
    try:
        ws = W.assemble(cand, policy, tmp / "artifact")
        P = PK.load(ws); M = G.read_manifest(ws)
        concrete = PK.expand(P, ws, M, "preflight") + PK.expand(P, ws, M)
        tc = G.toolchain(P, ws, G.tool_values(P)) if any(c.get("tools") for c in concrete) else {}
        return {"pack": P, "manifest": M, "concrete": concrete, "keys": keys(concrete, ws, tc, evaluator_digest(ws)),
                "artifact_files": W.files_matching(tmp / "artifact", ["**"])}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if ws: shutil.rmtree(ws, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("impact"); i.add_argument("--evidence", required=True); i.add_argument("--candidate", default=None); i.add_argument("--policy-from", default=None); i.add_argument("--json", action="store_true")
    v = sub.add_parser("verify"); v.add_argument("evidence")
    a = ap.parse_args()
    here = pathlib.Path(__file__).resolve().parent
    if a.cmd == "verify":
        E = load(a.evidence); S = json.loads((pathlib.Path(a.evidence) / "statement.intoto.json").read_text())
        ok = S["predicate"]["evidence_digest"] == E["digest"] and S["subject"][0]["digest"]["pith-tree-sha256"] == E["artifact_digest"]
        print(f"{'ok' if ok else 'MISMATCH'}: {len(E['records'])} records, artifact {E['artifact_digest'][:16]}, release {E['release_digest'][:16]}"); sys.exit(0 if ok else 1)
    prior = load(a.evidence)
    policy = pathlib.Path(a.policy_from).resolve() if a.policy_from else here.parent
    cand = pathlib.Path(a.candidate).resolve() if a.candidate else here.parent
    now = current(cand, policy); rows = impact(prior, now["keys"], now["pack"].get("contracts"))
    if a.json: print(json.dumps(rows, indent=1)); return
    for r in rows: print(f"{r['state']:>18}  {r['check']}" + (f"  — {r['why']}" if r.get("why") else ""))
    n = sum(r["state"] == "invalidated" for r in rows)
    print(f"{n} of {len(rows)} records invalidated; the rest still hold for these inputs (a re-run with --reuse re-checks only what is invalidated or not cacheable)")


if __name__ == "__main__":
    main()
