# Validation record — Pith v0.12.0 (contract upgrades on the main packs, the reservation kernels as a composition, a model-agent handoff)

Releases: reservation `f78d43798f1da2e0ddfe423f02810aabacdc326c619ac10c17d0f5fd20a6e32d`, booking
`9bf4ebbc9fb4b7cb05ae28feaf54eff6d53afc24e1c3cbe1587945a48bf48f90`, approval
`c5465e546a9f292a34b2864f4f0dc265bbf43a57496090e64ac4ac01b9054fdd`, quota
`492425a27b1c24a0c417f1d161bc0fa8f9eb0809db8dcbc085c02e41fd5448ee`; demonstrations unchanged. Local runs (advisory
isolation, unsandboxed browser) as before; CI runs the same steps, the new `upgrades` job and the enforced `isolated`
run. RFC: `docs/rfc/0006-upgrading-the-main-packs.md`.

### the contract upgrades (validation/upgrades.py; upgrades-record-<pack>.json)
Each previous release rebuilt from 8e63d7b had exactly the digest the v0.11.0 catalog recorded.

| Pack | Expectations | Old examples accepted, then migrated | Known-wrong migrations refused at verify (passing the ordinary judge) | Old results the classification says hold |
|---|---|---|---|---|
| reservation | 18 of 18 | build-a, build-b, club-desk, office-desk | skips-declines (yes), stamps-history | 15: the kernel proof and every design check |
| booking | 18 of 18 | calendar-py, desk-node, custom-py | drops-cancelled, drops-ledger (yes), default-buffer (yes) | 2: the runtime and profile choices |
| approval | 18 of 18 | approvals-py, approvals-node, adopt-handbook | drops-stale-approvals (yes), drops-request-ledger (yes), creates-not-requalified | 1: the runtime choice |
| quota | 16 of 16 | sliding-log-py, tally-node | clock-from-log (yes), counts-only (yes), closed-expiry | 1: the runtime choice |

In every pack the upgrade is classified behavioral, naming the records the RFC lists; the reference application judged
under the new release with the old evidence offered is accepted and reuses nothing; the old deployment record does not
cover the new artifact; every migration passes all seven steps (old artifact, populate, unrecognised state refused,
migrate, migrate again, verify, rollback stated). For the reservation, booking and approval packs, whose old evidence
awaits a human approval, the migration is bound to that evidence by `upgrades.py` (same artifact and release digests)
rather than by `migrate.py --old-evidence`.

### each pack under its new release
- Every example accepted with the pristine release (reservation: build-a, build-b, club-desk, office-desk; booking,
  approval, quota: all listed in the catalog). Every known-wrong application refused for exactly its defect,
  including the new `retry-not-released`, `buffer-ignored-on-move` and `retry-default-limit`; the entries of booking's
  and quota's `expected.yaml` that now also fail a new test seeing the same defect are listed in the RFC.
- Proofs and models: booking's core re-verifies (13), its 11 known-wrong cores fail, 15 traces pass; approval's model
  (30628 states) holds and its 10 known-wrong designs are rejected, refinement and 14 traces pass; quota's core
  re-verifies (17), 5 known-wrong cores rejected, 10 traces hold. The reservation kernels are unchanged.
- `compare_m1.py`: the same scoped results as the v0.6.0 judge, the claim-text differences being the new receipts
  wording; `evidence_reuse.py`, `test_packet.py`, `packets.py`, `adoption.py`, `governance.py`, `evolution.py`,
  `domain_free.py` (6 packs, 172 terms), `pack check` on every pack and `catalog.py check` pass.

### the reservation kernels as a composition (validation/compositions.py)
- `compose.py check compositions/reservation-kernels`: the integration keeps `AuthInv`, `PostingInv`, the permitted
  effects, `INV1` and `CaptureAgrees`; `ignores-posting`, `capture-forgets-posting` and `split-capture` each keep both
  kernels' rules and violate exactly the invariants they name. `ledger-receipts` as before.
- TLC: the integration refines `obligations/design/CoreActions.tla` and `CoreActions` refines the integration;
  `ignores-posting` does not refine `CoreActions`.

### the handoff between model agents (evolution/handoff; validation/handoff.py)
- One run, 2026-10-13. Agent A: one judge run, accepted; its migration, written without a description of version 1's
  state, passes every step on the state the accepted tally 1 application produced. Agent B: planned (integration),
  changed `service/run.py` only, classified (integration; the model checks hold), judged once with A's evidence:
  accepted, the two model checks reused, the three service checks run again; refused the bound change for counter
  `vip` as a contract change. `validation/handoff.py` re-checks all of it (11 expectations) without running a model.
