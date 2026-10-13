"""validation/matrix.py — the wrong-candidate matrix: each case mutates a passing build, runs the judge, and must be
refused at the named check (or, for the last case, pass with a reviewer flag). Build A uses the shipped sqlite profile;
build B a custom profile. Run case by case; a full boundary harness takes a minute or two per case."""

import shutil, subprocess, pathlib, os, re, sys, json, tempfile
# Usage: BUILD_A=<assembled candidate dir> BUILD_B=<assembled candidate dir> python3 validation/matrix.py [case indexes]
# Assemble candidates with validation/judge_example.sh (it prints the temp dir) or by overlaying examples/* onto a seed copy.
# DAFNY and TLA2TOOLS from the environment. Cases that mutated boundary_client.py in v2 now mutate service/run.py.
A = pathlib.Path(os.environ["BUILD_A"]); B = pathlib.Path(os.environ["BUILD_B"])
ENV = dict(os.environ, BOUNDARY_EXAMPLES=os.environ.get("BOUNDARY_EXAMPLES", "8"))

def fresh(src):
    d = pathlib.Path(tempfile.mkdtemp(prefix="wrong-")); shutil.rmtree(d); shutil.copytree(src, d, ignore=shutil.ignore_patterns("__pycache__", ".hypothesis", "app-claims.json")); return d
def sed(d, rel, old, new):
    p = d / rel; s = p.read_text(); assert old in s, (rel, old[:40]); p.write_text(s.replace(old, new))
def gate(d):
    r = subprocess.run([sys.executable, "gate/app_gate.py", "--out", str(d) + "-evidence"], cwd=d, env=ENV, capture_output=True, text=True); out = r.stdout + r.stderr
    first = next((l for l in out.splitlines() if l.startswith("[REFUSED]")), None)
    summary = next((l for l in out.splitlines() if l.startswith("app-claims.json:")), "")
    return r.returncode, first, summary

CASES = []
def case(name, src, expect_check, mutate, expect_exit=1): CASES.append((name, src, expect_check, mutate, expect_exit))

case("altered evaluator configuration (manifest adds kernel.gate)", A, "manifest allowlisted",
     lambda d: (d / "app.manifest.yaml").write_text((d / "app.manifest.yaml").read_text() + "kernel:\n  gate: ./pass.py\n"))
case("frozen harness weakened", A, "frozen files intact",
     lambda d: sed(d, "obligations/boundary/harness.py", 'rep = Monitor().run(evs); assert rep["alerts"] == [], rep["alerts"]', 'rep = Monitor().run(evs)'))
case("frozen pack.yaml edited", A, "frozen files intact", lambda d: sed(d, "pack.yaml", 'command: "{pytest} obligations/service/lifecycle.py"', 'command: "{pytest} obligations/service/nothing.py"'))
case("design hands the core a constant availability of 0", A, "design model (safety)", lambda d: shutil.copy(d / "obligations/design/WrongZeroAvail.tla", d / "design/Design.tla") and sed(d, "design/Design.tla", "MODULE WrongZeroAvail", "MODULE Design"))
case("design that stutters forever", A, "design coverage (CovDecided)", lambda d: shutil.copy(d / "obligations/design/WrongStutter.tla", d / "design/Design.tla") and sed(d, "design/Design.tla", "MODULE WrongStutter", "MODULE Design"))
case("design without retries (idempotency vacuous)", A, "design coverage (CovRetry)", lambda d: sed(d, "design/Design.tla", "Begin(r) \\/ Commit(r) \\/ Resend(r) \\/ Release(r)", "Begin(r) \\/ Commit(r) \\/ Release(r)"))
case("design reads availability at receipt (stale snapshot)", A, "design model (safety)", lambda d: (
     sed(d, "design/Design.tla", "VARIABLES phase, responses, tries", "VARIABLES phase, responses, tries, snapshot"),
     sed(d, "design/Design.tla", "vars == <<status, held, posted, phase, responses, tries>>", "vars == <<status, held, posted, phase, responses, tries, snapshot>>"),
     sed(d, "design/Design.tla", "designVars == <<phase, responses, tries>>", "designVars == <<phase, responses, tries, snapshot>>"),
     sed(d, "design/Design.tla", "/\\ tries = [r \\in Reqs |-> 0]", "/\\ tries = [r \\in Reqs |-> 0] /\\ snapshot = [r \\in Reqs |-> 0]"),
     sed(d, "design/Design.tla", "/\\ UNCHANGED <<status, held, posted, responses>>\n\nCommit", "/\\ snapshot' = [snapshot EXCEPT ![r] = Available] /\\ UNCHANGED <<status, held, posted, responses>>\n\nCommit"),
     sed(d, "design/Design.tla", "(CoreDecide(r, Available) \\/ CoreReplay(r))", "(CoreDecide(r, snapshot[r]) \\/ CoreReplay(r))"),
     sed(d, "design/Design.tla", "/\\ UNCHANGED tries\n\n\\* The client", "/\\ UNCHANGED <<tries, snapshot>>\n\n\\* The client"),
     sed(d, "design/Design.tla", "/\\ UNCHANGED <<status, held, posted, responses, tries>>", "/\\ UNCHANGED <<status, held, posted, responses, tries, snapshot>>")))
