// Known-wrong core: a move is "cancel the old booking, then book the new interval". When the new interval is
// taken, the original booking is already gone. Violates [M3]: a refused move must keep the original.
include "../BookingSpec.dfy"
module Wrong {
  import opened BookingSpec
  class C extends Rescheduler {
    method Reschedule(c: Calendar, id: Id, s: nat, e: nat) returns (o: Outcome, c': Calendar)
      requires Valid(c)
      ensures Valid(c')
      ensures o == NotActive <==> !IsActive(c, id)
      ensures o == Invalid <==> IsActive(c, id) && !WellFormed(s, e)
      ensures o == Accepted <==> IsActive(c, id) && WellFormed(s, e) && Free(c, s, e, id)
      ensures o == Accepted ==> |c'| == |c| && forall i :: 0 <= i < |c| ==> c'[i] == (if c[i].id == id then c[i].(start := s, end := e) else c[i])
      ensures o != Accepted ==> c' == c
      ensures o.Conflict? ==> exists i :: 0 <= i < |c| && c[i].id == o.with && Blocks(c[i], s, e, id)
    {
      var k := 0;
      while k < |c| && c[k].id != id invariant 0 <= k <= |c| { k := k + 1; }
      if k == |c| || !c[k].active { return NotActive, c; }
      if !WellFormed(s, e) { return Invalid, c; }
      var freed := c[k := c[k].(active := false)];
      var b := 0;
      while b < |freed| invariant 0 <= b <= |freed| {
        if Blocks(freed[b], s, e, id) { return Conflict(freed[b].id), freed; }
        b := b + 1;
      }
      return Accepted, c[k := c[k].(start := s, end := e)];
    }
  }
}
