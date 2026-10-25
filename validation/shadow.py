#!/usr/bin/env python3
"""validation/shadow.py OUT — a production drift, caught beside a live service, shrunk into a regression trace, replayed
(docs/rfc/0007-autonomous-assurance-and-runtime-composition.md § 7).

The brownfield club desk (examples/club-desk) is assembled with the release into a scratch DEPLOYMENT (the way the judge assembles a
workspace, but not judged), and so is a drifted copy of it whose own service code reads its reported availability from a cache that
lags one hold behind once an account is busy (validation/shadow-drift/drifted_repo.py). The same 30 mixed operations are driven
through the frozen client against each, and a sidecar (`python3 gen/out/monitor.py shadow`, a separate process) tails each
service's /events:

  1. the original: no divergence, and the shadow really ran the oracle (mode oracle, every committed operation replayed)
  2. the drifted desk: indistinguishable by decision, hold or account view for the first fifteen operations and afterwards (the
     core still decides on the true state); the stale figure shows in the receipts and the events from the sixteenth operation
     on, and the sidecar, tailing live, records the divergence (AVAIL-MISMATCH; the oracle disputes available_at_decision)
  3. `gate/cli.py trace harvest` shrinks the 15 reconstructed operations to the handful the divergence depends on, renders them
     (traces.dfy), and writes the unsigned provenance and a DRAFT revocation
  4. the rendering passes `dafny test` against the verified core (it encodes what the CORE does) and fails when its availability is
     the figure the drifted service reported (the test has teeth)
  5. `gate/cli.py trace replay` FAILS on the drifted desk's own files (on the same stale figure, one authorization sooner than the log
     showed it, because the shrunk steps leave out the capture and so keep a hold more live) and PASSES on the accepted club-desk
  6. the draft says the deployed artifact is not the accepted one, which the digests confirm: the drift is in the deployment's own
     code (a hot patch of profiles/ would be replaced by the release's pristine file the moment a candidate is assembled, so it
     could be neither judged nor replayed), the evidence never covered it, and nothing about the release is revoked
  7. a record whose observed answer is the oracle's is not harvested (nothing to harvest: the oracle agrees)

Writes OUT/shadow-record.json; exit 1 if any expectation fails. Limits: one drift, one workload; the shadow sees only what the service
emits (a side effect that bypasses the events is invisible); a trace shrunk against the oracle is a claim about the oracle until the
replay shows a candidate fails it (here it does).
"""
import json, os, pathlib, re, shutil, signal, socket, subprocess, sys, time, tempfile
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent; PY = sys.executable
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "gate"))
from obligations.service.client import Client
import deploy as DEPLOY
OUT = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else pathlib.Path(tempfile.mkdtemp(prefix="shadow-"))
OUT.mkdir(parents=True, exist_ok=True)
rec = {"format": "pith.shadow-record/v1", "checks": []}; failures = []


def expect(what, cond, detail=""):
    rec["checks"].append({"what": what, "ok": bool(cond), **({"detail": detail} if detail else {})})
    print(f"[{'ok' if cond else 'FAIL'}] {what}" + (f" — {detail}" if detail and not cond else ""))
    if not cond: failures.append(what)


def run(cmd, **kw): return subprocess.run(cmd, capture_output=True, text=True, timeout=kw.pop("timeout", 600), **kw)
def cli(*args): return run([PY, str(ROOT / "gate/cli.py"), *args, "--json"])
def jload(r):
    try: return json.loads(r.stdout)
    except ValueError: return {"unparsed": (r.stdout + r.stderr)[-600:]}


# ---- deployments --------------------------------------------------------------------------------------------------------------
RELEASE = run([PY, str(ROOT / "gate/release.py"), "id"]).stdout.strip()


