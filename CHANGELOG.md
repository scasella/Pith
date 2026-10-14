# Changelog

## v0.12.0 — 2026-10-13
What M5 left open and a maintainer can close alone: a contract upgrade with a migration on each of the four main
packs, the reservation pack's two kernels as a composition contract, and the handoff done once by model agents. RFC:
`docs/rfc/0006-upgrading-the-main-packs.md`. No format identifier changes; two small evaluator additions (below), so
every release digest changes, the demonstrations' included.

- **Reservation 0.12.0** (`authorization-and-posting/v3`): every write answers with its receipt and a retry returns
  it (`Receipts`); a retried release is no longer answered "not released". `MIG1` turns each acknowledged write of a v2
  database into its receipt from the event log, history byte for byte (`migrations/from-v2.yaml`,
  `profiles/sqlite/migrate.py`). New known-wrong application `retry-not-released` and migrations `skips-declines`,
  `stamps-history`. The proven kernels are unchanged.
- **Booking 0.12.0** (`interval-booking-core/v2`): a turnaround buffer per resource, in the verified core (`Near`,
  `BufferZeroIsHalfOpen`); `B0`, `HalfOpen`, `B2`, `B5`, `M1`, `BoundaryConformance` version 2, `Turnaround` and `MIG1`
  added. Old resources get buffer 0.
- **Approval 0.12.0** (`approval-workflow/v2`): a quorum per document, 2 to 5, fixed at creation (`A3`,
  `BoundaryConformance` version 2, `A9` and `MIG1` added; `QuorumFixed` in the model). Old documents get quorum 2 and
  keep every approval, stale ones included.
- **Quota 0.2.0** (`sliding-window-quota/v2`): a limit per key and `limit_for` (`Q0`, `Q1`, `Q3`, `Q4`, `Q5`,
  `Persistence`, `BoundaryConformance` version 2, `KEYLIMIT` and `MIG1` added); migrated dumps continue with version
  1's decisions. Made by this project's maintainer, now listed as the pack's second maintainer; not reviewed by its
  author (`packs/quota/AUTHORING-NOTES.md`).
- Every rollback is `forward-only`, with its reason. Each upgrade has known-wrong migrations, at least one of which
  passes the ordinary judge and is caught only on populated state.
- **The upgrade check** (`validation/upgrades.py`, `validation/upgrades.yaml`, CI job `upgrades`): each previous
  release rebuilt from the commit it was published at, with exactly its catalog digest; old examples accepted under
  it; the upgrade classified behavioral; the new reference accepted reusing nothing; the old deployment record not
  covering the new artifact; every example migrated from state its own old artifact produced; every known-wrong
  migration refused for exactly its defect.
- **Composition** (`compositions/reservation-kernels`, `validation/compositions.py`): authorization and posting with
  `INV1` and `CaptureAgrees` shared; three known-wrong integrations; TLC shows the integration and the frozen design
  obligations have the same behaviours.
- **Handoff by model agents** (`evolution/handoff`, `validation/handoff.py`): agent A built a tally 2 application from
  the release alone; agent B planned, made and classified an in-contract change, was judged reusing only what held,
  and refused the out-of-contract half of its request. The run found gaps in the tally 2 release (§ 6 of the RFC).
  One run, not a measurement.
- **Evaluator** (RFC 0006 § 5, both found by the upgrade check): `change.py classify` adds `evidence.reusable` and a
  note, because results that hold across a release are still not reused by the judge; `migrate.py run
  --allow-not-ready` accepts old evidence that awaits only a person's review and names it in the report
  (`from.awaiting_review`), as `deploy.py record --allow-not-ready` does. Self-reviewed: there is no second maintainer.
- **Decided, not changed** (RFC 0006 § 6): a release keeps holding only what the judge reads; the intent document and
  known-wrong examples travel with the seed, not the release.
- **Still needs people** (unchanged from RFC 0005 § 8): independent release reviews (every pack stays `draft`), a
  second maintainer, external adoption trials, the conditions experiment with real models, external review.

