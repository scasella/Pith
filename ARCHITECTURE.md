# Architecture

The application is organised as rings around a proven core. Each ring has a frozen contract, an oracle that
can fail, and a scoped claim. Nothing outside ring 0 is proven; everything outside ring 0 is unable to disagree
with ring 0 without a test failing or a monitor firing.

```
ring 0  kernel/            Dafny spec + proof; translated core executed by the service
ring 1  design/, adapter   TLA+ design (agent) against frozen obligations (CoreActions.tla, MC.tla); integration
                           judged black-box through the running service (obligations/service/lifecycle.py)
ring 2  service/, gen/     API, events, monitor derived from the kernel by a reviewed generator; boundary harness
ring 3  app/, ui/          prose spec (lint), UI contract, real-browser workflows, interaction obligations under
                           injected response faults; human review by attestation
```

## Why the judge is shaped like this

Two external reviews found the same class of defect twice: the evaluator ran candidate code in its own
process, so the candidate controlled the evidence. The current judge therefore:

- never imports candidate Python; the service is started from a fixed entrypoint as a separate process with a
  scrubbed environment, and all observations are the judge's own (HTTP through a frozen client, a browser the
  judge drives);
- judges a copied deployment artifact in a fresh workspace, digested whole with no basename exclusions;
- takes its own code and policy from a pristine release when run with `--candidate` or `--policy-from`;
- fails closed: a translator that produces nothing, an attestation that decides nothing, a browser that cannot
  launch are refusals or blockers, never passes;
- reports three statuses and a `release_ready` flag rather than one word.

- observes isolation instead of assuming it: a frozen probe runs under the candidate's identity before any
  candidate code and reports what it can reach; release-readiness needs that probe to find nothing.

A process boundary is not a sandbox. Until v0.5.0 a hostile `service/run.py` ran as the judge's user and
operational isolation was left to the operator. v0.6.0 ships one supported profile (`gate/isolation/` since v0.7.0):
a pinned container with no network, read-only policy and candidate mounts, the candidate's service and the
browser as two separate unprivileged users, and resource limits. Outside it the judge still runs, labelled
advisory, and reports what the candidate could reach.

## The evaluator and the pack

From v0.7.0 a release is a domain-free evaluator plus one contract pack (`docs/rfc/0001-contract-packs-and-evidence.md`).

```text
gate/        evaluator: judge, check kinds (command, tlc, source_rules, adapter, attestation, ...), evidence,
             workspace and digests, candidate identity and limits, isolation profile, release seal, review
pack.yaml    the reservation pack: policy and agent-owned dirs, toolchain, ordered checks, statuses,
             35 contract records; kernel/, obligations/, profiles/ are its policy dirs
```

The evaluator knows packages, artifacts, tools, checks, evidence, statuses and policies. Every path, pattern,
invariant name, command and sentence about reservations comes from `pack.yaml`; CI checks that none of the pack's
vocabulary, contract ids or check ids occurs in `gate/` (`validation/domain_free.py`). Delivery is a pack adapter
(`obligations/app/delivery_adapter.py`): a browser is this pack's way of delivering, not the method's.

Each check writes an evidence record keyed by the digests of its declared inputs, its toolchain, the evaluator's
code and the keys of the records it rests on (`evidence.json`, with an in-toto statement binding them to the
artifact). A change therefore invalidates exactly the records whose inputs, or whose supports, changed:
`gate/evidence.py impact` lists them, and `--reuse` re-runs only those plus everything that is not cacheable. Only
the proof and the model checks are cacheable; a check that starts the candidate's service always runs.

From v0.8.0 the same evaluator judges two more packs, each its own release built from `packs/<name>/`:
`pith.booking` (a verified Dafny core the candidate's service builds on, with a Python and a Node.js backend
profile, delivered as a page) and `pith.approval` (a TLA+ model; the candidate writes the whole workflow and is
judged against a reference model that `harness/refines.py` shows equal to the spec within bounds; delivered as a
CLI, with no human evaluation). What the evaluator had to learn for them, and why, is
`docs/rfc/0002-generality.md` § 4: multi-pack releases, glob and must-fail checks, service supervision and
browser containment moved out of the reservation pack, per-runtime limits. Every run records the evaluator's
digest, and `validation/generality.py` checks it is the same across all three packs.

