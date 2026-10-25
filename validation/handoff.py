#!/usr/bin/env python3
"""validation/handoff.py OUT — re-checks the recorded handoff between two model agents (evolution/handoff/README.md;
docs/rfc/0006-upgrading-the-main-packs.md § 6).

The agents ran once; what they produced is committed under evolution/handoff/ (agent-a/, agent-b/, and B's own
change-impact reports in recorded/). This script does not run any model. It judges what they produced, with the
pristine tally 2 release, and checks that the record says what happened:

  1. agent A's application is accepted, and migrates state the accepted tally 1 application produced (gate/migrate.py)
  2. B's recorded plans and classification name the integration route and the checks the change reads
  3. classifying B's application against A's evidence now gives the same route and checks B recorded
  4. B's application, judged with A's evidence offered, is accepted, and reuses only what the classification says holds
  5. B changed only service/run.py, and did not make the change it refused (counter "vip" still has bound 3)

Then (v0.13.0, RFC 0007 § 8) the fork-join handoff in evolution/handoff/fork-join: three SCRIPTED branches off the accepted
examples/build-a, judged by the reservation pack's release (the repository itself), and the merges `gate/change.py merge`
makes of them:

  6. the base and each branch alone (agent-a: storage profile, agent-b: page, agent-c: service) are accepted, each with the
     base's evidence offered, which reuses exactly the proof and the model checks
  7. a+b: no conflict, disjoint partitions, the judge on the merged tree accepts it, reusing exactly the cacheable records and
     running every other check again; every branch result resting on the other branch's partition is listed and not reused
  8. b+c: disjoint partitions, no static conflict, the cacheable evidence still holds, and the judge on the merged tree
     refuses it at delivery (this merge, and a+c below, are judged by `validation/judge_wrong.py --handoff`, called here, against
     fork-join/expected.yaml: exactly which workflows fail, exactly which conflict)
  9. a+c: refused statically, a conflict on partition `integration`, no judge run
 10. the fresh merge reports agree with evolution/handoff/fork-join/recorded/ on every field that is not machine-specific

`--record` rewrites recorded/ from this run (machine paths replaced by <run>) instead of comparing with it.
Writes OUT/handoff-record.json; exit 1 if any expectation fails."""
import json, pathlib, shutil, socket, subprocess, sys, tempfile, time, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent; PY = sys.executable
RECORD = "--record" in sys.argv[1:]
OUT = pathlib.Path([x for x in sys.argv[1:] if not x.startswith("--")][0]).resolve(); shutil.rmtree(OUT, ignore_errors=True); OUT.mkdir(parents=True)
V1, V2, H = ROOT / "evolution/tally-v1", ROOT / "evolution/tally-v2", ROOT / "evolution/handoff"
rec = {"format": "pith.handoff-record/v1", "expectations": []}; failures = []


