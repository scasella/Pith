---- MODULE Authorization ----
\* Component "authorization" (kernel/spec/AuthSpec.dfy): owns each request's status and the live holds. Its effects are
\* the decision, the release, and giving up a hold to a capture (the authorization half of the posting kernel's Capture,
\* kernel/spec/PostingSpec.dfy C2 and C3). The decision's availability figure is handed in: whether it is the right one
\* depends on the posting kernel's state, so it is the composition's business, not this component's.
EXTENDS Common
VARIABLES status, held

AuthInit == status = [r \in Reqs |-> "None"] /\ held = {}
Reserved == SumOf(held)

\* Any decision of an undecided request: authorized with a hold of exactly its amount, or declined with none.
AuthDecides(r) == /\ status[r] = "None"
                  /\ \/ status' = [status EXCEPT ![r] = "Auth"] /\ held' = held \cup {r}
                     \/ status' = [status EXCEPT ![r] = "Decl"] /\ held' = held
\* The decision against a given availability [P0][P1].
AuthDecide(r, avail) == /\ status[r] = "None"
                        /\ IF Amount[r] <= avail THEN status' = [status EXCEPT ![r] = "Auth"] /\ held' = held \cup {r}
                                                 ELSE status' = [status EXCEPT ![r] = "Decl"] /\ held' = held
AuthRelease(r) == status[r] = "Auth" /\ status' = [status EXCEPT ![r] = "Rel"] /\ held' = held \ {r}     \* [R1][R2]
AuthConsume(r) == status[r] = "Auth" /\ status' = [status EXCEPT ![r] = "Post"] /\ held' = held \ {r}    \* [C2][C3]

\* Local invariant: a hold exists exactly while its request is authorized [P2], over this component's state only.
AuthInv == status \in [Reqs -> {"None", "Auth", "Decl", "Rel", "Post"}] /\ held = {r \in Reqs : status[r] = "Auth"}
====
