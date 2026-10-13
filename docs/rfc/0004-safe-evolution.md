# RFC 0004 — Safe evolution: change classification, composition, migration, deployment

| | |
|---|---|
| Status | Implemented in v0.10.0 (roadmap milestone M5). § 8 says which M5 exit criteria are met. |
| Applies to | `gate/change.py`, `gate/compose.py`, `gate/migrate.py`, `gate/deploy.py`, `gate/evidence.py`, every pack's `pack.yaml` (`change_routes`, `migrations`), `compositions/`, `evolution/`, `validation/evolution.py` |
| Builds on | RFC 0001 (packs and evidence), RFC 0002 (generality), RFC 0003 (adoption and agent feedback). Nothing in their formats is withdrawn. |

## 1. What M5 asked

Applications survive substantial changes and upgrades without silently inheriting obsolete claims. Four parts: classify
a change before it is made; specify composition instead of assuming it; treat migrations as behavioural
transformations of real state; bind evidence to deployment. The exit gate: an agent handoff, a substantial rewrite, a
contract upgrade with populated state and a composed workflow, without inheriting stale evidence or erasing durable
history.

## 2. Change classification (`gate/change.py`)

Every contract record already names its route (`change: presentation | integration | behavioral`). A pack may now
also name routes for the candidate's own paths:

```yaml
change_routes:                      # advisory; validated by gate/pack.py
  - { paths: ["ui/**", "app/**"], route: presentation, why: "delivery and interaction checks" }
  - { paths: ["design/**", "service/**"], route: integration, why: "runtime assumptions and correspondence" }
```

All three shipped packs declare them. Two commands, both producing a report in format `pith.change-impact/v1`:

- `change.py plan --evidence PREV --paths P...`, **before** implementation: which checks read the paths (the previous
  run's recorded inputs, and the release's `inputs` globs, so a file that does not exist yet is still placed), the
  checks that rest on those, the contract records they establish, the route and what must be re-established.