def sh(*argv):
    r = subprocess.run([str(x) for x in argv], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0: print(r.stdout[-3000:], r.stderr[-3000:]); raise SystemExit(f"FAILED ({r.returncode}): {' '.join(map(str, argv))}")
    return r


def expect(what, cond, detail=""):
    rec["expectations"].append({"what": what, "ok": bool(cond), **({"detail": detail} if detail else {})})
    print(f"[{'ok' if cond else 'FAIL'}] {what}" + (f" — {detail}" if detail and not cond else ""), flush=True)
    if not cond: failures.append(what)


def release_id(rel): return sh(PY, rel / "gate/release.py", "id").stdout.strip()


def judge(rel, cand, out, reuse=None):
    offered = [reuse] if isinstance(reuse, (str, pathlib.Path)) else list(reuse or [])      # one evidence directory, or several (v0.13.0)
    r = subprocess.run([PY, "-I", rel / "gate/app_gate.py", "--candidate", cand, "--out", out, "--expected-release", release_id(rel)] + [x for o in offered for x in ("--reuse", o)],
                       cwd=ROOT, capture_output=True, text=True)
    c = json.loads((out / "app-claims.json").read_text()) if (out / "app-claims.json").exists() else {}
    E = json.loads((out / "evidence.json").read_text()) if (out / "evidence.json").exists() else {"records": []}
    return r.returncode, c, E


def reused(E): return sorted(r["check"] for r in E["records"] if r.get("reused_from"))
def reused_ids(E): return sorted(r["id"] for r in E["records"] if r.get("reused_from"))      # check ids, as the merge report and the pack name them (v0.13.0)


def change(cmd, ev, cand, rel, *extra):
    return json.loads(sh(PY, "gate/change.py", cmd, "--evidence", ev, "--candidate", cand, "--policy-from", rel, "--json", *extra).stdout)


def copy(src, name):
    d = OUT / "cand" / name; shutil.copytree(src, d, ignore=shutil.ignore_patterns("__pycache__")); return d


def probe_vip(cand):
    """Four requests on counter "vip" against B's running service: the fourth is refused and the bound is 3."""
    with socket.socket() as s: s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    db = pathlib.Path(tempfile.mkdtemp()) / "tally.db"
    p = subprocess.Popen([PY, "-I", cand / "service/run.py", "--port", str(port), "--db", db], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        def call(method, path, body=None):
            q = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, data=json.dumps(body).encode() if body is not None else None,
                                       headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(q, timeout=5) as r: return json.loads(r.read())
        for _ in range(100):
            try: call("GET", "/tally?counter=vip"); break
            except OSError: time.sleep(0.1)
        outcomes = [call("POST", "/requests", {"request_id": 900 + i, "counter": "vip"})["outcome"] for i in range(4)]
        return outcomes, call("GET", "/tally?counter=vip")
    finally:
        p.terminate(); p.wait(10)


rel_v1, rel_v2 = OUT / "release-v1", OUT / "release-v2"
sh(PY, "gate/release.py", "build", "--pack", V1, "--out", rel_v1); sh(PY, "gate/release.py", "build", "--pack", V2, "--out", rel_v2)
rec["release"] = release_id(rel_v2)

# 1. agent A
a = copy(H / "agent-a", "agent-a")
code, ca, EA = judge(rel_v2, a, OUT / "ev-agent-a")
expect("agent A's application is accepted under tally 2", code == 0, {k: ca.get(k) for k in ("model_assurance", "behavioral_assurance")})
o = copy(V1 / "examples/basic", "tally-v1-basic")
code, _, _ = judge(rel_v1, o, OUT / "ev-v1")
expect("the tally 1 application whose state A's migration receives is accepted under tally 1", code == 0)
r = subprocess.run([PY, "gate/migrate.py", "run", "--release", rel_v2, "--candidate", a, "--old-release", rel_v1, "--old-candidate", o,
                    "--old-evidence", OUT / "ev-v1", "--out", OUT / "migration-agent-a"], cwd=ROOT, capture_output=True, text=True)
M = json.loads((OUT / "migration-agent-a/migration-report.json").read_text()) if (OUT / "migration-agent-a/migration-report.json").exists() else {"ok": False, "steps": []}
expect("agent A's migration, on state the accepted tally 1 application produced: every step passes", r.returncode == 0 and M["ok"], [(s["step"], s["result"]) for s in M["steps"]])
rec["migration"] = [(s["step"], s["result"]) for s in M["steps"]]

# 2. what B recorded before and after its change
R = {n: json.loads((H / "recorded" / f"{n}.json").read_text()) for n in ("plan-run", "plan-vip", "classify")}
SERVICE = {"lifecycle harness (black-box)", "service entrypoint", "migration entrypoint"}
expect("B's recorded plan for the log line: integration, re-run the checks that read service/run.py",
       R["plan-run"]["route"] == "integration" and SERVICE <= set(R["plan-run"]["rerun"]), (R["plan-run"]["route"], R["plan-run"]["rerun"]))
expect("B's recorded plan for the vip bound reads integration by path: the route report cannot see that it would break T1",
       R["plan-vip"]["route"] == "integration" and not R["plan-vip"]["contract_changes"], R["plan-vip"]["route"])
expect("B's recorded classification: integration, only service/run.py changed, the model checks hold",
       R["classify"]["route"] == "integration" and [f["path"] for f in R["classify"]["files"]] == ["service/run.py"] and set(R["classify"]["evidence"]["holds"]) == {"model checked", "the model rejects a bound checked on counter default only"},
       (R["classify"]["route"], [f["path"] for f in R["classify"]["files"]], R["classify"]["evidence"]["holds"]))

# 3. the classification, recomputed
b = copy(H / "agent-b", "agent-b")
cls = change("classify", OUT / "ev-agent-a", b, rel_v2)
expect("classifying B's application against A's evidence now gives what B recorded",
       cls["route"] == R["classify"]["route"] and sorted(cls["rerun"]) == sorted(R["classify"]["rerun"]) and sorted(cls["evidence"]["holds"]) == sorted(R["classify"]["evidence"]["holds"]),
       (cls["route"], cls["rerun"], cls["evidence"]["holds"]))

# 4. B judged with A's evidence offered
code, cb, EB = judge(rel_v2, b, OUT / "ev-agent-b", reuse=OUT / "ev-agent-a")
expect("B's application, judged with A's evidence offered: accepted, reusing only what holds", code == 0 and reused(EB) and set(reused(EB)) <= set(cls["evidence"]["holds"]), (code, reused(EB)))
expect("nothing the change invalidated was reused", not set(reused(EB)) & set(cls["rerun"]), reused(EB))
rec["reused"] = reused(EB)

# 5. what B did not do
A, B = H / "agent-a", H / "agent-b"   # the committed files: the judged copies also hold the judge's own output
changed = sorted(str(p.relative_to(B)) for p in B.rglob("*") if p.is_file() and "__pycache__" not in p.parts and (not (A / p.relative_to(B)).is_file() or (A / p.relative_to(B)).read_bytes() != p.read_bytes()))
expect("B changed only service/run.py", changed == ["service/run.py"], changed)
outcomes, tally = probe_vip(b)
expect('B did not make the change it refused: counter "vip" is refused at its fourth request, bound 3', outcomes == ["OK", "OK", "OK", "REFUSED"] and tally.get("bound") == 3, (outcomes, tally))

# ================================================================== fork-join (v0.13.0; RFC 0007 § 8; evolution/handoff/fork-join/README.md)
# Three scripted branches off the accepted examples/build-a, judged by the reservation pack's release (this repository), one judge at a time.
FJ, BASE = H / "fork-join", ROOT / "examples/build-a"; fj = OUT / "fork-join"; fj.mkdir()
BRANCHES = ("agent-a", "agent-b", "agent-c")
NEG = {"agent-a+agent-b": "agent-a_agent-b", "agent-b+agent-c": "agent-b_agent-c", "agent-a+agent-c": "agent-a_agent-c"}   # judge_wrong.py --handoff names its merge directories like this
fjn = lambda label: fj / f"handoff-fork-join-{label}"                                                                     # ... and its evidence directories like this, so one set of runs serves both


def fj_tree(label, branch=None):
    d = fjn("cand") / label
    if not d.exists():
        shutil.copytree(BASE, d, ignore=shutil.ignore_patterns("__pycache__"))
        if branch: shutil.copytree(FJ / branch, d, dirs_exist_ok=True)
    return d


def fj_merge(label, names, with_judge=True):
    out = fjn(label); shutil.rmtree(out, ignore_errors=True); out.mkdir(parents=True)
    cmd = [PY, "gate/change.py", "merge", "--base-candidate", base_c, "--base", ev_base, "--out", out / "merged", "--report", out / "merge-report.json", "--json"]
    for n in names: cmd += ["--branch", f"{n}={cands[n]}:{evs[n]}"]
    if with_judge: cmd += ["--judge", out / "evidence"]
    r = subprocess.run([str(x) for x in cmd], cwd=ROOT, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return r.returncode, json.loads((out / "merge-report.json").read_text()) if (out / "merge-report.json").is_file() else {"branches": []}


def placeholders(o):
    if isinstance(o, str): return o.replace(str(OUT), "<run>")
    if isinstance(o, list): return [placeholders(x) for x in o]
    if isinstance(o, dict): return {k: placeholders(v) for k, v in o.items()}
    return o


def comparable(R):
    """What a merge report says that does not depend on the machine, the run, or the digests of the release it ran under."""
    E = R.get("evidence") or {}
    keep = {"ok": R.get("ok"), "conflicts": R.get("conflicts"), "problems": R.get("problems"),
            "branches": [{k: b[k] for k in ("name", "changed", "partitions")} for b in R.get("branches", [])],
            "holds": sorted((h["check"], h["source"], h["cacheable"]) for h in E.get("holds", [])), "rerun": sorted(h["check"] for h in E.get("rerun", [])),
            "cross_partition": sorted((x["branch"], x["check"], tuple(x["rests_on"])) for x in E.get("cross_partition", []))}
    if "judge" in R: keep["judge"] = {k: R["judge"][k] for k in ("exit", "unready", "reused", "first_failure", "accepted")}
    return keep


def holds_cacheable(R): return sorted(h["check"] for h in R.get("evidence", {}).get("holds", []) if h["cacheable"])
def cross(R): return {(x["branch"], x["check"]) for x in R.get("evidence", {}).get("cross_partition", [])}
def partitions(R): return {b["name"]: b["partitions"] for b in R.get("branches", [])}
def rerun(R): return {x["check"] for x in R.get("evidence", {}).get("rerun", [])}
def owned(d): return {str(q.relative_to(d)): q.read_bytes() for q in d.rglob("*") if q.is_file() and "__pycache__" not in q.parts and (q.relative_to(d).parts[0] in ("app", "design", "gen", "service", "ui") or q.relative_to(d).parts == ("app.manifest.yaml",))}


# 6. the base and each branch alone
base_c = fj_tree("base-build-a"); ev_base = fjn("base-build-a")
code, cb, EB0 = judge(ROOT, base_c, ev_base)
expect("fork-join: the base, examples/build-a, is accepted by the pristine release", code == 0 and str(cb.get("behavioral_assurance")).startswith("passed") and cb.get("application_delivery") == "passed", (code, cb.get("application_delivery")))
CACHE = sorted(["kernel", *[r["id"] for r in EB0["records"] if r.get("kind") == "tlc"]])    # the cacheable checks: the proof and every model check
STARTS_SERVICE = {"lifecycle", "boundary", "delivery"}
cands, evs = {}, {}
for n in BRANCHES:
    cands[n], evs[n] = fj_tree(f"build-a+{n}", n), fjn(n)
    code, c_, E_ = judge(ROOT, cands[n], evs[n], reuse=ev_base)
    expect(f"fork-join: {n} alone is accepted, with the base's evidence offered, which reuses exactly the proof and the model checks",
           code == 0 and c_.get("application_delivery") == "passed" and reused_ids(E_) == CACHE, (code, c_.get("application_delivery"), reused_ids(E_)))
changed = {n: sorted(str(q.relative_to(FJ / n)) for q in (FJ / n).rglob("*") if q.is_file()) for n in BRANCHES}
expect("fork-join: the branches are overlays: agent-a the storage-profile swap (manifest and service files), agent-b the page, agent-c the service without its /openapi.yaml route",
       changed == {"agent-a": ["app.manifest.yaml", "service/app.py", "service/migrate.py", "service/run.py"], "agent-b": ["ui/index.html"], "agent-c": ["service/app.py"]}, changed)

# 7. a + b: disjoint, and the judge on the merged tree accepts it
code, Rab = fj_merge("agent-a_agent-b", ["agent-a", "agent-b"])
J = Rab.get("judge", {}); Eab = json.loads((fjn("agent-a_agent-b") / "evidence/evidence.json").read_text()) if (fjn("agent-a_agent-b") / "evidence/evidence.json").is_file() else {"records": []}
expect("fork-join a+b: no conflict; the branches touch disjoint partitions (a: integration and migration, b: presentation)",
       code == 0 and not Rab.get("conflicts") and not Rab.get("problems") and partitions(Rab) == {"agent-a": ["integration", "migration"], "agent-b": ["presentation"]}, (code, Rab.get("conflicts"), partitions(Rab) if Rab else None))
expect("fork-join a+b: the judge on the merged tree accepts it and the merge stands", code == 0 and Rab.get("ok") and J.get("accepted") and not J.get("unready") and J.get("first_failure") is None, (code, J.get("unready"), J.get("first_failure")))
fresh = {r["id"] for r in Eab["records"] if not r.get("reused_from")}
expect("fork-join a+b: the judge reused exactly the cacheable records (the proof and every model check); every other check, including each that starts the service, ran again",
       J.get("reused") == CACHE and holds_cacheable(Rab) == CACHE and STARTS_SERVICE <= fresh and STARTS_SERVICE <= rerun(Rab)
       and not set(CACHE) & fresh, (J.get("reused"), sorted(STARTS_SERVICE - fresh)))
expect("fork-join a+b: each branch's service-starting results rest on the other branch's partition, are listed under cross_partition, and were not reused",
       all((n, c) in cross(Rab) for n in ("agent-a", "agent-b") for c in sorted(STARTS_SERVICE)) and not {c for _, c in cross(Rab)} & set(J.get("reused", [])),
       sorted(cross(Rab)))
M = fjn("agent-a_agent-b") / "merged"; want_tree = owned(base_c)
for n in ("agent-a", "agent-b"): want_tree.update({f: (FJ / n / f).read_bytes() for f in changed[n]})
expect("fork-join a+b: the merged application is the base with both branches' files, nothing else", M.is_dir() and owned(M) == want_tree)

# 8., 9. b + c and a + c: refused, each for exactly its reason, by validation/judge_wrong.py --handoff (against fork-join/expected.yaml)
r = subprocess.run([PY, "validation/judge_wrong.py", "--handoff", FJ, fj], cwd=ROOT, capture_output=True, text=True)
for line in r.stdout.splitlines(): print("    " + line[:260])
expect("fork-join: validation/judge_wrong.py --handoff: b+c is refused by the judge at delivery on exactly the workflows expected.yaml names, and a+c is refused statically on exactly its conflicts", r.returncode == 0, r.stdout[-800:] + r.stderr[-400:])
Rbc = json.loads((fjn(NEG["agent-b+agent-c"]) / "merge-report.json").read_text()) if (fjn(NEG["agent-b+agent-c"]) / "merge-report.json").is_file() else {"branches": []}
Rac = json.loads((fjn(NEG["agent-a+agent-c"]) / "merge-report.json").read_text()) if (fjn(NEG["agent-a+agent-c"]) / "merge-report.json").is_file() else {"branches": []}
Jbc = Rbc.get("judge", {}); Cbc = json.loads((fjn(NEG["agent-b+agent-c"]) / "evidence/app-claims.json").read_text()) if (fjn(NEG["agent-b+agent-c"]) / "evidence/app-claims.json").is_file() else {}
expect("fork-join b+c: the branches touch disjoint partitions (b: presentation, c: integration) and there is no static conflict",
       Rbc.get("conflicts") == [] and Rbc.get("problems") == [] and partitions(Rbc) == {"agent-b": ["presentation"], "agent-c": ["integration"]}, (Rbc.get("conflicts"), partitions(Rbc)))
expect("fork-join b+c: the cacheable evidence still holds and the judge reused exactly it", holds_cacheable(Rbc) == CACHE and Jbc.get("reused") == CACHE, (holds_cacheable(Rbc), Jbc.get("reused")))
expect("fork-join b+c: the judge on the merged tree refuses it at delivery, everything before delivery passing, and the merge is refused",
       Rbc.get("ok") is False and Jbc.get("accepted") is False and Jbc.get("first_failure") == "delivery" and Jbc.get("unready") == ["application_delivery"]
       and str(Cbc.get("behavioral_assurance")).startswith("passed") and Cbc.get("application_delivery") == "failed", (Jbc.get("first_failure"), Jbc.get("unready"), Cbc.get("application_delivery")))
expect("fork-join b+c: each branch passed delivery alone; each one's delivery result rests on the other's partition, is listed under cross_partition, and was not reused",
       {("agent-b", "delivery"), ("agent-c", "delivery")} <= cross(Rbc) and "delivery" not in Jbc.get("reused", []), sorted(cross(Rbc)))
expect("fork-join a+c: refused statically on partition `integration` (and the textual conflict in service/app.py, which both rewrote); the judge did not run and no merged tree was written",
       Rac.get("ok") is False and {(c["kind"], c.get("partition") or c.get("path")) for c in Rac.get("conflicts", [])} == {("partition", "integration"), ("textual", "service/app.py")}
       and "judge" not in Rac and "merged" not in Rac and not (fjn(NEG["agent-a+agent-c"]) / "merged").exists(), Rac.get("conflicts"))

# 10. the fresh reports against recorded/
REC = {"agent-a_agent-b": "merge-a-b.json", "agent-b_agent-c": "merge-b-c.json", "agent-a_agent-c": "merge-a-c.json"}
FRESH = {"agent-a_agent-b": Rab, "agent-b_agent-c": Rbc, "agent-a_agent-c": Rac}
if RECORD:
    (FJ / "recorded").mkdir(exist_ok=True)
    for k, f in REC.items(): (FJ / "recorded" / f).write_text(json.dumps(placeholders(FRESH[k]), indent=1) + "\n")
    print(f"    recorded {sorted(REC.values())} under {FJ / 'recorded'}")
for k, f in REC.items():
    p_ = FJ / "recorded" / f; old = json.loads(p_.read_text()) if p_.is_file() else None
    expect(f"fork-join: the fresh report for {k.replace('_', ' + ')} agrees with recorded/{f} on conflicts, partitions touched, evidence that holds or runs again, judge verdict, first failure and reused checks",
           old is not None and old.get("format") == "pith.merge-report/v1" and comparable(old) == comparable(FRESH[k]) and "/Users/" not in p_.read_text() and "/private/" not in p_.read_text(),
           "missing" if old is None else {x: (comparable(old)[x], comparable(FRESH[k])[x]) for x in comparable(FRESH[k]) if comparable(old).get(x) != comparable(FRESH[k])[x]})
rec["fork_join"] = {"cacheable": CACHE, "branches": {n: changed[n] for n in BRANCHES},
                    "merges": {k.replace("_", "+"): {"ok": R_.get("ok"), "conflicts": [{x: c[x] for x in c if x != "branches"} for c in R_.get("conflicts", [])],
                                                     "partitions": partitions(R_), "judge_accepted": (R_.get("judge") or {}).get("accepted"), "first_failure": (R_.get("judge") or {}).get("first_failure"),
                                                     "reused": (R_.get("judge") or {}).get("reused")} for k, R_ in FRESH.items()}}

rec["ok"] = not failures; rec["failures"] = failures
(OUT / "handoff-record.json").write_text(json.dumps(rec, indent=1, default=str))
print(f"handoff: {'every expectation holds' if not failures else f'{len(failures)} FAILED'} ({OUT / 'handoff-record.json'})")
sys.exit(0 if not failures else 1)
