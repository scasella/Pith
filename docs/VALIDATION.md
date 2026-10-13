# Validation record — Pith v0.7.0 (M2: contract pack, domain-free evaluator, structured evidence)

Release `34be91fc373f76106c1c52f298127639242d22ebd955a91bf6bf21d341b601fa`. Local runs (advisory isolation,
unsandboxed browser) as for v0.6.0; the CI `isolated` job is the enforced run.

### same scoped results as the v0.6.0 judge (validation/compare_m1.py, baseline recorded with the v0.6.0 judge)
Every example and known-wrong fixture judged through `pack.yaml` and the domain-free evaluator, compared with
`validation/baselines/m1.json` check by check (area, name, result, claim text with digests masked), status by
status, failing delivery obligations, `release_ready` and `release_ready_missing`:
- examples/build-a, build-b, club-desk, office-desk: same (31, 30, 31, 31 checks); assurance and delivery passed,
  human approval pending, release_ready_missing = human_approval, isolation, browser (advisory local run)
- examples/wrong/club-desk: same; delivery failed on exactly I2, I4, I5, I6
- examples/wrong/office-desk: same; delivery failed on exactly I1–I6
- the two expected claim-text differences: `frozen files intact` names the new release layout (75 files under
  gate/, kernel/, obligations/, profiles/ + pack.yaml), and `isolation` lists `write policy (profiles/)`, a pack
  policy dir the v0.6.0 probe did not try, and the README's new path
