// A non-proof placeholder so the audit step has something to run. It must NOT verify.
// (It claims Decide's precondition is contradictory, which it is not.)
include "../spec/AuthSpec.dfy"
module Audit {
  import opened AuthSpec
  lemma Unsatisfiable(a: Account, r: Request)
    requires Valid(a) && r.id !in a.status
    ensures false
  { }
}