Release digests: reservation `10d14f9cd91450c14c4861ebaaff23bf13d88e7e5ae804bba04d048613a937b0`, booking
`3adf212726d64e3b2f9ba12673f3e39d5a7da7d05bb39b85ce893611ef737cbc`, approval
`4ae7a61844ef11c848ab086a4403317b1bf14c4ec4fc5ae973d31e21fc420977`, quota
`8e81efd2474c99f90f4caae157f198ac09917e54fd546aea4d92e9d07a8add38`; demonstrations (contracts unchanged, new evaluator)
tally 1.0.0 `c0b1d23e8b992db871d54932d9f5b7f4d915fc8750f51d44a0668e75579598b0`, tally 2.0.0
`57d8620daecde6872faecb7850a8b738d0a07e3349145be4968c1b50eb72c55c`.

## v0.11.0 — 2026-10-13
M6 of the roadmap: what a community-ready release needs that can be built before the community exists. RFC:
`docs/rfc/0005-community-release.md`.

- **Governance** (`GOVERNANCE.md`): three roles (behavioral semantics, evaluator security, integration and developer
  experience) and what each must not approve; independent review of every pack release and acceptance-policy change;
  supported versions, deprecation and retirement; keys, attestations and revocation; what happens when unsoundness is
  found. It opens by saying that one maintainer currently holds every role.
- **Compatibility** (`COMPATIBILITY.md`): versioning for the project, packs, contract records and releases; the
  stable interfaces by format identifier; how they may change (new identifier, old one read for two minor releases).
- **Catalog and revocations**: `catalog.yaml` (three supported packs; the outside author's quota pack and two demonstration releases listed as `demonstration`), held to its packs
  by `gate/catalog.py check` in CI; the stage is derived from `pack check`, so `released` cannot be claimed without an
  independent review. `revocations.yaml` (append-only, empty), `catalog.py revoked`, and `gate/deploy.py check
  --revocations`.
- **The conditions experiment** (`experiments/`, `docs/EXPERIMENTS.md`): protocol (prose, core with conventional
  tests, full Pith; full crossing with rotated order; one budget; outcome measured after a substantial change), common
  external criteria that know nothing of Pith, the run-record schema, `harness.py plan|validate|analyze|dryrun`.
  Dry-run in CI with scripted agents; **not run with real models**.
- **Validation**: `validation/governance.py` (catalog, a claimed stage refused, revocation end to end, the experiment
  harness end to end); CI job `packs` runs it. `gate/cli.py catalog`.
- **Not met** (RFC 0005 § 7): a second maintainer, independent pack reviews, real-model experiments, external
  review. All six catalog entries are `draft`.
- **Brought in from M3's final state** (the independent trace review, `packs/quota` by an outside author): the quota
  pack (0.1.1) gains what the v0.9.0 to v0.11.0 formats ask of a pack (`parameters`, `change_routes`, the task-packet
  category and contract records for each known-wrong library) with no change to its checks, and a catalog entry
  (`draft`, status `demonstration` until its author says it is supported). The `tlc` kind keeps both the action-property match and the
  `toolchain_unavailable` category.
- **Task packets name the records of every failing test**: a pytest check's packet took the record ids from the last
  3000 characters of output, so when several tests failed the first one's could be cut off (CI saw booking's
  `closed-intervals` packet miss `HalfOpen` when the concurrent-burst test also failed). The `command` kind now reports
  the ids named in the head of each failing test over the whole output, and the packet adds them to those in the tail.

Release digests: reservation `b6a58ad409fd80070f39c35e402dd3fb46e659be8b123c11b73b4f65e083ffa7`, booking
`4b2171324020b247ee1675d207f7778e8a30fc1d21143e26c8b0b7a3d65de774`, approval
`a0c27100b0d0c7838041e6e822238883ebb072e46f0ba813c8b1da89c2f8118f`, quota
`b10e8147eade371f29522ef47d170e39ed1eef40c7e38308e8ee5c3883fea8bc`; demonstrations tally 1.0.0
`94e8781945f07514f989abc1e3e9b52cb434301dbcd6e98ddb544ae47ee294b4`, tally 2.0.0
`e7bf373c80b4a359a02e1242f1ffe76aee54f6c3c772c34b865c48d7c7c434b3`.

## v0.10.0 — 2026-10-13
M5 of the roadmap: safe evolution. Applications change and upgrade without silently inheriting obsolete claims.
RFC: `docs/rfc/0004-safe-evolution.md`.

