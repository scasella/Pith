# The booking service contract (pith.booking, interval-booking-core/v2)

Frozen. This is what a candidate's service must do; the harness in this directory judges it black-box, over HTTP,
as a separate process started by the evaluator (`gate/service.py`). The candidate owns `service/`, `ui/` and
`app.manifest.yaml`; everything else in a judged workspace is the pack's.

## Starting

| `app.manifest.yaml` `runtime` | Entrypoint the judge starts |
|---|---|
| `python` | `python -I service/run.py --port <port> --db <path>` |
| `node` | `node service/run.mjs --port <port> --db <path>` |

The service listens on `127.0.0.1:<port>`, keeps all state under the directory of `<path>` (the only place it may
write), serves `ui_entry` at `/`, and exits on SIGTERM. It must survive SIGKILL at any point: whatever it
acknowledged is there after a restart on the same `<path>`.

`profile: shipped` means the service calls the pack's integration for its runtime (`profiles/python/store.py`,
`profiles/node/store.mjs`), which runs the verified core. `profile: custom` means the service brings its own; it is
then judged only through this API, against the verified core as the reference.

## Semantics

A **resource** is a bookable thing with capacity one and a **turnaround buffer**: a whole number of minutes in
`[0, 1440]` that must separate any two active bookings on it (cleaning, changeover). The buffer is given when the
resource is created (default `0`) and never changes. A **booking** holds the half-open interval `[start, end)` of
whole minutes on an abstract time line. Two active bookings `a` and `b` on one resource with buffer `g` are always
separated by at least the buffer: `a.end + g <= b.start` or `b.end + g <= a.start`. With `g = 0` that is plain
half-open non-overlap (touching endpoints do not conflict); with buffer `g` a booking may start exactly `g` minutes
after another ends, not earlier. Resources are independent. Recurrence, timezones and external calendars are not
part of this contract.

Every write carries a `request_id`: one namespace for all operations, the idempotency key. Repeating a request
returns the recorded result with `replayed: true` and changes nothing; reusing a `request_id` for a different
operation or different parameters is `409`. The id of an accepted booking is its book request's `request_id`.

Integers are JSON integers in `[0, 2^53)`; anything else (a fraction, a string, a boolean, null, a negative
number, a missing field) is `400` and changes nothing.

## Endpoints

| Method and path | Body | Success |
|---|---|---|
| `POST /resources` | `{id, name, buffer?}` | `201 {id, name, buffer}`; `buffer` defaults to `0`; a duplicate id is `409` (whatever its buffer) |
| `GET /resources` | | `200 {resources: [{id, name, buffer}]}` |
| `GET /resources/{id}` | | `200 {id, name, buffer, bookings: [{id, start, end, active}]}` in booking-id order; unknown is `404` |
| `POST /resources/{id}/bookings` | `{request_id, start, end}` | `200 {request_id, booking_id, resource, outcome, conflicts_with, replayed}`; unknown resource `404` |
| `GET /bookings/{id}` | | `200 {id, resource, start, end, active}`; unknown `404` |
| `POST /bookings/{id}/cancel` | `{request_id}` | `200 {request_id, booking_id, cancelled, replayed}`; unknown booking `404` |
| `POST /bookings/{id}/reschedule` | `{request_id, start, end}` | `200 {request_id, booking_id, outcome, conflicts_with, start, end, replayed}`; unknown `404` |
| `GET /events?since=N` | | `200 [{seq, type, ...}]`: every operation's events, then one `op.committed` |

`buffer` is a JSON integer in `[0, 1440]`; anything else (a fraction, a negative number, more than 1440, a string, a
boolean, null) is `400` and changes nothing. Leaving it out means `0`.

`outcome` is `ACCEPTED`, `CONFLICT` (with `conflicts_with`: the id of another active booking on the resource that is
within its buffer of the requested interval, i.e. not separated from it by at least the buffer), `INVALID`
(`end <= start`) or, for reschedule, `NOT_ACTIVE` (the booking is cancelled). A move is checked against every other
active booking with the resource's buffer, never against the booking's own interval. A refused book or move changes
nothing; a refused move keeps the booking where it was (its `start` and `end` are in the response). Cancelling a
cancelled booking returns `cancelled: false` and changes nothing; a cancelled booking frees its interval and its
buffer.

The JSON Schemas the boundary harness enforces are in `api.schema.json`.

## Upgrading from version 1

A deployment running interval-booking-core/v1 is upgraded with its state (`migrations/from-v1.yaml`, record MIG1).
The judge stops the version 1 service, runs the candidate's migrate entrypoint once on the state directory it left
(through `migrations/migrate.py`, which picks it by `app.manifest.yaml` `runtime`), then starts this version's
service on the same `<path>`:

| `runtime` | Migrate entrypoint |
|---|---|
| `python` | `python -I service/migrate.py --db <path>` |
| `node` | `node service/migrate.mjs --db <path>` |

The shipped profiles provide the transformation (`profiles/python/store.py` `migrate`, `profiles/node/store.mjs`
`migrate`); a custom profile brings its own. After it:

- every version 1 resource is a version 2 resource with **buffer 0**, version 1's convention, so every calendar
  version 1 accepted (touching bookings included) is still valid and nothing is re-decided;
- every booking, active and cancelled, keeps its id, resource, interval and state, and `GET /bookings/{id}` serves it;
- every recorded result is kept: a repeat of a version 1 `request_id` with the same operation and parameters returns
  that result with `replayed: true`, never a new decision; reusing it for something else is still `409`;
- the event history version 1 served is kept, in order;
- a request that was in flight when version 1 stopped is decided at most once (replayed if version 1 recorded it,
  decided once by version 2 otherwise);
- the migrate entrypoint refuses (non-zero exit, nothing changed) state it does not recognise as version 1 or 2, and
  running it again on state it already migrated succeeds and changes nothing.

Version 1 clients keep working unchanged (`buffer` is optional). There is no way back: once a resource with a buffer
above 0 exists, version 1 cannot represent the state (`rollback: forward-only`).
