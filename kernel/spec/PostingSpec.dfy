// PostingSpec.dfy — the second kernel: capture (posting) of an authorized hold.
// A separate module that imports the shared state type and the shared invariant from AuthSpec.
// Obligation tags in square brackets are read by gate/gate.py.
include "AuthSpec.dfy"
module PostingSpec {
  import opened AuthSpec

  // Capture moves an authorized hold into posted, in full. Partial capture is a behavioural
  // extension (INTENT.md); it is not what this kernel does.
  trait {:termination false} Capturer {
    method Capture(a: Account, id: ReqId) returns (a': Account)
      requires Valid(a)
      requires id in a.holds                                                               // a live, authorized hold
      ensures Valid(a')                                                                    // [INV1] posted + reserved still <= limit
      ensures a'.limit == a.limit                                                          // [F]
      ensures a'.holds == a.holds - {id}                                                   // [C2]  the hold is gone
      ensures a'.posted == a.posted + a.holds[id]                                          // [C1]  exactly the held amount is posted
      ensures a'.status == a.status[id := Post]                                            // [C3]  the request is Post; nothing else changes
  }

  // Post is terminal: once captured, a request's status never changes again. This is a property of
  // every operation in the kernel; it is stated here and discharged by the frame conditions of each.
  ghost predicate PostTerminal(a: Account, a': Account)                                    // [P4]
  { forall id :: id in a.status && a.status[id] == Post ==> id in a'.status && a'.status[id] == Post }

  lemma DecidePreservesPost(a: Account, a': Account, r: ReqId)
    requires forall id :: id in a.status ==> id in a'.status && a'.status[id] == a.status[id]
    ensures PostTerminal(a, a') {}
  lemma ReleasePreservesPost(a: Account, a': Account, id: ReqId)
    requires id in a.holds && Valid(a)
    requires a'.status == a.status[id := Rel]
    ensures PostTerminal(a, a') {}
  lemma CapturePreservesPost(a: Account, a': Account, id: ReqId)
    requires id in a.holds && Valid(a)
    requires a'.status == a.status[id := Post]
    ensures PostTerminal(a, a') {}
}
