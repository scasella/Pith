# tally 1 — intent

The "before" contract of the evolution demonstrations (`evolution/README.md`): the scaffold's example contract, kept
as `gate/cli.py pack new` wrote it. Every promise is tagged with the id of its contract record in `pack.yaml`.

- **T1** The tally never exceeds its bound (3 in the service, 2 in the model).
- **T2** The tally equals the number of accepted requests: nothing is counted twice, nothing accepted is lost.
- **Idempotency** A request is identified by its `request_id`; sending it again returns the recorded result and
  changes nothing.
- **Durability** A result the service acknowledged survives a crash and restart.

What it does **not** promise: decrementing, resetting, more than one tally, who may send requests.
