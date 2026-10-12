# Validation record — Pith (then core-seed) v0.4.1 (release 7c161daa9147f952a3385d275fa134c848890a60bc0a87aa89e2849750d63433; re-run after the public-release cleanup)
v4.1 adds portability fixes surfaced by the first unassisted agent build (macOS): OS metadata files ignored everywhere, paced readers
in the lifecycle harness, robust toolchain record, a venv-based bootstrap with a macOS branch, and --candidate (the pristine release's judge
run against a checkout). Browser runs here are unsandboxed, so release_ready is false by policy.

### examples judged by the pristine gate under the final sealed release (validation/judge_example.sh)
- examples/build-a: behavioral_assurance=passed | application_delivery=passed | human_approval=pending | artifact c8961552db342d4d | release 7c161daa9147f952 | gate_mode=authoritative
- examples/build-b: behavioral_assurance=passed | application_delivery=passed | human_approval=pending | artifact a965aacf900d49d4 | release 7c161daa9147f952 | gate_mode=authoritative
- examples/agent-build-hold-desk: behavioral_assurance=passed | application_delivery=passed | human_approval=pending | artifact 3b4aaf4e382a93c0 | release 7c161daa9147f952 | gate_mode=authoritative
- fresh seed: ring 0 passes, ring 1 refuses at 'design module present' (expected)


### planted OS metadata (.DS_Store in kernel/ and obligations/, ._app_gate.py in gate/): integrity and release digest unaffected
[ok] policy · frozen files intact: 52 frozen files intact (OS metadata files ignored); release digest b1a17e337131b397 unchanged with metadata planted

### agent build 'Hold Desk' (first unassisted build, built on macOS) — judged by the pristine release's gate (--candidate), pinned, .DS_Store files left in place
/home/claude/seed5/gate/app_gate.py:94: DeprecationWarning: Accessing jsonschema.__version__ is deprecated and will be removed in a future release. Use importlib.metadata directly to query for jsonschema's version.
  try: return getattr(__import__(pkg), "__version__", "present (version unknown)")
[ok] policy · frozen files intact: 52 frozen files intact; nothing added under ['kernel', 'obligations', 'gate', 'profiles'] (OS metadata files ignored)
[ok] policy · release seal: platform release df6b12a3aeae9c5c matches release.seal.json
[ok] policy · external release pin: platform matches the externally pinned release df6b12a3aeae9c5c
[ok] policy · manifest allowlisted: manifest keys within ['name', 'profile', 'extra_tests', 'ui_entry']
[ok] policy · integration profile: profile = sqlite (shipped; in-process tests apply)
[ok] policy · artifact: deployment artifact copied and digested (3b4aaf4e382a93c0); judged in a fresh copy, never the live checkout
[ok] ring0 · kernel gate: proven core: include closure verified, translation reproduced fail-closed, TCB scan, adequacy, traces
[ok] ring1 · design module present: design/Design.tla
[ok] ring1 · design extends obligations: EXTENDS CoreActions
[ok] ring1 · core state only via core actions: status/held change only through CoreDecide/CoreReplay/CoreRelease
[ok] ring1 · design interface: declares VARIABLE responses; does not redefine any checked predicate (they are bound in the frozen MC.tla)
[ok] ring1 · design model (safety): INV1, P2, P3, DecideCorrect, Idempotent, Consistent hold over the configured model (predicates bound by the frozen MC.tla)
[ok] ring1 · design coverage (CovDecided): the design reaches the behaviour CovDecided guards
[ok] ring1 · design coverage (CovContention): the design reaches the behaviour CovContention guards
[ok] ring1 · design coverage (CovDecline): the design reaches the behaviour CovDecline guards
[ok] ring1 · design coverage (CovRelease): the design reaches the behaviour CovRelease guards
[ok] ring1 · design coverage (CovRetry): the design reaches the behaviour CovRetry guards
[ok] ring1 · obligations reject the known-bad design: receipt-time design violates INV1 under the same obligations
[ok] ring1 · service entrypoint: service/run.py present (the supervisor starts it as a separate process)
[ok] ring1 · shipped profile tests: sqlite profile (frozen) in-process tests pass (22)
[ok] ring1 · lifecycle harness (black-box): through the running service: duplicate create, idempotent replay and conflicts, crash (SIGKILL) + restart + retry, restart durability, event contract (op_id, chain, state_after, one commit per op), concurrency with readers (6 checks)
[ok] ring2 · generated artifacts present: gen/out present
[ok] ring2 · generated artifacts current: openapi, event schema and monitor equal the generator's output
[ok] ring2 · monitor negative suite: generated monitor detects each named violation (rehashed mutants), op lifecycle, watermark; silent on the good stream
[ok] ring2 · boundary harness (black-box): API not falsified: JSON-Schema-valid requests/responses/events; invalid and malformed inputs rejected without effect; conflicts rejected; agrees with the proven core under bursts; idempotent; monitor silent; both branches exercised (20 checks)
[ok] ring3 · application delivery: real-browser workflows ['W1', 'W2', 'W3', 'W4', 'W5'] + replay display passed at ['desktop', 'mobile'] (sandboxed=False); SPEC structurally complete (lint is structural, not semantic)
[ok] ring3 · human approval: pending (no attestation supplied)
[ok] policy · judged copy unchanged: the artifact copy that was judged is byte-identical at the end (an observation at two points, not a monitor)
app-claims.json: behavioral_assurance=passed;  | application_delivery=passed | human_approval=pending | release_ready=False | gate_mode=authoritative | evidence=/tmp/e5-agent
exit=0

