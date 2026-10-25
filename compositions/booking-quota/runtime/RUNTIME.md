# The booking-quota runtime contract (`pith.composition/v1`, `runtime:` block)

Policy for `gate/compose.py verify` and `stagger`. A composed candidate is three processes the judge starts through
`gate/service.py` (the candidate's identity, a scrubbed environment, its own state directory, SIGKILL on a crash), each behind
a judge-owned fault proxy, and judged only through their HTTP APIs and their own stored state. The candidate owns
`components/` and `coordinator/` (and `app.manifest.yaml`); everything else in a judged workspace is the composition's.

```text
client ──> coordinator ──> booking      (a pith.booking service: components/booking, its own SQLite store)
  (judge)   (the saga)  └─> quota        (a pith.quota library behind a wrapper: components/quota, its own SQLite store)
```

Each box is its own pack's candidate where it has one: `components/booking` is a candidate of `pith.booking` and `components/quota`
(`lib/limiter.py`) of `pith.quota`, judged by those packs unchanged. This contract adds only the quota wrapper, the coordinator and
what they owe each other.

## Entrypoints

Every process listens on `127.0.0.1:<port>`, answers `GET /health` with `200` (booking: `GET /resources`) once it serves, keeps all
its state under its own `--db` file or `--state` directory (the only place it may write), and exits on SIGTERM. It must survive
SIGKILL at any point: whatever it acknowledged is there after a restart on the same state. The judge starts them with
`python -I`, from the root of the candidate's artifact:

| Process | Command | Owns |
|---|---|---|
| booking | `components/booking/service/run.py --port P --db PATH` | the bookings (`harness/SERVICE.md` of `pith.booking`, unchanged) |
| quota | `components/quota/service/run.py --port P --db PATH [--limit N] [--window W]` | the grants (defaults: limit 1, window 1000000) |
| coordinator | `coordinator/run.py --port P --state DIR --component booking=URL --component quota=URL` | the saga log and the receipts |

The coordinator is given the proxies' URLs, never the components' own. The judge keeps the addresses it hands out stable across a
restart of any process, so a restarted coordinator is started with the same two URLs.

## The quota wrapper

An idempotent HTTP wrapper over the library's `Limiter` (`harness/LIBRARY.md` of `pith.quota`). One key per resource: `resource:<id>`.

| Request | Answer |
|---|---|
| `POST /acquire {request_id, key, now}` | `200 {request_id, key, now, granted, remaining, retry_after, replayed}`; `409` for a clock behind the limiter's (`{error, clock}`) or a request id reused for another key or instant; `400` for anything malformed |
| `GET /grants?key=K` | `200 {key, grants: [request ids that were granted a unit for K, ascending]}` |
| `GET /health` | `200 {ok: true}` |

An acquire is decided once per `request_id`: a repeat returns the recorded answer, granted or refused, with `replayed: true` and
changes nothing. The decision and its record are one SQLite transaction together with the limiter's dump, so a restart never grants a
request twice and never loses a grant it answered.

## The coordinator

| Request | Answer |
|---|---|
| `POST /reservations {request_id, resource, start, end, now}` | `200 {request_id, outcome, resource, ..., replayed}` with `outcome` one of `ACCEPTED`, `CONFLICT`, `INVALID`, `QUOTA_EXCEEDED`; `409` when the request id was used for other parameters; `404`, `400` as booking says for an unknown resource or a malformed booking; `503 {error: "in progress"}` when a component could not be reached within the call's budget (the saga stays in the log) |
| `GET /reservations/{id}` | `200` the stored receipt (the body above without `replayed`), or `404` when none has been written |
| `GET /health` | `200 {ok: true}` |

`request_id` is an integer in `[0, 2^52)`; the other fields are integers in `[0, 2^53)`. A receipt carries the booking's id
(`booking_id`, equal to `request_id`) for `ACCEPTED` and `QUOTA_EXCEEDED`, `conflicts_with` for `CONFLICT`, and `reason` for `QUOTA_EXCEEDED`.
The judge never trusts a field the coordinator reports about itself: it reads booking's listing, quota's grants and the stored receipt.

## The saga

A reservation is: log, book, log, take one quota unit, then either finish `ACCEPTED`, or log the refusal, cancel the booking and finish
`QUOTA_EXCEEDED`. Booking's own refusals finish with its outcome (`CONFLICT`, `INVALID`) and take no unit. In order:

1. log the saga (`begun`) **before** any call, so there is always something to recover;
2. call booking `POST /resources/{resource}/bookings {request_id, start, end}`; log `booked` when it is `ACCEPTED`;
3. call quota `POST /acquire {request_id, key: resource:<resource>, now}`; when granted, write the receipt `ACCEPTED` and end the saga in one transaction;
4. when refused (or quota gives no decision: a `4xx`), log `denied` **before** issuing the cancel;
5. call booking `POST /bookings/{request_id}/cancel {request_id: request_id + 2^52}`; write the receipt `QUOTA_EXCEEDED` and end the saga in one transaction.

A rejected reservation therefore never burns quota, and a booking is never left without its unit or a unit without its booking
once the saga is no longer in flight.

## Idempotency

Every call the coordinator makes carries a request id its component deduplicates, so any of them can be repeated after a lost
answer or a crash: booking's `book` under the reservation's `request_id`, quota's `acquire` under the same id in quota's own namespace,
and the cancel under its own id, derived deterministically as `request_id + 2^52` (booking has one request-id namespace for all its
operations, and reservation ids stay below `2^52`, so a derived id never collides with a reservation's). A call that cannot be
answered (connection refused or reset, a timeout, a `5xx`) is repeated with a bounded backoff; an answer is acted on once. A repeat
of `POST /reservations` for a decided request returns its stored receipt with `replayed: true`; for one still in flight it drives the
same saga, never a second one.

## The recovery duty

On start, and from then on, the coordinator completes or compensates **every** saga in its durable log without any client retry:
a saga logged `begun` or `booked` is resumed from that step (the calls are idempotent), one logged `denied` has its cancel issued,
and each ends with its receipt. A coordinator killed at any instant, between a component committing and the coordinator logging what
it means, therefore leaves the components at rest once it is restarted: a resource's active bookings and its quota grants name the same
requests. A saga that cannot make progress (a component unreachable) stays in the log and is retried.

## What the judge does, and what it does not claim

`runtime/harness.py` starts the three processes fresh for each test. Faults are programmed per request at a proxy and fire once
(or a stated number of times): the coordinator is killed when its call to quota arrives, quota's answer is dropped, the coordinator is
killed on the response path, the compensating cancel is severed, the client's own answer is dropped. After a crash the coordinator is
restarted and the test waits, bounded and without any client retry, by polling the components' own state. It checks:

- `QuotaMatchesBookings`: a resource's active bookings (booking's listing) and its quota grants (quota's `/grants`) name the same requests;
- `ReceiptAgrees`: a stored receipt says `ACCEPTED` exactly when the booking is active and its unit granted; `QUOTA_EXCEEDED` only when the
  booking was cancelled and no unit is granted; `CONFLICT` only when there is no booking and no unit.

`composition.yaml` `runtime.checks` maps each test to the invariants it checks. This is a test of the faults it injects, not a proof over all
crash points; each component's own atomicity is its pack's obligation (or the wrapper's), and the model (`model/`) states the rest within
its bounds. `runtime/migrations/booking-v1-to-v2.yaml` is the staggered upgrade of the booking component.
