#!/usr/bin/env python3
"""
gate/app_gate.py — the judge. FROZEN.

    python3 gate/app_gate.py --out EVIDENCE [--expected-release DIGEST] [--review att.json --reviewer-key pub.pem]
    python3 <pristine>/gate/app_gate.py --candidate DIR --out EVIDENCE --expected-release DIGEST ...
        authoritative: the judge's own code AND the policy come from the pristine release; DIR is only read for its artifact
    python3 gate/app_gate.py --policy-from DIR ...    same thing invoked from the checkout: re-executes DIR's gate with --candidate

How judging works, and why:
  * The judge never imports candidate Python. The candidate's service runs as a separate process started from the
    fixed entrypoint (service/run.py) with a scrubbed environment and -I; the judge talks to it only over HTTP through
    the frozen client, drives the browser itself, and writes all evidence itself. Candidate stdout is never evidence.
  * The judge works on a COPY: a fresh workspace = policy dirs (from this checkout, or from --policy-from) + the
    deployment artifact (the agent-owned files, copied). The artifact digest covers every file in that copy; nothing
    is excluded by basename. The live checkout is not touched.
  * pytest runs with --noconftest -c /dev/null, cwd in the judged copy, under -I.
  * Isolation is observed, not declared: a frozen probe runs under the candidate's identity before any candidate code
    and reports what that identity can reach (evidence, policy, gate code, protected paths, network). Without a
    separate identity (SEED_CANDIDATE_UID, see obligations/isolation/) the run is advisory and says so.
  * Three statuses are reported separately; release_ready requires all three plus an authoritative pinned run, an
    enforced isolation profile and a contained browser. Exit 0 iff assurance and delivery passed; 2 if delivery
    incomplete; 1 on refusal.
"""
import argparse, hashlib, importlib.metadata, json, os, platform, re, shutil, subprocess, sys, tempfile, time, pathlib
import yaml

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
POLICY_DIRS = ["kernel", "obligations", "gate", "profiles"]
EVALUATOR_PATHS = {"app-claims.json", "release.seal.json", ".tools", ".venv", "evidence", ".git", "__pycache__", ".hypothesis", ".pytest_cache", "states"}
OS_METADATA = {".DS_Store", "Thumbs.db", "desktop.ini"}          # written by file browsers, not by anyone; ignored everywhere
def is_os_metadata(p): return p.name in OS_METADATA or p.name.startswith("._")


def sh(cmd, cwd, env=None, timeout=900):
    r = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, env=env, timeout=timeout)
    return r.returncode, r.stdout + r.stderr


def sha(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def digest_dir(d):
    """Digest of EVERY file under d, by relative path. No exclusions."""
    h = hashlib.sha256()
    for p in sorted(pathlib.Path(d).rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(d)).encode()); h.update(sha(p).encode())
    return h.hexdigest()


def copy_artifact(src, dst, owned_dirs):
    """The deployment artifact: app.manifest.yaml + every file under the agent-owned dirs, excluding only evaluator-owned paths."""
    dst.mkdir(parents=True)
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if not p.is_file() or is_os_metadata(p) or set(rel.parts) & EVALUATOR_PATHS or rel.parts[0] in POLICY_DIRS: continue
        if rel.parts[0] in owned_dirs or str(rel) == "app.manifest.yaml":
            (dst / rel).parent.mkdir(parents=True, exist_ok=True); shutil.copy2(p, dst / rel)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy-from", default=None); ap.add_argument("--candidate", default=None); ap.add_argument("--out", required=True)
    ap.add_argument("--expected-release", default=None); ap.add_argument("--review", default=None); ap.add_argument("--reviewer-key", default=None)
    a = ap.parse_args()
    if a.policy_from:                      # re-exec the PRISTINE gate so the judge's code is not the candidate's copy
        pristine = pathlib.Path(a.policy_from).resolve()
        cmd = [sys.executable, "-I", str(pristine / "gate" / "app_gate.py"), "--candidate", str(ROOT), "--out", a.out] + \
              (["--expected-release", a.expected_release] if a.expected_release else []) + (["--review", a.review] if a.review else []) + (["--reviewer-key", a.reviewer_key] if a.reviewer_key else [])
        sys.exit(subprocess.call(cmd))
    candidate = pathlib.Path(a.candidate).resolve() if a.candidate else ROOT
    out = pathlib.Path(a.out).absolute()
    if out.exists(): sys.exit(f"refused: evidence directory {out} exists; use a fresh one")
    if out.resolve().is_relative_to(candidate.resolve()): sys.exit("refused: evidence directory must be outside the candidate workspace")
    judge(candidate, ROOT, out, mode="authoritative" if a.candidate else "local (advisory)",
          expected_release=a.expected_release, review=a.review and pathlib.Path(a.review).absolute(), reviewer_key=a.reviewer_key and pathlib.Path(a.reviewer_key).absolute())


