# pith.quota — intent

Reviewed prose; not an oracle. The oracle is `spec/QuotaSpec.dfy` (the decisions), `harness/LIBRARY.md` (the
library's API and domain) and `delivery/CONSUMER-CONTRACT.md` (what using it must be like). This file says what they
are meant to capture, so a reviewer can check the formal statements against it before the pack is sealed.

## What the contract promises

A service protects itself with per-key quotas: "at most `limit` units per `window`", where some keys (a plan, a
tier) may have a limit of their own. The candidate writes the **library** that makes those decisions; the service
around it, and where `now` comes from, are the caller's. This is contract version 2 (`sliding-window-quota/v2`); what
changed from version 1, and how a version 1 deployment is upgraded, is at the end.

- **Each key has a limit.** A limiter is made with a default `limit` and, optionally, `limits` naming keys that have a
  limit of their own, above or below the default. A key's limit is its own if it has one, the default otherwise;
  `limit_for(key)` says which, and changes nothing. Every promise below about "the limit" means the key's limit.
  The limits are fixed when the limiter is made: nothing changes a key's limit afterwards. [KEYLIMIT]
- **Every window, not just some.** At every instant `t`, what a key was granted at instants in `(t − window, t]`
  is at most its limit. Not only at the instants where a call was made, and not only in fixed buckets
  `[0, window)`, `[window, 2·window)`, …: a fixed-window counter lets a client take `limit` just before a bucket
  boundary and `limit` again just after it, and the contract forbids that. [Q0]
- **The window is half-open.** A grant made at `g` counts at `g + window − 1` and no longer at `g + window`. [WINDOW]
- **No needless denials.** A request is granted exactly when it fits: when what the key used in the window ending
  now, plus its cost, is within the key's limit. A key with a limit above the default is granted past the default. A limiter that is safe but stingy (an off-by-one window, counting
  denials) breaks the contract too. [Q1]
- **A denial consumes nothing.** Asking again while over quota does not push recovery back. [Q2]
- **`remaining` is exact** after every decision. [Q3]
- **The retry hint is exact.** A denied request says how long to wait: the *earliest* instant at which the same
  request would be granted if nothing else were granted to that key meanwhile. Waiting that long is enough; waiting
  less is not. A request costing more than the key's limit can never fit and gets no hint. [Q4]
- **Peeking is free.** [Q5]
- **Time is an input and never runs backwards.** Every call names its instant. A call naming an instant before the
  latest one any call named raises `ClockRegression` and changes nothing; the clock is shared by every key of a
  limiter. The library never reads a wall clock, so it is deterministic. [CLOCK] [Determinism]
- **Keys and limiters are independent.** [InstanceIsolation]
- **State can be carried.** `dump()` is text; `load` of it in another process continues with exactly the decisions
  the original would have made, per-key limits and clock included. What is kept is what can still count, not the
  history. [Persistence] [LI3]
- **A Python limiter can be shared by threads** without granting more than the limit. [Atomicity]
- **Malformed arguments are refused** with `InvalidArgument` naming the argument (a malformed `limits` refuses the
  whole configuration), before the clock is looked at, and change nothing. Errors share one base class a caller can catch. [BoundaryConformance] [LW3]

## What it explicitly does not promise

Distributed quotas (several processes or hosts sharing one quota); where time comes from, clock skew, time zones;
token or leaky buckets, bursts above a key's limit, changing a key's limit after the limiter is made, quota resets,
refunds of a grant, priorities, fairness between keys; performance beyond retained state following the window (LI3). Adding any of these is a
behavioural change to the pack.

## How a behavioural change is made

Edit `spec/QuotaSpec.dfy` and this file together, add a known-wrong core in `spec/wrong/` with `REJECTED-BY` and
`DIFFERS-ON` headers and a trace in `spec/TraceData.dfy` that tells it apart, re-prove `spec/QuotaCore.dfy`,
regenerate the oracle (`harness/translate.py`), re-run the pack's checks, have the traces reviewed
(`python3 harness/adequacy.py --print`), then reseal (`python3 gate/release.py seal --pack packs/quota`). The contract
version in `pack.yaml` changes; evidence from the old version is not reused.

## Version 2 (0.2.0): a limit per key, and the upgrade from version 1

Version 1 held every key to the limiter's one `limit`. Version 2 adds `limits` (and `limit_for`): Q0, Q1, Q3, Q4 and
Q5 now say "the key's limit" where they said "the limit" (version 2 of each); Persistence carries the per-key limits
(version 2); the domain of malformed arguments includes them (BoundaryConformance version 2); KEYLIMIT is new. Q2,
WINDOW and CLOCK mean what they meant. A limiter made without `limits` decides exactly as version 1 did.

**Upgrading a version 1 deployment keeps its state.** [MIG1] A library has no service and no database; what a
deployment keeps is the dumps it stored to hand to `load` later. The candidate's migrate entrypoint converts every
stored version 1 dump in place to a version 2 dump with the same configuration, no per-key limits, the same clock and
every grant that can still count, so that loading it gives exactly the decisions version 1's `load` of that dump would
have given for every later call: old keys under the default limit, the same retry hints, `ClockRegression` for every
earlier instant. Grants a process made after it took a dump are not in that dump, and the upgrade does not invent
them; calls carry no identifiers, so there is nothing to replay. It refuses (changing nothing) what it does not
recognise, and a second run changes nothing. Per-key limits come from limiters made after the upgrade, never from the
upgrade changing an old key's limit. Rollback is forward-only: a dump of a limiter with per-key limits has no version 1
meaning. The precise statement is `migrations/from-v1.yaml` and `harness/LIBRARY.md` § Upgrading from version 1;
`gate/migrate.py` judges it on dumps the accepted version 1 library made.
