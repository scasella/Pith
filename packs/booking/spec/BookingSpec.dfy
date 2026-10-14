// BookingSpec.dfy — the interval-booking contract. This file is the oracle; cores may not edit it.
// Obligation tags in square brackets are named by the pack's contract records (pack.yaml:contracts).
//
// One calendar is the bookings of ONE resource (capacity 1). Resources are independent: the service partitions
// by resource and the boundary harness checks that independence black-box. Times are whole minutes on an
// abstract, timezone-free line; recurrence, timezones and external calendars are outside this contract (INTENT.md).
//
// Version 2 (interval-booking-core/v2): every calendar has a turnaround buffer g, the whole minutes that must
// separate any two of its active bookings. g belongs to the calendar (to its resource), not to a slot: it is passed
// alongside the calendar to Valid, Blocks, Free and every operation, and the service fixes it when the resource is
// created [Turnaround]. With g = 0 every statement below is version 1's (BufferZeroIsHalfOpen).
module BookingSpec {

  type Id = nat

  datatype Slot = Slot(id: Id, start: nat, end: nat, active: bool)     // active: accepted and not cancelled
  type Calendar = seq<Slot>                                                // the slots of one resource; its buffer g travels with it
  datatype Outcome = Accepted | Conflict(with: Id) | Invalid | NotActive

  // ---- the boundary convention ------------------------------------------------------------------------------

  predicate WellFormed(s: nat, e: nat) { s < e }                                         // [WF] non-empty interval
  predicate Overlaps(s1: nat, e1: nat, s2: nat, e2: nat) { s1 < e2 && s2 < e1 }           // [HALF-OPEN] [s, e): touching endpoints do not overlap
  // [B0] within the buffer: neither interval ends at least g minutes before the other starts. The buffer extends each
  // interval's exclusive end, so [HALF-OPEN] also fixes where it is measured from: the next booking may start at end + g.
  predicate Near(s1: nat, e1: nat, s2: nat, e2: nat, g: nat) { Overlaps(s1, e1 + g, s2, e2 + g) }
  predicate Blocks(x: Slot, s: nat, e: nat, except: Id, g: nat) { x.active && x.id != except && Near(x.start, x.end, s, e, g) }
  predicate Free(c: Calendar, s: nat, e: nat, except: Id, g: nat) { forall i :: 0 <= i < |c| ==> !Blocks(c[i], s, e, except, g) }
  predicate Has(c: Calendar, id: Id) { exists i :: 0 <= i < |c| && c[i].id == id }
  predicate IsActive(c: Calendar, id: Id) { exists i :: 0 <= i < |c| && c[i].id == id && c[i].active }

  // ---- state invariant ----------------------------------------------------------------------------------------

  ghost predicate Valid(c: Calendar, g: nat)
  {
    && (forall i, j :: 0 <= i < j < |c| ==> c[i].id != c[j].id)                                         // [ID] one slot per booking id
    && (forall i :: 0 <= i < |c| ==> WellFormed(c[i].start, c[i].end))                                 // [WF]
    && (forall i, j :: 0 <= i < j < |c| && c[i].active && c[j].active ==>
          !Near(c[i].start, c[i].end, c[j].start, c[j].end, g))                                         // [B0] active bookings at least g apart
  }

  // A zero buffer is version 1's half-open non-overlap, so a version 1 calendar is a Valid version 2 calendar with
  // g = 0 and nothing in it is re-decided (migrations/from-v1.yaml) [B0] [HALF-OPEN] [MIG1].
  lemma BufferZeroIsHalfOpen(s1: nat, e1: nat, s2: nat, e2: nat)
    ensures Near(s1, e1, s2, e2, 0) <==> Overlaps(s1, e1, s2, e2)
  {}

  // ---- obligations ------------------------------------------------------------------------------------------

  trait {:termination false} Booker {      // cross-module trait (see tcb.yaml)
    // Book a new interval atomically. Precondition: the booking id is new to this calendar.
    method Book(c: Calendar, g: nat, id: Id, s: nat, e: nat) returns (o: Outcome, c': Calendar)
      requires Valid(c, g) && !Has(c, id)
      ensures Valid(c', g)                                                                              // [B0] preserved
      ensures o == Invalid <==> !WellFormed(s, e)                                                       // [B1] empty or reversed intervals are invalid
      ensures o == Accepted <==> WellFormed(s, e) && Free(c, s, e, id, g)                               // [B2] accepted exactly when free (at least g from every other)
      ensures o == Accepted ==> c' == c + [Slot(id, s, e, true)]                                        // [B3] acceptance adds exactly this booking
      ensures o != Accepted ==> c' == c                                                                 // [B4] a refusal changes nothing
      ensures o.Conflict? ==> exists i :: 0 <= i < |c| && c[i].id == o.with && Blocks(c[i], s, e, id, g)   // [B5] a conflict names a booking really within the buffer
      ensures !o.NotActive?
  }

  trait {:termination false} Canceller {
    method Cancel(c: Calendar, g: nat, id: Id) returns (ok: bool, c': Calendar)
      requires Valid(c, g)
      ensures Valid(c', g)
      ensures ok <==> IsActive(c, id)                                                                   // [X1] only an active booking is cancelled
      ensures ok ==> |c'| == |c| && forall i :: 0 <= i < |c| ==>
                c'[i] == (if c[i].id == id then c[i].(active := false) else c[i])                       // [X2] cancelling frees exactly that booking
      ensures !ok ==> c' == c                                                                           // [X3] cancelled is terminal; unknown ids change nothing
  }

  trait {:termination false} Rescheduler {
    // Move an active booking to a new interval atomically: either the move happens, or nothing changes.
    method Reschedule(c: Calendar, g: nat, id: Id, s: nat, e: nat) returns (o: Outcome, c': Calendar)
      requires Valid(c, g)
      ensures Valid(c', g)
      ensures o == NotActive <==> !IsActive(c, id)                                                      // [M0] only an active booking moves
      ensures o == Invalid <==> IsActive(c, id) && !WellFormed(s, e)                                    // [B1]
      ensures o == Accepted <==> IsActive(c, id) && WellFormed(s, e) && Free(c, s, e, id, g)            // [M1] free of every other, ignoring the booking's own interval
      ensures o == Accepted ==> |c'| == |c| && forall i :: 0 <= i < |c| ==>
                c'[i] == (if c[i].id == id then c[i].(start := s, end := e) else c[i])                  // [M2] only that booking's interval changes
      ensures o != Accepted ==> c' == c                                                                 // [M3] a refused move keeps the original booking
      ensures o.Conflict? ==> exists i :: 0 <= i < |c| && c[i].id == o.with && Blocks(c[i], s, e, id, g)   // [B5]
  }
}
