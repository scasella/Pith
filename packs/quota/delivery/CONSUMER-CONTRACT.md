# The consumer contract (pith.quota delivery). FROZEN.

For a library, "the application" is what a programmer gets when they use it. `harness/LIBRARY.md` says what the
library decides; this file says what using it must be like. Every obligation below is exercised by a frozen consumer
program (`delivery/consumers/consumer.py` for `runtime: python`, `consumer.mjs` for `runtime: node`) that the
delivery adapter runs as the candidate's user and judges from its output. The consumers use only the API in
`harness/LIBRARY.md`, written the way its examples write it.

## Workflows

- **LW1 quickstart.** The examples in `harness/LIBRARY.md § The API` run as written: the names import, the keyword
  arguments (properties) are accepted, including a key with a limit of its own, a decision has `granted`,
  `remaining` and `retry_after` (`retryAfter`), `limit_for` (`limitFor`) gives a key's limit, and the values are the
  ones the contract gives.
- **LW2 backoff client.** A client that, when denied, waits exactly the `retry_after` it was given and asks again is
  granted at that instant, never earlier and never after a second denial (when nothing else was granted
  meanwhile), over a bursty workload. The schedule it ends up with is the one the verified core gives.
- **LW3 errors a caller can handle.** One `except LimiterError` (`catch` + `instanceof LimiterError`) handles both
  `InvalidArgument` and `ClockRegression`; in Python `InvalidArgument` is also a `ValueError`, in Node.js every
  error is an `Error`. `InvalidArgument.argument` names the offending parameter (`limit`, `window`, `limits`, `key`,
  `cost`, `now`, `text`); `ClockRegression.clock` is the limiter's clock; every message is non-empty.
- **LW4 persistence across processes.** One process makes calls on a limiter with a key that has a limit of its own and
  hands `dump()`'s text to a second process (as a command-line argument); the second `Limiter.load`s it and continues;
  its decisions are the ones the original would have made, that key's own limit included.

## Interaction obligations

- **LI1 a silent import.** Importing the library prints nothing on stdout or stderr.
- **LI2 decisions are values.** A decision returned earlier keeps its values after later calls on the same limiter
  (no shared, reused or live result objects).
- **LI3 memory follows the window.** After 20 000 grants spread over time, with a window that can hold at most 10 of
  them, `dump()` is under 2 000 characters: what the limiter keeps is what can still count, not its history.
