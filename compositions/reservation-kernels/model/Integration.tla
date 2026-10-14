---- MODULE Integration ----
\* The reservation pack's integration of its two kernels, as obligations/design/CoreActions.tla states it: each core
\* action is one atomic step over the shared account. The decision reads the posted total and the holds in the step
\* that commits it; a capture gives up the hold and posts its amount in one step. correspondence/ shows, with TLC,
\* that these are exactly CoreActions' behaviours.
EXTENDS Authorization, Posting
vars == <<status, held, posted, captured>>

Init == AuthInit /\ PostingInit
Decide(r) == AuthDecide(r, Limit - posted - Reserved) /\ UNCHANGED <<posted, captured>>
Release(r) == AuthRelease(r) /\ UNCHANGED <<posted, captured>>
Capture(r) == AuthConsume(r) /\ Post(r)
Next == \E r \in Reqs : Decide(r) \/ Release(r) \/ Capture(r)
Spec == Init /\ [][Next]_vars
====
