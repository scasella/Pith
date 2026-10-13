# pith.quota — intent

Reviewed prose; not an oracle. The oracle is `spec/QuotaSpec.dfy` (the decisions), `harness/LIBRARY.md` (the
library's API and domain) and `delivery/CONSUMER-CONTRACT.md` (what using it must be like). This file says what they
are meant to capture, so a reviewer can check the formal statements against it before the pack is sealed.

## What the contract promises

A service protects itself with per-key quotas: "at most `limit` units per `window`". The candidate writes the
**library** that makes those decisions; the service around it, and where `now` comes from, are the caller's.

- **Every window, not just some.** At every instant `t`, what a key was granted at instants in `(t − window, t]`
  is at most `limit`. Not only at the instants where a call was made, and not only in fixed buckets
  `[0, window)`, `[window, 2·window)`, …: a fixed-window counter lets a client take `limit` just before a bucket
  boundary and `limit` again just after it, and the contract forbids that. [Q0]
- **The window is half-open.** A grant made at `g` counts at `g + window − 1` and no longer at `g + window`. [WINDOW]
- **No needless denials.** A request is granted exactly when it fits: when what the key used in the window ending
  now, plus its cost, is within the limit. A limiter that is safe but stingy (an off-by-one window, counting
  denials) breaks the contract too. [Q1]
- **A denial consumes nothing.** Asking again while over quota does not push recovery back. [Q2]
- **`remaining` is exact** after every decision. [Q3]
- **The retry hint is exact.** A denied request says how long to wait: the *earliest* instant at which the same
  request would be granted if nothing else were granted to that key meanwhile. Waiting that long is enough; waiting
  less is not. A request costing more than the limit can never fit and gets no hint. [Q4]
- **Peeking is free.** [Q5]
- **Time is an input and never runs backwards.** Every call names its instant. A call naming an instant before the
  latest one any call named raises `ClockRegression` and changes nothing; the clock is shared by every key of a
  limiter. The library never reads a wall clock, so it is deterministic. [CLOCK] [Determinism]
- **Keys and limiters are independent.** [InstanceIsolation]
- **State can be carried.** `dump()` is text; `load` of it in another process continues with exactly the decisions
  the original would have made, clock included. What is kept is what can still count, not the history. [Persistence] [LI3]
- **A Python limiter can be shared by threads** without granting more than the limit. [Atomicity]
- **Malformed arguments are refused** with `InvalidArgument` naming the argument, before the clock is looked at,
  and change nothing. Errors share one base class a caller can catch. [BoundaryConformance] [LW3]

## What it explicitly does not promise

Distributed quotas (several processes or hosts sharing one quota); where time comes from, clock skew, time zones;
token or leaky buckets, bursts above the limit, per-key limits, quota resets, refunds of a grant, priorities,
fairness between keys; performance beyond retained state following the window (LI3). Adding any of these is a
behavioural change to the pack.

## How a behavioural change is made

Edit `spec/QuotaSpec.dfy` and this file together, add a known-wrong core in `spec/wrong/` with `REJECTED-BY` and
`DIFFERS-ON` headers and a trace in `spec/TraceData.dfy` that tells it apart, re-prove `spec/QuotaCore.dfy`,
regenerate the oracle (`harness/translate.py`), re-run the pack's checks, have the traces reviewed
(`python3 harness/adequacy.py --print`), then reseal (`python3 gate/release.py seal --pack packs/quota`). The contract
version in `pack.yaml` changes; evidence from the old version is not reused.
