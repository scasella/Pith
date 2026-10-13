#!/usr/bin/env python3
"""
gate/app_gate.py — the judge. FROZEN. Domain-independent: everything it checks comes from the contract pack.

    python3 gate/app_gate.py --out EVIDENCE [--expected-release DIGEST] [--review att.json --reviewer-key pub.pem] [--reuse PREV_EVIDENCE]
    python3 <pristine>/gate/app_gate.py --candidate DIR --out EVIDENCE --expected-release DIGEST ...
        authoritative: the judge's own code AND the pack come from the pristine release; DIR is only read for its artifact
    python3 gate/app_gate.py --policy-from DIR ...    same thing invoked from the checkout: re-executes DIR's gate with --candidate

What the evaluator knows: packages (a release = this evaluator + one pack), artifacts, tools, checks, evidence,
statuses and policies. What it does not know: anything the pack's contract is about. pack.yaml names the policy and
agent-owned directories, the ordered checks (each of a kind in gate/kinds.py), the toolchain, how checks roll up into
statuses, and the contract records the checks establish (docs/rfc/0001-contract-packs-and-evidence.md).

How judging works, and why:
  * The judge never imports candidate code. Pack harnesses reach the candidate only as a separate process, under the
    candidate's identity when one is configured (gate/sandbox.py), and all evidence is written by the judge.
  * The judge works on a COPY: a fresh workspace = policy (gate/, pack.yaml, the pack's policy dirs, from this
    checkout or from --policy-from) + the deployment artifact (app.manifest.yaml and the agent-owned dirs, copied).
    The artifact digest covers every file in that copy; nothing is excluded by basename. The live checkout is not touched.
  * Isolation is observed, not declared: a frozen probe runs under the candidate's identity before any candidate code
    and reports what that identity can reach. Without a separate identity (SEED_CANDIDATE_UID, gate/isolation/) the
    run is advisory and says so.
  * Every check yields an evidence record keyed by its inputs, toolchain and dependencies (gate/evidence.py);
    evidence.json and an in-toto statement are written next to app-claims.json. --reuse takes a previous run's
    evidence for cacheable checks whose key is unchanged, and says so in the record.
  * Statuses are reported separately; release_ready requires each at its pack-declared value plus an authoritative
    pinned run, an enforced isolation profile and the adapters' own conditions. Exit 0 iff the pack's completion
    status passed; 2 if it did not; 1 on refusal.
  * Every failure carries a category (violation, not_exercised, evidence_missing, toolchain_unavailable,
    contract_change, infrastructure) and the basis for it, and every run ends with a task packet (task-packet.json,
    TASK.md): the first failure, its contract records, a minimal counterexample, what may be edited, how to rerun
    (gate/packet.py). An exception or a timeout inside a check is a refusal in category infrastructure, never a crash.
  * Coverage is stated: the judged paths (the pack's agent-owned dirs, plus any `include` paths an adopting project
    names when the pack allows it) and that nothing else in the candidate's repository is covered.
"""
import argparse, importlib.metadata, json, os, platform, re, subprocess, sys, time, pathlib
import yaml

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import workspace as W, pack as PK, evidence as EV, kinds as K, sandbox as SB, packet as PT

PROBE_HOSTS = ["1.1.1.1:443", "github.com:443"]


def sh(cmd, cwd, env=None, timeout=900):
    r = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, env=env, timeout=timeout)
    return r.returncode, r.stdout + r.stderr


def read_manifest(root): return yaml.safe_load((pathlib.Path(root) / W.MANIFEST).read_text()) if (pathlib.Path(root) / W.MANIFEST).exists() else {}


def _raw_pack(root):
    """The pack as written, for the task packet of a run refused before the pack was validated (a frozen file edited)."""
    try:
        P = yaml.safe_load((pathlib.Path(root) / W.PACK_FILE).read_text())
        return P if isinstance(P, dict) and isinstance(P.get("pack"), dict) else {}
    except Exception: return {}


def tool_values(P): return {n: os.environ.get(t["env"], t.get("default", "")) for n, t in (P.get("tools") or {}).items()}


def toolchain(P, root, tools):
    def ver(pkg):
        try: return importlib.metadata.version(pkg)
        except Exception: return "not importable"
    tc = {"python": platform.python_version()}
    for name, t in (P.get("toolchain") or {}).items():
        if "python_package" in t: tc[name] = ver(t["python_package"]); continue
        code, o = sh(K.fmt(t["command"], **tools), root)
        if t.get("regex"):
            m = re.search(t["regex"], o); tc[name] = (m.group(t.get("group", 0)).strip() if m else "unknown")
        else: tc[name] = o.strip() if code == 0 else "unavailable"          # v0.9.0: a failing version command is not a version
    return tc


