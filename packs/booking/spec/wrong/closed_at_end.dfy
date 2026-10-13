// Known-wrong core: closed at the requester's end only ([s, e] against [start, end)), so a booking that ENDS exactly
// when another starts is refused, while one that starts when another ends is accepted (traces.dfy T1 passes; T9
// does not). Safe, but violates [B2]: touching endpoints are free on both sides. With a buffer g the same mistake
// refuses a booking that ends exactly g before another starts.
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
        if c[k].active && c[k].start <= e + g && s < c[k].end + g { return Conflict(c[k].id), c; }
        k := k + 1;
      }
      return Accepted, c + [Slot(id, s, e, true)];
    }
  }
}
