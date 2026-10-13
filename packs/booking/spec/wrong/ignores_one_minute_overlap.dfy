// Known-wrong core: ignores overlaps of a single minute, so [600, 660) and [659, 720) are both accepted. Violates
// [B0] (two active bookings overlap) and [B2]; traces.dfy T10 refuses the second.
include "../BookingSpec.dfy"
module Wrong {
  import opened BookingSpec
  class C extends Booker {
    method Book(c: Calendar, id: Id, s: nat, e: nat) returns (o: Outcome, c': Calendar)
      requires Valid(c) && !Has(c, id)
      ensures Valid(c')
      ensures o == Invalid <==> !WellFormed(s, e)
      ensures o == Accepted <==> WellFormed(s, e) && Free(c, s, e, id)
      ensures o == Accepted ==> c' == c + [Slot(id, s, e, true)]
      ensures o != Accepted ==> c' == c
      ensures o.Conflict? ==> exists i :: 0 <= i < |c| && c[i].id == o.with && Blocks(c[i], s, e, id)
      ensures !o.NotActive?
    {
      if !WellFormed(s, e) { return Invalid, c; }
      var k := 0;
      while k < |c| invariant 0 <= k <= |c| {
        if c[k].active && c[k].start + 1 < e && s + 1 < c[k].end { return Conflict(c[k].id), c; }
        k := k + 1;
      }
      return Accepted, c + [Slot(id, s, e, true)];
    }
  }
}
