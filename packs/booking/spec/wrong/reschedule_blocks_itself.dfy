// Known-wrong core: checks the new interval against EVERY active booking, including the one being moved, so
// shortening or shifting a booking within its own time is refused as a conflict with itself. Violates [M1].
include "../BookingSpec.dfy"
module Wrong {
  import opened BookingSpec
  class C extends Rescheduler {
    method Reschedule(c: Calendar, g: nat, id: Id, s: nat, e: nat) returns (o: Outcome, c': Calendar)
      requires Valid(c, g)
      ensures Valid(c', g)
      ensures o == NotActive <==> !IsActive(c, id)
      ensures o == Invalid <==> IsActive(c, id) && !WellFormed(s, e)
      ensures o == Accepted <==> IsActive(c, id) && WellFormed(s, e) && Free(c, s, e, id, g)
      ensures o == Accepted ==> |c'| == |c| && forall i :: 0 <= i < |c| ==> c'[i] == (if c[i].id == id then c[i].(start := s, end := e) else c[i])
      ensures o != Accepted ==> c' == c
      ensures o.Conflict? ==> exists i :: 0 <= i < |c| && c[i].id == o.with && Blocks(c[i], s, e, id, g)
    {
      var k := 0;
      while k < |c| && c[k].id != id invariant 0 <= k <= |c| { k := k + 1; }
      if k == |c| || !c[k].active { return NotActive, c; }
      if !WellFormed(s, e) { return Invalid, c; }
      var b := 0;
      while b < |c| invariant 0 <= b <= |c| {
        if c[b].active && Near(c[b].start, c[b].end, s, e, g) { return Conflict(c[b].id), c; }
        b := b + 1;
      }
      return Accepted, c[k := c[k].(start := s, end := e)];
    }
  }
}