def assemble(candidate, dest):
    """The release (the evaluator and the pack's policy dirs, pack.yaml, the seal) plus the candidate's files: what validation/judge_example.sh
    builds, deployed instead of judged."""
    dest = pathlib.Path(dest); shutil.rmtree(dest, ignore_errors=True); dest.mkdir(parents=True)
    ignore = shutil.ignore_patterns("__pycache__", ".pytest_cache", ".hypothesis", ".DS_Store")
    for d in run([PY, str(ROOT / "gate/release.py"), "dirs"]).stdout.split(): shutil.copytree(ROOT / d, dest / d, ignore=ignore)
    for f in ("pack.yaml", "release.seal.json"): shutil.copy(ROOT / f, dest / f)
    shutil.copytree(candidate, dest, dirs_exist_ok=True, ignore=ignore)
    for f in [dest / "claims-from-release.json", *dest.glob("*.example")]: f.unlink(missing_ok=True)
    return dest


def drifted_candidate(dest):
    """examples/club-desk with its own service code changed after acceptance: the drifted store, and service/run.py serving it."""
    dest = pathlib.Path(dest); shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(ROOT / "examples/club-desk", dest, ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"))
    shutil.copy(ROOT / "validation/shadow-drift/drifted_repo.py", dest / "service/drifted_repo.py")
    run_py = dest / "service/run.py"; src = run_py.read_text(); old = "from profiles.sqlite.repo import Repo"
    assert old in src; run_py.write_text(src.replace(old, "from service.drifted_repo import Repo"))
    return dest


class Deployment:
    """A service started the way a deployment starts it (python -I service/run.py --port P --db PATH), its database and log in a scratch directory."""
    def __init__(self, root, name):
        self.root, self.name = pathlib.Path(root), name; self.db = OUT / f"db-{name}" / "state.db"; self.db.parent.mkdir(parents=True, exist_ok=True)
    def start(self):
        with socket.socket() as s: s.bind(("127.0.0.1", 0)); self.port = s.getsockname()[1]
        self.log = open(OUT / f"service-{self.name}.log", "wb")
        self.proc = subprocess.Popen([PY, "-I", "service/run.py", "--port", str(self.port), "--db", str(self.db)], cwd=self.root, stdout=self.log, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, start_new_session=True)
        self.url = f"http://127.0.0.1:{self.port}"; self.client = Client(self.url); t0 = time.time()
        while time.time() - t0 < 30:
            if self.proc.poll() is not None: raise SystemExit(f"{self.name}: the service exited early (code {self.proc.returncode}); see {self.log.name}")
            try:
                if self.client.events()[0] == 200: return self
            except Exception: pass
            time.sleep(0.1)
        raise SystemExit(f"{self.name}: the service did not become ready")
    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try: self.proc.wait(10)
            except subprocess.TimeoutExpired: os.killpg(self.proc.pid, 9)
        self.log.close()


def sidecar(dep, log, *extra, follow=False):
    """The shadow as a separate process: the generated monitor of the DEPLOYMENT, tailing its service's /events."""
    cmd = [PY, "-I", str(dep.root / "gen/out/monitor.py"), "shadow", "--events", dep.url, "--out", str(log), "--release", RELEASE, "--artifact", ARTIFACT[dep.name], *extra]
    return subprocess.Popen(cmd + ([] if follow else ["--once"]), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


# ---- the workload: ordinary use of a desk, 30 operations --------------------------------------------------------------------------
# Account 1 (limit 1000) is the busy one: from operation 16 it has three live holds when a request is decided.
WORKLOAD = [
    ("create", 1, 1000), ("create", 2, 500), ("create", 3, 80),
    ("auth", 1, 1, 100), ("auth", 2, 1, 150), ("auth", 1, 2, 200),
    ("auth", 1, 1, 100),                                   # a retry: its receipt, no event
    ("release", 2, 1), ("auth", 2, 2, 600),                # declined: over the limit
    ("auth", 3, 1, 80), ("auth", 3, 2, 1),                 # the limit used up exactly, then declined
    ("capture", 1, 1),                                     # 100 posted
    ("auth", 1, 3, 50), ("auth", 1, 4, 120),               # account 1: three live holds (2, 3, 4)
    ("release", 3, 1),
    ("auth", 1, 5, 400),                                   # 16: decided with three live holds: the stale cache reports 650, the true availability is 530
    ("auth", 1, 6, 100),
    ("auth", 1, 7, 120),                                   # declined (30 available) but the stale cache reports 130: the receipt contradicts itself
    ("release", 1, 3), ("capture", 1, 2), ("auth", 1, 8, 30),
    ("auth", 2, 3, 500), ("auth", 2, 3, 400),              # a replay with another amount: refused
    ("auth", 9, 1, 10),                                    # unknown account
    ("auth", 1, 9, 0),                                     # outside the proof's domain
    ("release", 1, 99), ("capture", 2, 3), ("auth", 2, 4, 10),
    ("view", 1), ("view", 2),
]
EVENTED = 15             # operations that emit events before the first drifted one, in the oracle's vocabulary (operation 16 is the 15th, index 14)


def drive(client, ops, pause=0.0):
    out = []
    for op in ops:
        k = op[0]
        call = {"create": client.create, "auth": client.authorize, "release": client.release, "capture": client.capture, "view": client.account}[k]
        out.append(call(*op[1:]))
        if pause: time.sleep(pause)
    return out


def strip(body): return {k: v for k, v in body.items() if k != "available_at_decision"} if isinstance(body, dict) else body


# ================================================================================================================================
ACCEPTED = ROOT / "examples/club-desk"
cand_drifted = drifted_candidate(OUT / "candidates/drifted-club-desk")
dep_ok = Deployment(assemble(ACCEPTED, OUT / "deploy/club-desk"), "club-desk")
dep_bad = Deployment(assemble(cand_drifted, OUT / "deploy/drifted-club-desk"), "drifted-club-desk")
ARTIFACT = {"club-desk": DEPLOY.artifact_digest(ACCEPTED, ROOT), "drifted-club-desk": DEPLOY.artifact_digest(cand_drifted, ROOT)}
expect("a deployment is the release plus the candidate's files, and the drifted desk is a different artifact from the accepted one",
       ARTIFACT["club-desk"] != ARTIFACT["drifted-club-desk"] and all((d.root / "gen/out/monitor.py").is_file() and (d.root / "obligations/boundary/oracle.py").is_file() for d in (dep_ok, dep_bad)))
def regenerates_identically(dep):
    """gen.current on the deployment: its generator reproduces its own gen/out/monitor.py byte for byte (the deployment is left as it was)."""
    mon = dep.root / "gen/out/monitor.py"; before = mon.read_bytes()
    r = run([PY, "obligations/boundary/generate.py"], cwd=dep.root); same = r.returncode == 0 and mon.read_bytes() == before; mon.write_bytes(before)
    return same
expect("the deployed monitor is the generator's output (gen.current), so the shadow in it is the one the pack ships", all(regenerates_identically(d) for d in (dep_ok, dep_bad)))

answers = {}; logs = {dep.name: OUT / f"divergence-{dep.name}.jsonl" for dep in (dep_ok, dep_bad)}
try:
    # -- 1. the accepted desk: ordinary use, shadowed -------------------------------------------------------------------------
    dep_ok.start(); answers["ok"] = drive(dep_ok.client, WORKLOAD)
    sc = sidecar(dep_ok, logs["club-desk"]); out, err = sc.communicate(timeout=120)
    s_ok = json.loads(out.splitlines()[-1]) if out.strip() else {}
    expect("the accepted club desk: the sidecar reads its whole feed, replays every committed operation through the oracle and records no divergence",
           sc.returncode == 0 and s_ok.get("mode") == "oracle" and s_ok.get("divergences") == 0 and s_ok.get("errors") == 0 and not logs["club-desk"].exists()
           and s_ok.get("operations", 0) >= EVENTED and s_ok.get("alerts") == [], f"exit {sc.returncode} {s_ok} {err[-300:]}")
    rec["accepted"] = s_ok

    # -- 2. the drifted desk: live tailing while it serves -------------------------------------------------------------------
    dep_bad.start(); head = drive(dep_bad.client, WORKLOAD[:10])
    live = sidecar(dep_bad, logs["drifted-club-desk"], "--poll", "0.2", follow=True)
    tail = drive(dep_bad.client, WORKLOAD[10:], pause=0.02); answers["bad"] = head + tail
    t0 = time.time()
    while time.time() - t0 < 30 and not logs["drifted-club-desk"].exists(): time.sleep(0.1)
    time.sleep(1.5); live.send_signal(signal.SIGTERM); out, err = live.communicate(timeout=60)
    s_bad = json.loads(out.splitlines()[-1]) if out.strip() else {}
    total_events = len(dep_bad.client.events()[1])
    expect("the drifted desk's sidecar tails it live (a separate process), reads every event and stops cleanly on SIGTERM",
           live.returncode == 0 and s_bad.get("events") == total_events and s_bad.get("mode") == "oracle" and s_bad.get("errors") == 0, f"exit {live.returncode} {s_bad} {err[-300:]}")
    rec["drifted"] = s_bad

    # -- 3. the drift is invisible in ordinary use ---------------------------------------------------------------------------
    pairs = list(zip(answers["ok"], answers["bad"]))
    differing = [i + 1 for i, (a, b) in enumerate(pairs) if a != b]
    expect("the drift is invisible in ordinary use: same status, decision, hold and account view for every one of the 30 operations; only the reported "
           "available_at_decision differs, first at operation 16", all(a[0] == b[0] and strip(a[1]) == strip(b[1]) for a, b in pairs) and differing[:1] == [16] and len(differing) >= 3,
           f"differing operations {differing}")
    expect("and the decision the contract requires was made at operation 18 (declined) with a receipt that says more was available than was asked for",
           answers["bad"][17][1]["decision"] == "DECLINED" and answers["bad"][17][1]["available_at_decision"] >= 120 and answers["ok"][17][1]["available_at_decision"] == 30,
           str(answers["bad"][17]))

    # -- 4. the sidecar's divergence log -----------------------------------------------------------------------------------
    lines = [json.loads(l) for l in logs["drifted-club-desk"].read_text().splitlines()] if logs["drifted-club-desk"].exists() else []
    first = lines[0] if lines else {}
    d = first.get("disagreement") or {}
    expect("the sidecar recorded pith.divergence/v1 lines; the first is operation 16 (the 15th committed operation): AVAIL-MISMATCH, the oracle disputes only available_at_decision (530, not 650)",
           len(lines) >= 2 and first.get("format") == "pith.divergence/v1" and first.get("alert") == "AVAIL-MISMATCH" and first.get("diverged_at") == EVENTED - 1
           and d.get("fields") == ["available_at_decision"] and d["expected"]["available_at_decision"] == 530 and d["observed"]["available_at_decision"] == 650
           and len(first.get("operations", [])) == EVENTED and first.get("release_digest") == RELEASE and first.get("artifact_digest") == ARTIFACT["drifted-club-desk"]
           and not first.get("lossy") and "DecideCorrect" in first.get("records", []), json.dumps(first)[:600])
    expect("a later record is the contradicting receipt: the monitor's P0-obs beside the availability mismatch",
           any("P0-obs" in [a["code"] for a in r.get("alerts", [])] for r in lines[1:]), str([[a["code"] for a in r.get("alerts", [])] for r in lines]))

    # -- 5. harvest ---------------------------------------------------------------------------------------------------------
    H = OUT / "harvest"; shutil.rmtree(H, ignore_errors=True)
    h = jload(cli("trace", "harvest", str(logs["drifted-club-desk"]), "--pack", str(ROOT), "--out", str(H)))
    steps = h.get("steps", {})
    expect("harvest shrinks the reconstructed operations to the handful the divergence depends on", h.get("ok") is True and steps.get("from") == EVENTED and 0 < steps.get("to", 99) <= 8
           and sorted(h.get("files", [])) == ["revocation.draft.yaml", "trace.yaml", "traces.dfy", "traces.provenance.yaml"], json.dumps(h)[:600])
    trace = yaml.safe_load((H / "trace.yaml").read_text()) if (H / "trace.yaml").exists() else {}
    last = (trace.get("steps") or [{}])[-1]
    expect("the trace's last step is the authorization the service answered 650 to, where the contract requires 530, and it begins with the account's creation",
           last.get("action") == "authorize" and last.get("expected", {}).get("available_at_decision") == 530 and trace.get("observed_at_divergence", {}).get("available_at_decision") == 650
           and trace["steps"][0]["action"] == "create_account" and trace.get("records") == first.get("records"), json.dumps(last))
    rec["harvest"] = {"operations_before": steps.get("from"), "steps_after": steps.get("to"), "steps": [{k: s[k] for k in ("action", "args", "expected")} for s in trace.get("steps", [])],
                      "observed_at_divergence": trace.get("observed_at_divergence")}

    # -- 6. the rendering runs against the verified core ---------------------------------------------------------------------
    K = OUT / "dafny"; shutil.rmtree(K, ignore_errors=True); (K / "kernel/adequacy").mkdir(parents=True)
    for sub in ("core", "spec"): shutil.copytree(ROOT / "kernel" / sub, K / "kernel" / sub, ignore=shutil.ignore_patterns("py", "__pycache__"))
    dfy = (H / "traces.dfy").read_text() if (H / "traces.dfy").exists() else ""
    (K / "kernel/adequacy/traces.dfy").write_text(dfy)
    DAFNY = os.environ.get("DAFNY", "dafny")
    t = run([DAFNY, "test", "--target", "py", "traces.dfy"], cwd=K / "kernel/adequacy")
    expect("the rendered traces.dfy passes `dafny test` against the verified core: the core answers the contract's 530 and every other step as the trace expects",
           t.returncode == 0 and "PASSED" in t.stdout and "FAILED" not in t.stdout and 'include "../core/Kernel.dfy"' in dfy and "method {:test}" in dfy, (t.stdout + t.stderr)[-500:])
    needle = "== 530;"; wrong = dfy.replace(needle, "== 650;")
    (K / "kernel/adequacy/traces_wrong.dfy").write_text(wrong)
    tw = run([DAFNY, "test", "--target", "py", "traces_wrong.dfy"], cwd=K / "kernel/adequacy")
    expect("the same rendering with the figure the drifted service reported (650) FAILS: it is a test of the core, not a restatement of the log",
           dfy.count(needle) == 1 and tw.returncode != 0 and "FAILED" in tw.stdout and "expectation violation" in tw.stdout, (tw.stdout + tw.stderr)[-400:])
    (H / "traces.dfy").write_text(dfy)
    rec["traces_dfy"] = dfy

    # -- 7. replay ------------------------------------------------------------------------------------------------------------
    r_bad = jload(cli("trace", "replay", str(H / "trace.yaml"), "--pack", str(ROOT), "--candidate", str(cand_drifted)))
    out_bad = r_bad.get("output", "") if isinstance(r_bad.get("output"), str) else ""
    m = re.search(r"step (\d+) of (\d+) \(authorize[^\n]*the service answered ([^\n]*?), the contract requires", out_bad)
    expect("replay FAILS on the drifted desk's own files, on the reported availability (the shrunk steps trigger the drift one authorization sooner than the log did)",
           r_bad.get("ok") is False and r_bad.get("exit") == 1 and m is not None and m.group(2) == str(steps.get("to")) and "available_at_decision" in m.group(3), out_bad[-600:])
    rec["replay_failed_at"] = {"step": m and int(m.group(1)), "of": steps.get("to"), "answered": m and m.group(3)}
    r_ok = jload(cli("trace", "replay", str(H / "trace.yaml"), "--pack", str(ROOT), "--candidate", str(ACCEPTED)))
    expect("replay PASSES on the accepted club desk (the trace is a regression test that separates them)", r_ok.get("ok") is True and r_ok.get("exit") == 0, str(r_ok)[-500:])
    expect("the replay judged the artifacts the deployments are (digests equal)",
           r_bad.get("artifact_digest") == ARTIFACT["drifted-club-desk"] and r_ok.get("artifact_digest") == ARTIFACT["club-desk"], f"{r_bad.get('artifact_digest')} {r_ok.get('artifact_digest')}")
    rec["replay"] = {"drifted": {"ok": r_bad.get("ok"), "output": (r_bad.get("output") or "")[-600:]}, "accepted": {"ok": r_ok.get("ok")}}

    # -- 8. provenance and the draft revocation ---------------------------------------------------------------------------------
    prov = yaml.safe_load((H / "traces.provenance.yaml").read_text()); rev = yaml.safe_load((H / "revocation.draft.yaml").read_text())
    rel = (rev.get("releases") or [{}])[0]
    expect("the provenance is unsigned, names no reviewer, and says what it came from and how it was shrunk",
           prov.get("status") == "unsigned" and prov.get("reviewers") == [] and prov["source"]["release_digest"] == RELEASE and prov["source"]["artifact_digest"] == ARTIFACT["drifted-club-desk"]
           and prov["source"]["alert"] == "AVAIL-MISMATCH" and prov["shrink"]["from_steps"] == EVENTED and prov["shrink"]["to_steps"] == steps.get("to") and prov["shrink"]["against"] == "oracle"
           and "replay" in prov.get("note", ""), json.dumps(prov)[:400])
    expect("the revocation is a DRAFT, not filed, for this release, with the effect `unsound-for` the records, and its advisory says to file it only if the deployment was the accepted artifact",
           str(rev.get("status", "")).startswith("DRAFT") and rel.get("digest") == RELEASE and rel.get("effect", "").startswith("unsound-for:") and "DecideCorrect" in rel.get("effect", "")
           and "650" in rel.get("reason", "") and "530" in rel.get("reason", "") and "deploy.py check" in rel.get("advisory", "") and "nothing is revoked" in rel.get("advisory", ""), json.dumps(rev)[:500])
    accepted_artifact = ARTIFACT["drifted-club-desk"] == ARTIFACT["club-desk"]
    expect("this draft is NOT to be filed: the drifted deployment is not the artifact the evidence accepted (its own code differs), so the release is not shown unsound",
           accepted_artifact is False)
    rec["revocation"] = {"status": rev.get("status"), "effect": rel.get("effect"), "reason": rel.get("reason"), "deployment_is_the_accepted_artifact": accepted_artifact,
                         "artifact_digests": ARTIFACT, "release": RELEASE}

    # -- 9. a record that is not a divergence is not harvested ------------------------------------------------------------------
    doctored = dict(first); ops = json.loads(json.dumps(first["operations"])); k = first["diverged_at"]; ops[k]["observed"] = ops[k]["expected"]; doctored["operations"] = ops
    (OUT / "not-a-divergence.json").write_text(json.dumps(doctored))
    n = cli("trace", "harvest", str(OUT / "not-a-divergence.json"), "--pack", str(ROOT), "--out", str(OUT / "harvest-none")); nj = jload(n)
    expect("a record whose observed answer is the oracle's is refused: nothing to harvest, the oracle agrees", n.returncode == 1 and nj.get("ok") is False
           and any("nothing to harvest" in p for p in nj.get("problems", [])) and any("oracle agrees" in p for p in nj.get("problems", []))
           and not (OUT / "harvest-none").exists(), str(nj)[:300])
finally:
    for dep in (dep_ok, dep_bad):
        try: dep.stop()
        except Exception: pass

rec["ok"] = not failures; rec["failures"] = failures
(OUT / "shadow-record.json").write_text(json.dumps(rec, indent=1, default=str))
print(f"\n{len(rec['checks']) - len(failures)}/{len(rec['checks'])} expectations hold; wrote {OUT / 'shadow-record.json'}")
sys.exit(1 if failures else 0)
