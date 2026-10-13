# Changelog

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
Release digest `RELEASE_DIGEST`.

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
