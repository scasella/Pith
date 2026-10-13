# Changelog

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
