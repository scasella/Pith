---- MODULE Quota ----
\* Component "quota" (a pith.quota library behind an idempotent wrapper): owns grants, the requests that were given a
\* unit, at most Limit of them. A grant is kept (the model has no expiry: the runtime check uses a window far longer
\* than a test). Granting a request that already holds a unit is a replay and changes nothing.
EXTENDS Common
VARIABLE grants

QuotaInit == grants = {}
QuotaCanGrant(r) == r \notin grants /\ Cardinality(grants) < Limit
QuotaGrant(r) == QuotaCanGrant(r) /\ grants' = grants \cup {r}

\* Local invariant, over this component's state only.
QuotaInv == grants \subseteq Reqs /\ Cardinality(grants) <= Limit
====
