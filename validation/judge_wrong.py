"""validation/judge_wrong.py — judge every known-wrong fixture of a pack with the pristine gate and check the verdict
its expected.yaml names. Exit 0 iff every fixture is refused for exactly its defects.

    python3 validation/judge_wrong.py <evidence-root> [fixture ...]                         the reservation pack (examples/wrong/)
    python3 validation/judge_wrong.py --pack packs/booking <evidence-root> [fixture ...]    another pack (<pack>/examples/wrong/)
    python3 validation/judge_wrong.py --composition compositions/booking-quota <evidence-root> [fixture ...]
                                       a composition's runtime known-wrong candidates and staggered migrations (v0.13.0)
    python3 validation/judge_wrong.py --handoff evolution/handoff/fork-join <evidence-root> [name ...]
                                       a fork-join handoff's known-wrong merges (v0.13.0): DIR/expected.yaml names each

Two kinds of expectation:
  must_fail: [obligation ids]            behavioral assurance passes, application delivery fails on EXACTLY these obligations
  refused_at: <check id>                 the run is refused at exactly that check (the first blocking failure), and
  failing_tests: [names]                 the failing tests named in its output are exactly these, plus at most
  may_also_fail: [names]                 these, where whether a concurrent test observes the defect depends on scheduling
and, for either (v0.9.0), what the task packet must say about the first failure:
  category: <category>                   gate/packet.py's category of the first failure
  contracts: [ids]                       contract records the packet must name for it (at least these)

A negative judged by another tool than app_gate.py names it (v0.13.0, docs/rfc/0007 § 2), with the same "exactly":
  tool: compose verify                   gate/compose.py verify refuses it: the failing driver tests are exactly
    failing_tests: [names]               these (plus at most may_also_fail), and the shared invariants they show
    violates: [ids]                      violated are exactly these
  promoted_from: <gap id>                a fixture gate/redteam.py promoted: the pack's red-team gap record must record that gap as
                                         promoted to this fixture (the ratchet is not undone by hand)
  tool: compose stagger                  gate/compose.py stagger refuses it at exactly refused_step, upgrading
    component: <id>                      that component from old_candidate (a directory of the composition);
    old_candidate: <dir>                 when the step is the verify step, failing_tests and violates as above
    refused_step: <step name>
  tool: handoff merge                    gate/change.py merge refuses it (--handoff DIR: DIR/expected.yaml, one entry per merge;
    base: <repo path>                    the base is an accepted application, each branch DIR/<name>/ holds only the files
    branches: [names]                    it changes relative to it). The base is judged first (evidence already in the root, e.g.
    refused: partition                   from validation/handoff.py, is reused), then gate/change.py merge runs:
      conflict: {kind, partition}        partition: refused statically, no judge run, the partition conflicts are exactly
    refused: judge                       `conflict`; judge: each branch is judged alone with the base's evidence offered,
      first_failure: <check id>          there is no conflict, the judge on the merged tree is refused at exactly
      failing_workflows: [ids]           first_failure and the delivery workflows and interaction obligations that failed
      category: <category>               are exactly these (app-claims.json delivery_detail; the browser harness's own
                                         `error` stands for a workflow run that raised); category as above
      textual: [paths]                   for `partition`: the textual conflicts reported beside it, exactly (whole-file)
"""
import json, pathlib, re, subprocess, sys
import yaml

SEED = pathlib.Path(__file__).resolve().parent.parent
args = sys.argv[1:]; pack = None


