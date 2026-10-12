// Wrong candidate for Release: marks the request Released but leaves the hold in place,
// so funds stay reserved forever. Expected rejection: [R1] and [P2].
include "../spec/AuthSpec.dfy"
module Candidate {
  import opened AuthSpec
  class C extends Releaser {
    method Release(a: Account, id: ReqId) returns (a': Account)
      requires Valid(a)
      requires id in a.holds
      ensures Valid(a')
      ensures a'.limit == a.limit && a'.posted == a.posted
      ensures a'.holds == a.holds - {id}
      ensures a'.status == a.status[id := Rel]
    {
      a' := a.(status := a.status[id := Rel]);
    }
  }
}
