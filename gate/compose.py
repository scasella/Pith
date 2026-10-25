#!/usr/bin/env python3
"""
gate/compose.py — composition contracts. FROZEN. Domain-free.

A composition contract (`composition.yaml`, format pith.composition/v1) names the components of a workflow, the state
each one owns, the effects through which that state may change, each component's local invariants, the invariants
that span components, the transitions that must be atomic and the assumptions between components. The model is TLA+
in its native form: one module per component, an integration module, and a contract module that extends the
integration and states the shared invariants.

    python3 gate/compose.py check DIR [--integration MODULE_FILE] [--json]

`check` establishes, by model checking within the model's bounds:
  1. structure: every component declares exactly the variables it owns, no variable has two owners, every shared
     invariant spans at least two components, atomicity and known-wrong entries name what exists;
  2. the integration (model/ or --integration) keeps every local invariant and every permitted-effect rule (owned
     state changes only through the owner's declared effects), and every shared invariant;
  3. every known-wrong integration keeps the local invariants and effect rules and violates exactly the shared
     invariants it is listed for — so the check can tell a broken composition from a broken component.
Exit 0 when all hold. The joint result is only as strong as the atomicity assumptions; the report repeats them.

Runtime composition (v0.13.0, docs/rfc/0007-autonomous-assurance-and-runtime-composition.md § 3). A composition may
add a `runtime` block: the candidate's directories, one process per component, a driver (pytest, the composition's
policy) that starts them through gate/service.py behind judge-owned fault proxies, injects faults between the steps of
a cross-component operation and checks the shared invariants from each component's own state, and the runtime tests
that check each shared invariant. Every shared invariant must be checked by at least one runtime test. A runtime component
is {id, argv, ready?}: argv may use {python}, {port} and {state} (gate/service.py) and {url:ID}, the address of the fault
proxy in front of runtime component ID; `ready` is the path that answers once it is up. The driver interprets them; this
module checks that every {url:ID} names a runtime component.

    python3 gate/compose.py verify DIR --candidate APP --out OUT [--known-wrong] [--json]
        judge a composed candidate at runtime: a fresh workspace (the evaluator, the composition's policy, its declared
        support files and a copy of the candidate's artifact), the driver run against it, failing tests mapped to the
        shared invariants they check. With --known-wrong, also every runtime known-wrong candidate the composition lists,
        each of which must violate exactly the shared invariants it is listed for
    python3 gate/compose.py stagger DIR --component ID --old-candidate OLD --candidate NEW --out OUT [--json]
        a staggered upgrade: the old composed candidate populates every component's state; the new candidate's migrate
        command transforms ONE component's state (refusing unrecognised state, then twice); every other component's
        state must stay byte-identical; the new composed candidate is then verified on the migrated state
"""
import argparse, json, os, pathlib, re, shutil, subprocess, sys, tempfile
import xml.etree.ElementTree as ET
import yaml

HERE = pathlib.Path(__file__).resolve().parent; ROOT = HERE.parent; sys.path.insert(0, str(HERE))
FORMAT = "pith.composition/v1"
MIGRATION = "pith.migration/v1"


