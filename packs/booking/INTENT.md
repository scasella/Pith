# pith.booking — intent

Reviewed prose; not an oracle. The oracle is `spec/BookingSpec.dfy` (the core), `harness/SERVICE.md` (the service)
and `delivery/UI-CONTRACT.md` (the page). This file says what they are meant to capture, so a reviewer can check
the formal statements against it before the pack is sealed.

## What the contract promises

A front desk books rooms (resources) by the minute. Each resource holds at most one booking at any moment.

- **No conflicting accepted intervals.** Two active bookings on one resource never overlap. [B0]
- **The boundary convention is half-open.** A booking holds `[start, end)`. One that starts exactly when another
  ends does not conflict with it; one that starts a minute earlier does. [HALF-OPEN] A booking must be non-empty:
  `end <= start` is invalid. [B1]
- **Accepted exactly when free.** A request is accepted if and only if its interval is valid and no active booking
  on that resource overlaps it. The desk never refuses a free interval (that is a lost booking, not caution). [B2]
- **A refusal changes nothing, and says why.** A conflict names a booking that really is in the way. [B4] [B5]
- **Cancelling frees exactly that booking**, and a cancelled booking stays cancelled: cancelling again, or moving
  it, changes nothing. [X1] [X2] [X3] [M0]
- **Rescheduling is atomic.** A move is checked against every other active booking (not against the booking's own
  current time, so a booking can shrink or shift within itself), and either happens completely or not at all: a
  refused move leaves the booking where it was. [M1] [M2] [M3]
- **Resources are independent.** Bookings on one resource never block another.
- **Every write is idempotent by request id**, survives a crash once acknowledged, and is decided against the
  latest committed state even under concurrent requests.

## What it explicitly does not promise

Recurrence, timezones (times are whole minutes on an abstract, timezone-free line, not bounded to one day), daylight-saving transitions,
external calendar synchronisation, capacity above one, waitlists, holds that expire, and who may book what
(there is no actor model here; see the approval pack for one). Adding any of these is a behavioural change to the
pack: it needs new obligations, new wrong cores and a new contract version, not a UI change.

## How a behavioural change is made

Edit `spec/BookingSpec.dfy` and this file together, add a known-wrong core in `spec/wrong/` that the new
obligation rejects and a trace in `spec/traces.dfy` that distinguishes it, re-run the pack's checks, review the
traces, then reseal (`python3 gate/release.py seal --pack packs/booking`). The contract version in `pack.yaml`
changes; evidence from the old version is not reused (docs/rfc/0001 § Reuse).
