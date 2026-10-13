---- MODULE WrongDefaultBound ----
(* Known wrong: a v1 leftover. Counts per counter but checks the bound against counter "default" only, so any other
   counter is unbounded. The model's invariants must reject it. *)
EXTENDS Naturals, FiniteSets
CONSTANTS Bound, Reqs, Counters
VARIABLES tally, results
vars == <<tally, results>>
Init == tally = [c \in Counters |-> 0] /\ results = [r \in {} |-> [o |-> "OK", c |-> "x"]]
Record(r, v) == results' = [x \in DOMAIN results \cup {r} |-> IF x = r THEN v ELSE results[x]]
Request(r, c) ==
  /\ r \notin DOMAIN results
  /\ IF tally["default"] < Bound
       THEN tally' = [tally EXCEPT ![c] = @ + 1] /\ Record(r, [o |-> "OK", c |-> c])
       ELSE UNCHANGED tally /\ Record(r, [o |-> "REFUSED", c |-> c])
Next == \E r \in Reqs, c \in Counters : Request(r, c)
Spec == Init /\ [][Next]_vars
Bounded == \A c \in Counters : tally[c] <= Bound
Exact == \A c \in Counters : tally[c] = Cardinality({r \in DOMAIN results : results[r] = [o |-> "OK", c |-> c]})
====
