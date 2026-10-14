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

Writes OUT/handoff-record.json; exit 1 if any expectation fails."""
import json, pathlib, shutil, socket, subprocess, sys, tempfile, time, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent; PY = sys.executable
OUT = pathlib.Path(sys.argv[1]).resolve(); shutil.rmtree(OUT, ignore_errors=True); OUT.mkdir(parents=True)
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
    r = subprocess.run([PY, "-I", rel / "gate/app_gate.py", "--candidate", cand, "--out", out, "--expected-release", release_id(rel)] + (["--reuse", reuse] if reuse else []),
                       cwd=ROOT, capture_output=True, text=True)
    c = json.loads((out / "app-claims.json").read_text()) if (out / "app-claims.json").exists() else {}
    E = json.loads((out / "evidence.json").read_text()) if (out / "evidence.json").exists() else {"records": []}
    return r.returncode, c, E


def reused(E): return sorted(r["check"] for r in E["records"] if r.get("reused_from"))


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

rec["ok"] = not failures; rec["failures"] = failures
(OUT / "handoff-record.json").write_text(json.dumps(rec, indent=1, default=str))
print(f"handoff: {'every expectation holds' if not failures else f'{len(failures)} FAILED'} ({OUT / 'handoff-record.json'})")
sys.exit(0 if not failures else 1)