- Findings by the agents: the tally 2 release lacks its intent document and known-wrong examples, and nothing in it
  describes version 1's state.

# Validation record — Pith v0.11.0 (M6: governance, compatibility, catalog, experiment harness)

Releases: reservation `b6a58ad409fd80070f39c35e402dd3fb46e659be8b123c11b73b4f65e083ffa7`, booking
`4b2171324020b247ee1675d207f7778e8a30fc1d21143e26c8b0b7a3d65de774`, approval
`a0c27100b0d0c7838041e6e822238883ebb072e46f0ba813c8b1da89c2f8118f`, quota
`b10e8147eade371f29522ef47d170e39ed1eef40c7e38308e8ee5c3883fea8bc`; demonstrations tally 1.0.0
`94e8781945f07514f989abc1e3e9b52cb434301dbcd6e98ddb544ae47ee294b4`, tally 2.0.0
`e7bf373c80b4a359a02e1242f1ffe76aee54f6c3c772c34b865c48d7c7c434b3`. This release also carries M3's final state (the
trace review and `packs/quota`); the v0.9.0 and v0.10.0 records below were made before it was merged in. Local runs (advisory isolation, unsandboxed browser)
as before; CI runs the same steps and the enforced `isolated` run.

### governance mechanics (validation/governance.py)
- `catalog.yaml` matches all six packs it lists (sealed digests, derived stages, listed files, maintainers): every
  entry is `draft`, because no pack has an independent release review
- an entry that claims `released` without one is refused by `gate/catalog.py check`
- revocation end to end: evidence and a deployment record resting on a release revoked in a scratch revocations file
  are reported revoked (`catalog.py revoked`, `deploy.py check --revocations`); without the revocation the same
  deployment is covered

### the experiment harness, dry run only (experiments/harness.py dryrun)
- 6 planned runs (2 scripted agents × 1 task × 3 conditions), every record valid against the schema, the analysis
  recomputes the primary outcome and labels itself a dry run
- the paths it must see: a false acceptance in core-tests (a migration that drops refusals passes the conventional
  tests, fails external criterion D5), the same migration refused by the judge in the pith condition followed by a
  repair cycle, and success everywhere for the careful scripted agent. These numbers measure the harness; **no
  experiment with real models has been run**
- the plan crosses every model, task, condition and repeat, and rotates which condition runs first

### the quota pack on this evaluator
- sliding-log-py and tally-node accepted; the six known-wrong libraries refused (four at `library.lifecycle` by exactly
  their tests, two failing delivery on exactly LW3 and LI3), each task packet with category `violation` naming the
  expected record; `pack check` stage `draft`; `domain_free.py`: gate/ is free of 6 packs' 149 terms and ids

### unchanged results from v0.10.0
- wrong-candidate matrix (validation/matrix.py, 19 cases), re-run against the final v0.11.0 reservation release
  (with M3's final state merged in): all 19 refused at their intended check, the same checks as v0.10.0 (the
  over-limit SPEC claim passes with a reviewer flag, exit 0)
- every v0.10.0 check above re-run in CI on this release (jobs `judge` and `packs`)

# Validation record — Pith v0.10.0 (M5: safe evolution)

Releases: reservation `a43a0626f59a8e5ca4a150b5966938ef001d78b037c5a027d5f93fc9ba079957`, booking
`d3158a1352189fcb39c8a0439cc31bc3c5fa173aa8ee6a1e675154cef35779a0`, approval
`92a7fa52d8f70354e958080efd713c5d92b1df2b0552425240c7d30cc13be19e`; demonstrations tally 1.0.0
`103143ba3bbbbe07cd9dbec50a325c37ddaa4b93a78839f336bdd8c7cb1e7970`, tally 2.0.0
`f3fd8dba1625afbc696d55501492baf1f20d4c8d5f1a4c04903ac925c48ed59f`.

### the exit demonstrations (validation/evolution.py; evolution-record.json)
- **agent handoff**: agent A's application (tally 2 `basic`) accepted; agent B starts from A's packet (state `done`,
  with the rerun and impact commands); `change.py plan` for `service/run.py` before the edit says integration and
  re-run the lifecycle harness and the two entrypoint checks; `classify` after the edit says the same; B judged with
  A's evidence offered is accepted, reusing exactly the two model checks, nothing the change invalidated
