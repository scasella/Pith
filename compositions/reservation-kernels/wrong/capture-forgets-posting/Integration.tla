---- MODULE Integration ----
\* DEFECT (known-wrong integration): a capture gives up the hold and marks the request Post, but the posting kernel is
\* never told. Each kernel keeps its own rules, INV1 holds (the account only looks emptier), and the two kernels
\* disagree about what was captured: CaptureAgrees fails (kernel/adequacy/capture_forgets_posting.dfy, at the seam).
EXTENDS Authorization, Posting
vars == <<status, held, posted, captured>>

Init == AuthInit /\ PostingInit
Decide(r) == AuthDecide(r, Limit - posted - Reserved) /\ UNCHANGED <<posted, captured>>
Release(r) == AuthRelease(r) /\ UNCHANGED <<posted, captured>>
Capture(r) == AuthConsume(r) /\ UNCHANGED <<posted, captured>>
Next == \E r \in Reqs : Decide(r) \/ Release(r) \/ Capture(r)
Spec == Init /\ [][Next]_vars
====