- masked as properties of the machine, not the judge: the delivery claim's `sandboxed=` flag and `browser` in
  `release_ready_missing` (the baseline host cannot run Chromium's sandbox; CI can)

### the evaluator is domain-free (validation/domain_free.py)
- no pack vocabulary (pack.yaml:domain_vocabulary), contract record id or check id occurs anywhere in gate/

### evidence is invalidated by exactly what changed (validation/evidence_reuse.py, build-a)
- presentation edit (comment appended to ui/index.html): proof, all 13 design checks, generator checks, monitor
  suite and profile tests still hold; lifecycle, boundary, delivery and approval are invalidated
- design edit (comment appended to design/Design.tla): proof, generator, monitor and profile tests hold; all 13
  design checks and everything that runs the service are invalidated
- the presentation edit judged with `--reuse`: exactly the proof and the 9 TLC checks reused, everything else
  re-run, statuses identical to the base run

### wrong-candidate matrix (validation/matrix.py, 19 cases): every case refused at its intended check
- the same 19 cases and the same refusing checks as v0.6.0, now named by the pack: manifest allowlist; frozen files
  (weakened harness, and an edited `pack.yaml` in place of the removed `gate/policy.yaml`); design safety (zero
  availability, receipt-time snapshot); coverage (CovDecided, CovRetry); lifecycle harness (5 cases); boundary
  harness (3 cases); generated artifacts current; absent UI and empty SPEC refused at delivery (exit 2); the
  over-limit SPEC claim passes with a reviewer flag (exit 0)

# Validation record — Pith v0.6.0 (M1: interaction obligations, desk fixtures, isolation profile)

Release `512e9c778ffd78fad9c8b8822339d74ddd086f3a0eb429cf9cdc5721e65a53ee`. Local runs use an unsandboxed browser and no
isolation profile, so `release_ready` is false by policy there; the CI `isolated` job is the enforced run.

### examples judged by the pristine gate (validation/judge_example.sh)
- examples/build-a (on pith-view.js): behavioral_assurance=passed | application_delivery=passed (W1–W6 desktop+mobile, I1–I6) | human_approval=pending | artifact 92a2dbd2c64634a1
- examples/build-b (hand-written state): behavioral_assurance=passed | application_delivery=passed (W1–W6, I1–I6) | human_approval=pending | artifact 1e42f6181c10af7e
- examples/club-desk (corrected): behavioral_assurance=passed | application_delivery=passed (W1–W6, I1–I6) | human_approval=pending | artifact a99350671cf28cd6
- examples/office-desk (corrected): behavioral_assurance=passed | application_delivery=passed (W1–W6, I1–I6) | human_approval=pending | artifact 6da9d253c1df9989

### known-wrong fixtures (validation/judge_wrong.py): refused for exactly the reviewed defects
- examples/wrong/club-desk: assurance=passed, delivery=failed on I2, I4, I5, I6 (expected I2, I4, I5, I6)
- examples/wrong/office-desk: assurance=passed, delivery=failed on I1–I6 (expected I1–I6)
Both fixtures pass every ring-0..2 obligation and W1–W6; before v0.6.0 they would have been judged delivered.

### isolation profile (CI job `isolated`, obligations/isolation/judge-isolated.sh, build-a)
- isolation=enforced: candidate uid 10001 with no groups; evidence read/write, policy writes, gate-code modification,
  outbound connections (1.1.1.1:443, github.com:443) and root all denied
- browser ran as uid 10002; behavioral_assurance=passed, application_delivery=passed; release_ready_missing=['human_approval']
- finding: a container-wide `--ulimit fsize` makes Dafny (.NET) die with SIGXFSZ and no output; the profile bounds disk
  with the /tmp tmpfs instead and keeps RLIMIT_FSIZE on candidate processes only

### wrong-candidate matrix (validation/matrix.py, 19 cases): every case refused at its intended check
- policy: manifest allowlist; frozen files intact (weakened harness, edited policy.yaml)
- ring 1: design safety (zero availability, receipt-time snapshot); coverage (CovDecided, CovRetry); lifecycle harness
  (conflicting replay, lost state on restart, missing op.committed, dropped reservation event, always-declining service)
- ring 2: boundary harness (negative amounts, wrong hold amount, skipped validation); generated artifacts current
- ring 3: absent UI and empty SPEC refused (exit 2); an over-limit SPEC claim passes with a reviewer flag (exit 0)
- the matrix had drifted since v0.5.0 (check and source names); its cases were updated, not weakened

### client-state library
- obligations/app/lib/test_pith_view.mjs: 9 node:test cases pass, one or more per interaction obligation

# Validation record — Pith v0.5.0 (two kernels)

### v0.5.0: both kernels, judged by the pristine gate under the sealed release
- kernel gate: 21 verified (authorization + posting, include closure), translation of the two-kernel unit reproduced
  byte-for-byte (6 files), 9 adequacy candidates rejected by the expected obligations (4 new for Capture), 7 traces executed
- design obligations: INV1 (composition), P2, P3, P4, PostedExact, DecideCorrect, Idempotent, Consistent hold for both
  reference designs with both kernels interleaving; coverage reached for decisions, contention, declines, releases, captures,
  captures under contention, retries; the receipt-time design still violates INV1
- examples/build-a: behavioral_assurance=passed | application_delivery=passed (W1–W6 at desktop and mobile) | human_approval=pending | artifact 471f74490f2f1a4b | release df0b0b2eb69ebde3
- examples/build-b: behavioral_assurance=passed | application_delivery=passed (W1–W6 at desktop and mobile) | human_approval=pending | artifact 4a23533859ee83f9 | release df0b0b2eb69ebde3
- fresh seed: ring 0 passes (both kernels), ring 1 refuses at 'design module present'
- archived: examples/archive/agent-build-hold-desk-v0.4.1 conforms to v0.4.1 only (predates W6)

### finding
Two kernels share one state type and one invariant; the proofs separate per module, the composition invariant is
checked only in the design model. See ARCHITECTURE.md § Two kernels.

# Validation record — core-seed v0.4.1 (previous release; carried forward) (release 7c161daa9147f952a3385d275fa134c848890a60bc0a87aa89e2849750d63433; re-run after the public-release cleanup)
# Validation record — Pith (then core-seed) v0.4.1 (previous release; carried forward) (release 7c161daa9147f952a3385d275fa134c848890a60bc0a87aa89e2849750d63433; re-run after the public-release cleanup)
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
