# Changelog

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
