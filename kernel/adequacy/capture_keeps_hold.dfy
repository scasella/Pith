// Wrong candidate for Capture: posts the amount but leaves the hold in place (double counting: funds posted AND reserved).
// Expected rejection: [INV1].
include "../spec/PostingSpec.dfy"
module Candidate {
  import opened AuthSpec
  import opened PostingSpec
  class C extends Capturer {
    method Capture(a: Account, id: ReqId) returns (a': Account)
      requires Valid(a)
      requires id in a.holds
      ensures Valid(a')
      ensures a'.limit == a.limit
      ensures a'.holds == a.holds - {id}
      ensures a'.posted == a.posted + a.holds[id]
      ensures a'.status == a.status[id := Post]
    {
      a' := a.(posted := a.posted + a.holds[id], status := a.status[id := Post]);
    }
  }
}
