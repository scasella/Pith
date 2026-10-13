// Known-wrong core: Cancel flips the active flag, so cancelling a cancelled booking brings it back without any
// conflict check. Violates [X3] (cancelled is terminal) and, through it, [B0].
include "../BookingSpec.dfy"
module Wrong {
  import opened BookingSpec
  class C extends Canceller {
    method Cancel(c: Calendar, g: nat, id: Id) returns (ok: bool, c': Calendar)
      requires Valid(c, g)
      ensures Valid(c', g)
      ensures ok <==> IsActive(c, id)
      ensures ok ==> |c'| == |c| && forall i :: 0 <= i < |c| ==> c'[i] == (if c[i].id == id then c[i].(active := false) else c[i])
      ensures !ok ==> c' == c
    {
      var k := 0;
      while k < |c| && c[k].id != id invariant 0 <= k <= |c| { k := k + 1; }
      if k == |c| { return false, c; }
      return c[k].active, c[k := c[k].(active := !c[k].active)];
    }
  }
}