def composition(comp, root, names):
    """Every runtime known-wrong candidate (examples/wrong) and staggered migration (examples/wrong-migrations) of a
    composition, judged by gate/compose.py; returns the number that were not refused for exactly their defect."""
    bad = 0
    for sub in ("wrong", "wrong-migrations"):
        f = comp / "examples" / sub / "expected.yaml"
        if not f.is_file(): continue
        for name, want in (yaml.safe_load(f.read_text()) or {}).items():
            if names and name not in names: continue
            out = root / f"{sub}-{comp.name}-{name}"; cand = comp / "examples" / sub / name
            if want["tool"] == "compose verify":
                r = subprocess.run([sys.executable, str(SEED / "gate/compose.py"), "verify", str(comp), "--candidate", str(cand), "--out", str(out), "--json"], capture_output=True, text=True)
                R = (json.loads(r.stdout) if r.stdout.strip().startswith("{") else {}).get("runtime") or {}
                tests, violated = R.get("failing_tests", []), R.get("violated", [])
                need = set(want["failing_tests"]); extra = set(tests) - need
                ok = r.returncode == 1 and not R.get("ok", True) and need <= set(tests) and extra <= set(want.get("may_also_fail", [])) and violated == sorted(want["violates"])
                print(f"{'ok  ' if ok else 'FAIL'} {name}: compose verify refused={r.returncode == 1}; failing tests {tests}; violated {violated} (expected {sorted(want['violates'])})")
            elif want["tool"] == "compose stagger":
                r = subprocess.run([sys.executable, str(SEED / "gate/compose.py"), "stagger", str(comp), "--component", want["component"], "--old-candidate",
                                    str(comp / want["old_candidate"]), "--candidate", str(cand), "--out", str(out), "--json"], capture_output=True, text=True)
                S = (json.loads(r.stdout) if r.stdout.strip().startswith("{") else {}).get("stagger") or {}
                fails = [x for x in S.get("steps", []) if x["result"] == "fail"]; first = fails[0] if fails else {}
                ok = r.returncode == 1 and first.get("step") == want["refused_step"]
                if "failing_tests" in want: ok = ok and set(want["failing_tests"]) <= set(first.get("failing_tests", [])) and set(first.get("failing_tests", [])) - set(want["failing_tests"]) <= set(want.get("may_also_fail", []))
                if "violates" in want: ok = ok and first.get("violated") == sorted(want["violates"])
                print(f"{'ok  ' if ok else 'FAIL'} {name}: compose stagger refused at {first.get('step')!r} (expected {want['refused_step']!r})"
                      + (f"; failing tests {first.get('failing_tests')}; violated {first.get('violated')}" if first.get("failing_tests") else ""))
            else:
                ok = False; print(f"FAIL {name}: unknown tool {want['tool']!r}")
            bad += not ok
    return bad