### solA4 — pristine judge (--candidate), pinned
/home/claude/seed5/gate/app_gate.py:94: DeprecationWarning: Accessing jsonschema.__version__ is deprecated and will be removed in a future release. Use importlib.metadata directly to query for jsonschema's version.
  try: return getattr(__import__(pkg), "__version__", "present (version unknown)")
[ok] policy · frozen files intact: 52 frozen files intact; nothing added under ['kernel', 'obligations', 'gate', 'profiles'] (OS metadata files ignored)
[ok] policy · release seal: platform release df6b12a3aeae9c5c matches release.seal.json
[ok] policy · external release pin: platform matches the externally pinned release df6b12a3aeae9c5c
[ok] policy · manifest allowlisted: manifest keys within ['name', 'profile', 'extra_tests', 'ui_entry']
[ok] policy · integration profile: profile = sqlite (shipped; in-process tests apply)
[ok] policy · artifact: deployment artifact copied and digested (c8961552db342d4d); judged in a fresh copy, never the live checkout
[ok] ring0 · kernel gate: proven core: include closure verified, translation reproduced fail-closed, TCB scan, adequacy, traces
[ok] ring1 · design module present: design/Design.tla
[ok] ring1 · design extends obligations: EXTENDS CoreActions
[ok] ring1 · core state only via core actions: status/held change only through CoreDecide/CoreReplay/CoreRelease
[ok] ring1 · design interface: declares VARIABLE responses; does not redefine any checked predicate (they are bound in the frozen MC.tla)
[ok] ring1 · design model (safety): INV1, P2, P3, DecideCorrect, Idempotent, Consistent hold over the configured model (predicates bound by the frozen MC.tla)
[ok] ring1 · design coverage (CovDecided): the design reaches the behaviour CovDecided guards
[ok] ring1 · design coverage (CovContention): the design reaches the behaviour CovContention guards
[ok] ring1 · design coverage (CovDecline): the design reaches the behaviour CovDecline guards
[ok] ring1 · design coverage (CovRelease): the design reaches the behaviour CovRelease guards
[ok] ring1 · design coverage (CovRetry): the design reaches the behaviour CovRetry guards
[ok] ring1 · obligations reject the known-bad design: receipt-time design violates INV1 under the same obligations
[ok] ring1 · service entrypoint: service/run.py present (the supervisor starts it as a separate process)
[ok] ring1 · shipped profile tests: sqlite profile (frozen) in-process tests pass (22)
[ok] ring1 · lifecycle harness (black-box): through the running service: duplicate create, idempotent replay and conflicts, crash (SIGKILL) + restart + retry, restart durability, event contract (op_id, chain, state_after, one commit per op), concurrency with readers (6 checks)
[ok] ring2 · generated artifacts present: gen/out present
[ok] ring2 · generated artifacts current: openapi, event schema and monitor equal the generator's output
[ok] ring2 · monitor negative suite: generated monitor detects each named violation (rehashed mutants), op lifecycle, watermark; silent on the good stream
[ok] ring2 · boundary harness (black-box): API not falsified: JSON-Schema-valid requests/responses/events; invalid and malformed inputs rejected without effect; conflicts rejected; agrees with the proven core under bursts; idempotent; monitor silent; both branches exercised (20 checks)
[ok] ring3 · application delivery: real-browser workflows ['W1', 'W2', 'W3', 'W4', 'W5'] + replay display passed at ['desktop', 'mobile'] (sandboxed=False); SPEC structurally complete (lint is structural, not semantic)
[ok] ring3 · human approval: pending (no attestation supplied)
[ok] policy · judged copy unchanged: the artifact copy that was judged is byte-identical at the end (an observation at two points, not a monitor)
app-claims.json: behavioral_assurance=passed;  | application_delivery=passed | human_approval=pending | release_ready=False | gate_mode=authoritative | evidence=/tmp/e5-solA4
exit=0

