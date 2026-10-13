// Known-wrong core: reports a conflict correctly but names the requested booking id instead of the booking that
// blocks it, so a user cannot tell what is in the way. Violates [B5].
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
      while k < |c| invariant 0 <= k <= |c| invariant forall i :: 0 <= i < k ==> !Blocks(c[i], s, e, id) {
        if Blocks(c[k], s, e, id) { return Conflict(id), c; }
        k := k + 1;
      }
      o, c' := Accepted, c + [Slot(id, s, e, true)];
      forall i, j | 0 <= i < j < |c'| && c'[i].active && c'[j].active ensures !Overlaps(c'[i].start, c'[i].end, c'[j].start, c'[j].end) {
        if j == |c| { assert !Blocks(c[i], s, e, id); }
      }
    }
  }
}
