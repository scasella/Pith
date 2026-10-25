"""validation/packets.py — the M4 failure categories, end to end: one run of the reservation pack's pristine gate per
category, each built to fail in that way, and the task packet must name it. Every packet is also checked against
gate/schemas/task-packet.schema.json. Runs after a judge of examples/build-a has left its candidate (the kernel proof is
reused from the first run, so only the first run proves it).

    python3 validation/packets.py <evidence-root>

  evidence_missing        a fresh seed: no design module
  contract_change         build-a with a frozen harness file edited, judged by its own checkout's gate as an agent would
  toolchain_unavailable   build-a with TLA2TOOLS pointing at nothing (the model checks cannot run)
  not_exercised           build-a whose design never retries (a coverage obligation is not reached)
  infrastructure          build-a whose design module is a directory (the evaluator cannot read it; it must say so, not crash)
  done                    build-a as it is (state done; human approval pending and not the candidate's)

Since v0.13.0 every run's distilled packet (task-packet.distilled.json, docs/rfc/0007 § 5) is also checked: schema-valid, and no host
path, stack frame or identifier of the judge's own code in it. Then examples/wrong/retry-not-released is judged and its counterexample
must be a shrunk trace of domain steps naming Receipts, and every wrong-* evidence directory beside the evidence root (judge_wrong.py's)
is distilled again with its pack's policy root and checked the same way.
"""
import json, os, pathlib, re, shutil, subprocess, sys, tempfile
import jsonschema, yaml

SEED = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SEED))
from gate import packet as PT
S = json.loads((SEED / "gate/schemas/task-packet.schema.json").read_text())
root = pathlib.Path(sys.argv[1]); root.mkdir(parents=True, exist_ok=True)
REL = subprocess.run([sys.executable, str(SEED / "gate/release.py"), "id"], capture_output=True, text=True).stdout.strip()

# What a distilled packet (docs/rfc/0007 § 5) must not hold. Strings only: the packet's own keys, and the field names of a service's
# own answers, are the vocabulary of the format and the contract, not of the judge.
HOST = [re.compile(p) for p in (r"/Users/", r"/home/", r"/private/", r"/var/folders/", r"/tmp/", r"/opt/", r'File "', r"Traceback", r"<[A-Za-z_]\w*(?:\.\w+)+ object at 0x",
                                r"^\s*at\s+(?:async\s+)?[^\s(]+\s+\([^)]*:\d+:\d+\)\s*$", r"^\s*at\s+[^\s(]+:\d+:\d+\s*$")]      # a Node.js frame
RESERVATION_STEPS = {"create_account", "authorize", "release", "capture"}


def strings(o):
    if isinstance(o, str): yield o
    elif isinstance(o, list):
        for x in o: yield from strings(x)
    elif isinstance(o, dict):
        for v in o.values(): yield from strings(v)


def leaks(D, code):
    """Every way the packet leaks: a host path, a stack frame, a Python file name, a repr with an address, or an identifier the
    release's own Python code defines (and the pack's documents do not use)."""
    found = []
    for t in strings(D):
        found += [f"{p.pattern!r} in {t[:80]!r}" for p in HOST for l in t.splitlines() if p.search(l)]
        found += [f"identifier {w} in {t[:80]!r}" for w in sorted(set(PT.WORD.findall(t)) & code)]
    return found


def distilled(out, policy=SEED):
    """The distilled packet a run wrote: schema-valid, and no leak, judged against the vocabulary of the release it was judged under."""
    D = json.loads((out / "task-packet.distilled.json").read_text()); jsonschema.validate(D, S)
    P = yaml.safe_load((pathlib.Path(policy) / "pack.yaml").read_text()); _, code = PT.vocabulary(policy, P)
    return D, leaks(D, code) + leaks((out / "TASK.distilled.md").read_text(), code) + ([] if D.get("disclosure") == "redacted" else ["disclosure is not redacted"])


bad = 0


