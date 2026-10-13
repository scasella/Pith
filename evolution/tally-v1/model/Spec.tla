---- MODULE Spec ----
(* The scaffold's example oracle: a bounded tally with idempotent requests. Replace with yours. FROZEN once sealed. *)
EXTENDS Naturals, FiniteSets
CONSTANTS Bound, Reqs
VARIABLES tally, results          \* results: request id -> "OK" | "REFUSED" (absent: not yet seen)
vars == <<tally, results>>

Init == tally = 0 /\ results = [r \in {} |-> "OK"]

Request(r) ==
  /\ r \notin DOMAIN results
  /\ IF tally < Bound
       THEN tally' = tally + 1 /\ results' = [x \in DOMAIN results \cup {r} |-> IF x = r THEN "OK" ELSE results[x]]
       ELSE UNCHANGED tally /\ results' = [x \in DOMAIN results \cup {r} |-> IF x = r THEN "REFUSED" ELSE results[x]]

Next == \E r \in Reqs : Request(r)
Spec == Init /\ [][Next]_vars

Bounded == tally <= Bound                                                      \* [T1]
Exact == tally = Cardinality({r \in DOMAIN results : results[r] = "OK"})       \* [T2]
====
