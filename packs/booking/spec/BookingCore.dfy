// BookingCore.dfy — the pack's verified core. It includes spec/BookingSpec.dfy and may not modify it.
// Translated to Python (profiles/python/core) and JavaScript (profiles/node/core) by profiles/translate.py.
include "BookingSpec.dfy"

module BookingCore {
  import opened BookingSpec

  // The first slot that blocks [s, e) for a booking other than `except`, or -1 when the interval is free.
  method FindBlocker(c: Calendar, s: nat, e: nat, except: Id) returns (k: int)
    ensures -1 <= k < |c|
    ensures k == -1 <==> Free(c, s, e, except)
    ensures k >= 0 ==> Blocks(c[k], s, e, except)
  {
    k := 0;
    while k < |c|
      invariant 0 <= k <= |c|
      invariant forall i :: 0 <= i < k ==> !Blocks(c[i], s, e, except)
    {
      if Blocks(c[k], s, e, except) { return; }
      k := k + 1;
    }
    k := -1;
  }

  method IndexOf(c: Calendar, id: Id) returns (k: int)
    ensures -1 <= k < |c|
    ensures k == -1 <==> !Has(c, id)
    ensures k >= 0 ==> c[k].id == id
  {
    k := 0;
    while k < |c|
      invariant 0 <= k <= |c|
      invariant forall i :: 0 <= i < k ==> c[i].id != id
    {
      if c[k].id == id { return; }
      k := k + 1;
    }
    k := -1;
  }

  class Core extends Booker, Canceller, Rescheduler {

    constructor () {}

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
      var k := FindBlocker(c, s, e, id);
      if k >= 0 { return Conflict(c[k].id), c; }
      o, c' := Accepted, c + [Slot(id, s, e, true)];
      forall i, j | 0 <= i < j < |c'| && c'[i].active && c'[j].active
        ensures !Overlaps(c'[i].start, c'[i].end, c'[j].start, c'[j].end)
      {
        if j == |c| { assert !Blocks(c[i], s, e, id); }
      }
    }

    method Cancel(c: Calendar, id: Id) returns (ok: bool, c': Calendar)
      requires Valid(c)
      ensures Valid(c')
      ensures ok <==> IsActive(c, id)
      ensures ok ==> |c'| == |c| && forall i :: 0 <= i < |c| ==> c'[i] == (if c[i].id == id then c[i].(active := false) else c[i])
      ensures !ok ==> c' == c
    {
      var k := IndexOf(c, id);
      if k < 0 || !c[k].active { return false, c; }
      ok, c' := true, c[k := c[k].(active := false)];
      forall i | 0 <= i < |c| ensures c'[i] == (if c[i].id == id then c[i].(active := false) else c[i]) {
        if i != k { assert c[i].id != c[k].id; }
      }
    }

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
      var k := IndexOf(c, id);
      if k < 0 || !c[k].active { return NotActive, c; }
      if !WellFormed(s, e) { return Invalid, c; }
      var b := FindBlocker(c, s, e, id);
      if b >= 0 { return Conflict(c[b].id), c; }
      o, c' := Accepted, c[k := c[k].(start := s, end := e)];
      forall i | 0 <= i < |c| ensures c'[i] == (if c[i].id == id then c[i].(start := s, end := e) else c[i]) {
        if i != k { assert c[i].id != c[k].id; }
      }
      forall i, j | 0 <= i < j < |c'| && c'[i].active && c'[j].active
        ensures !Overlaps(c'[i].start, c'[i].end, c'[j].start, c'[j].end)
      {
        if i == k { assert !Blocks(c[j], s, e, id); }
        else if j == k { assert !Blocks(c[i], s, e, id); }
      }
    }
  }
}
