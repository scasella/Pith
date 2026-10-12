---------------------------- MODULE Design ----------------------------
EXTENDS CoreActions

VARIABLES responses, lost
vars == <<status, held, responses, lost>>

Init ==
  /\ CoreInit
  /\ responses = [r \in Reqs |-> <<>>]
  /\ lost = [r \in Reqs |-> FALSE]

DecisionResponse(r) == IF status'[r] = "Decl" THEN "Decl" ELSE "Auth"

DecideAndDeliver(r) ==
  /\ status[r] = "None"
  /\ CoreDecide(r, Available)
  /\ responses' = [responses EXCEPT ![r] = Append(@, DecisionResponse(r))]
  /\ UNCHANGED lost

DecideAndLose(r) ==
  /\ status[r] = "None"
  /\ CoreDecide(r, Available)
  /\ UNCHANGED responses
  /\ lost' = [lost EXCEPT ![r] = TRUE]

Decide(r) == DecideAndDeliver(r) \/ DecideAndLose(r)

Replay(r) ==
  /\ status[r] # "None"
  /\ Len(responses[r]) < 2
  /\ CoreReplay(r)
  /\ responses' = [responses EXCEPT ![r] = Append(@, CoreDecision(r))]
  /\ UNCHANGED lost

Release(r) ==
  /\ CoreRelease(r)
  /\ UNCHANGED <<responses, lost>>

Next == \E r \in Reqs : Decide(r) \/ Replay(r) \/ Release(r)
Spec == Init /\ [][Next]_vars
=============================================================================
