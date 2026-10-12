# audit/ — the channel for rejecting the template instead of the submission

If you believe the obligations in `spec/AuthSpec.dfy` cannot be satisfied, do not weaken
them and do not work around them. Put a Dafny file here that proves it:

```dafny
include "../spec/AuthSpec.dfy"
module Audit {
  import opened AuthSpec
  lemma Unsatisfiable(a: Account, r: Request)
    requires Valid(a) && r.id !in a.status
    ensures false          // or: ensures no (d, a') can meet Decide's postconditions
  { ... }
}
```

The gate verifies every `audit/*.dfy`. If one verifies, the gate refuses with
`template rejected`, and the template owner must fix the obligations. (Modelled on the
audit mechanism in the Vero benchmark, where agents may prove a provided specification
unsatisfiable rather than silently satisfying a broken one.)