class Ctx:
    """What a check kind may use. `outputs` holds the exported outputs of earlier checks by declared id."""
    def __init__(self, **kw): self.__dict__.update(kw); self.outputs = {}
    def sh(self, cmd, cwd=None): return sh(cmd, cwd or self.root)
    def subst(self, s): return K.fmt(s, python=self.python, pytest=K.fmt(self.pack.get("pytest", ""), python=self.python, root=self.root), root=self.root, **self.tools)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy-from", default=None); ap.add_argument("--candidate", default=None); ap.add_argument("--out", required=True)
    ap.add_argument("--expected-release", default=None); ap.add_argument("--review", default=None); ap.add_argument("--reviewer-key", default=None)
    ap.add_argument("--reuse", default=None, help="a previous run's evidence directory; cacheable checks with unchanged keys are not re-run")
    a = ap.parse_args()
    if a.policy_from:                      # re-exec the PRISTINE gate so the judge's code is not the candidate's copy
        pristine = pathlib.Path(a.policy_from).resolve()
        cmd = [sys.executable, "-I", str(pristine / "gate" / "app_gate.py"), "--candidate", str(ROOT), "--out", a.out] + \
              sum(([f"--{k.replace('_', '-')}", v] for k, v in (("expected_release", a.expected_release), ("review", a.review), ("reviewer_key", a.reviewer_key), ("reuse", a.reuse)) if v), [])
        sys.exit(subprocess.call(cmd))
    candidate = pathlib.Path(a.candidate).resolve() if a.candidate else ROOT
    out = pathlib.Path(a.out).absolute()
    if out.exists(): sys.exit(f"refused: evidence directory {out} exists; use a fresh one")
    if out.resolve().is_relative_to(candidate.resolve()): sys.exit("refused: evidence directory must be outside the candidate workspace")
    judge(candidate, ROOT, out, mode="authoritative" if a.candidate else "local (advisory)", expected_release=a.expected_release,
          review=a.review and pathlib.Path(a.review).absolute(), reviewer_key=a.reviewer_key and pathlib.Path(a.reviewer_key).absolute(),
          reuse=a.reuse and pathlib.Path(a.reuse).absolute())


