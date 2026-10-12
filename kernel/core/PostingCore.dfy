// PostingCore.dfy — implementation of the posting kernel.
include "../spec/PostingSpec.dfy"
module PostingCore {
  import opened AuthSpec
  import opened PostingSpec

  class Poster extends Capturer {
    constructor () {}

    method Capture(a: Account, id: ReqId) returns (a': Account)
      requires Valid(a)
      requires id in a.holds
      ensures Valid(a')
      ensures a'.limit == a.limit
      ensures a'.holds == a.holds - {id}
      ensures a'.posted == a.posted + a.holds[id]
      ensures a'.status == a.status[id := Post]
    {
      SumRemove(a.holds, id);
      a' := a.(holds := a.holds - {id}, posted := a.posted + a.holds[id], status := a.status[id := Post]);
    }
  }
}
