// Known-wrong core: the turnaround buffer is kept only AFTER existing bookings ("the room needs cleaning after a
// guest leaves"), so a new booking may end right before an existing one starts, with no buffer between them.
// Violates [B0] (two active bookings closer than g) and [B2]; traces.dfy T13 refuses [526, 586) next to [600, 660).
include "../BookingSpec.dfy"
module Wrong {
  import opened BookingSpec
  class C extends Booker {
    method Book(c: Calendar, g: nat, id: Id, s: nat, e: nat) returns (o: Outcome, c': Calendar)
      requires Valid(c, g) && !Has(c, id)
      ensures Valid(c', g)
      ensures o == Invalid <==> !WellFormed(s, e)
      ensures o == Accepted <==> WellFormed(s, e) && Free(c, s, e, id, g)
      ensures o == Accepted ==> c' == c + [Slot(id, s, e, true)]
      ensures o != Accepted ==> c' == c
      ensures o.Conflict? ==> exists i :: 0 <= i < |c| && c[i].id == o.with && Blocks(c[i], s, e, id, g)
      ensures !o.NotActive?
    {
      if !WellFormed(s, e) { return Invalid, c; }
      var k := 0;
      while k < |c| invariant 0 <= k <= |c| {
        if c[k].active && c[k].start < e && s < c[k].end + g { return Conflict(c[k].id), c; }
        k := k + 1;
      }
      return Accepted, c + [Slot(id, s, e, true)];
    }
  }
}
