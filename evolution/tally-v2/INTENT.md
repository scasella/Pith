# tally 2 — intent

The "after" contract of the evolution demonstrations (`evolution/README.md`). Release 2.0.0 changes what release 1.0.0
promised (behavioral change: T1 and T2 are new versions) and says how a running tally/v1 service is upgraded (M1).
Every promise is tagged with the id of its contract record in `pack.yaml`.

- **T1** (version 2) Each named counter has its own bound (3 in the service, 2 in the model) and never exceeds it.
  Version 1 had one tally; it is now the counter named `default`.
- **T2** (version 2) Each counter's tally equals the number of requests accepted for that counter.
- **Idempotency** (unchanged) A request is identified by its `request_id` across all counters; sending it again
  returns the recorded result, with the counter it was recorded for, and changes nothing.
- **Durability** (unchanged) A result the service acknowledged survives a crash and restart.
- **M1** Upgrading a tally/v1 service keeps its history: every result v1 recorded is still recorded, for the counter
  `default`, with the same outcome; a v1 client's retry of an old `request_id` gets that recorded result, never a new
  decision; v1's tally is counter `default`'s tally, so the bound already reached stays reached. A request that was
  in flight when v1 stopped is decided at most once, by whichever version records it first.

What it does **not** promise: rolling back. Once v2 has recorded a request for any counter other than `default`, the
state cannot be expressed in v1; backing out is a forward repair (a new release), never a downgrade
(`migrations/from-1.yaml: rollback`). Also not promised: decrementing, resetting, deleting counters, who may send
requests.
