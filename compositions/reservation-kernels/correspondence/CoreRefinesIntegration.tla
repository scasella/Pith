---- MODULE CoreRefinesIntegration ----
\* Every behaviour of CoreActions' core actions is a behaviour of the composition's integration, with the posting
\* kernel's `captured` read off the requests that are Post.
EXTENDS CoreActions
CoreReqs == 1..3
CoreAmount == <<60, 60, 40>>
CoreSpec == CoreInit /\ [][\E r \in Reqs : CoreDecide(r, Available) \/ CoreRelease(r) \/ CoreCapture(r)]_coreVars
Comp == INSTANCE Integration WITH Limit <- Limit, status <- status, held <- held, posted <- posted,
                                  captured <- {r \in Reqs : status[r] = "Post"}
CompSpec == Comp!Spec
====