From v0.9.0 every failure is categorised (`violation`, `not_exercised`, `evidence_missing`, `toolchain_unavailable`,
`contract_change`, `infrastructure`, with the basis for the inference) and every run ends with a task packet
(`gate/packet.py`); an exception or timeout inside a check is a refusal in category `infrastructure`, never a crash
without evidence. `gate/cli.py` is the one command-line and JSON interface. A pack may let an existing project name
its own code (`include`), which is copied into the judged artifact and judged only through the pack's entrypoints;
every run states what it covered (`coverage`). `docs/rfc/0003-adoption-and-agent-feedback.md`.

The rings below are the reservation pack's structure (`area` in `pack.yaml`), not the evaluator's.

## The interface is a layer too

The Club Desk / Office Desk review (`docs/VALIDATION.md`, v0.6.0) found two applications whose protected
implementations were intact and whose proofs held, yet a displayed hold could release or capture a hold on a
different account, and a successful authorization could be shown as an error after a failed refresh. The core's
validity does not establish that the interface maps what the user selected to the operation it submits.

For each protected behaviour the chain of confidence is:

```text
approved intent → precise obligation → abstract model → implementation and runtime assumptions
    → observed operation, persistence, receipt and presentation → evidence for this artifact
```

v0.6.0 adds the last observable link for the reference domain: interaction obligations I1–I6
(`obligations/app/UI-CONTRACT.md`), judged in a real browser through a judge-owned proxy that delays, fails or
loses chosen responses. They are stated in observable terms (which account the submitted operation names, which
account's figures are shown, what outcome the page claims) and judged from the service's own state. The known
desk defects are kept as release fixtures (`examples/wrong/`) that must fail exactly those obligations.

## Why the obligations are shaped like this

- The spec ships with *wrong candidates* it must reject (always-decline, decline-at-equality, hold-on-decline,
  rewritten history, release-leaves-hold) because verifier-accepted specifications are routinely vacuous.
- Agent-written design models must *reach* behaviours (retries, contention, declines under load, releases),
  checked as invariants TLC must violate, because a model that models too little passes everything.
- The checked design predicates are bound in a frozen wrapper (`MC.tla`), not defined by the candidate.
- Every event carries an operation id and a hash chain; `op.committed` carries the committed state; the monitor
  tracks operation lifecycles and accepts a watermark, because event atoms alone cannot say an operation finished.

## Two kernels: what composition turned out to mean

v0.5.0 added a second proven kernel (posting: `Capture` moves an authorized hold into `posted`) to test the
claim that an application is several proven cores composed in the design model. The result, recorded here
because it narrows the earlier wording:

- **The proofs separate at the module level, not at the state level.** `PostingSpec.dfy` is its own module
  with its own trait, implementation, adequacy suite and tags, and it is verified in the same run. But it
  imports the *shared state type* and the *shared invariant* (`Valid`, hence `INV1`) from `AuthSpec.dfy`. Two
  operations on the same account state cannot have independent invariants; the invariant is defined once and
  each kernel's proof discharges it for its own transitions. "Two kernels" therefore means two obligation
  sets over one state, not two states.
- **The composition invariant lives in ring 1 and only there.** `INV1` (`posted + reserved ≤ limit`) is now
  something either kernel can break. Each proof shows its own transition preserves it; nothing in Dafny
  shows that interleavings of Decide, Release and Capture preserve it, because Dafny sees one call at a
  time. `CoreActions.tla` composes the kernels as atomic actions and TLC checks `INV1` across their
  interleavings, together with `DecideCorrect` (a decision is made against the availability of the same
  step, which capture now changes) and coverage obligations requiring the design to actually capture under
  contention. This is the piece that was asserted in v0.4 and is exercised in v0.5.
- **Cross-kernel terminality needed stating.** "Post is terminal" is a property of every kernel's frame
  conditions, not of Capture alone; `PostingSpec.dfy` states it as a predicate with a lemma per operation,
  and `P4` restates it over the composed model.
- **Disjoint state does not mean no shared invariant.** v0.5.0 guessed that an idempotency-receipt store would
  share no invariant with authorization and could be composed loosely. v0.10.0 built the case
  (`compositions/ledger-receipts`, `gate/compose.py`, `docs/rfc/0004-safe-evolution.md` § 3) and the guess was
  wrong: a receipt store and an effect store, each owning its own state, still owe each other "the receipt and the
  effect agree". A known-wrong integration that records the receipt before applying the effect keeps every local
  rule of both components and breaks that joint invariant, and the composition check finds it. A composition is
  now stated, not assumed: owned state, permitted effects, shared invariants, atomicity, assumptions.
  v0.12.0 restated the reservation pack's own two kernels in that form (`compositions/reservation-kernels`: `INV1`
  and `CaptureAgrees` shared, `Decide` and `Capture` atomic across both) and checked with TLC that it has the same
  behaviours as the design obligations it restates.