def handoff(fj, root, names):
    """Every known-wrong merge of a fork-join handoff (DIR/expected.yaml), judged by gate/change.py merge; returns the number
    that were not refused for exactly their defect. Evidence is kept under <root>/handoff-<dir>-... : the base
    (`-base-<name>`), each branch alone (`-<branch>`, judged with the base's evidence offered) and each merge (`-<entry>`);
    evidence already there that was accepted is reused, so validation/handoff.py and this mode share one set of runs."""
    import shutil
    E = yaml.safe_load((fj / "expected.yaml").read_text()) or {}; bad = 0; rel = None
    root.mkdir(parents=True, exist_ok=True); prefix = f"handoff-{fj.name}"
    def sh(*argv):
        return subprocess.run([str(x) for x in argv], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    def tree(label, base, branch=None):
        d = root / f"{prefix}-cand" / label
        if not d.exists():
            d.parent.mkdir(parents=True, exist_ok=True); shutil.copytree(SEED / base, d, ignore=shutil.ignore_patterns("__pycache__"))
            if branch: shutil.copytree(fj / branch, d, dirs_exist_ok=True)
        return d
    def accepted(out):
        f = out / "app-claims.json"
        if not f.is_file() or not (out / "evidence.json").is_file(): return False
        c = json.loads(f.read_text()); return str(c.get("behavioral_assurance")).startswith("passed") and c.get("application_delivery") == "passed"
    def judged(label, cand, reuse=None):
        nonlocal rel
        out = root / f"{prefix}-{label}"
        if accepted(out): return out, True
        shutil.rmtree(out, ignore_errors=True); rel = rel or sh(sys.executable, SEED / "gate/release.py", "id").stdout.strip()
        r = sh(sys.executable, "-I", SEED / "gate/app_gate.py", "--candidate", cand, "--out", out, "--expected-release", rel, *[x for p in (reuse or []) for x in ("--reuse", p)])
        return out, r.returncode == 0 and accepted(out)
    for name, want in E.items():
        if names and name not in names: continue
        if want.get("tool") != "handoff merge": bad += 1; print(f"FAIL {name}: unknown tool {want.get('tool')!r}"); continue
        base_dir = tree(f"base-{pathlib.Path(want['base']).name}", want["base"])
        base_ev, ok = judged(f"base-{pathlib.Path(want['base']).name}", base_dir)
        if not ok: bad += 1; print(f"FAIL {name}: the base {want['base']} is not accepted by the pristine gate, so a merge of changes to it says nothing"); continue
        specs = []
        for b in want["branches"]:
            bdir = tree(f"{pathlib.Path(want['base']).name}+{b}", want["base"], b)
            if want["refused"] == "judge":       # the judge's verdict on the merge is the point: each branch must be accepted alone, and its evidence is offered
                bev, ok = judged(b, bdir, [base_ev])
                if not ok: bad += 1; print(f"FAIL {name}: branch {b} is not accepted alone; the merge would not be the interesting refusal"); break
            else:                                # a static refusal needs no evidence; offer a branch's when it is already there
                bev = root / f"{prefix}-{b}"; ok = accepted(bev)
            specs.append(f"{b}={bdir}" + (f":{bev}" if ok else ""))
        else:
            out = root / f"{prefix}-{name.replace('+', '_')}"; shutil.rmtree(out, ignore_errors=True); out.mkdir(parents=True)
            report = out / "merge-report.json"
            cmd = [sys.executable, SEED / "gate/change.py", "merge", "--base-candidate", base_dir, "--base", base_ev, "--out", out / "merged", "--report", report, "--json"]
            for s_ in specs: cmd += ["--branch", s_]
            if want["refused"] == "judge": cmd += ["--judge", out / "evidence"]
            r = sh(*cmd); R = json.loads(report.read_text()) if report.is_file() else {}
            conflicts = R.get("conflicts", []); detail = ""
            if want["refused"] == "partition":
                got = [{k: c[k] for k in ("kind", "partition")} for c in conflicts if c["kind"] in ("partition", "boundary")]
                ok = (r.returncode == 1 and not R.get("ok", True) and got == [want["conflict"]] and "judge" not in R and "merged" not in R and not (out / "merged").exists()
                      and sorted({c["path"] for c in conflicts if c["kind"] == "textual"}) == sorted(want.get("textual", [])))
                detail = f"merge refused={r.returncode == 1}; partition conflicts {got} (expected {[want['conflict']]}); textual {sorted({c['path'] for c in conflicts if c['kind'] == 'textual'})}; judge run: {'judge' in R}"
            else:
                J = R.get("judge") or {}; wf = ((json.loads((out / "evidence/app-claims.json").read_text()) if (out / "evidence/app-claims.json").is_file() else {}).get("delivery_detail") or {}).get("workflows", {})
                failed = sorted(k for k, v in wf.items() if not v["ok"])
                ok = (r.returncode == 1 and not R.get("ok", True) and not conflicts and not R.get("problems") and J.get("accepted") is False
                      and J.get("first_failure") == want["first_failure"] and failed == sorted(want["failing_workflows"]))
                if "category" in want:      # an unavailable browser also fails delivery, with nothing to say about the merge: the packet's category tells them apart
                    cat = ((json.loads((out / "evidence/task-packet.json").read_text()) if (out / "evidence/task-packet.json").is_file() else {}).get("first_failure") or {}).get("category")
                    ok = ok and cat == want["category"]; detail_c = f"; category {cat} (expected {want['category']})"
                else: detail_c = ""
                detail = f"merge refused={r.returncode == 1}; conflicts {len(conflicts)}; judge refused at {J.get('first_failure')} (expected {want['first_failure']}); failing {failed} (expected {sorted(want['failing_workflows'])}){detail_c}"
            print(f"{'ok  ' if ok else 'FAIL'} {name}: {detail}")
            bad += not ok
    return bad


if args[:1] == ["--handoff"]:
    sys.exit(1 if handoff((SEED / args[1]).resolve(), pathlib.Path(args[2]).resolve(), args[3:]) else 0)

if args[:1] == ["--composition"]:
    sys.exit(1 if composition((SEED / args[1]).resolve(), pathlib.Path(args[2]), args[3:]) else 0)
if args[:1] == ["--pack"]: pack = (SEED / args[1]).resolve(); args = args[2:]
WRONG = (pack / "examples/wrong") if pack else SEED / "examples/wrong"
EXPECT = yaml.safe_load((WRONG / "expected.yaml").read_text())
root = pathlib.Path(args[0]); names = args[1:] or list(EXPECT)
prefix = f"wrong-{pack.name}-" if pack else "wrong-"
bad = 0
for name in names:
    out = root / f"{prefix}{name}"; want = EXPECT[name]
    subprocess.run(["bash", str(SEED / "validation/judge_example.sh"), *(["--pack", str(pack)] if pack else []), str(WRONG / name), str(out)], capture_output=True, text=True)
    c = json.loads((out / "app-claims.json").read_text())
    if "must_fail" in want:
        wf = c.get("delivery_detail", {}).get("workflows", {})
        failed = sorted(k for k, v in wf.items() if not v["ok"])
        ok = str(c["behavioral_assurance"]).startswith("passed") and c["application_delivery"] == "failed" and failed == sorted(want["must_fail"])
        print(f"{'ok  ' if ok else 'FAIL'} {name}: assurance={str(c['behavioral_assurance'])[:6]} delivery={c['application_delivery']} failing={failed} expected={sorted(want['must_fail'])}")
        for k in failed: print(f"       {k}: {wf[k]['evidence'][0][:220]}")
    else:
        fails = [x for x in c["checks"] if x["result"] == "fail"]
        first = fails[0] if fails else {}
        tests = sorted(set(re.findall(r"FAILED \S+::(\w+)", first.get("why", ""))))
        need = set(want.get("failing_tests", tests)); extra = set(tests) - need
        ok = c["behavioral_assurance"] == "refused" and first.get("id") == want["refused_at"] and need <= set(tests) and extra <= set(want.get("may_also_fail", []))
        print(f"{'ok  ' if ok else 'FAIL'} {name}: assurance={c['behavioral_assurance']} refused at {first.get('id')} (expected {want['refused_at']}); failing tests {tests}")
        if not ok and want.get("failing_tests"): print(f"       expected tests {sorted(want['failing_tests'])}" + (f", possibly also {sorted(want['may_also_fail'])}" if want.get("may_also_fail") else ""))
    if want.get("promoted_from"):
        P_ = yaml.safe_load(((pack or SEED) / "pack.yaml").read_text()); led = (pack or SEED) / (P_.get("redteam") or {}).get("gaps", "redteam/gaps.yaml")
        G = {g["id"]: g for g in ((yaml.safe_load(led.read_text()) or {}).get("gaps", []) if led.exists() else [])}.get(want["promoted_from"], {})
        lok = G.get("status") == "promoted" and (G.get("promoted") or {}).get("to") == f"examples/wrong/{name}"
        print(f"{'ok  ' if lok else 'FAIL'} {name} gaps: gap {want['promoted_from']} is {G.get('status')} -> {(G.get('promoted') or {}).get('to')}")
        ok = ok and lok
    if "category" in want or "contracts" in want:
        f = (json.loads((out / "task-packet.json").read_text()) if (out / "task-packet.json").exists() else {}).get("first_failure") or {}
        named = {x["id"] for x in f.get("contracts", [])}
        pok = f.get("category") == want.get("category", f.get("category")) and set(want.get("contracts", [])) <= named
        print(f"{'ok  ' if pok else 'FAIL'} {name} task packet: category {f.get('category')} (expected {want.get('category')}); contracts {sorted(named)} ⊇ {want.get('contracts', [])}")
        ok = ok and pok
    bad += not ok
sys.exit(1 if bad else 0)
