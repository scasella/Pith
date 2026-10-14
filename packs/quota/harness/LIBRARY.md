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

plans = Limiter(limit=3, window=60, limits={"vip": 10})   # "vip" has 10 per window; every other key the default 3
plans.limit_for("vip"), plans.limit_for("alice")          # 10, 3
plans.acquire("vip", now=10, cost=5)                      # granted, remaining 5
```

Node.js:

```js
const lim = new Limiter({ limit: 3, window: 60 });
const d = lim.acquire("alice", { now: 10 });       // { now: 10, cost: 2 }
d.granted, d.remaining, d.retryAfter               // boolean, number, number or null
lim.peek("alice", { now: 10 });                    // number
const text = lim.dump();                           // string
const lim2 = Limiter.load(text);

const plans = new Limiter({ limit: 3, window: 60, limits: { vip: 10 } });
plans.limitFor("vip"), plans.limitFor("alice");    // 10, 3
plans.acquire("vip", { now: 10, cost: 5 });        // granted, remaining 5
```

Keyword names are part of the contract (`limit`, `window`, `limits`, `now`, `cost` in Python; the same properties in
Node.js). `limits` is optional: omitted, no key has a limit of its own (version 1's behaviour).

## Values

- **Whole numbers.** `limit`, `window` and `cost` are whole numbers in [1, 2^31 − 1]; `now` is a whole number in
  [0, 2^53 − 1]. In Python a whole number is an `int` that is not a `bool`; in Node.js it is a `number` for which
  `Number.isSafeInteger` holds (so `1.0` is `1` there, while in Python `1.0` is a float and is refused).
- **Keys** are strings of 1 to 64 characters, each one of `A–Z a–z 0–9 _ . : -`.
- **Per-key limits** (`limits`) map keys to whole numbers in [1, 2^31 − 1]: in Python a `dict`, in Node.js a plain
  object (not `null`, not an array). It may be empty, and a key's own limit may be above or below the default.
  Omitting it is the same as passing an empty one; `None`/`null` is not.
- Anything else is refused with **`InvalidArgument`** whose `argument` attribute (property) names the parameter
  (`"limit"`, `"window"`, `"limits"`, `"key"`, `"cost"`, `"now"`, `"text"`); a configuration is checked in that order
  (`limit`, `window`, `limits`), and a malformed `limits` (not a mapping, a key that is not a key, a limit that is not
  one) refuses the whole configuration. A refused call changes nothing: not the log, not the clock.
  Arguments are checked before the clock: a call that is both malformed and too early raises `InvalidArgument`.

## The semantics (spec/QuotaSpec.dfy is the oracle; the tags are its obligations)

- A limiter has a **clock**, the latest `now` any accepted call named (0 initially). A call whose `now` is earlier
  raises **`ClockRegression`** (its `clock` attribute is the limiter's clock) and changes nothing. Every other call
  (granted, denied or a peek) sets the clock to its `now`. The clock is shared by every key. [CLOCK]
- What a key has **used** at instant `t` is the sum of the costs of its grants made at instants `g` with
  `t − window < g ≤ t`: the window is half-open, and a grant stops counting at exactly `g + window`. [WINDOW]
- A key's **limit**, `limit(key)` below, is `limits[key]` when the limiter's `limits` names the key, and the default
  `limit` otherwise. `limit_for(key)` (`limitFor`) returns it; it takes no instant, so it neither needs nor moves the
  clock, and it is the default for every key the limiter's `limits` does not name, seen or not. [KEYLIMIT]
- `acquire(key, now, cost)` is **granted exactly when** `used(key, now) + cost ≤ limit(key)` [Q1]; a grant records
  `(key, now, cost)` and a denial records nothing [Q2]. So in every window of length `window`, at every instant,
  no key is granted more than its own limit [Q0].
- `remaining` is `limit(key) − used(key, now)` after the decision (after the grant, if granted) [Q3].
- `retry_after` is `None`/`null` when granted. When denied it is the least `r ≥ 1` such that the same request would be
  granted at `now + r` if nothing else were granted meanwhile; it is `None`/`null` when `cost > limit(key)` (never) [Q4].
- `peek(key, now)` returns `limit(key) − used(key, now)` and grants nothing [Q5].
- Keys are independent quotas; separate `Limiter` objects are independent of each other [InstanceIsolation].
- `dump()` returns text; `Limiter.load(text)` returns a limiter that gives the same decisions and raises the same
  errors as the original would for every later sequence of calls (configuration, per-key limits included; clock; and
  every grant that can still count) [Persistence]. `load` refuses text that `dump` did not produce with
  `InvalidArgument("text")`. A limiter's configuration is fixed when it is made: no call changes a key's limit, so a
  window can never end up over a key's limit because that limit was lowered under grants already made.
- **Python only:** one `Limiter` may be shared by threads; each call is decided against the state left by the
  calls before it, one at a time [Atomicity]. (A Node.js limiter is synchronous; run-to-completion gives the same.)

## How the pack drives it

`harness/driver.py` and `harness/driver.mjs` take one JSON program on the command line: a list of steps
(`new` with an optional `limits`, `acquire`, `peek`, `limit_for`, `dump`, `load`, `burst`, `sleep`), each naming a limiter, and print one JSON result per
step: `{"ok": value}` or `{"error": "InvalidArgument" | "ClockRegression" | "other", ...}`. The harnesses compare
those results with the verified core (`harness/oracle.py`, the Python translation of `spec/QuotaCore.dfy`).

## Upgrading from version 1

Version 1 of this contract (`sliding-window-quota/v1`) had one `limit` for every key. A library has no service and
no database: what a deployment keeps is the text `dump()` returned, which it stores and later hands to
`Limiter.load` (LW4). Upgrading a deployment is converting its stored dumps (`migrations/from-v1.yaml`, record MIG1):

- **The entrypoint.** `python -I lib/migrate.py --state DIR` (`runtime: python`) or `node lib/migrate.mjs --state DIR`
  (`runtime: node`); the judge calls it through the pack's `migrations/migrate.py`, which picks one by
  `app.manifest.yaml`. `DIR` holds one dump per file, `<name>.dump`, exactly the text a version 1 `dump()` returned.
  The entrypoint rewrites each in place as text this version's `Limiter.load` accepts. It runs as the candidate, with
  only the standard library of its runtime.
- **The mapping.** Each version 1 dump becomes a dump of the same configuration (`limit`, `window`) with **no**
  per-key limits, the same clock, and every grant that can still count at that clock (instant and cost): nothing
  dropped, nothing added, nothing re-decided. So the limiter loaded from it gives exactly the decisions version 1's
  `load` of the same dump would have given for every later call: old keys under the default limit, the same retry
  hints, and `ClockRegression` for every instant before the dump's clock.
- **Refusals and re-runs.** A file it does not recognise as a dump of version 1 or of this version (anything in `DIR`
  not named `*.dump`, or a `*.dump` that is neither) makes it exit non-zero **before writing anything**. A file that
  is already a dump of this version is left as it is, so a second run (an interrupted upgrade, retried) succeeds and
  changes nothing.
- **What is not there.** A dump is a snapshot. Grants a process made after it took a dump are not in that dump, and
  the upgrade must not invent them. Requests carry no identifiers, so there is nothing to replay: the dump's clock and
  live grants are the whole state, and every decision version 1 acknowledged before the dump is in it as the grant it
  recorded (or as nothing, for a denial). Per-key limits belong to the limiters a deployment *makes* after the upgrade
  (`Limiter(limit=..., window=..., limits=...)`); a migrated dump never gains them.
- **No way back.** Rollback is forward-only: a dump of a limiter with per-key limits has no version 1 meaning.
