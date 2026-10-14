---- MODULE Posting ----
\* Component "posting" (kernel/spec/PostingSpec.dfy): owns the posted total and the requests it has posted. Its one
\* effect posts a request's amount exactly [C1], once.
EXTENDS Common
VARIABLES posted, captured

PostingInit == posted = 0 /\ captured = {}
Post(r) == r \notin captured /\ captured' = captured \cup {r} /\ posted' = posted + Amount[r]

\* Local invariant: the posted total is exactly the amounts of the posted requests, over this component's state only.
PostingInv == captured \subseteq Reqs /\ posted = SumOf(captured)
====
