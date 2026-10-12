---------------------------- MODULE WrongZeroAvail ----------------------------
(* Validation candidate: hands the core a constant availability of 0 (declines everything).
   Keeps INV1, P2, P3, Idempotent and Consistent. Must be rejected by DecideCorrect. *)
EXTENDS CoreActions
VARIABLES responses
vars == <<status, held, posted, responses>>
Init == CoreInit /\ responses = [r \in Reqs |-> << >>]
Decide(r) == CoreDecide(r, 0) /\ responses' = [responses EXCEPT ![r] = Append(@, "Decl")]
Next == \E r \in Reqs : Decide(r)
Spec == Init /\ [][Next]_vars
=============================================================================
