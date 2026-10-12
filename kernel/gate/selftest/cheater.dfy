// A submission that tries to pass by assuming its way through. The gate must refuse at step 3 (tcb).
include "../../spec/AuthSpec.dfy"
module Cheater {
  import opened AuthSpec
  class C extends Authorizer, Releaser {
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
    { assume {:axiom} false; }
    method Release(a: Account, id: ReqId) returns (a': Account)
      requires Valid(a)
      requires id in a.holds
      ensures Valid(a')
      ensures a'.limit == a.limit && a'.posted == a.posted
      ensures a'.holds == a.holds - {id}
      ensures a'.status == a.status[id := Rel]
    { assume {:axiom} false; }
  }
}