def problems(C, d):
    out = []
    if C.get("format") != FORMAT: out.append(f"format is not {FORMAT}")
    comps = C.get("components") or []
    ids = [c.get("id") for c in comps]
    if len(comps) < 2: out.append("a composition needs at least two components")
    if len(set(ids)) != len(ids): out.append("duplicate component ids")
    owner = {}
    for c in comps:
        for k in ("id", "module", "owns", "invariants", "effects"):
            if not c.get(k): out.append(f"component {c.get('id')}: missing {k}")
        mod = d / C["model"]["dir"] / f"{c.get('module')}.tla"
        if not mod.is_file(): out.append(f"component {c.get('id')}: {mod.relative_to(d)} does not exist"); continue
        declared = set()
        for m in re.finditer(r"^\s*VARIABLES?\s+([^\n\\]+)", mod.read_text(), re.M): declared |= {v.strip() for v in m.group(1).split(",") if v.strip()}
        if declared != set(c.get("owns") or []): out.append(f"component {c['id']}: module declares {sorted(declared)}, owns lists {sorted(c.get('owns') or [])}")
        for v in c.get("owns") or []:
            if v in owner: out.append(f"variable {v} is owned by both {owner[v]} and {c['id']}")
            owner[v] = c["id"]
    for s in C.get("shared_invariants") or []:
        if len(set(s.get("components") or [])) < 2: out.append(f"shared invariant {s.get('id')}: spans fewer than two components (a local invariant belongs to its component)")
        for x in s.get("components") or []:
            if x not in ids: out.append(f"shared invariant {s.get('id')}: unknown component {x}")
    if not C.get("shared_invariants"): out.append("no shared invariants: nothing about the composition is claimed")
    for a in C.get("atomicity") or []:
        for x in a.get("components") or []:
            if x not in ids: out.append(f"atomicity {a.get('transition')}: unknown component {x}")
    shared = {s.get("id") for s in C.get("shared_invariants") or []}
    if not C.get("wrong"): out.append("no known-wrong integration: nothing shows the shared invariants can fail")
    for w in C.get("wrong") or []:
        if not (d / w.get("dir", "")).is_dir(): out.append(f"wrong {w.get('dir')}: not a directory")
        if not set(w.get("violates") or []) <= shared or not w.get("violates"): out.append(f"wrong {w.get('dir')}: violates must name shared invariants")
    if not C.get("assumptions"): out.append("no assumptions stated")
    return out


def tlc(C, d, integration, invariants, properties):
    """Model-check the contract module with `integration` (a file) as the integration module. Returns (ok, violated, output)."""
    m = C["model"]; work = pathlib.Path(tempfile.mkdtemp(prefix="compose-"))
    try:
        for f in (d / m["dir"]).glob("*.tla"): shutil.copy(f, work)
        if integration: shutil.copy(integration, work / f"{m['integration']}.tla")
        owned = {c["id"]: c for c in C["components"]}
        effects = "\n".join(f"Effects_{i} == [][ " + " \\/ ".join(f"({e})" for e in c["effects"]) + f" ]_<<{', '.join(c['owns'])}>>" for i, c in owned.items())
        (work / "MCCompose.tla").write_text(f"---- MODULE MCCompose ----\nEXTENDS {m['contract']}\n{effects}\n====\n")
        consts = "\n".join(f"  {k} = {v}" for k, v in m.get("constants", {}).items())
        (work / "MCCompose.cfg").write_text(f"CONSTANTS\n{consts}\nSPECIFICATION Spec\n" + "".join(f"INVARIANT {i}\n" for i in invariants) + "".join(f"PROPERTY {p}\n" for p in properties))
        jar = os.environ.get("TLA2TOOLS", "tla2tools.jar")
        r = subprocess.run(["java", "-XX:+UseParallelGC", "-cp", jar, "tlc2.TLC", "-nowarning", "-workers", "2", "-deadlock", "-config", "MCCompose.cfg", "MCCompose"], cwd=work, capture_output=True, text=True, timeout=900)
        o = r.stdout + r.stderr
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if not re.search(r"TLC2 Version|Starting\.\.\.", o): return None, None, o[-600:]
    v = re.search(r"(?:Invariant|Temporal property|Action property) (\S+) is violated", o)
    return "No error has been found" in o, (v.group(1) if v else None), o


def check(d, integration=None):
    d = pathlib.Path(d).resolve(); C = yaml.safe_load((d / "composition.yaml").read_text())
    rep = {"format": "pith.composition-report/v1", "composition": C.get("id"), "version": C.get("version"), "runs": [], "assumptions": C.get("assumptions", []), "atomicity": C.get("atomicity", [])}
    rep["problems"] = problems(C, d) + runtime_problems(C, d)
    if rep["problems"]: rep["ok"] = False; return rep
    local = [i for c in C["components"] for i in c["invariants"]]; eff = [f"Effects_{c['id']}" for c in C["components"]]
    shared = [s["id"] for s in C["shared_invariants"]]

    def run(label, integ, invs, props, want_ok, want_violated=None):
        ok, violated, out = tlc(C, d, integ, invs, props)
        if ok is None: passed, why = False, "TLC did not run (java or TLA2TOOLS unavailable): " + out[-300:]
        elif want_ok: passed, why = bool(ok), ("holds" if ok else f"violated: {violated or 'see output'}")
        else: passed, why = (not ok and violated == want_violated), (f"violated: {violated}" if not ok else "holds (expected a violation)")
        rep["runs"].append({"run": label, "invariants": invs, "properties": props, "result": "pass" if passed else "fail", "detail": why,
                            **({"counterexample": _trace(out)} if ok is False else {})})
        return passed

    cand = pathlib.Path(integration).resolve() if integration else None
    run("integration: local invariants, permitted effects, shared invariants", cand, local + shared, eff, True)
    for w in C["wrong"]:
        f = d / w["dir"] / f"{C['model']['integration']}.tla"
        run(f"known-wrong {w['dir']}: local invariants and permitted effects hold", f, local, eff, True)
        for s in shared:
            if s in w["violates"]: run(f"known-wrong {w['dir']}: {s} is violated", f, [s], [], False, s)
            else: run(f"known-wrong {w['dir']}: {s} holds", f, [s], [], True)
    rep["ok"] = all(r["result"] == "pass" for r in rep["runs"])
    return rep