def judge(candidate, policy_src, out, mode, expected_release, review, reviewer_key, reuse=None):
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    # ---- build the judged workspace: policy (trusted source) + artifact (copied)
    root = W.assemble(candidate, policy_src, out / "artifact")
    import release as REL
    policy_dirs, _ = W.load_pack_policy(root)
    tools = None; P = {}
    claims = {"gate_mode": mode, "policy_source": str(policy_src), "evidence_dir": str(out), "judged_copy": str(root),
              "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "release_digest": None, "authority": "local-unpinned",
              "artifact_digest": W.digest_dir(out / "artifact"), "release_ready": False, "pack": None, "toolchain": {}, "checks": []}
    records = []; statuses = []; evaluator = EV.evaluator_digest(root); prior = None; keys = {}

    def finish():
        claims["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        claims["policy_sha256"] = {d: W.digest_dir(root / d) for d in policy_dirs if (root / d).exists()}
        if (root / W.PACK_FILE).exists(): claims["policy_sha256"][W.PACK_FILE] = W.sha(root / W.PACK_FILE)
        claims["artifact_digest_at_end"] = W.digest_dir(out / "artifact")
        claims["evidence"] = "evidence.json"
        E = EV.write(out, {"format": EV.FORMAT, "pack": claims["pack"], "release_digest": claims["release_digest"], "evaluator_digest": evaluator,
                           "artifact_digest": claims["artifact_digest"], "gate_mode": mode, "authority": claims["authority"],
                           "isolation": (claims.get("isolation") or {}).get("status"), "toolchain": claims["toolchain"],
                           "statuses": {s: claims.get(s) for s in statuses}, "release_ready": claims["release_ready"],
                           "reused_from": str(reuse) if reuse else None, "records": records})
        claims["evidence_digest"] = E["digest"]
        claims["task_packet"] = "task-packet.json"
        (out / "app-claims.json").write_text(json.dumps(claims, indent=2))
        PK_ = P or _raw_pack(root)
        if PK_: PT.write(out, PT.build(claims, records, PK_, mode, candidate, policy_src, out, claims["toolchain"], claims["release_digest"] or ""))
        try: (candidate / "app-claims.json").write_text(json.dumps(claims, indent=2))
        except Exception: pass
        (out / "README.txt").write_text("Evidence applies ONLY to artifact/ (the copy that was judged) and release_digest.\n"
            "app-claims.json reports each status the pack declares separately; release_ready needs every one at its required value plus an\n"
            "authoritative pinned run, an enforced isolation profile and the adapters' conditions (release_ready_missing lists what is absent).\n"
            "evidence.json holds one record per check: method, contract records established, inputs and their digests, toolchain,\n"
            "dependencies and the key that binds them; statement.intoto.json binds those records to the artifact digest.\n"
            "The judge imported no candidate code; the candidate ran as a separate process (see isolation for its identity and what it could reach).\n"
            "Unavailable tools are blockers, never passes. Prior evidence is reused only where a record says reused_from.\n")
        import shutil; shutil.rmtree(root, ignore_errors=True)
        print("app-claims.json: " + " | ".join(f"{s}={claims.get(s)}" for s in statuses) + f" | release_ready={claims['release_ready']} | gate_mode={mode} | evidence={out}")
        if PK_: print(f"task packet: {out / 'TASK.md'} (task-packet.json: first failure, its category and contract records, what to edit, how to rerun)")

    def refuse_exit(spec=None):
        if statuses:       # the status the failing check contributes to is refused; evaluator checks refuse refusal_status
            rs = (spec or {}).get("status") if (spec or {}).get("status") in statuses else P["refusal_status"]; claims[rs] = claims.get(rs) or "refused"
            for s in statuses: claims[s] = claims.get(s) or "not evaluated"
        finish(); sys.exit(1)

    def check(area, name, ok, claim, why=None, blocking=True, spec=None, res=None, reused=None, exc=None):
        cat = None if ok else PT.classify(name, spec["kind"] if spec else "evaluator", spec, res.category if res else None, why, claims.get("toolchain") or {}, exc)
        claims["checks"].append({"area": area, "check": name, "result": "pass" if ok else "fail", "claim": claim, **({"why": why} if (why and not ok) else {}),
                                 **({"id": spec["id"]} if spec else {}), **({"reused_from": reused} if reused else {}), **({"category": cat[0]} if cat else {})})
        print((f"[ok] {area} · {name}: {claim}" + (" (reused)" if reused else "")) if ok else f"[REFUSED] {area} · {name}: {why or claim}")
        rec = {"id": spec["id"] if spec else f"evaluator.{re.sub(r'[^a-z]+', '-', name.lower()).strip('-')}", "check": name, "area": area,
               "result": "pass" if ok else "fail", "claim": claim, **({"why": why[-3000:]} if (why and not ok) else {}), "blocking": blocking,
               **({"category": cat[0], "category_basis": cat[1]} if cat else {}), **({"failing_contracts": res.failing_contracts} if (res and res.failing_contracts) else {})}
        if spec:
            k = keys.get(spec["id"], {})
            rec.update({"kind": spec["kind"], "method": spec["method"], "contributes_to": spec.get("status"), "establishes": spec.get("establishes", []),
                        "assumptions": spec.get("assumptions"), "depends_on": k.get("deps", []), "key": k.get("key"), "own_key": k.get("own_key"),
                        "inputs": spec.get("inputs", []), "files": k.get("files", {}), "tools": k.get("tools", {}),
                        "outcome": res.outcome if res else None, "outputs": res.outputs if res else {}, **({"reused_from": reused} if reused else {})})
        else: rec.update({"kind": "evaluator", "method": "policy"})
        records.append(rec)
        if not ok and blocking: refuse_exit(spec)

    # ---------------- release integrity, pin, pack, manifest ----------------
    frozen = {}
    for line in (root / "gate/frozen.sha256").read_text().splitlines():
        hh, p = line.split("  ", 1); frozen[p] = hh
    changed = [p for p, hh in frozen.items() if not (root / p).exists() or W.sha(root / p) != hh]
    extra = [str(p.relative_to(root)) for d in policy_dirs if (root / d).exists() for p in (root / d).rglob("*")
             if p.is_file() and not W.is_os_metadata(p) and str(p.relative_to(root)) not in frozen and p.name not in ("claims.json", "frozen.sha256") and not (W.CACHE_DIRS & set(p.parts))]
    check("policy", "frozen files intact", not changed and not extra, f"{len(frozen)} frozen files intact; nothing added under {policy_dirs} (OS metadata files ignored)", f"edited/missing: {changed}; unlisted: {extra}")
    rd = REL.release_digest(root); claims["release_digest"] = rd
    seal = json.loads((root / W.SEAL).read_text()) if (root / W.SEAL).exists() else {}
    check("policy", "release seal", seal.get("release_digest") == rd, f"platform release {rd[:16]} matches release.seal.json", f"seal {str(seal.get('release_digest'))[:16]} vs disk {rd[:16]}")
    if expected_release:
        check("policy", "external release pin", expected_release == rd, f"platform matches the externally pinned release {expected_release[:16]}", f"pinned {expected_release[:16]} but this platform is {rd[:16]}")
        claims["authority"] = "externally-pinned-release"
    try: P = PK.load(root); err = None
    except Exception as e: err = f"{type(e).__name__}: {e}"
    if err: check("policy", "pack well-formed", False, "pack.yaml", err)
    claims["pack"] = {k: P["pack"].get(k) for k in ("id", "version", "contract_version")}
    statuses = list(P["statuses"])
    for s in statuses: claims[s] = None
    tools = tool_values(P); claims["toolchain"] = toolchain(P, root, tools)
    M = read_manifest(root) or {}
    bad = sorted(set(M) - set(P["candidate"]["manifest_allowlist"]))
    check("policy", "manifest allowlisted", not bad, f"manifest keys within {P['candidate']['manifest_allowlist']}", f"disallowed keys: {bad}")
    inc = M.get("include") or []
    if inc:
        problems = W.include_problems(inc, policy_dirs, candidate)
        check("policy", "included paths", not problems, f"existing project: {inc} judged as part of the artifact (only through the pack's entrypoints)", "; ".join(problems))
    claims["coverage"] = {"subsystem": M.get("subsystem") or M.get("name"), "owned_dirs": P["candidate"]["owned_dirs"], "included": inc,
                          "judged_paths": sorted({p.relative_to(out / "artifact").parts[0] for p in (out / "artifact").rglob("*") if p.is_file()}),
                          "statement": f"evidence covers only the behaviour of {P['pack']['id']}'s contract records, as exposed through the candidate's entrypoints, "
                                       f"for the judged paths; " + ("included code is judged only through those entrypoints, and " if inc else "")
                                       + "nothing else in the candidate's repository is covered"}
    pre, main_checks = PK.expand(P, root, M, "preflight"), PK.expand(P, root, M); concrete = pre + main_checks
    keys.update(EV.keys(concrete, root, claims["toolchain"], evaluator))       # before anything runs: outputs never change a key
    if reuse:
        try: prior = EV.load(reuse)
        except Exception as e: print(f"[note] --reuse {reuse} not used: {e}")
    ctx = Ctx(root=root, out=out, pack=P, manifest=M, tools=tools, python=f"{sys.executable} -I", mode=mode, review=review, reviewer_key=reviewer_key,
              artifact_digest=claims["artifact_digest"], release_digest=rd, isolation_enforced=False)
    results = {}

    def run(c):
        r, why_not = EV.reusable(prior, c, keys[c["id"]]["key"], rd, evaluator)
        if r:
            res = K.Result(True, r["claim"], outputs=r.get("outputs", {}), outcome=r.get("outcome"))
            reused = r.get("reused_from") or {"evidence": str(reuse), "evidence_digest": prior["digest"], "key": r["key"]}
        else:
            reused = None
            try: res = K.RUN[c["kind"]](c, ctx); exc = None
            except subprocess.TimeoutExpired as e:
                res = K.Result(False, c.get("claim", c["name"]), f"timed out after {e.timeout} s: {' '.join(map(str, e.cmd)) if isinstance(e.cmd, list) else e.cmd}"[:600]); exc = "a timeout (if the candidate can hang, the cause may be the candidate's)"
            except Exception as e:
                res = K.Result(False, c.get("claim", c["name"]), f"evaluator error: {type(e).__name__}: {e}"[:600]); exc = f"{type(e).__name__}"
            if exc: res.claim = K.fmt(res.claim, count="?", item=c.get("item", ""))
        for name, v in res.outputs.items():
            if name not in ("reviewer_context", "reviewer_flags"): claims[name] = v
        ctx.outputs.setdefault(c["group"], {}).update(res.outputs)
        if res.detail is not None and c.get("claims_key"): claims[c["claims_key"]] = res.detail
        results[c["id"]] = res
        check(c["area"], c["name"], res.ok, res.claim, res.why, blocking=c.get("blocking", True), spec=c, res=res, reused=reused, exc=None if reused else exc)

    for c in pre: run(c)
    check("policy", "artifact", True, f"deployment artifact copied and digested ({claims['artifact_digest'][:16]}); judged in a fresh copy, never the live checkout")
    claims["app"] = M.get("name")

    # ---------------- isolation: observed under the candidate's identity before any candidate code runs ----------------
    ident = SB.candidate_identity()
    if ident: root.chmod(0o755)                         # the judged copy is readable by the candidate, owned (and writable) by the judge only
    probe = [sys.executable, "-I", str(root / "gate/isolation/probe.py"), "--evidence", str(out), "--policy", str(root)] + \
            [x for d in policy_dirs for x in ("--policy-dir", d)] + [x for hp in PROBE_HOSTS for x in ("--host", hp)] + \
            [x for p_ in os.environ.get("SEED_PROTECTED_PATHS", "").split(":") if p_ for x in ("--secret", p_)]
    try:
        code, o = SB.run_as_candidate(probe, cwd=root); seen = json.loads(o.strip().splitlines()[-1])
    except Exception as e:
        seen = {"checks": {"probe ran": f"reachable (probe failed: {type(e).__name__}: {str(e)[:120]})"}}
    reachable = sorted(k for k, v in seen.get("checks", {}).items() if not v.startswith("denied"))
    enforced = bool(ident) and not reachable; ctx.isolation_enforced = enforced
    claims["isolation"] = {"status": "enforced" if enforced else "not enforced",
                           "profile": os.environ.get("SEED_ISOLATION_PROFILE") or ("candidate uid " + str(ident[0]) if ident else "none (candidate runs as the judge's user)"),
                           "candidate_identity": {"uid": ident[0], "gid": ident[1]} if ident else None, "resource_limits": SB.LIMITS if ident else {k: v for k, v in SB.LIMITS.items() if k != "RLIMIT_NPROC"},
                           "observed": seen, "reachable_from_candidate": reachable,
                           "scope": "observed by a frozen probe run under the candidate's identity: evidence dir, policy dirs, gate code, protected paths, outbound network; "
                                    "the candidate has no build or dependency-install step in this release (it runs on the judge's pinned runtimes: "
                                    + ", ".join(P["candidate"].get("runtimes") or ["python"]) + ")"}
    check("policy", "isolation", True, f"candidate isolation {claims['isolation']['status']}" + (f": reachable from the candidate: {reachable}" if reachable else f" ({claims['isolation']['profile']})")
          + ("" if enforced else " — advisory run; release_ready requires an enforced profile (gate/isolation/README.md)"), blocking=False)

    # ---------------- the pack's checks, in order ----------------
    for c in main_checks: run(c)

    stable = W.digest_dir(out / "artifact") == claims["artifact_digest"]
    check("policy", "judged copy unchanged", stable, "the artifact copy that was judged is byte-identical at the end (an observation at two points, not a monitor)", "artifact copy changed during judging", blocking=False)

    # ---------------- statuses and release readiness ----------------
    def ready(s, v):
        cond = P["statuses"][s]["ready"]
        return isinstance(v, str) and (v.startswith(cond["startswith"]) if "startswith" in cond else v == cond["equals"])
    for s, d in P["statuses"].items():
        if d["rule"] == "all_pass":
            mine = [r for r in records if r.get("contributes_to") == s]
            claims[s] = d["passed"] if all(r["result"] == "pass" for r in mine) else "failed"
        else:
            res = next((r for cid, r in results.items() if cid == d["check"] or cid.startswith(d["check"] + "/")), None)
            claims[s] = res.outcome if res else "not evaluated"
    conds = [(s, ready(s, claims[s]), P["statuses"][s]["ready"].get("equals") or P["statuses"][s]["ready"].get("startswith")) for s in statuses]
    conds += [("gate_mode", mode == "authoritative", "authoritative"), ("authority", claims["authority"] == "externally-pinned-release", "externally-pinned-release"),
              ("isolation", enforced, "enforced")]
    conds += [x for r in results.values() for x in r.release_conditions]
    claims["release_ready"] = bool(stable and all(ok for _, ok, _ in conds))
    claims["release_ready_requires"] = {n: req for n, _, req in conds}
    claims["release_ready_missing"] = [n for n, ok, _ in conds if not ok] + ([] if stable else ["judged copy unchanged"])
    finish()
    sys.exit(0 if (ready(P["completion_status"], claims[P["completion_status"]]) and stable) else (1 if not stable else 2))


if __name__ == "__main__":
    main()
