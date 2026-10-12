------------------------------- MODULE Design -------------------------------
(* Agent's ring-1 design: concurrent clients, lost responses, retries with the request id as
   idempotency key, releases at any time. Availability is read inside Commit, the same step the
   core decides (the lock / BEGIN IMMEDIATE design).                                           *)
EXTENDS CoreActions
MaxTries == 2
VARIABLES phase, responses, tries
vars == <<status, held, phase, responses, tries>>
designVars == <<phase, responses, tries>>

Init == CoreInit /\ phase = [r \in Reqs |-> "idle"] /\ responses = [r \in Reqs |-> << >>] /\ tries = [r \in Reqs |-> 0]

Begin(r) == phase[r] = "idle" /\ tries[r] < MaxTries
            /\ phase' = [phase EXCEPT ![r] = "inflight"] /\ tries' = [tries EXCEPT ![r] = @ + 1]
            /\ UNCHANGED <<status, held, responses>>

Commit(r) ==
  /\ phase[r] = "inflight"
  /\ (CoreDecide(r, Available) \/ CoreReplay(r))         \* availability read in this step
  /\ LET d == IF status'[r] = "Decl" THEN "Decl" ELSE "Auth" IN
     \/ responses' = [responses EXCEPT ![r] = Append(@, d)] /\ phase' = [phase EXCEPT ![r] = "done"]   \* delivered
     \/ responses' = responses /\ phase' = [phase EXCEPT ![r] = "idle"]                                  \* lost; retry
  /\ UNCHANGED tries

\* The client re-sends although a response was delivered (timeout raced the response, or a
\* duplicate submit). This is the case that gives Idempotent and Consistent teeth.
Resend(r) == phase[r] = "done" /\ tries[r] < MaxTries /\ phase' = [phase EXCEPT ![r] = "idle"]
             /\ UNCHANGED <<status, held, responses, tries>>

Release(r) == CoreRelease(r) /\ UNCHANGED designVars

Next == \E r \in Reqs : Begin(r) \/ Commit(r) \/ Resend(r) \/ Release(r)
Spec == Init /\ [][Next]_vars

=============================================================================