- **Change classification** (`gate/change.py plan|classify`, `pith.change-impact/v1`): before a change, which checks
  read the paths, the contract records at stake, the route and what must be re-established; after it, what changed
  (files and contract records), which evidence holds and which is invalidated. Never authoritative; ambiguity is
  listed. Every pack declares `change_routes` for the candidate's paths.
- **Composition contracts** (`gate/compose.py`, `pith.composition/v1`): owned state, permitted effects, local and
  shared invariants, atomicity, assumptions; TLC checks the integration and requires each known-wrong integration to
  keep the local rules and break exactly the shared invariant. `compositions/ledger-receipts`: separate stores still
  owe "the receipt and the effect agree" (this corrects a guess in `ARCHITECTURE.md`).
- **Migrations** (`gate/migrate.py`, `pith.migration/v1`): judged on state the previously accepted artifact's own
  service produced, including a request in flight; the candidate's migration must refuse unrecognised state and be
  re-runnable; the new service is judged on the migrated state; rollback policy stated. `evolution/tally-v1` →
  `tally-v2` is the contract upgrade (T1, T2 version 2, M1 added, forward-only), with two applications (one a rewrite
  on a journal) and two known-wrong migrations that pass the ordinary judge.
- **Deployment records** (`gate/deploy.py record|check`, `pith.deployment/v1`): artifact, release, evidence and
  contract identity, toolchain, runtime and configuration digests; `check` reports drift. Monitoring scope stated.
- **Evaluator**: evidence records `contracts` (record versions and routes) and `artifact_files`; `impact`
  invalidates evidence for a changed contract record; `evidence.current()`; `pack.py` validates routes; `pack check`
  validates `migrations` and accepts a migration as a record's verifier. `gate/cli.py change|compose|migrate|deploy|impact`.
- **Validation**: `validation/evolution.py` (agent handoff, substantial rewrite, contract upgrade with populated
  state, composed workflow), in CI job `packs`; `domain_free.py` scans the evolution packs and compositions.
- **Not done** (RFC 0004 § 8): the reservation pack's two-kernel composition is not yet restated as a composition
  contract; none of the three main packs has had a contract upgrade; the handoff's agents are scripted.
Release digests: reservation `a43a0626f59a8e5ca4a150b5966938ef001d78b037c5a027d5f93fc9ba079957`, booking
`d3158a1352189fcb39c8a0439cc31bc3c5fa173aa8ee6a1e675154cef35779a0`, approval
`92a7fa52d8f70354e958080efd713c5d92b1df2b0552425240c7d30cc13be19e`; demonstrations tally 1.0.0
`103143ba3bbbbe07cd9dbec50a325c37ddaa4b93a78839f336bdd8c7cb1e7970`, tally 2.0.0
`f3fd8dba1625afbc696d55501492baf1f20d4c8d5f1a4c04903ac925c48ed59f`.

## v0.9.0 — 2026-10-13
M4 of the roadmap: self-service adoption. RFC: `docs/rfc/0003-adoption-and-agent-feedback.md`; guide:
`docs/ADOPTING.md`.

- **Task packets** (`TASK.md`, `task-packet.json`, `pith.task-packet/v1`) after every run: the first failure, its
  category, the contract records it bears on, a minimal counterexample, what may be edited, and the rerun commands.
- **Six failure categories** (violation, not_exercised, evidence_missing, toolchain_unavailable, contract_change,
  infrastructure) on every failed check, with the basis. Pack-side `about: release` and `failure_category`; adapters
  report categories and failing obligations; harness tests name their contract records. An exception or timeout in a
  check is now a refusal with evidence, not a traceback.
- **CLI** (`gate/cli.py`, `./pith`): `doctor`, `verify`, `packet`, `pack new`, `pack check`, `adopt`; `--json` and
  stable exit codes. `integrations/spec-kit/` is a thin wrapper.
- **Contract authors**: `templates/pack` (a judgeable draft pack, judged in CI), `pack check` (consistency and
  adequacy; manifest keys need a declared domain and evidence, `parameters:`), and a pack release review signed by
  a non-maintainer (`gate/review.py sign-pack`); the stage is derived.
