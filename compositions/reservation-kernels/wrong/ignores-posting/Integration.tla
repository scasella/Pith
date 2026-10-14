---- MODULE Integration ----
\* DEFECT (known-wrong integration): the decision is handed the limit minus the holds, ignoring what has been posted.
\* Each kernel keeps its own rules (every decision is exact for the figure it is given, captures are atomic and exact),
\* yet after a capture the account can authorize past its limit: INV1 fails, CaptureAgrees holds.
EXTENDS Authorization, Posting
vars == <<status, held, posted, captured>>

Init == AuthInit /\ PostingInit
Decide(r) == AuthDecide(r, Limit - Reserved) /\ UNCHANGED <<posted, captured>>
Release(r) == AuthRelease(r) /\ UNCHANGED <<posted, captured>>
Capture(r) == AuthConsume(r) /\ Post(r)
Next == \E r \in Reqs : Decide(r) \/ Release(r) \/ Capture(r)
Spec == Init /\ [][Next]_vars
====