- **substantial rewrite**: the journal rewrite is classified integration with every service file changed, every
  service-derived record invalidated; judged on its own evidence it is accepted, only the two model checks reused
- **contract upgrade with populated state**: v1 `basic` accepted under tally/v1 and recorded for deployment; moving
  to tally/v2 classified behavioral (T1 and T2 version 1 → 2, M1 added), no v1 evidence holds; judged under v2 with
  v1's evidence offered, nothing is reused; the v1 deployment record does not cover the v2 artifact (release and
  artifact differ). Migration of state the accepted v1 artifact's own service produced (two results, a request in
  flight at SIGKILL, two more after restart, a refusal), all seven steps passing for both `basic` (adds a column) and
  the journal rewrite (converts the database): old artifact matches its evidence, unrecognised state refused and left
  unchanged, migrate, migrate again, verify (4 tests), rollback policy stated. Known-wrong migrations:
  `drops-refused` refused at verify by `test_every_recorded_result_is_kept_and_replayed` (and, when the in-flight
  request was never recorded, `test_in_flight_request_is_decided_once`); `renames-default` by all four verify tests.
  `drops-refused` passes the ordinary judge
- **composed workflow**: `compositions/ledger-receipts` — the integration keeps `LedgerInv`, `ReceiptsInv`, both
  permitted-effect properties and `ReceiptAgrees`; `wrong/receipt-first` keeps the local invariants and effect rules
  and violates `ReceiptAgrees` (TLC trace: a receipt reports "ok" before the effect is applied)

### the tally packs
- tally 1 `basic` and tally 2 `basic` and `journal` accepted; tally 2's known-wrong `default-bound` refused at
  `service.lifecycle` by its two tests, packet category violation naming T1; the model rejects `WrongDefaultBound`
  (Bounded violated)

### unchanged results from v0.9.0
- the reservation pack still matches the M2 baseline (`compare_m1.py`), the known-wrong fixtures of all three packs
  are refused with their expected categories and contract records, one run per failure category (`packets.py`), the
  adoption journey, the scaffold, generality across packs: re-run in CI on this release
- `validation/domain_free.py` now also scans the tally packs and the composition demos: gate/ is free of 5 packs'
  115 terms and ids
- wrong-candidate matrix (validation/matrix.py, 19 cases), re-run against the v0.10.0 reservation release: all 19
  refused at their intended check, the same checks as v0.9.0 (the over-limit SPEC claim passes with a reviewer flag,
  exit 0)

# Validation record — Pith v0.9.0 (M4: task packets, authoring, adoption)

Releases: reservation `117f339033b4c2b38c036ce9d277fd487f128c30435a002b4e01fd6cb12fce35`, booking
`ae8c1b06dcf3d6eb794cf039494625339df78f048a503f969e565393175e1598`, approval
`78a7bd4575d9f54abf9a1c0f5eaf2291744ed6d66b120efea52c0a4c175d598b`.

