# __PACK__ — intent (draft)

Write this first, in plain words, before any formal statement. Every promise is tagged with the id of its contract
record in `pack.yaml`; a reviewer checks the model, the traces and the wrong examples against these sentences.

The scaffold's example contract, to be replaced:

- **T1** The tally never exceeds its bound (3 in the service, 2 in the model).
- **T2** The tally equals the number of accepted requests: nothing is counted twice, nothing accepted is lost.
- **Idempotency** A request is identified by its `request_id`; sending it again returns the recorded result and
  changes nothing.
- **Durability** A result the service acknowledged survives a crash and restart.

What it does **not** promise: decrementing, resetting, more than one tally, who may send requests.
