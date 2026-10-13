---- MODULE IntegrationRefinesCore ----
\* Every behaviour of the composition's integration is a behaviour of obligations/design/CoreActions.tla's core
\* actions on the same account state (status, held, posted).
EXTENDS Integration
Core == INSTANCE CoreActions WITH Reqs <- Reqs, Amount <- Amount, Limit <- Limit, status <- status, held <- held, posted <- posted
CoreNext == \E r \in Reqs : Core!CoreDecide(r, Core!Available) \/ Core!CoreRelease(r) \/ Core!CoreCapture(r)
CoreSpec == Core!CoreInit /\ [][CoreNext]_<<status, held, posted>>
====