def _trace(o):
    m = re.search(r"Error: .*?is violated.*?(?=\n\d+ states generated|\nThe number of states|\Z)", o, re.S)
    return (m.group(0) if m else o[-800:])[:1500]


# ---------------------------------------------------------------- runtime composition (v0.13.0)
def runtime_problems(C, d):
    """What is wrong with the `runtime` block (empty when there is none or it is well-formed)."""
    R = C.get("runtime")
    if R is None: return []
    out = []
    for k in ("contract", "owned_dirs", "driver", "components", "checks"):
        if not R.get(k): out.append(f"runtime: missing {k}")
    ids = {c.get("id") for c in C.get("components") or []}; shared = {s.get("id") for s in C.get("shared_invariants") or []}
    procs = {c.get("id") for c in R.get("components") or []}
    for c in R.get("components") or []:
        if c.get("id") not in ids: out.append(f"runtime component {c.get('id')}: not a component of the composition")
        if not c.get("argv"): out.append(f"runtime component {c.get('id')}: no argv")
        for u in re.findall(r"\{url:([^}]*)\}", " ".join(map(str, c.get("argv") or []))):
            if u not in procs or u == c.get("id"): out.append(f"runtime component {c.get('id')}: {{url:{u}}} names no other runtime component")
        if c.get("ready") is not None and not str(c["ready"]).startswith("/"): out.append(f"runtime component {c.get('id')}: ready must be a path")
    for f in [R.get("contract"), R.get("driver")]:
        if f and not (d / f).is_file(): out.append(f"runtime: {f} does not exist")
    for f in R.get("support") or []:
        if not (ROOT / f).is_file(): out.append(f"runtime support file {f} does not exist")
    checked = set()
    for ch in R.get("checks") or []:
        if not ch.get("test") or not ch.get("shared"): out.append(f"runtime check {ch}: needs a test and the shared invariants it checks")
        for s in ch.get("shared") or []:
            if s not in shared: out.append(f"runtime check {ch.get('test')}: unknown shared invariant {s}")
            checked.add(s)
    for s in sorted(shared - checked): out.append(f"runtime: shared invariant {s} is checked by no runtime test")
    for w in R.get("wrong") or []:
        if not (d / w.get("dir", "")).is_dir(): out.append(f"runtime wrong {w.get('dir')}: not a directory")
        if not w.get("violates") or not set(w["violates"]) <= shared: out.append(f"runtime wrong {w.get('dir')}: violates must name shared invariants")
    for m in R.get("migrations") or []:
        if m.get("component") not in ids: out.append(f"runtime migration {m.get('spec')}: unknown component {m.get('component')}")
        if not (d / str(m.get("spec"))).is_file(): out.append(f"runtime migration {m.get('spec')}: does not exist")
    if not R.get("wrong"): out.append("runtime: no known-wrong candidate shows the runtime checks can fail")
    return out