- `change.py classify --evidence PREV [--candidate DIR] [--policy-from RELEASE]`, **after**: the files that changed
  since PREV was judged (evidence now records every judged file's digest, `artifact_files`), the contract records
  that changed when RELEASE is a new release (evidence now records each record's version and route, `contracts`),
  which evidence holds and which is invalidated and why.

The route of a change is the strictest of: the route of each changed contract record (a record without one is
behavioral); for each changed path, its declared route and the route implied by the records of the checks that read
it. An implementation change to code that feeds a behavioral record is an **integration** change: it re-establishes
the record's evidence, it does not change the record. Only a change to the contract itself is behavioral.

What each route requires (`required` in the report):

| Route | Required |
|---|---|
| presentation | re-run the affected delivery and interaction checks |
| integration | re-establish the runtime assumptions and correspondence: re-run every invalidated check |
| behavioral | revise and review the contract records, validate intent, update the known-wrong candidates, publish a new release, judge against it; no evidence for the old contract carries over |

**Not authoritative.** Every report says `authoritative: false`. It is ambiguous, says so and lists why, when declared
routes disagree for a path, when a path's declared route is weaker than what the checks reading it establish, when a
changed path is read by no check and has no declared route, or when a frozen release file changes (whether the
contract's meaning changed is the maintainers' call). The route given is then the strictest candidate. A path outside
the judged artifact has no route: nothing rests on it and nothing covers it. The judge decides acceptance, never the
report.

`evidence.py impact` gained the same contract awareness: a record that establishes a contract record whose version
changed is invalidated even when its inputs did not change (it is evidence for the old contract). Reuse was already
release-bound (`--reuse` takes nothing from another release), and the demonstrations check it.

## 3. Composition contracts (`gate/compose.py`)

Format `pith.composition/v1` (`compositions/<name>/composition.yaml`): components, each with the module that declares
its state, the variables it **owns**, its local invariants and its **permitted effects** (the only actions through
which its state may change); **shared invariants**, each spanning at least two components; **atomicity** requirements
(which transitions must commit across which components); **assumptions** between components; and **known-wrong
integrations** with the shared invariants each must violate. The model stays TLA+ in its own form: one module per
component, an integration module, and a contract module that extends the integration with the shared invariants.

`compose.py check DIR [--integration FILE]` establishes, within the model's bounds:

1. structure: each component's module declares exactly the variables it owns, no variable has two owners, every
   shared invariant spans two or more components, atomicity and wrong entries name what exists;
2. the integration keeps every local invariant, every permitted-effect rule (generated as `[][E1 \/ E2 ...]_owned`
   per component) and every shared invariant;
3. every known-wrong integration keeps the local invariants and effect rules and violates exactly the shared
   invariants it is listed for, so the check can tell a broken composition from a broken component.

The demonstration is `compositions/ledger-receipts`: a ledger (owns the applied effects, bounded by a capacity) and a
receipt store (owns the outcome each client is told, written once) with the shared invariant `ReceiptAgrees`. The
integration decides at the ledger and records the receipt in one atomic step. The known-wrong integration checks for
room, records the receipt and applies the effect in three steps: each component's rules hold throughout, and TLC
finds a receipt reporting an effect that is not there. Separate storage did not remove the coupling.

The joint result is only as strong as the atomicity assumption; the report repeats the assumptions. The engineering
obligation, that the implementation executes the modelled transitions atomically, is the integration route's and is
not discharged by the composition check. The reservation pack's two kernels, which share account state through the
design model, are an existing composition that is not yet restated in this format.

## 4. Migrations (`gate/migrate.py`)

A release that changes a contract can declare migrations (`pack.yaml: migrations: [{from: <contract version>, spec}]`,
the spec inside the release's policy dirs, so it is frozen with the release). Format `pith.migration/v1`: from and
to contract versions, the contract records the migration establishes, the state it applies to, the **mapping** from
old state to new, how **old retries** and requests **in flight** behave, the **rollback** policy (`forward-only` with
the reason, or `reversible`), and three commands: `populate` (the release's), `migrate` (the candidate's) and
`verify` (the release's harness). A contract record may name the migration that verifies it (`migration:`), and
`pack check` accepts that as its verifier.

`migrate.py run --release NEW --candidate NEW_CANDIDATE --old-release OLD --old-candidate OLD_CANDIDATE
[--old-evidence EV] --out DIR`:

1. with `--old-evidence`, the old candidate must be the artifact that evidence accepted under the old release (same
   artifact and release digests, every status ready): the state comes from what was actually accepted;
2. `populate` drives the **old artifact's own service** to produce real state (results, refusals, a request in flight
   when the service is killed) and records what it acknowledged;
3. `migrate` must refuse state it does not recognise and leave it untouched;
4. `migrate` transforms the state, as the candidate's identity; then runs **again** and must succeed (an interrupted
   and retried migration is the norm);
5. `verify` judges the new service, black-box, on the migrated state against what the old service acknowledged;
6. the rollback policy is reported; `forward-only` is a stated compatibility restriction, not a check.

The report (`pith.migration-report/v1`) carries both releases' and artifacts' digests, the migrated state's digest,
each step's result and failure category, and the spec's statements.

The demonstration is `evolution/tally-v1` → `evolution/tally-v2`: version 1 is the scaffold's contract (one bounded
tally), version 2 bounds each named counter (T1, T2 version 2), keeps Idempotency and Durability, and adds M1 (the
upgrade keeps every recorded result for counter `default`, replays old request ids, keeps the reached bound, decides
an in-flight request at most once). Rollback is forward-only: once version 2 records a request for another counter,
version 1 cannot represent the state. Two version 2 applications migrate: `basic` (SQLite, adds a column) and
`journal` (a rewrite on an append-only journal, which converts the database). Two known-wrong migrations,
`drops-refused` and `renames-default`, pass the ordinary judge (their service is the conforming one) and are refused
at `verify` for exactly their defect: only the run with populated state catches them.

## 5. Deployment records (`gate/deploy.py`)

`deploy.py record --evidence EV --release RELEASE --candidate DIR [--config K=V ...]` refuses unless the evidence
verifies, it is from an authoritative run, the release is the one it names, the candidate is the judged artifact, and
every status is at its ready value (or `--allow-not-ready`, which the record states). The record (`pith.deployment/v1`)
carries the artifact, release, evidence and evaluator digests, the contract identity (pack, version, contract version,
each record's version), the statuses, isolation, toolchain and dependency versions the evaluator recorded, the runtime
(Python version, platform), and the runtime configuration as SHA-256 digests of each value (values may be secrets).

`deploy.py check --record R --release RELEASE --deployed DIR [--config K=V ...]` recomputes the deployed artifact's
digest under the release and reports every difference: release, artifact, runtime, configuration. A deployment that
differs runs something the evidence does not cover.

Both say what the record does not do: it does not observe the running system, and runtime monitoring covers only
what the service emits, so a complete-looking event stream is not proof that no side effect bypassed it.

## 6. Evaluator changes

Each forced by a demonstration: `evidence.json` records `contracts` (each record's version and route) and
`artifact_files` (each judged file's digest), so a later change can be classified; `evidence.current()` computes keys
for a candidate without running anything (used by `impact` and `change.py`); `impact` invalidates evidence for changed
contract records; `pack.py` validates `change` and `change_routes`; `pack check` validates `migrations` and accepts a
migration as a record's verifier, and strips a `#section` from semantics paths. Four new evaluator modules, all
domain-free (`validation/domain_free.py` now also scans the evolution packs and the composition demos).

## 7. The exit demonstrations (`validation/evolution.py`)

Run in CI (job `packs`). Each expectation is recorded in `evolution-record.json`.

1. **Agent handoff.** Agent A's accepted run and task packet are handed to agent B. B plans a change to
   `service/run.py` (`plan`: integration, re-run the lifecycle harness and the entrypoint checks), makes it, classifies
   it (`classify`: the same route, the same checks), and is judged with A's evidence offered: accepted, only records
   the change left intact are reused, nothing it invalidated is.
2. **Substantial rewrite.** The same application rewritten on a journal instead of SQLite: classified integration,
   every service-derived record invalidated, judged on its own evidence; only the model checks carry over.
3. **Contract upgrade with populated state.** The v1 application is accepted and recorded for deployment; moving to
   tally/v2 is classified behavioral (T1, T2 version 1 → 2, M1 added); no v1 evidence holds or is reused under v2; the
   v1 deployment record does not cover the v2 artifact; both v2 applications migrate state the accepted v1 artifact
   produced, history intact; both known-wrong migrations are refused for their defect, and one of them passes the
   ordinary judge.
4. **Composed workflow.** `compose.py check compositions/ledger-receipts`.

## 8. M5 exit criteria

| Criterion | State |
|---|---|
| Changes classified before implementation; machine-readable change-impact reports; ambiguity not presented as authority | **Met** (`change.py plan`/`classify`, `pith.change-impact/v1`, `authoritative: false`, ambiguity listed). |
| Composition specified, with a broken integration that keeps local rules and breaks the joint contract | **Met for one demonstration** (`compositions/ledger-receipts`). The reservation pack's two-kernel composition is not yet restated in this format. |
| Migrations as behavioural transformations: mapping, populated state, old retries, rollback stated | **Met for one contract upgrade** (tally/v1 → v2, two applications, two known-wrong migrations). The three main packs have not had a contract upgrade yet, so none ships a migration. |
| Evidence bound to deployment; monitoring scoped | **Met** (`deploy.py record`/`check`). |
| **Exit gate:** agent handoff, substantial rewrite, contract upgrade with populated state, composed workflow, without stale evidence or erased history | **Met in the repository, scripted** (`validation/evolution.py`, CI). The agents in the handoff are scripted edits, not model runs; M6's experiment harness is where real agents are measured. |

## 9. Limits

- Routes are inferred from declarations and from which checks read which files. A change whose meaning is behavioral
  but that touches only presentation files (a label that now says something different) is classified presentation;
  the report cannot know intent, which is why it is never authoritative.
- The composition check is bounded model checking of a model; it says nothing about whether an implementation's
  transactions match the modelled atomic steps.
- The migration check runs one populated history (with one request in flight). It is a test of the mapping, not a
  proof; the spec's statements about retries and rollback are claims the verify harness checks only where it can.
- A deployment record proves equality of digests, not that the deployment runs only the recorded artifact.