def judge(candidate, policy_src, out, mode, expected_release, review, reviewer_key):
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    # ---- build the judged workspace: policy (trusted source) + artifact (copied)
    ws = pathlib.Path(tempfile.mkdtemp(prefix="judged-")); POL_TMP = yaml.safe_load((policy_src / "gate" / "policy.yaml").read_text())
    for d in POLICY_DIRS:
        if (policy_src / d).exists(): shutil.copytree(policy_src / d, ws / d, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".hypothesis", ".DS_Store", "Thumbs.db", "desktop.ini", "._*"))
    if (policy_src / "release.seal.json").exists(): shutil.copy(policy_src / "release.seal.json", ws / "release.seal.json")
    copy_artifact(candidate, out / "artifact", POL_TMP["candidate"]["owned_dirs"])
    shutil.copytree(out / "artifact", ws, dirs_exist_ok=True)
    root = ws
    sys.path.insert(0, str(root / "gate")); import release as REL, review as REV
    POL = yaml.safe_load((root / "gate" / "policy.yaml").read_text())
    DAFNY = os.environ.get("DAFNY", "dafny"); TLA = os.environ.get("TLA2TOOLS", "tla2tools.jar"); PY = f"{sys.executable} -I"
    PT = f"{PY} -m pytest {POL['pytest_args']} --rootdir={root}"
    def ver(pkg):
        try: return importlib.metadata.version(pkg)
        except Exception:
            try: return getattr(__import__(pkg), "__version__", "present (version unknown)")
            except Exception: return "not importable"
    claims = {"gate_mode": mode, "policy_source": str(policy_src), "evidence_dir": str(out), "judged_copy": str(root),
              "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "release_digest": None, "authority": "local-unpinned",
              "artifact_digest": digest_dir(out / "artifact"), "release_ready": False,
              "toolchain": {"dafny": sh(f"{DAFNY} --version", root)[1].strip(), "python": platform.python_version(), "hypothesis": ver("hypothesis"),
                            "jsonschema": ver("jsonschema"), "playwright": ver("playwright"), "cryptography": ver("cryptography")},
              "checks": [], "behavioral_assurance": None, "application_delivery": None, "human_approval": None}
    tlc_out = sh(f"java -cp {TLA} tlc2.TLC -h", root)[1] + sh("java -version", root)[1]
    m = re.search(r"TLC2 Version [^\n]*|TLC - [^\n]*Version [^\n]*", tlc_out); claims["toolchain"]["tlc"] = m.group(0).strip() if m else "unknown"
    jv = re.search(r'version "([^"]+)"', tlc_out); claims["toolchain"]["java"] = jv.group(1) if jv else "unknown"

    def finish():
        claims["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        claims["policy_sha256"] = {d: digest_dir(root / d) for d in POLICY_DIRS if (root / d).exists()}
        claims["artifact_digest_at_end"] = digest_dir(out / "artifact")
        (out / "app-claims.json").write_text(json.dumps(claims, indent=2))
        try: shutil.copy(out / "app-claims.json", candidate / "app-claims.json")
        except Exception: pass
        (out / "README.txt").write_text("Evidence applies ONLY to artifact/ (the copy that was judged) and release_digest.\n"
            "app-claims.json separates behavioral_assurance, application_delivery and human_approval; release_ready needs all three plus an\n"
            "authoritative pinned run, an enforced isolation profile and a contained browser (release_ready_missing lists what is absent).\n"
            "The judge imported no candidate code; the candidate ran as a separate process (see isolation for its identity and what it could reach).\n"
            "Unavailable tools are blockers, never passes. No prior evidence is reused.\n")
        shutil.rmtree(root, ignore_errors=True)
        print(f"app-claims.json: behavioral_assurance={claims['behavioral_assurance']} | application_delivery={claims['application_delivery']} | human_approval={claims['human_approval']} | release_ready={claims['release_ready']} | gate_mode={mode} | evidence={out}")

    def check(area, name, ok, claim, why=None, blocking=True):
        claims["checks"].append({"area": area, "check": name, "result": "pass" if ok else "fail", "claim": claim, **({"why": why} if (why and not ok) else {})})
        print(f"[ok] {area} · {name}: {claim}" if ok else f"[REFUSED] {area} · {name}: {why or claim}")
        if not ok and blocking:
            claims["behavioral_assurance"] = claims["behavioral_assurance"] or "refused"
            claims["application_delivery"] = claims["application_delivery"] or "not evaluated"
            claims["human_approval"] = claims["human_approval"] or "not evaluated"
            finish(); sys.exit(1)

    # ---------------- policy integrity, pin, manifest ----------------
    frozen = {}
    for line in (root / "gate/frozen.sha256").read_text().splitlines():
        h, p = line.split("  ", 1); frozen[p] = h
    changed = [p for p, h in frozen.items() if not (root / p).exists() or sha(root / p) != h]
    extra = [str(p.relative_to(root)) for d in POLICY_DIRS if (root / d).exists() for p in (root / d).rglob("*")
             if p.is_file() and not is_os_metadata(p) and str(p.relative_to(root)) not in frozen and p.name not in ("claims.json", "frozen.sha256") and not ({"__pycache__", ".pytest_cache", ".hypothesis"} & set(p.parts))]
    check("policy", "frozen files intact", not changed and not extra, f"{len(frozen)} frozen files intact; nothing added under {POLICY_DIRS} (OS metadata files ignored)", f"edited/missing: {changed}; unlisted: {extra}")
    rd = REL.release_digest(root); claims["release_digest"] = rd
    seal = json.loads((root / "release.seal.json").read_text()) if (root / "release.seal.json").exists() else {}
    check("policy", "release seal", seal.get("release_digest") == rd, f"platform release {rd[:16]} matches release.seal.json", f"seal {str(seal.get('release_digest'))[:16]} vs disk {rd[:16]}")
    if expected_release:
        check("policy", "external release pin", expected_release == rd, f"platform matches the externally pinned release {expected_release[:16]}", f"pinned {expected_release[:16]} but this platform is {rd[:16]}")
        claims["authority"] = "externally-pinned-release"
    M = yaml.safe_load((root / "app.manifest.yaml").read_text()) or {}
    bad = sorted(set(M) - set(POL["manifest_allowlist"]))
    check("policy", "manifest allowlisted", not bad, f"manifest keys within {POL['manifest_allowlist']}", f"disallowed keys: {bad}")
    profile = M.get("profile") or "sqlite"
    check("policy", "integration profile", profile in ("sqlite", "custom"), f"profile = {profile}" + (" (shipped; in-process tests apply)" if profile == "sqlite" else " (custom; judged only through the service)"), "profile must be sqlite or custom")
    check("policy", "artifact", True, f"deployment artifact copied and digested ({claims['artifact_digest'][:16]}); judged in a fresh copy, never the live checkout")
    claims["app"] = M.get("name")

    # ---------------- isolation: observed under the candidate's identity before any candidate code runs ----------------
    sys.path.insert(0, str(root)); from obligations.service import supervisor as SUP
    ident = SUP.candidate_identity()
    if ident: root.chmod(0o755)                         # the judged copy is readable by the candidate, owned (and writable) by the judge only
    probe = [sys.executable, "-I", str(root / "obligations/isolation/probe.py"), "--evidence", str(out), "--policy", str(root),
             "--host", "1.1.1.1:443", "--host", "github.com:443"] + [x for p_ in os.environ.get("SEED_PROTECTED_PATHS", "").split(":") if p_ for x in ("--secret", p_)]
    try:
        code, o = SUP.run_as_candidate(probe, cwd=root); seen = json.loads(o.strip().splitlines()[-1])
    except Exception as e:
        seen = {"checks": {"probe ran": f"reachable (probe failed: {type(e).__name__}: {str(e)[:120]})"}}
    reachable = sorted(k for k, v in seen.get("checks", {}).items() if not v.startswith("denied"))
    enforced = bool(ident) and not reachable
    claims["isolation"] = {"status": "enforced" if enforced else "not enforced",
                           "profile": os.environ.get("SEED_ISOLATION_PROFILE") or ("candidate uid " + str(ident[0]) if ident else "none (candidate runs as the judge's user)"),
                           "candidate_identity": {"uid": ident[0], "gid": ident[1]} if ident else None, "resource_limits": SUP.LIMITS if ident else {k: v for k, v in SUP.LIMITS.items() if k != "RLIMIT_NPROC"},
                           "observed": seen, "reachable_from_candidate": reachable,
                           "scope": "observed by a frozen probe run under the candidate's identity: evidence dir, policy dirs, gate code, protected paths, outbound network; "
                                    "the candidate has no build or dependency-install step in this release (it runs on the judge's interpreter and packages)"}
    check("policy", "isolation", True, f"candidate isolation {claims['isolation']['status']}" + (f": reachable from the candidate: {reachable}" if reachable else f" ({claims['isolation']['profile']})")
          + ("" if enforced else " — advisory run; release_ready requires an enforced profile (obligations/isolation/README.md)"), blocking=False)

    # ---------------- ring 0 ----------------
    k = POL["kernel"]
    code, o = sh(f"DAFNY={DAFNY} {PY} {k['gate']} {k['impl']} --out {k['claims']}", root)
    check("ring0", "kernel gate", code == 0, "proven core: include closure verified, translation reproduced fail-closed, TCB scan, adequacy, traces", o[-1500:])
    try: claims["ring0_scope"] = json.loads((root / k["claims"]).read_text()).get("scope")
    except Exception: pass

    # ---------------- ring 1: design ----------------
    r1 = POL["rings"][1]; dm = root / r1["design_module"]
    check("ring1", "design module present", dm.exists(), r1["design_module"], f"{r1['design_module']} not found: write a TLA+ design that EXTENDS CoreActions, declares VARIABLE responses, defines Spec")
    src = dm.read_text()
    check("ring1", "design extends obligations", bool(re.search(r"EXTENDS[^\n]*\bCoreActions\b", src)), "EXTENDS CoreActions", "design must EXTENDS CoreActions")
    illegal = [l.strip() for l in src.splitlines() if re.search(r"\b(status|held|posted)'\s*=", l)]
    check("ring1", "core state only via core actions", not illegal, "status/held/posted change only through CoreDecide/CoreReplay/CoreRelease/CoreCapture", f"direct assignment: {illegal}")
    redefined = [n for n in ("Idempotent", "Consistent", "CovRetry", "IdempotentResp", "ConsistentResp", "RetryCov", "DecideCorrect", "INV1", "P2", "P3", "P4", "PostedExact") if re.search(rf"^\s*{n}\s*==", src, re.M)]
    declares = bool(re.search(r"VARIABLES?[^\n=]*\bresponses\b", src))
    check("ring1", "design interface", declares and not redefined, "declares VARIABLE responses; does not redefine any checked predicate (they are bound in the frozen MC.tla)", f"responses declared={declares}; redefined={redefined}")
    od = root / r1["obligations_dir"]; work = pathlib.Path(tempfile.mkdtemp(dir=root / "design"))
    def tlc(cfg, module): return sh(f"java -XX:+UseParallelGC -cp {TLA} tlc2.TLC -nowarning -workers 2 -deadlock -config {cfg} {module}", work)
    def tlc_why(o_):
        mm = re.search(r"Error: (Invariant \w+ is violated|Action property \w+ is violated|Temporal properties were violated)", o_)
        i = o_.find("The behavior up to this point is:"); return (mm.group(1) if mm else "TLC did not report success") + ("\n" + o_[i:i + 1800] if i >= 0 else "\n" + o_[-800:])
    try:
        for f in od.iterdir():
            if f.suffix in (".tla", ".cfg", ".list"): shutil.copy(f, work)
        shutil.copy(dm, work / "Design.tla")
        code, o = tlc(r1["required_cfg"], "MC.tla")
        check("ring1", "design model (safety)", "No error has been found" in o, "INV1 (composition), P2, P3, P4, PostedExact, DecideCorrect, Idempotent, Consistent hold over the configured model with both kernels interleaving (predicates bound by the frozen MC.tla)", tlc_why(o))
        base_cfg = (work / r1["required_cfg"]).read_text().split("SPECIFICATION")[0]
        for cov in (work / r1["coverage_list"]).read_text().split():
            (work / f"cov_{cov}.cfg").write_text(base_cfg + f"SPECIFICATION Spec\nINVARIANTS {cov}\n")
            code, o = tlc(f"cov_{cov}.cfg", "MC.tla")
            check("ring1", f"design coverage ({cov})", f"Invariant {cov} is violated" in o, f"the design reaches the behaviour {cov} guards", f"{cov} never reached: the design does not model this behaviour")
        b = r1["broken"]; code, o = tlc(b["cfg"], b["module"])
        check("ring1", "obligations reject the known-bad design", f"Invariant {b['expect']} is violated" in o, f"receipt-time design violates {b['expect']} under the same obligations", o[-800:])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    # ---------------- ring 2 artifacts first: the service reads gen/out at startup ----------------
    r2 = POL["rings"][2]
    missing = [g for g in r2["generated"] if not (root / g).exists()]
    check("ring2", "generated artifacts present", not missing, "gen/out present", f"{missing} missing: run python3 {r2['generator']}")
    before = {g: sha(root / g) for g in r2["generated"]}
    with tempfile.TemporaryDirectory() as td:
        for g in r2["generated"]: shutil.copy(root / g, td)
        sh(f"{PY} {r2['generator']}", root)
        drift = [g for g in r2["generated"] if sha(root / g) != before[g]]
        for g in r2["generated"]: shutil.copy(pathlib.Path(td) / pathlib.Path(g).name, root / g)
    check("ring2", "generated artifacts current", not drift, "openapi, event schema and monitor equal the generator's output", f"hand-edited: {drift}")
    # ---------------- ring 1: integration, black-box through the service ----------------
    ep = root / POL["candidate"]["entrypoint"]
    check("ring1", "service entrypoint", ep.exists(), f"{POL['candidate']['entrypoint']} present (the supervisor starts it as a separate process)", f"{POL['candidate']['entrypoint']} missing")
    if profile == "sqlite":
        code, o = sh(f"{PT} {r1['sqlite_profile_tests']}", root); n = re.search(r"(\d+) passed", o)
        check("ring1", "shipped profile tests", code == 0, f"sqlite profile (frozen) in-process tests pass ({n.group(1) if n else '?'})", o[-2500:])
    code, o = sh(f"{PT} {r1['lifecycle']}", root); n = re.search(r"(\d+) passed", o)
    check("ring1", "lifecycle harness (black-box)", code == 0, f"through the running service: duplicate create, idempotent replay and conflicts, crash (SIGKILL) + restart + retry, restart durability, event contract (op_id, chain, state_after, one commit per op), concurrency with readers ({n.group(1) if n else '?'} checks)", o[-3000:])
    for cmd in M.get("extra_tests") or []:
        code, o = sh(cmd, root); check("ring1", f"extra test: {cmd}", code == 0, "supplementary; reported only", o[-1200:], blocking=False)

    # ---------------- ring 2 (continued) ----------------
    code, o = sh(f"{PT} {r2['monitor_tests']}", root)
    check("ring2", "monitor negative suite", code == 0, "generated monitor detects each named violation (rehashed mutants), op lifecycle, watermark; silent on the good stream", o[-1500:])
    code, o = sh(f"{PT} {r2['harness']}", root); n = re.search(r"(\d+) passed", o)
    check("ring2", "boundary harness (black-box)", code == 0, f"API not falsified: JSON-Schema-valid requests/responses/events; invalid and malformed inputs rejected without effect; conflicts rejected; agrees with the proven core under bursts; idempotent; monitor silent; both branches exercised ({n.group(1) if n else '?'} checks)", o[-3000:])
    claims["behavioral_assurance"] = ("passed; scoped: ring0 proven under kernel/tcb.yaml; ring1 design model-checked within configured bounds and service not falsified by the frozen black-box lifecycle harness; "
                                      "ring2 not falsified by the frozen boundary harness; conformance of the implementation to the design model is by test only")

    # ---------------- ring 3: delivery (browser, in the judge's process) ----------------
    r3 = POL["rings"][3]; D = yaml.safe_load((root / r3["delivery"]).read_text())
    code, o = sh(f"{PY} {r3['lint']}", root); dl_fail = []; lint = {"evaluations": {}, "flags": []}
    if code != 0: dl_fail.append(o.strip())
    else:
        try: lint = json.loads(o.strip().splitlines()[-1])
        except Exception: dl_fail.append("lint produced no summary")
    browser = {"status": "unavailable", "detail": "lint failed; browser not run"}
    if not dl_fail:
        sys.path.insert(0, str(root / "obligations" / "app")); sys.path.insert(0, str(root))
        import browser_workflows as bw; bw.ROOT = root
        try: browser = bw.run(out / "browser")
        except Exception as e: browser = {"status": "failed", "detail": f"{type(e).__name__}: {e}"}
    if browser["status"] == "unavailable": dl_fail.append("browser workflows unavailable: " + browser.get("detail", "") + " (a blocker, not a pass; see SEED_CHROMIUM)")
    elif browser["status"] != "passed":
        failed = [(r["viewport"], s_["workflow"], s_["evidence"][:80]) for r in browser.get("runs", []) for s_ in r["steps"] if not s_["ok"]]
        dl_fail.append(f"browser workflows failed: {failed[:4] or browser.get('detail')}")
    results = {}
    for r in browser.get("runs", []):
        for s_ in r["steps"]:
            results.setdefault(s_["workflow"], {"ok": True, "evidence": []}); results[s_["workflow"]]["ok"] &= s_["ok"]; results[s_["workflow"]]["evidence"].append(f"{r['viewport']}: {s_['evidence']}")
    for i in browser.get("interactions", []):
        results.setdefault(i["obligation"], {"ok": True, "evidence": []}); results[i["obligation"]]["ok"] &= i["ok"]; results[i["obligation"]]["evidence"].append(i["evidence"])
    if browser["status"] == "failed":
        dl_fail.extend(f"interaction {i['obligation']} failed: {i['evidence'][:160]}" for i in browser.get("interactions", []) if not i["ok"])
    for w in D["required_workflows"] + D.get("required_interactions", []):
        r = results.get(w["id"])
        if browser["status"] == "passed" and not (r and r.get("ok")): dl_fail.append(f"{w['id']} not demonstrated in the browser")
    claims["application_delivery"] = "passed" if not dl_fail else ("failed" if browser["status"] == "failed" else "incomplete")
    claims["delivery_detail"] = {"workflows": results, "browser": {k_: browser.get(k_) for k_ in ("status", "browser_sandbox", "browser_user", "chromium_version", "detail")}, "problems": dl_fail}
    check("ring3", "application delivery", not dl_fail, f"real-browser workflows {[w['id'] for w in D['required_workflows']]} + replay display passed at {[r['viewport'] for r in browser.get('runs', [])]}; interaction obligations {[i['id'] for i in D.get('required_interactions', [])]} passed under injected response faults (sandboxed={browser.get('browser_sandbox')}, browser user={browser.get('browser_user')}); SPEC structurally complete (lint is structural, not semantic)", " | ".join(dl_fail), blocking=False)

    # ---------------- ring 3: human approval (attestation only) ----------------
    flags = lint.get("flags", [])
    status, detail = REV.verify(review, reviewer_key, artifact_digest=claims["artifact_digest"], release_digest=claims["release_digest"], required_ids=[e["id"] for e in D["required_evaluations"]])
    claims["human_approval"] = status; claims["human_approval_detail"] = {"attestation": detail, "spec_table_informational": lint.get("evaluations", {}), "semantic_flags_for_reviewers": flags}
    check("ring3", "human approval", True, f"{status} ({detail.get('reason') or detail.get('reviewer')})" + (f"; {len(flags)} wording flag(s) for reviewers" if flags else ""), blocking=False)

    stable = digest_dir(out / "artifact") == claims["artifact_digest"]
    check("policy", "judged copy unchanged", stable, "the artifact copy that was judged is byte-identical at the end (an observation at two points, not a monitor)", "artifact copy changed during judging", blocking=False)
    sandboxed = browser.get("browser_sandbox") is True
    isolated = claims["isolation"]["status"] == "enforced"
    contained = sandboxed or (isolated and browser.get("browser_user") not in (None, "judge"))   # Chromium's sandbox, or a separate unprivileged user inside the enforced profile
    claims["release_ready"] = bool(stable and claims["behavioral_assurance"].startswith("passed") and claims["application_delivery"] == "passed" and mode == "authoritative" and claims["authority"] == "externally-pinned-release" and contained and isolated and status == "approved")
    claims["release_ready_requires"] = {"behavioral_assurance": "passed", "application_delivery": "passed", "human_approval": "approved", "gate_mode": "authoritative", "authority": "externally-pinned-release",
                                        "isolation": "enforced", "browser": "Chromium sandbox, or a separate unprivileged browser user under the enforced isolation profile"}
    claims["release_ready_missing"] = [k for k, ok in (("behavioral_assurance", claims["behavioral_assurance"].startswith("passed")), ("application_delivery", claims["application_delivery"] == "passed"),
                                       ("human_approval", status == "approved"), ("gate_mode", mode == "authoritative"), ("authority", claims["authority"] == "externally-pinned-release"),
                                       ("isolation", isolated), ("browser", contained), ("judged copy unchanged", stable)) if not ok]
    finish(); sys.exit(0 if (claims["application_delivery"] == "passed" and stable) else (1 if not stable else 2))


if __name__ == "__main__":
    main()