def workspace(C, d, candidate, artifact):
    """A fresh judged workspace: the evaluator, the composition's policy (everything but its example candidates), the
    support files it declares at their own paths, and a copy of the candidate's artifact (also left in `artifact`)."""
    import workspace as W
    R = C["runtime"]; ign = shutil.ignore_patterns(*W.CACHE_DIRS, *W.OS_METADATA, "._*")
    ws = pathlib.Path(tempfile.mkdtemp(prefix="composed-"))
    shutil.copytree(HERE, ws / "gate", ignore=ign)
    shutil.copytree(d, ws / "composition", ignore=shutil.ignore_patterns("examples", *W.CACHE_DIRS, *W.OS_METADATA, "._*"))
    for f in R.get("support") or []:
        (ws / f).parent.mkdir(parents=True, exist_ok=True); shutil.copy(ROOT / f, ws / f)
    policy = ["gate", "composition"] + sorted({pathlib.PurePosixPath(f).parts[0] for f in R.get("support") or []})
    W.copy_artifact(pathlib.Path(candidate).resolve(), artifact, policy, R["owned_dirs"])
    shutil.copytree(artifact, ws, dirs_exist_ok=True)
    return ws


def drive(ws, driver, out, label, env=None, timeout=1800):
    """Run one driver file (pytest) in the workspace; returns (exit code, output tail, [{test, outcome, message}])."""
    junit = out / f"{label}.junit.xml"
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--noconftest", "-c", "/dev/null", f"--rootdir={ws}",
           f"--junitxml={junit}", str(ws / "composition" / driver)]
    try:
        r = subprocess.run(cmd, cwd=ws, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                           env={**os.environ, "PITH_COMPOSE_WORKSPACE": str(ws), **(env or {})})
        code, o = r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired as e:
        code, o = None, f"driver timed out after {timeout}s\n" + ((e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or ""))
    tests = []
    if junit.is_file():
        for tc in ET.parse(junit).getroot().iter("testcase"):
            bad = next((x for x in tc if x.tag in ("failure", "error", "skipped")), None)
            outcome = {"failure": "failed", "error": "error", "skipped": "skipped"}.get(bad.tag) if bad is not None else "passed"
            tests.append({"test": tc.get("name", "").split("[")[0], "outcome": outcome,
                          **({"message": (bad.get("message") or "")[:600]} if bad is not None else {})})
    (out / f"{label}.log").write_text(o)
    return code, o[-4000:], tests


def judged(tests, checks):
    """Failing tests, the shared invariants their failure shows violated, and the declared checks that did not pass or run."""
    by = {}
    for ch in checks: by.setdefault(ch["test"], set()).update(ch["shared"])
    failing = sorted({t["test"] for t in tests if t["outcome"] in ("failed", "error")})
    ran = {t["test"] for t in tests if t["outcome"] == "passed"}
    return failing, sorted({s for t in failing for s in by.get(t, ())}), sorted(t for t in by if t not in ran and t not in failing)


def run_runtime(C, d, candidate, out):
    import workspace as W
    out.mkdir(parents=True, exist_ok=True); art = out / "artifact"
    ws = workspace(C, d, candidate, art)
    try:
        code, tail, tests = drive(ws, C["runtime"]["driver"], out, "driver", {"PITH_COMPOSE_MODE": "verify"})
    finally:
        shutil.rmtree(ws, ignore_errors=True)
    failing, violated, unchecked = judged(tests, C["runtime"]["checks"])
    return {"candidate": str(pathlib.Path(candidate).resolve()), "artifact_digest": W.digest_dir(art), "tests": tests, "failing_tests": failing,
            "violated": violated, "unchecked": unchecked, "ok": code == 0 and bool(tests) and not failing and not unchecked,
            **({"output": tail} if code != 0 else {})}


def verify(d, candidate, out, known_wrong=False):
    d = pathlib.Path(d).resolve(); out = pathlib.Path(out).resolve(); C = yaml.safe_load((d / "composition.yaml").read_text())
    rep = {"format": "pith.composition-report/v1", "composition": C.get("id"), "version": C.get("version"), "assumptions": C.get("assumptions", []),
           "atomicity": C.get("atomicity", []), "problems": problems(C, d) + runtime_problems(C, d)}
    if not C.get("runtime"): rep["problems"].append("no runtime block: nothing to verify at runtime")
    if rep["problems"]: rep["ok"] = False; return rep
    if out.exists(): rep["problems"].append(f"{out} exists; use a fresh one"); rep["ok"] = False; return rep
    rep["runtime"] = run_runtime(C, d, candidate, out / "candidate")
    rep["ok"] = rep["runtime"]["ok"]
    if known_wrong:
        rep["known_wrong"] = []
        for w in C["runtime"]["wrong"]:
            r = run_runtime(C, d, d / w["dir"], out / ("wrong-" + pathlib.PurePosixPath(w["dir"]).name))
            passed = not r["ok"] and r["violated"] == sorted(w["violates"]) and not r["unchecked"]
            rep["known_wrong"].append({"dir": w["dir"], "violates": sorted(w["violates"]), "violated": r["violated"], "failing_tests": r["failing_tests"],
                                       "result": "pass" if passed else "fail"})
        rep["ok"] = rep["ok"] and all(x["result"] == "pass" for x in rep["known_wrong"])
    return rep


