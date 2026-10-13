# pith.booking — intent

Reviewed prose; not an oracle. The oracle is `spec/BookingSpec.dfy` (the core), `harness/SERVICE.md` (the service),
`delivery/UI-CONTRACT.md` (the page) and `migrations/from-v1.yaml` (the upgrade). This file says what they are meant
to capture, so a reviewer can check the formal statements against it before the pack is sealed.

This is contract version 2 (`interval-booking-core/v2`, pack 0.12.0). Version 1 had no turnaround buffer; version 2
gives every resource one, and says how a running version 1 deployment is upgraded with its state. Records whose
meaning changed carry version 2 (B0, HalfOpen, B2, B5, M1, BoundaryConformance); Turnaround and MIG1 are new.

## What the contract promises

A front desk books rooms (resources) by the minute. Each resource holds at most one booking at any moment, and
needs a **turnaround buffer** between bookings (cleaning, changeover).

- **The buffer belongs to the resource.** Every resource has a buffer: a whole number of minutes from 0 to 1440,
  0 unless the desk gives one when it creates the resource. It is fixed then (nothing in this version changes it)
  and applies to every booking and every move on that resource. An out-of-domain buffer (a fraction, a negative
  number, more than 1440, a string, a boolean, null) is refused and creates nothing. [Turnaround]
- **Active bookings are separated by at least the buffer.** For two active bookings `a` and `b` on one resource with
  buffer `g`: `a.end + g <= b.start` or `b.end + g <= a.start`. With `g = 0` that is exactly version 1's promise:
  two active bookings never overlap. [B0]
- **The boundary convention is half-open, and the buffer is measured from the exclusive end.** A booking holds
  `[start, end)`. At buffer 0, one that starts exactly when another ends does not conflict with it; one that starts
  a minute earlier does. With buffer `g`, the next booking may start exactly `g` minutes after another ends, and not
  a minute earlier; on the other side, a booking may end exactly `g` minutes before another starts. [HalfOpen]
  A booking must be non-empty: `end <= start` is invalid. [B1]
- **Accepted exactly when free.** A request is accepted if and only if its interval is valid and no other active
  booking on that resource is within the buffer of it. The desk never refuses an interval that is far enough from
  every other booking (that is a lost booking, not caution). Acceptance adds exactly the requested booking. [B2] [B3]
- **A refusal changes nothing, and says why.** A conflict names a booking that really is in the way: an active
  booking on the resource within the buffer of the requested interval. [B4] [B5]
- **Cancelling frees exactly that booking** (its interval and the buffer around it), and a cancelled booking stays
  cancelled: cancelling again, or moving it, changes nothing. [X1] [X2] [X3] [M0]
- **Rescheduling is atomic, and keeps the buffer.** A move is checked like a booking, against every other active
  booking with the resource's buffer, but not against the booking's own current time (so a booking can shrink or
  shift within itself and its own buffer), and either happens completely or not at all: a refused move leaves the
  booking where it was. [M1] [M2] [M3]
- **Resources are independent.** Bookings on one resource never block another; each resource's buffer applies to it
  alone. [Independence]
- **Every write is idempotent by request id**, survives a crash once acknowledged, and is decided against the
  latest committed state even under concurrent requests. [Idempotency] [Durability] [Atomicity]

## Upgrading from version 1

A deployment that ran version 1 is upgraded in place, with its state; nothing it acknowledged is lost or
re-decided. [MIG1]

- **Every version 1 resource gets buffer 0**, version 1's convention, so every calendar version 1 accepted is still
  valid: two bookings that touched (one starting exactly when the other ends) stay booked, and the next booking may
  still touch them. A migration that gave old resources a non-zero buffer would make accepted bookings invalid
  after the fact.
- **History is kept**: every booking, active and cancelled, with its id, resource, interval and state; the event
  history. A cancelled booking is not "dead data": `GET /bookings/{id}` and a retried cancel still find it.
- **Every acknowledged result is kept and replayed**: a version 1 client retrying an old request id gets the result
  it was given, with `replayed: true`, even if the state has changed since (a refused request is not retried as a
  new one); reusing an old request id for a different request is still refused.
- **A request in flight** when version 1 stopped is decided at most once: replayed if version 1 recorded it,
  decided by version 2 otherwise, never both.
- **Version 1 clients keep working**: `buffer` is optional when creating a resource.
- **No rollback.** Once a resource with a buffer above 0 exists, version 1 cannot represent the state (it would
  accept bookings version 2 refused); backing out is a forward repair in a new release.

## What it explicitly does not promise

Recurrence, timezones (times are whole minutes on an abstract, timezone-free line, not bounded to one day), daylight-saving transitions,
external calendar synchronisation, capacity above one, waitlists, holds that expire, buffers that differ by booking
or by side (before/after), changing a resource's buffer after it is created (and what that would mean for bookings
already accepted), and who may book what (there is no actor model here; see the approval pack for one). Adding any
of these is a behavioural change to the pack: it needs new obligations, new wrong cores and a new contract version,
not a UI change.

## How a behavioural change is made

Edit `spec/BookingSpec.dfy` and this file together, add a known-wrong core in `spec/wrong/` that the new
obligation rejects and a trace in `spec/traces.dfy` that distinguishes it, re-run the pack's checks, review the
traces, then reseal (`python3 gate/release.py seal --pack packs/booking`). The contract version in `pack.yaml`
changes; evidence from the old version is not reused (docs/rfc/0001 § Reuse). When deployments carry state from the
old version, ship a migration with it (`migrations/`, docs/rfc/0004 § 4) and known-wrong migrations in
`examples/wrong-migrations/`.

Version 2 was made this way: the buffer `g` became a parameter of `Valid`, `Blocks`, `Free` and the three traits
(with the lemma `BufferZeroIsHalfOpen` tying `g = 0` to version 1); the core was re-verified and re-translated;
`spec/wrong/ignores_buffer.dfy`, `buffer_after_only.dfy` and `reschedule_ignores_buffer.dfy` were added (and every
existing wrong core ported, still rejected); traces T12-T15 show a booking exactly `g` away accepted and `g - 1`
refused, on both sides and for moves; the harnesses, schemas, profiles and examples followed.