- **Existing projects**: manifest `include` and `subsystem`, the `coverage` statement in every report, `adopt`, and
  `packs/approval/examples/adopt-handbook` with its known-wrong twin `adopt-handbook-stale`.
- **Validation**: every known-wrong application of the three packs gets its expected category and contract records;
  `validation/packets.py` (one run per category), `validation/adoption.py`, `validation/test_packet.py`.
- **Not met** (RFC 0003 § 8): external developers completing a fresh-seed build and an existing-project adoption from
  the published instructions; no pack has had an independent release review.
Release digests: reservation `117f339033b4c2b38c036ce9d277fd487f128c30435a002b4e01fd6cb12fce35`, booking
`ae8c1b06dcf3d6eb794cf039494625339df78f048a503f969e565393175e1598`, approval
`78a7bd4575d9f54abf9a1c0f5eaf2291744ed6d66b120efea52c0a4c175d598b`.

## v0.8.0 — 2026-10-13
M3 of the roadmap: generality. Two structurally different packs judged by the same evaluator as the reservation
pack. RFC: `docs/rfc/0002-generality.md`; authoring guide: `docs/PACK-AUTHORING.md`.

- **`packs/booking/` (`pith.booking`)**: interval booking with half-open intervals, cancellation and atomic
  rescheduling. Dafny spec and verified core (B0–B5, X1–X3, M0–M3), eight known-wrong cores the spec rejects,
  reviewed traces T1–T11; shipped Python/SQLite and Node.js/journal profiles on the Python and JavaScript
  translations (both reproduced byte-for-byte on every run, each with its own profile tests) or a custom store;
  black-box lifecycle, boundary and conformance harnesses; a browser UI contract (BW1–BW6, BI1–BI3 under injected
  faults) and human evaluations BE1–BE2. Examples `calendar-py`, `desk-node`, `custom-py`; four wrong applications.
- **`packs/approval/` (`pith.approval`)**: document approval with roles, per-revision separation of duties,
  approvals bound to a revision and a two-approver quorum, over a simulated actor model. TLA+ model (A1–A8) checked
  by TLC, eight known-wrong designs it rejects, a reference model `harness/refines.py` shows equal to the spec
  (1898 states, 2330 transitions, actors included), reviewed traces T1–T11; the candidate writes the whole service and is judged
  black-box against the reference; a command-line client contract (AW1–AW5, AI1–AI3 under a judge-owned fault
  proxy); no human evaluation and a `model_assurance` status. Examples `approvals-py`, `approvals-node`; three
  wrong applications.
- **`packs/quota/` (`pith.quota`)**: sliding-window quotas delivered as a library (Python or Node.js), with no
  service, written from the docs by an independent agent author with no edits to `gate/`. Dafny spec and verified
  core (Q0–Q5, WINDOW, CLOCK), four wrong cores checked to fail only on their claimed obligations and to differ on
  a named trace, eight traces, frozen drivers run as the candidate, a consumer-program delivery adapter; examples
  `sliding-log-py`, `tally-node`; six wrong applications. Its friction log, `packs/quota/AUTHORING-NOTES.md`, lists
  five evaluator additions it wanted (RFC 0002 § 4); `docs/PACK-AUTHORING.md` § 4 answers its documentation gaps.
- **Evaluator** (`gate/`), each change forced by one of the packs (RFC 0002 § 4): `release.py build|id|seal
  --pack`; `each: {glob}`; `expect_exit: nonzero` and `{item}` for `command`; `gate/service.py` (supervised
  candidate service); `sandbox.limits` overrides and `run_as_candidate_full`; `gate/browser.py` (browser
  containment); isolation scope names the pack's candidate runtimes; the exit code follows the completion
  status's `ready` condition; a blocking failure refuses the status its check counts toward; `tlc`'s
  `{violated: X}` also accepts an action property.
- **Validation**: `validation/generality.py` (one evaluator digest across packs; variation per pack);
  `domain_free.py` scans every pack's vocabulary; `judge_example.sh` and `judge_wrong.py` take `--pack`; CI job
  `packs` judges both new packs and their wrong applications. The reservation pack keeps the M2 baseline
  (`compare_m1.py`).