def stagger(d, component, old_candidate, candidate, out):
    """A staggered upgrade of one component in a running composition (see the module docstring)."""
    import workspace as W, migrate as MG, sandbox as SB
    d = pathlib.Path(d).resolve(); out = pathlib.Path(out).resolve(); C = yaml.safe_load((d / "composition.yaml").read_text())
    rep = {"format": "pith.composition-report/v1", "composition": C.get("id"), "version": C.get("version"), "assumptions": C.get("assumptions", []),
           "problems": problems(C, d) + runtime_problems(C, d)}
    m = next((x for x in (C.get("runtime") or {}).get("migrations") or [] if x.get("component") == component), None)
    if m is None: rep["problems"].append(f"the composition declares no runtime migration for component {component}")
    if out.exists(): rep["problems"].append(f"{out} exists; use a fresh one")
    if rep["problems"]: rep["ok"] = False; return rep
    S = yaml.safe_load((d / m["spec"]).read_text())
    st = rep["stagger"] = {"component": component, "spec": m["spec"], "from": S.get("from"), "to": S.get("to"), "records": S.get("records", []),
                           "mapping": S.get("mapping"), "in_flight": S.get("in_flight"), "rollback": S.get("rollback"), "steps": []}
    def step(name, ok, detail, category=None, **kw):
        st["steps"].append({"step": name, "result": "pass" if ok else "fail", "detail": detail[-2000:] if isinstance(detail, str) else detail,
                            **({"category": category} if not ok else {}), **kw})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}", file=sys.stderr)
        return ok
    def done():
        st["ok"] = rep["ok"] = bool(st["steps"]) and all(s["result"] == "pass" for s in st["steps"])
        for w in (old_ws, new_ws): shutil.rmtree(w, ignore_errors=True)
        return rep
    shape = S.get("format") == MIGRATION and S.get("component") == component and isinstance(S.get("state"), dict) and component in S["state"] \
        and all(S.get(k) for k in ("populate", "migrate", "verify"))
    out.mkdir(parents=True); old_ws = new_ws = out / "none"
    if not step("migration spec", shape, f"{m['spec']} must be {MIGRATION} for component {component}, with state (per component), populate, migrate and verify", "contract_change"): return done()
    old_ws = workspace(C, d, old_candidate, out / "old-artifact"); new_ws = workspace(C, d, candidate, out / "artifact")
    st["old_artifact_digest"] = W.digest_dir(out / "old-artifact"); st["artifact_digest"] = W.digest_dir(out / "artifact")
    state = out / "state"; state.mkdir(); observed = out / "observed.json"
    env = {"PITH_COMPOSE_STATE": str(state), "PITH_COMPOSE_OBSERVED": str(observed)}
    code, tail, _ = drive(old_ws, S["populate"], out, "populate", {**env, "PITH_COMPOSE_MODE": "populate"})
    if not step("populate: the old composed candidate produced state", code == 0 and observed.is_file(), tail, "infrastructure"): return done()
    others = sorted(set(S["state"]) - {component})
    before = {c: W.digest_dir(state / S["state"][c]) for c in S["state"]}
    sub = lambda c, where: c.replace("{python}", sys.executable).replace("{state}", str(where))
    if S.get("unrecognised"):
        bad = pathlib.Path(tempfile.mkdtemp(prefix="unrecognised-")); kept = {}
        for f, text in S["unrecognised"].get("files", {}).items():
            (bad / f).parent.mkdir(parents=True, exist_ok=True); (bad / f).write_text(text); kept[f] = text
        code, o = MG.sh(sub(S["migrate"], bad), new_ws, as_candidate=True)
        same = all((bad / f).read_text() == t for f, t in kept.items())
        step("migrate refuses unrecognised state", code != 0 and same, (o or "") + f"\nexit {code}; state {'unchanged' if same else 'CHANGED'}", "violation")
        shutil.rmtree(bad, ignore_errors=True)
    ident = SB.candidate_identity()
    if ident:
        for p in [state, *state.rglob("*")]: os.chown(p, *ident)
    for label in ("migrate", "migrate again (interrupted and retried)"):
        code, o = MG.sh(sub(S["migrate"], state), new_ws, as_candidate=True)
        if not step(label, code == 0, o, "violation" if code not in (126, 127) else "toolchain_unavailable"): return done()
    after = {c: W.digest_dir(state / S["state"][c]) for c in S["state"]}
    touched = [c for c in others if after[c] != before[c]]
    if not step("every other component's state is untouched", not touched, f"changed: {touched}" if touched else f"unchanged: {others}", "violation", changed=touched): return done()
    st["migrated_state_digest"] = W.digest_dir(state)
    code, tail, tests = drive(new_ws, S["verify"], out, "verify", {**env, "PITH_COMPOSE_MODE": "verify-migrated"})
    failing, violated, unchecked = judged(tests, S.get("checks") or [])
    step("verify: the new composed candidate on the migrated state", code == 0 and bool(tests) and not failing and not unchecked, tail, "violation",
         failing_tests=failing, violated=violated, unchecked=unchecked)
    rb = S.get("rollback") or {}
    step("rollback policy stated", rb.get("policy") in ("forward-only", "reversible") and bool(rb.get("why")), f"{rb.get('policy')}: {str(rb.get('why', '')).strip()}", "evidence_missing")
    return done()


