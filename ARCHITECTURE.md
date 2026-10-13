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
- **Kernels over disjoint state would compose more loosely.** An idempotency-receipt store, for example,
  would share no invariant with authorization and could be composed through the design model alone. That
  case is not yet built; it is the next thing to test.

The honest summary: proven cores compose, but the unit of proof is the shared state, and the unit of
composition is the design model. The project's claim is true in the model and narrower in the proofs than
v0.4 implied.

## What this is not

Not a proof of the application. Not a stdlib-only host (the Dafny Python runtime is required to run the core).
Not a sandbox. Not a complete payment system: posting, settlement, expiry and eligibility are out of scope and
documented as behavioural extensions requiring a new release.
