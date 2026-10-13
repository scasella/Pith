# The booking service contract (pith.booking)

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

A **resource** is a bookable thing with capacity one. A **booking** holds the half-open interval `[start, end)` of
whole minutes on an abstract time line. Two active bookings on one resource never overlap; touching endpoints do
not overlap. Resources are independent. Recurrence, timezones and external calendars are not part of this
contract.

Every write carries a `request_id`: one namespace for all operations, the idempotency key. Repeating a request
returns the recorded result with `replayed: true` and changes nothing; reusing a `request_id` for a different
operation or different parameters is `409`. The id of an accepted booking is its book request's `request_id`.

Integers are JSON integers in `[0, 2^53)`; anything else (a fraction, a string, a boolean, null, a negative
number, a missing field) is `400` and changes nothing.

## Endpoints

| Method and path | Body | Success |
|---|---|---|
| `POST /resources` | `{id, name}` | `201 {id, name}`; a duplicate id is `409` |
| `GET /resources` | | `200 {resources: [{id, name}]}` |
| `GET /resources/{id}` | | `200 {id, name, bookings: [{id, start, end, active}]}` in booking-id order; unknown is `404` |
| `POST /resources/{id}/bookings` | `{request_id, start, end}` | `200 {request_id, booking_id, resource, outcome, conflicts_with, replayed}`; unknown resource `404` |
| `GET /bookings/{id}` | | `200 {id, resource, start, end, active}`; unknown `404` |
| `POST /bookings/{id}/cancel` | `{request_id}` | `200 {request_id, booking_id, cancelled, replayed}`; unknown booking `404` |
| `POST /bookings/{id}/reschedule` | `{request_id, start, end}` | `200 {request_id, booking_id, outcome, conflicts_with, start, end, replayed}`; unknown `404` |
| `GET /events?since=N` | | `200 [{seq, type, ...}]`: every operation's events, then one `op.committed` |

`outcome` is `ACCEPTED`, `CONFLICT` (with `conflicts_with`: the id of an active booking that overlaps), `INVALID`
(`end <= start`) or, for reschedule, `NOT_ACTIVE` (the booking is cancelled). A refused book or move changes
nothing; a refused move keeps the booking where it was (its `start` and `end` are in the response). Cancelling a
cancelled booking returns `cancelled: false` and changes nothing.

The JSON Schemas the boundary harness enforces are in `api.schema.json`.
