---- MODULE Integration ----
\* DEFECT (known-wrong integration): a capture is two steps, as two stores committed separately would make it: the
\* posting kernel posts the amount, and later the authorization kernel gives up the hold. Each step is one kernel's own
\* correct operation; in between the amount counts twice (INV1 fails) and the kernels disagree (CaptureAgrees fails).
EXTENDS Authorization, Posting
vars == <<status, held, posted, captured>>

Init == AuthInit /\ PostingInit
Decide(r) == AuthDecide(r, Limit - posted - Reserved) /\ UNCHANGED <<posted, captured>>
Release(r) == AuthRelease(r) /\ UNCHANGED <<posted, captured>>
PostFirst(r) == status[r] = "Auth" /\ Post(r) /\ UNCHANGED <<status, held>>
ConsumeLater(r) == r \in captured /\ AuthConsume(r) /\ UNCHANGED <<posted, captured>>
Next == \E r \in Reqs : Decide(r) \/ Release(r) \/ PostFirst(r) \/ ConsumeLater(r)
Spec == Init /\ [][Next]_vars
====