The honest summary: proven cores compose, but the unit of proof is the shared state, and the unit of
composition is the design model. The project's claim is true in the model and narrower in the proofs than
v0.4 implied.

## Change is a layer too

v0.10.0 (`docs/rfc/0004-safe-evolution.md`) treats change as something the release describes rather than something
evidence silently survives. Every contract record names its change route and a pack names routes for the
candidate's paths; `gate/change.py` turns a planned or made change into a report of what it reaches and what must be
re-established, and never claims authority. Evidence records each contract record's version, so evidence for an old
contract is invalidated by a contract upgrade even where its inputs did not change, and `--reuse` never crosses
releases. A contract upgrade ships a migration that is judged on state the previously accepted artifact produced,
not on an empty database. A deployment record binds the evidence to what is deployed and says what it cannot see.
v0.12.0 (`docs/rfc/0006-upgrading-the-main-packs.md`) did this for real on all four main packs, each judged from the
release it actually published (`validation/upgrades.py`).

## Assurance that runs on its own (v0.13.0)

`docs/rfc/0007-autonomous-assurance-and-runtime-composition.md` adds six things, each with a known-wrong case it must
refuse, and none weakening a rule above:

- **Composition at runtime.** A composition contract may add a `runtime` block: one process per component behind a
  judge-owned fault proxy, a driver that kills or severs between the steps of a cross-component operation, and shared
  invariants checked from each component's own state (`gate/compose.py verify`). `compose stagger` upgrades one component
  of a running composition and requires the others' state byte-identical (`compositions/booking-quota`).
- **Adequacy by adversaries.** `gate/redteam.py` takes mutants (generated, or brought as saboteur packets with a witness)
  and records each one the gate accepts although its witness shows it wrong; `pack check --release` refuses a pack with
  an open gap until the checks are tightened and the gap promoted into its known-wrong suite.
- **Packets an agent can act on without seeing the judge.** Every run also writes a redacted packet with a structured,
  shrunk counterexample in the contract's own words.
- **Concurrency without timing.** `gate/interleave.py` runs the threads under test one at a time and explores every
  schedule within a preemption bound, so a race within the bound is found on every run; the reservation pack gains an
  optimistic-concurrency profile (`sqlite-occ`) checked for linearizability within that bound.
- **A shadow oracle beside the live service.** The generated monitor can run as a sidecar that replays each committed
  operation through the pack's oracle; `gate/trace.py` shrinks a divergence into a regression trace and a draft revocation.
- **Fork-join handoffs.** Branches made in parallel from one accepted base merge when they touch disjoint partitions the
  pack declares; the merged tree is judged again, reusing only cacheable evidence. Disjointness says which evidence
  carries over, never that the merged application works: every check that starts the service runs again, and that is
  what catches two branches that each work alone and break together.

## What this is not

Not a proof of the application. Not a stdlib-only host (the Dafny Python runtime is required to run the core).
Not a sandbox. Not a complete payment system: posting, settlement, expiry and eligibility are out of scope and
documented as behavioural extensions requiring a new release.
