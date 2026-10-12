# Architecture

The application is organised as rings around a proven core. Each ring has a frozen contract, an oracle that
can fail, and a scoped claim. Nothing outside ring 0 is proven; everything outside ring 0 is unable to disagree
with ring 0 without a test failing or a monitor firing.

```
ring 0  kernel/            Dafny spec + proof; translated core executed by the service
ring 1  design/, adapter   TLA+ design (agent) against frozen obligations (CoreActions.tla, MC.tla); integration
                           judged black-box through the running service (obligations/service/lifecycle.py)
ring 2  service/, gen/     API, events, monitor derived from the kernel by a reviewed generator; boundary harness
ring 3  app/, ui/          prose spec (lint), UI contract, real-browser workflows; human review by attestation
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

A process boundary is not a sandbox. A hostile `service/run.py` runs as the judge's user; operational
isolation (container, restricted user, network policy) is outside the repository and required for trust.

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
