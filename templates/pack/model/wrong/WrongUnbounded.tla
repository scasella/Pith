---- MODULE WrongUnbounded ----
(* Known wrong: accepts every new request, ignoring the bound. The model's invariants must reject it. *)
EXTENDS Naturals, FiniteSets
CONSTANTS Bound, Reqs
VARIABLES tally, results
vars == <<tally, results>>
Init == tally = 0 /\ results = [r \in {} |-> "OK"]
Request(r) ==
  /\ r \notin DOMAIN results
  /\ tally' = tally + 1 /\ results' = [x \in DOMAIN results \cup {r} |-> IF x = r THEN "OK" ELSE results[x]]
Next == \E r \in Reqs : Request(r)
Spec == Init /\ [][Next]_vars
Bounded == tally <= Bound
Exact == tally = Cardinality({r \in DOMAIN results : results[r] = "OK"})
====
