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
"""
import json, os, pathlib, shutil, subprocess, sys, tempfile
import jsonschema

SEED = pathlib.Path(__file__).resolve().parent.parent
S = json.loads((SEED / "gate/schemas/task-packet.schema.json").read_text())
root = pathlib.Path(sys.argv[1]); root.mkdir(parents=True, exist_ok=True)
REL = subprocess.run([sys.executable, str(SEED / "gate/release.py"), "id"], capture_output=True, text=True).stdout.strip()


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
    return out, pk


bad = 0
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
sys.exit(1 if bad else 0)
