---------------------------- MODULE WrongStutter ----------------------------
(* Validation candidate: initialises correctly and never does anything. Keeps every safety
   obligation. Must be rejected by the coverage obligations. *)
EXTENDS CoreActions
VARIABLES responses
vars == <<status, held, posted, responses>>
Init == CoreInit /\ responses = [r \in Reqs |-> << >>]
Next == UNCHANGED vars
Spec == Init /\ [][Next]_vars
=============================================================================