def candidate(example=None):
    d = pathlib.Path(tempfile.mkdtemp(prefix="pk-"))
    for x in subprocess.run([sys.executable, str(SEED / "gate/release.py"), "dirs"], capture_output=True, text=True).stdout.split():
        shutil.copytree(SEED / x, d / x, ignore=shutil.ignore_patterns("__pycache__"))
    for f in ("pack.yaml", "release.seal.json"): shutil.copy(SEED / f, d / f)
    if example:
        shutil.copytree(SEED / "examples" / example, d, dirs_exist_ok=True)
        for f in d.glob("*.example"): f.unlink()
        (d / "claims-from-release.json").unlink(missing_ok=True)
    return d


def judge(name, cand, env=None, reuse=None, local=False):
    """The pristine gate on the candidate (authoritative), or with local=True the candidate checkout's own gate, the way an
    agent runs it in its workspace (only there can an edited frozen file be seen: the pristine gate never reads it)."""
    out = root / f"pk-{name}"
    shutil.rmtree(out, ignore_errors=True)
    cmd = ([sys.executable, str(cand / "gate/app_gate.py")] if local else [sys.executable, "-I", str(SEED / "gate/app_gate.py"), "--candidate", str(cand)]) + \
          ["--out", str(out), "--expected-release", REL]
    if reuse: cmd += ["--reuse", str(reuse)]
    subprocess.run(cmd, env={**os.environ, **(env or {})}, capture_output=True, text=True)
    pk = json.loads((out / "task-packet.json").read_text()); jsonschema.validate(pk, S)
    D, problems = distilled(out)
    global bad
    bad += bool(problems); print(f"{'ok  ' if not problems else 'FAIL'} {name:22} distilled packet: schema-valid, disclosure {D.get('disclosure')}, " + ("no host path, stack frame or harness identifier" if not problems else f"LEAKS {problems[:3]}"))
    return out, pk


def expect(name, pk, state, category=None, check=None):
    global bad
    f = pk["first_failure"] or {}
    ok = pk["state"] == state and f.get("category") == category and (check is None or f.get("check", "").startswith(check))
    print(f"{'ok  ' if ok else 'FAIL'} {name:22} state={pk['state']:8} first={f.get('check')} category={f.get('category')} ({f.get('category_basis')})")
    bad += not ok


base, pk = judge("evidence-missing", candidate())
expect("evidence_missing", pk, "refused", "evidence_missing", "design.present")

d = candidate("build-a"); p = d / "obligations/service/lifecycle.py"; p.write_text(p.read_text() + "\n# weakened\n")
_, pk = judge("contract-change", d, reuse=base, local=True); expect("contract_change", pk, "refused", "contract_change", "evaluator.frozen-files-intact")

_, pk = judge("toolchain", candidate("build-a"), env={"TLA2TOOLS": "/nonexistent/tla2tools.jar"}, reuse=base)
expect("toolchain_unavailable", pk, "refused", "toolchain_unavailable", "design.safety")

d = candidate("build-a"); p = d / "design/Design.tla"; s = p.read_text()
assert "Begin(r) \\/ Commit(r) \\/ Resend(r) \\/ Release(r)" in s
p.write_text(s.replace("Begin(r) \\/ Commit(r) \\/ Resend(r) \\/ Release(r)", "Begin(r) \\/ Commit(r) \\/ Release(r)"))
_, pk = judge("not-exercised", d, reuse=base); expect("not_exercised", pk, "refused", "not_exercised", "design.coverage/CovRetry")

d = candidate("build-a"); t = (d / "design/Design.tla").read_text(); (d / "design/Design.tla").unlink(); (d / "design/Design.tla").mkdir(); (d / "design/Design.tla/Design.tla").write_text(t)
_, pk = judge("infrastructure", d, reuse=base); expect("infrastructure", pk, "refused", "infrastructure", "design.")

os.environ.setdefault("SEED_ALLOW_UNSANDBOXED_BROWSER", os.environ.get("SEED_ALLOW_UNSANDBOXED_BROWSER", ""))
_, pk = judge("done", candidate("build-a"), reuse=base)
expect("done", pk, "done", None)
if "human_approval" not in pk["not_yours"]: print("FAIL done: human_approval should be listed as not the candidate's"); bad += 1
print(f"{'ok' if not bad else 'FAIL'}: {6 - bad} of 6 category runs as expected; every packet schema-valid")

