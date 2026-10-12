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

## What this is not

Not a proof of the application. Not a stdlib-only host (the Dafny Python runtime is required to run the core).
Not a sandbox. Not a complete payment system: posting, settlement, expiry and eligibility are out of scope and
documented as behavioural extensions requiring a new release.
