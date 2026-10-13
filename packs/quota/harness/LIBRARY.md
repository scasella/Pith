# The library contract (pith.quota). FROZEN.

The candidate delivers a **library**, not a service: there is no port, no process the evaluator keeps running, and no
persistence of its own. The pack judges it by running frozen pack programs (`harness/driver.py`, `harness/driver.mjs`,
`delivery/consumers/*`) **as the candidate's user** (`gate/sandbox.py:run_as_candidate_full`); those programs import
the candidate's library and report what it did. The judge never imports candidate code.

## Where the library is

| `app.manifest.yaml:runtime` | file | imported as |
|---|---|---|
| `python` (default) | `lib/limiter.py` (it may import other modules from `lib/`) | `from limiter import Limiter, LimiterError, InvalidArgument, ClockRegression` (with `lib/` on `sys.path`) |
| `node` | `lib/limiter.mjs` (an ES module; it may import other files from `lib/`) | `import { Limiter, LimiterError, InvalidArgument, ClockRegression } from "<root>/lib/limiter.mjs"` |

Only the standard library of the judge's runtime is available. The library must not read the wall clock, randomness,
the environment, the network or the file system to make a decision, and must not print on import.

## The API

Python:

```python
lim = Limiter(limit=3, window=60)                 # limit: units per window; window: its length in instants
d = lim.acquire("alice", now=10)                   # cost defaults to 1;  lim.acquire("alice", now=10, cost=2)
d.granted, d.remaining, d.retry_after              # bool, int, int or None
lim.peek("alice", now=10)                          # int: what "alice" could still be granted at 10
text = lim.dump()                                  # str
lim2 = Limiter.load(text)                          # an equivalent, independent limiter
```

Node.js:

```js
const lim = new Limiter({ limit: 3, window: 60 });
const d = lim.acquire("alice", { now: 10 });       // { now: 10, cost: 2 }
d.granted, d.remaining, d.retryAfter               // boolean, number, number or null
lim.peek("alice", { now: 10 });                    // number
const text = lim.dump();                           // string
const lim2 = Limiter.load(text);
```

Keyword names are part of the contract (`limit`, `window`, `now`, `cost` in Python; the same properties in Node.js).

## Values

- **Whole numbers.** `limit`, `window` and `cost` are whole numbers in [1, 2^31 − 1]; `now` is a whole number in
  [0, 2^53 − 1]. In Python a whole number is an `int` that is not a `bool`; in Node.js it is a `number` for which
  `Number.isSafeInteger` holds (so `1.0` is `1` there, while in Python `1.0` is a float and is refused).
- **Keys** are strings of 1 to 64 characters, each one of `A–Z a–z 0–9 _ . : -`.
- Anything else is refused with **`InvalidArgument`** whose `argument` attribute (property) names the parameter
  (`"limit"`, `"window"`, `"key"`, `"cost"`, `"now"`, `"text"`). A refused call changes nothing: not the log, not the clock.
  Arguments are checked before the clock: a call that is both malformed and too early raises `InvalidArgument`.

## The semantics (spec/QuotaSpec.dfy is the oracle; the tags are its obligations)

- A limiter has a **clock**, the latest `now` any accepted call named (0 initially). A call whose `now` is earlier
  raises **`ClockRegression`** (its `clock` attribute is the limiter's clock) and changes nothing. Every other call
  (granted, denied or a peek) sets the clock to its `now`. The clock is shared by every key. [CLOCK]
- What a key has **used** at instant `t` is the sum of the costs of its grants made at instants `g` with
  `t − window < g ≤ t`: the window is half-open, and a grant stops counting at exactly `g + window`. [WINDOW]
- `acquire(key, now, cost)` is **granted exactly when** `used(key, now) + cost ≤ limit` [Q1]; a grant records
  `(key, now, cost)` and a denial records nothing [Q2]. So in every window of length `window`, at every instant,
  no key is granted more than `limit` [Q0].
- `remaining` is `limit − used(key, now)` after the decision (after the grant, if granted) [Q3].
- `retry_after` is `None`/`null` when granted. When denied it is the least `r ≥ 1` such that the same request would be
  granted at `now + r` if nothing else were granted meanwhile; it is `None`/`null` when `cost > limit` (never) [Q4].
- `peek(key, now)` returns `limit − used(key, now)` and grants nothing [Q5].
- Keys are independent quotas; separate `Limiter` objects are independent of each other [Isolation].
- `dump()` returns text; `Limiter.load(text)` returns a limiter that gives the same decisions and raises the same
  errors as the original would for every later sequence of calls (configuration, clock and every grant that can
  still count) [Persistence]. `load` refuses text that `dump` did not produce with `InvalidArgument("text")`.
- **Python only:** one `Limiter` may be shared by threads; each call is decided against the state left by the
  calls before it, one at a time [Atomicity]. (A Node.js limiter is synchronous; run-to-completion gives the same.)

## How the pack drives it

`harness/driver.py` and `harness/driver.mjs` take one JSON program on the command line: a list of steps
(`new`, `acquire`, `peek`, `dump`, `load`, `burst`, `sleep`), each naming a limiter, and print one JSON result per
step: `{"ok": value}` or `{"error": "InvalidArgument" | "ClockRegression" | "other", ...}`. The harnesses compare
those results with the verified core (`harness/oracle.py`, the Python translation of `spec/QuotaCore.dfy`).