# ---- a known-wrong fixture's counterexample is a trace of domain steps, shrunk against the pack's offline oracle -----------
# retry-not-released: a retried release is answered "not released" instead of its receipt. The lifecycle harness puts the calls it
# made in the failing assertion's message (obligations/service/trace.py); the packet reads them, cuts them to what the oracle
# (obligations/boundary/oracle.py, the verified core) still answers the same way, and names the record.
nb = bad
out, pk = judge("retry-not-released", candidate("wrong/retry-not-released"), reuse=base)
expect("retry-not-released", pk, "refused", "violation", "lifecycle")
D, _ = distilled(out); cx = (D["first_failure"] or {}).get("counterexample") or {}; trace = cx.get("trace") or []; sh = cx.get("shrunk") or {}
checks = {"a trace of domain steps": bool(trace) and all(s.get("action") in RESERVATION_STEPS and isinstance(s.get("args"), dict) and "observed" in s for s in trace),
          "violated names Receipts": "Receipts" in (cx.get("violated") or []),
          "expected is the receipt and observed is not": cx.get("expected", {}).get("released") is True and cx.get("expected", {}).get("replayed") is True and cx.get("observed", {}).get("released") is False,
          "shrunk against the oracle to fewer steps": sh.get("against") == "oracle" and sh.get("to_steps", 99) < sh.get("from_steps", 0) and len(trace) == sh.get("to_steps"),
          "the last step is the retried release, with what the contract requires": bool(trace) and trace[-1].get("action") == "release" and trace[-1].get("expected") == cx.get("expected"),
          "the text reads as steps, not as a pytest diff": "Step " in cx.get("text", "") and "assert " not in cx.get("text", "")}
for what, ok in checks.items(): print(f"{'ok  ' if ok else 'FAIL'} retry-not-released counterexample: {what}")
bad += sum(not ok for ok in checks.values())
print(f"     {len(trace)} steps from {sh.get('from_steps')}: " + "; ".join(f"{s['action']}({', '.join(f'{k}={v}' for k, v in s['args'].items())})" for s in trace))

# ---- every known-wrong fixture judged next to this run (CI runs judge_wrong.py first): distilled with the policy root of its pack -----
PACKS = {"pith.reservation": SEED, "pith.booking": SEED / "packs/booking", "pith.quota": SEED / "packs/quota", "pith.approval": SEED / "packs/approval"}
releases = {SEED: SEED}
n = 0
for ev in sorted(d for d in root.parent.glob("wrong-*") if d.is_dir()):
    if not (ev / "task-packet.json").is_file(): print(f"FAIL {ev.name}: no task packet"); bad += 1; continue
    pid = (json.loads((ev / "app-claims.json").read_text()).get("pack") or {}).get("id")
    if pid not in PACKS: print(f"skip {ev.name}: pack {pid} has no policy root here"); continue
    pol = PACKS[pid]
    if pol not in releases:
        releases[pol] = root / f"release-{pol.name}"
        if not releases[pol].exists(): subprocess.run([sys.executable, str(SEED / "gate/release.py"), "build", "--pack", str(pol), "--out", str(releases[pol])], capture_output=True)
    r = subprocess.run([sys.executable, str(SEED / "gate/packet.py"), "distill", str(ev), "--policy-from", str(releases[pol]), "--json"], capture_output=True, text=True)
    D, problems = distilled(ev, releases[pol]) if r.returncode == 0 else (None, [f"distill exited {r.returncode}: {r.stderr[-200:]}"])
    cx = ((D or {}).get("first_failure") or {}).get("counterexample") or {}
    n += 1; bad += bool(problems)
    print(f"{'ok  ' if not problems else 'FAIL'} {ev.name:40} distilled: schema-valid, " + (f"{len(cx.get('trace') or [])} trace steps, " if cx else "no counterexample, ") + ("no leak" if not problems else f"LEAKS {problems[:3]}"))
print(f"{'ok' if bad == 0 else 'FAIL'}: {n} known-wrong evidence directories distilled with no host path, stack frame or harness identifier")
sys.exit(1 if bad else 0)