### solB4 — pristine judge (--candidate), pinned
/home/claude/seed5/gate/app_gate.py:94: DeprecationWarning: Accessing jsonschema.__version__ is deprecated and will be removed in a future release. Use importlib.metadata directly to query for jsonschema's version.
  try: return getattr(__import__(pkg), "__version__", "present (version unknown)")
[ok] policy · frozen files intact: 52 frozen files intact; nothing added under ['kernel', 'obligations', 'gate', 'profiles'] (OS metadata files ignored)
[ok] policy · release seal: platform release df6b12a3aeae9c5c matches release.seal.json
[ok] policy · external release pin: platform matches the externally pinned release df6b12a3aeae9c5c
[ok] policy · manifest allowlisted: manifest keys within ['name', 'profile', 'extra_tests', 'ui_entry']
[ok] policy · integration profile: profile = custom (custom; judged only through the service)
[ok] policy · artifact: deployment artifact copied and digested (a965aacf900d49d4); judged in a fresh copy, never the live checkout
[ok] ring0 · kernel gate: proven core: include closure verified, translation reproduced fail-closed, TCB scan, adequacy, traces
[ok] ring1 · design module present: design/Design.tla
[ok] ring1 · design extends obligations: EXTENDS CoreActions
[ok] ring1 · core state only via core actions: status/held change only through CoreDecide/CoreReplay/CoreRelease
[ok] ring1 · design interface: declares VARIABLE responses; does not redefine any checked predicate (they are bound in the frozen MC.tla)
[ok] ring1 · design model (safety): INV1, P2, P3, DecideCorrect, Idempotent, Consistent hold over the configured model (predicates bound by the frozen MC.tla)
[ok] ring1 · design coverage (CovDecided): the design reaches the behaviour CovDecided guards
[ok] ring1 · design coverage (CovContention): the design reaches the behaviour CovContention guards
[ok] ring1 · design coverage (CovDecline): the design reaches the behaviour CovDecline guards
[ok] ring1 · design coverage (CovRelease): the design reaches the behaviour CovRelease guards
[ok] ring1 · design coverage (CovRetry): the design reaches the behaviour CovRetry guards
[ok] ring1 · obligations reject the known-bad design: receipt-time design violates INV1 under the same obligations
[ok] ring1 · service entrypoint: service/run.py present (the supervisor starts it as a separate process)
[ok] ring1 · lifecycle harness (black-box): through the running service: duplicate create, idempotent replay and conflicts, crash (SIGKILL) + restart + retry, restart durability, event contract (op_id, chain, state_after, one commit per op), concurrency with readers (6 checks)
[ok] ring2 · generated artifacts present: gen/out present
[ok] ring2 · generated artifacts current: openapi, event schema and monitor equal the generator's output
[ok] ring2 · monitor negative suite: generated monitor detects each named violation (rehashed mutants), op lifecycle, watermark; silent on the good stream
[ok] ring2 · boundary harness (black-box): API not falsified: JSON-Schema-valid requests/responses/events; invalid and malformed inputs rejected without effect; conflicts rejected; agrees with the proven core under bursts; idempotent; monitor silent; both branches exercised (20 checks)
[ok] ring3 · application delivery: real-browser workflows ['W1', 'W2', 'W3', 'W4', 'W5'] + replay display passed at ['desktop', 'mobile'] (sandboxed=False); SPEC structurally complete (lint is structural, not semantic)
[ok] ring3 · human approval: pending (no attestation supplied)
[ok] policy · judged copy unchanged: the artifact copy that was judged is byte-identical at the end (an observation at two points, not a monitor)
app-claims.json: behavioral_assurance=passed;  | application_delivery=passed | human_approval=pending | release_ready=False | gate_mode=authoritative | evidence=/tmp/e5-solB4
exit=0

