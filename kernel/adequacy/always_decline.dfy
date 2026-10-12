// Wrong candidate: declines everything, never reserves. Satisfies INV1, P1, P2, P3.
// The template must reject it. Expected rejection: [P0].
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
      d := Declined;
      a' := a.(status := a.status[r.id := Decl]);
    }
  }
}