### failure categories and task packets (validation/packets.py, validation/judge_wrong.py)
- one run per category on the reservation pack, each with the expected first failure: evidence_missing (fresh seed,
  `design.present`), contract_change (an edited frozen file, judged by the candidate's own gate), toolchain_unavailable
  (TLC recorded unavailable, `design.safety`), not_exercised (a design that never retries, `design.coverage/CovRetry`),
  infrastructure (the evaluator raising inside `design.extends`), and done; every packet valid against
  `gate/schemas/task-packet.schema.json` and under 6 KB
- every known-wrong application of the three packs (12) refused for exactly its defect as before, and its packet
  names the expected category (all violation) and at least the expected contract records: club-desk I2, I4–I6;
  office-desk I1–I6; closed-intervals HalfOpen; check-then-insert Atomicity, B0; move-loses-booking M3;
  receipt-overwritten BI1, BI2; stale-approvals-counted A3; self-approval A1; unknown-as-refused AI1, AI2;
  adopt-handbook-stale A3

### authoring and adoption
- the scaffold (`gate/cli.py pack new`) seals, passes `pack check`, judges its `basic` example as passing and refuses
  `no-limit` at `service.lifecycle` (category violation, T1)
- `pack check`: 0 errors on all three packs; all three `draft`
- the adoption journey (`validation/adoption.py`): `adopt` writes the manifest and the record and names the two
  entrypoints still to write; judged before they exist, refused with evidence_missing; with them, every status passes;
  coverage names `handbook` and only the judged paths; the rest of the project is not in the artifact; a project whose
  code sits in a pack policy dir is refused. This is the repository's own scripted run, not an external adoption

### unchanged results from v0.8.0
- the reservation pack matches the M2 baseline, with one more expected claim-text difference: the allowlist claim
  now names `include` and `subsystem` (`compare_m1.py`); evidence invalidation and reuse as before
  (`evidence_reuse.py`); one evaluator across 8 runs of the three packs (`generality.py`)
- wrong-candidate matrix (validation/matrix.py, 19 cases), re-run against the v0.9.0 reservation release: all 19
  refused at their intended check, the same checks as v0.8.0 (the over-limit SPEC claim passes with a reviewer flag,
  exit 0)

# Validation record — Pith v0.8.0 (M3: four packs, one evaluator)

Releases: reservation `3286ed7e2257e2d6b93728e2fce0dd95e86eec4f1547f44bc6374fcb1d2c6119`, booking
`a90e315748315501532551968263d46bb67019cec66bcadf140b7fdd0923331c`, approval
`14d4b7a14b79144851fe7256ef33b3a63848b36ee48434bc75cc212eec61ab6c`, quota
`3e7b2cb3817a228c70d70c7b300c791c3b9dd3e24332c3119c6314bd839e7e9e`. Local runs (advisory isolation, unsandboxed
browser) as for v0.7.0; CI runs the same steps (jobs `judge` and `packs`) and the enforced `isolated` run.

### one evaluator, four packs (validation/generality.py)
- 11 runs, 4 packs, one evaluator digest (`425c61dc6ab0fb76`) in every run's evidence.json
- reservation: build-a, build-b (custom profile), club-desk, office-desk; booking: calendar-py (Python profile, 27
  checks), desk-node (Node.js profile on the JavaScript translation, 27), custom-py (own store, 26); approval:
  approvals-py (Python + SQLite, 19), approvals-node (Node.js + journal, 19); quota: sliding-log-py (Python library), tally-node (Node.js library).
  Every mechanical status passed;
  human approval pending where the pack asks for it (the approval pack does not)

### the reservation pack keeps the M2 baseline (validation/compare_m1.py)
- examples/build-a, build-b, club-desk, office-desk and both wrong desks: same as the v0.6.0 judge, with the same
  two expected claim-text differences as v0.7.0; evidence invalidation and `--reuse` as v0.7.0
  (validation/evidence_reuse.py)

### known-wrong applications (validation/judge_wrong.py --pack)
- booking: closed-intervals, check-then-insert, move-loses-booking refused at `service.lifecycle` by exactly their
  tests (closed-intervals may also fail the concurrent-burst test, when a touching interval wins the race: listed
  as `may_also_fail`); receipt-overwritten passes assurance and fails delivery on exactly BI1, BI2
- approval: stale-approvals-counted and self-approval refused at `service.lifecycle` by exactly their tests;
  unknown-as-refused passes assurance and fails delivery on exactly AI1, AI2
- quota: fixed-window, closed-window, shared-state, unlocked refused at `library.lifecycle` by exactly their tests;
  flat-errors and never-prunes pass assurance and fail delivery on exactly LW3 and LI3
- pack adequacy, on every run: the eight wrong booking cores fail to verify (`core.adequacy`); the eight wrong
  approval designs violate the invariant or action property named for each (`model.adequacy.*`); `harness/refines.py` finds the
  reference and the spec equal (1898 states, 2330 transitions) and detects a one-line mutation of the reference;
  reviewed traces pass (`core.traces`, `model.traces`), and a changed expectation in model/traces.yaml fails `model.traces`

### the evaluator is domain-free across every pack (validation/domain_free.py)
- no vocabulary, contract id or check id of any of the four packs occurs in gate/ (the first run of the
  extended scan found comments added in M3 that used the reservation pack's terms; they were reworded)

### intermittent failures seen while validating (not reproduced)
- the reservation `boundary` check on club-desk failed once and `model.adequacy.self` on approvals-py failed once,
  both while other judge runs and the quota author's runs shared the machine; each passed on re-run with nothing
  changed. Neither record said why (the failing `tlc` check printed its fixed claim, not TLC's output; that is now
  fixed in `gate/kinds.py`, so a recurrence will show what TLC reported)

### wrong-candidate matrix (validation/matrix.py, 19 cases)
- re-run against the final v0.8.0 reservation release: all 19 cases refused at their intended check, the same checks as
  v0.7.0 (the over-limit SPEC claim passes with a reviewer flag, exit 0)

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
