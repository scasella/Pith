---- MODULE Spec ----
(* tally/v2: one bounded tally per named counter, idempotent requests across counters. FROZEN once sealed. *)
EXTENDS Naturals, FiniteSets
CONSTANTS Bound, Reqs, Counters
VARIABLES tally, results          \* tally: counter -> count; results: request id -> [o: "OK" | "REFUSED", c: counter]
vars == <<tally, results>>

Init == tally = [c \in Counters |-> 0] /\ results = [r \in {} |-> [o |-> "OK", c |-> "x"]]

Record(r, v) == results' = [x \in DOMAIN results \cup {r} |-> IF x = r THEN v ELSE results[x]]
Request(r, c) ==
  /\ r \notin DOMAIN results
  /\ IF tally[c] < Bound
       THEN tally' = [tally EXCEPT ![c] = @ + 1] /\ Record(r, [o |-> "OK", c |-> c])
       ELSE UNCHANGED tally /\ Record(r, [o |-> "REFUSED", c |-> c])

Next == \E r \in Reqs, c \in Counters : Request(r, c)
Spec == Init /\ [][Next]_vars

Bounded == \A c \in Counters : tally[c] <= Bound                                                          \* [T1]
Exact == \A c \in Counters : tally[c] = Cardinality({r \in DOMAIN results : results[r] = [o |-> "OK", c |-> c]})   \* [T2]
====