case("custom adapter accepts negative amounts", B, "boundary harness", lambda d: sed(d, "adapter/jsonrepo.py", 'core.validate_id(req_id, "request_id"), core.validate_amount(amount)', 'core.validate_id(req_id, "request_id"), int(amount)'))
case("custom adapter accepts a conflicting replay", B, "lifecycle harness", lambda d: sed(d, "adapter/jsonrepo.py", 'if rec["amount"] != amount: raise core.ConflictingReplay', 'if False: raise core.ConflictingReplay'))
case("custom adapter loses state on restart (ignores path)", B, "lifecycle harness", lambda d: sed(d, "adapter/jsonrepo.py", 'self.path = path or os.path.join', 'self.path = os.path.join'))
case("custom adapter omits op.committed", B, "lifecycle harness", lambda d: sed(d, "adapter/jsonrepo.py", "def _done(self, doc, acct_id, req_id, op, a):\n", "def _done(self, doc, acct_id, req_id, op, a):\n        return\n"))
case("custom adapter emits the wrong hold amount", B, "boundary harness", lambda d: sed(d, "adapter/jsonrepo.py", '{"type": "reservation.created", "account_id": acct_id, "request_id": req_id, "amount": amount}', '{"type": "reservation.created", "account_id": acct_id, "request_id": req_id, "amount": amount + 1}'))
case("custom adapter drops the reservation event (lost event)", B, "lifecycle harness", lambda d: sed(d, "adapter/jsonrepo.py", 'if d.is_Authorized: self._emit(doc, {"type": "reservation.created"', 'if False: self._emit(doc, {"type": "reservation.created"'))
case("service skips request validation", A, "boundary harness", lambda d: sed(d, "service/app.py", "err = next(validator.iter_errors(body), None)\n            if err: raise InvalidRequest", "err = None\n            if err: raise InvalidRequest"))
case("service always declines (never calls the adapter)", A, "lifecycle harness", lambda d: sed(d, "service/app.py", 'return self._send(200, repo.authorize(int(parts[1]), b["request_id"], b["amount"]))', 'return self._send(200, {"request_id": b["request_id"], "decision": "DECLINED", "available_at_decision": 0, "replayed": False})'))
case("generated schema hand-edited", A, "generated artifacts current", lambda d: sed(d, "gen/out/openapi.yaml", "minimum: 1", "minimum: 0"))
case("absent UI", A, "application delivery", lambda d: (d / "ui/index.html").unlink(), expect_exit=2)
case("empty SPEC.md", A, "application delivery", lambda d: (d / "app/SPEC.md").write_text("# nothing\n"), expect_exit=2)
case("SPEC claims the app authorizes over-limit requests (flagged, not refused)", A, None, lambda d: sed(d, "app/SPEC.md", "- OC-4 (W5)", "- OC-8 informal: the desk shall authorize any request that exceeds the limit when the operator insists. Evaluation: product review.\n- OC-4 (W5)"), expect_exit=0)

rows = []
sel = [int(x) for x in sys.argv[1:]] or list(range(len(CASES)))
for i in sel:
    name, src, expect, mutate, expect_exit = CASES[i]
    d = fresh(src)
    try: mutate(d)
    except Exception as e: rows.append((name, "MUTATION FAILED " + str(e)[:80], "", "")); continue
    code, first, summary = gate(d)
    got = re.search(r"\] (\w+ · [^:]+):", first).group(1) if first else "(no refusal)"
    ok = (expect is None or expect in got) and code == expect_exit
    flags = ""
    if expect is None:
        c = json.loads((d / "app-claims.json").read_text()); flags = f"flags={len(c['human_approval_detail']['semantic_flags_for_reviewers'])}"
    rows.append((name, ("OK" if ok else "UNEXPECTED") + f" exit={code}", got, (first or summary)[:150].replace("\n", " ") + " " + flags))
    shutil.rmtree(d, ignore_errors=True)
with open(os.environ.get("MATRIX_OUT", "matrix.txt"), "a") as f:
    for r in rows:
        line = f"- {r[0]}\n    -> {r[1]}  [{r[2]}]\n       {r[3]}\n"; print(line, end=""); f.write(line)