- **Not done** (RFC 0002 § 7): the traces were reviewed by an independent agent (`docs/reviews/m3-trace-review.md`,
  every finding applied) but not yet by a human, and the independent pack author is an agent, not a person. The isolation container has no Node.js, so the enforced-isolation CI run is still
  reservation-only.
Release digests: reservation `3286ed7e2257e2d6b93728e2fce0dd95e86eec4f1547f44bc6374fcb1d2c6119`, booking
`a90e315748315501532551968263d46bb67019cec66bcadf140b7fdd0923331c`, approval
`14d4b7a14b79144851fe7256ef33b3a63848b36ee48434bc75cc212eec61ab6c`, quota
`3e7b2cb3817a228c70d70c7b300c791c3b9dd3e24332c3119c6314bd839e7e9e`.

## v0.7.0 — 2026-10-13
M2 of the roadmap: a reusable foundation. The reservation seed becomes one contract pack judged by a domain-free
evaluator, with structured, dependency-aware evidence. RFC: `docs/rfc/0001-contract-packs-and-evidence.md`.

- **Contract pack** `pack.yaml` (replaces `gate/policy.yaml`): policy and agent-owned dirs, toolchain, the ordered
  checks (each of a kind, with inputs, dependencies, method and the contract records it establishes), how checks
  roll up into the three statuses, and 35 contract records (identity, version, intent, exclusions, native
  semantics, timing, verification, assumptions, satisfying and violating examples, change route).
- **Domain-free evaluator** `gate/`: `app_gate.py` (judge), `pack.py` (load, validate, expand), `kinds.py` (command,
  files_present, source_rules, tlc, regenerated, manifest_choice, manifest_commands, adapter, attestation),
  `workspace.py`, `sandbox.py` (candidate identity and limits, from the supervisor), `isolation/` (moved from
  `obligations/isolation/`). Nothing in `gate/` names the pack's domain; `validation/domain_free.py` checks it in CI.
- **Delivery is an adapter**: `obligations/app/delivery_adapter.py` holds the lint + browser aggregation the judge
  used to do; the evaluator only sees a status, problems, detail and release conditions.
- **Structured evidence**: `evidence.json` (one record per check: method, establishes, depends_on, input files and
  digests, tools, key) and `statement.intoto.json` (in-toto Statement v1, unsigned) in every evidence directory.
  `gate/evidence.py impact` says which records a change invalidates and why; `app_gate.py --reuse` reuses cacheable
  records (proof, model checks) with identical keys from the same release and evaluator, and says so.
- `release.py`: the release is `gate/` + `pack.yaml` + the pack's `policy_dirs`; seal format 2 names the pack;
  `release.py dirs` lists the release's directories. The isolation probe now also tries every pack policy dir.
- `app-claims.json` keeps every v0.6.0 key and adds `pack`, `evidence`, `evidence_digest` and a check `id`.
- Validation: `validation/compare_m1.py` (+ `baselines/m1.json`, recorded with the v0.6.0 judge),
  `validation/evidence_reuse.py`, `validation/domain_free.py`; the matrix case for an edited policy file now edits
  `pack.yaml`.
Release digest `34be91fc373f76106c1c52f298127639242d22ebd955a91bf6bf21d341b601fa`.

## v0.6.0 — 2026-10-13
M1 of the roadmap: the reservation application as an honest end-to-end reference.

- **Interaction obligations I1–I6** (`obligations/app/UI-CONTRACT.md`, `delivery.yaml:required_interactions`):
  action-target binding, failed switch, view consistency under reordered responses, receipt preservation across a
  failed refresh, outcome/view separation (`UNKNOWN` / `REJECTED` / decision), receipt scope. Judged in a real
  browser through a judge-owned fault proxy (`obligations/app/faultproxy.py`) that delays, fails or loses chosen
  responses while the page runs unmodified; every verdict is read from the service's own state. Each probe must
  reach its precondition, so an interface without the affordances cannot pass vacuously. UI contract additions:
  `btn-load`, `loaded-account` (`data-account-id`, `data-state`), `data-account-id` on rows and on `decision`,
  `data-request-id` on `decision`, decision values `REJECTED` and `UNKNOWN`.
- **Optional client-state library** `obligations/app/lib/pith-view.js` (draft selection, loaded view, pending
  operation, receipt; pure transitions + a fetch driver; 9 node tests). Framework-free and not required.
