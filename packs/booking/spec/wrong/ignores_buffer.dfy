// Known-wrong core: version 1's booking check kept unchanged under version 2: it tests half-open overlap only and
// ignores the resource's buffer, so with g > 0 a booking touching another (or closer than g) is accepted. Correct
// at g = 0, which is why it survives every version 1 test. Violates [B0] and [B2]; traces.dfy T12 refuses [660, 670)
// next to [600, 660) at buffer 15.
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
      while k < |c| invariant 0 <= k <= |c| invariant forall i :: 0 <= i < k ==> !(c[i].active && c[i].id != id && Overlaps(c[i].start, c[i].end, s, e)) {
        if c[k].active && c[k].id != id && Overlaps(c[k].start, c[k].end, s, e) { return Conflict(c[k].id), c; }
        k := k + 1;
      }
      return Accepted, c + [Slot(id, s, e, true)];
    }
  }
}
