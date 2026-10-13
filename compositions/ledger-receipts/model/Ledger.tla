---- MODULE Ledger ----
\* Component "ledger": owns `held`, the requests whose effect has been applied, up to the capacity Cap.
EXTENDS Common
VARIABLE held

LedgerInit == held = {}
LedgerCanReserve(r) == r \notin held /\ Cardinality(held) < Cap
LedgerReserve(r) == LedgerCanReserve(r) /\ held' = held \cup {r}

\* Local invariant: the ledger's own rule, stated over its own state only.
LedgerInv == held \subseteq Reqs /\ Cardinality(held) <= Cap
====