- **Known-wrong release fixtures** `examples/wrong/club-desk`, `examples/wrong/office-desk`: the desk applications
  as submitted to the 2026-10-13 review, contract markup only. `validation/judge_wrong.py` (CI) requires the
  pristine gate to fail each on exactly the obligations in `examples/wrong/expected.yaml`.
- **Corrected desks** `examples/club-desk`, `examples/office-desk` pass every obligation; the reference UIs
  (`build-a` on the library, `build-b` by hand) were corrected too: both had the action-target defect.
- **Supported isolation profile** `obligations/isolation/`: pinned container, no network, read-only mounts, the
  candidate's service (uid 10001) and the browser (uid 10002) as separate unprivileged users, rlimits and cgroup
  limits. The gate runs a frozen probe under the candidate's identity before any candidate code and records what
  it could reach; `isolation.status` is `enforced` only if nothing was. The supervisor drops privileges, owns the
  candidate's process group and applies rlimits.
- `release_ready` additionally requires an enforced isolation profile and a contained browser (Chromium's sandbox,
  or the separate browser user under the enforced profile); `release_ready_missing` names what is absent.
- Docs reconciled (README, ARCHITECTURE § The interface is a layer too, AGENT, CUSTOMIZATION, SECURITY,
  CONTRIBUTING, examples/README). CI judges four examples and the wrong fixtures, runs the library tests, and judges
  build-a inside the isolation profile.
Release digest `512e9c778ffd78fad9c8b8822339d74ddd086f3a0eb429cf9cdc5721e65a53ee`.

## v0.5.0 — 2026-10-12
Second proven kernel: posting (`Capture`), as a separate Dafny module importing the shared state and invariant;
four capture adequacy candidates; two capture traces. Design obligations compose both kernels: `posted` is a
variable, `CoreCapture` an atomic action, `INV1` the composition invariant checked under interleaving, `P4`
(Post terminal), `PostedExact`, coverage for captures and captures under contention. Rings 2–3: capture route,
`capture.posted` event, monitor capture semantics with negative cases, lifecycle and boundary coverage, UI
contract `btn-capture`/`posted`, workflow W6. ARCHITECTURE.md records what composition turned out to mean.
Release digest `df0b0b2eb69ebde3e2bdbd89fec5c679df28d74cb6e458ee371a3aa3ec35ec89`.

## v0.4.1 — 2026-10-12
Published as **Pith** (formerly core-seed). Also: `bootstrap.sh` fails on a bad toolchain download instead of
printing ok; CI workflow fixes (monitor generated before its suite, pipeline exit codes no longer masked, Chromium
sandbox enabled on ubuntu-24.04, toolchain cached, actions on Node 24). No frozen file changed; release digest unchanged.

Portability fixes surfaced by the first unassisted agent build (macOS): OS metadata files ignored by every check
and digest; paced readers in the lifecycle harness; robust toolchain record; venv-based bootstrap with a macOS
branch; `--candidate` runs the pristine release's judge against a checkout. Release digest `7c161daa9147f952a3385d275fa134c848890a60bc0a87aa89e2849750d63433`.

## v0.4.0 — 2026-10-11
Evaluator made external after review: no candidate Python imported; service run as a separate process from a
fixed entrypoint; judged copy of the deployment artifact digested whole; pytest without conftest; frozen `MC.tla`
binds checked design predicates; fail-closed translation reproduction and attestation verification; monitor
operation lifecycle by `op_id` with watermark; full runtime postcondition re-check incl. Release.

## v0.3.0 — 2026-10-11
Merged from an independent implementation (ProofSeed): release seal and external pin, evidence directory with
artifact snapshot, Ed25519 review attestations, UI contract and real-browser workflow acceptance, hash-chained
events with committed state, runtime postcondition re-check, `release_ready`.

## v0.2.0 — 2026-10-11
After external review: frozen policy and manifest allowlist; `DecideCorrect` and coverage obligations; shipped
SQLite profile with domain validation; frozen adapter and boundary harnesses with JSON Schema validation; monitor
contract and negative suite; three separate statuses.

## v0.1.0 — 2026-10-11
Initial seed: Dafny kernel with adequacy suite and audit channel, TLA+ obligations, generator, lint, app gate.