def main():
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("dir"); c.add_argument("--integration"); c.add_argument("--json", action="store_true")
    v = sub.add_parser("verify"); v.add_argument("dir"); v.add_argument("--candidate", required=True); v.add_argument("--out", required=True)
    v.add_argument("--known-wrong", action="store_true"); v.add_argument("--json", action="store_true")
    s = sub.add_parser("stagger"); s.add_argument("dir"); s.add_argument("--component", required=True); s.add_argument("--old-candidate", required=True)
    s.add_argument("--candidate", required=True); s.add_argument("--out", required=True); s.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.cmd == "verify": rep = verify(a.dir, a.candidate, a.out, a.known_wrong)
    elif a.cmd == "stagger": rep = stagger(a.dir, a.component, a.old_candidate, a.candidate, a.out)
    else: rep = check(a.dir, a.integration)
    if a.out if a.cmd != "check" else False:
        pathlib.Path(a.out).mkdir(parents=True, exist_ok=True); (pathlib.Path(a.out) / "composition-report.json").write_text(json.dumps(rep, indent=1))
    if a.json: print(json.dumps(rep, indent=1))
    else:
        for p in rep["problems"]: print(f"[ERROR] {p}")
        for r in rep.get("runs", []): print(f"[{'PASS' if r['result'] == 'pass' else 'FAIL'}] {r['run']} — {r['detail']}")
        if rep.get("runtime"):
            R = rep["runtime"]
            print(f"[{'PASS' if R['ok'] else 'FAIL'}] runtime: {sum(t['outcome'] == 'passed' for t in R['tests'])} of {len(R['tests'])} driver tests passed"
                  + (f"; failing {R['failing_tests']}, violated {R['violated']}" if R["failing_tests"] else "") + (f"; not run {R['unchecked']}" if R["unchecked"] else ""))
        for w in rep.get("known_wrong", []):
            print(f"[{'PASS' if w['result'] == 'pass' else 'FAIL'}] known-wrong {w['dir']}: violated {w['violated']} (expected {w['violates']}); failing {w['failing_tests']}")
        for s_ in (rep.get("stagger") or {}).get("steps", []): print(f"[{'PASS' if s_['result'] == 'pass' else 'FAIL'}] {s_['step']}")
        print(f"composition {rep['composition']}: {'ok' if rep['ok'] else 'NOT ok'}; holds under the assumptions: " + "; ".join(rep["assumptions"]))
    sys.exit(0 if rep["ok"] else 1)


if __name__ == "__main__":
    main()
