// Wrong candidate: uses >= instead of >. Declines a request exactly at the available limit.
// Expected rejection: [P0] (at the boundary).
include "../spec/AuthSpec.dfy"
module Candidate {
  import opened AuthSpec
  class C extends Authorizer {
    method Decide(a: Account, r: Request) returns (d: Decision, a': Account)
      requires Valid(a)
      requires r.id !in a.status
      ensures Valid(a')
      ensures a'.limit == a.limit && a'.posted == a.posted
      ensures a'.status.Keys == a.status.Keys + {r.id}
      ensures r.id in a'.status
      ensures d == Authorized <==> a'.status[r.id] == Auth
      ensures d == Declined   <==> a'.status[r.id] == Decl
      ensures forall id :: id in a.status ==> id in a'.status && a'.status[id] == a.status[id]
      ensures r.amount as int >  Available(a) ==> d == Declined   && a'.holds == a.holds
      ensures r.amount as int <= Available(a) ==> d == Authorized && a'.holds == a.holds[r.id := r.amount]
    {
      var reserved := SumHolds(a.holds);
      if r.amount as int >= a.limit as int - a.posted as int - reserved as int {
        d := Declined; a' := a.(status := a.status[r.id := Decl]);
      } else {
        SumAdd(a.holds, r.id, r.amount);
        d := Authorized; a' := a.(holds := a.holds[r.id := r.amount], status := a.status[r.id := Auth]);
      }
    }
    method SumHolds(m: map<ReqId, nat>) returns (s: nat) ensures s == Sum(m) decreases m.Keys
    { if m == map[] { return 0; } var k :| k in m; var rest := SumHolds(m - {k}); SumRemove(m, k); s := m[k] + rest; }
  }
}