### carried forward from v4 (same checks, re-run on the same obligations)
### the previous reviewer's candidates (v3 findings), against the v4 judge
### R1 conftest.py that turns every test into a no-op (reviewer's bypass)
  direct: with --noconftest the hook is not loaded:
    25 passed in 0.98s
  and the artifact copy excludes it anyway (conftest.py is not in an owned dir):
app app.manifest.yaml design gen service ui 

### R2 service that prints a fabricated passing browser report then crashes
[REFUSED] ring1 · lifecycle harness (black-box):                         cwd=self.root, env=env, stdout=self.log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)

### R3 two artifacts differing only in ui/claims.json must have different digests
  digests differ: True 042b30655612 aeb313e6b312

### R4 translator failure must not pass (unit: exit 17, no files)
  problems: ['translator exit 17', 'translator produced no Python files', "file set differs: fresh [] vs shipped ['AuthCore.py', 'AuthSpec.py', '__main__.py', 'module_.py']"] -> passes: False

### R5 attestations: pending decisions, null decisions, junk expiry (real signatures, operator key)
  pending      -> rejected
  null         -> rejected
  junk expiry  -> rejected
  all approved -> approved

### R6 design that defines Idempotent == TRUE, Consistent == TRUE, CovRetry == FALSE
[REFUSED] ring1 · design interface: responses declared=True; redefined=['Idempotent', 'Consistent', 'CovRetry']

### monitor streams from the v3 review (now in obligations/boundary/test_monitor.py)
create without commit -> OP-composition; declined authorization with a second commit -> OP-after-commit; release absorbed into an
authorize commit -> OP-composition; interleaved operations -> OP-interleaved; prefix ending at a commit boundary -> silent without a
watermark, INCOMPLETE with one (documented limit).

### Notes
- state_after carries limit/posted/aggregate reserved: aggregate continuity, not the per-request map. The per-request state is checked
  by the boundary harness against the proven core, not by the monitor.
- The "judged copy unchanged" check is two observations of the copy the judge itself holds; the live checkout is not executed at all.
- Still true: the concurrent-reader test exercises isolation and cannot prove it; trace provenance in the kernel is unsigned.
- The v2 wrong-candidate matrix (validation/matrix.py) applies unchanged in substance; cases that referenced boundary_client.py now
  mutate service/run.py instead.

### notes on the unassisted build
- Agent on macOS, no reference solution, local advisory run on a mirror because .DS_Store files failed v4's integrity check; its artifact
  digest (3b4aaf4e…) equals the one the pristine judge computed here and its browser ran sandboxed on its host.
- TLC caught the agent's first design (response computed from the pre-state); the agent added response loss itself after re-reading AGENT.md.
- No coverage obligation distinguishes a resend after loss from a resend after delivery; a design without loss can pass. Documented limit.
- The agent added a 15 ms pause to account reads to survive v4's unpaced readers on macOS; v4.1 paces the readers so no such workaround is needed.
