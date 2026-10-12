------------------------------- MODULE Design -------------------------------
(* Build B design: a single-writer queue. Clients enqueue; one worker dequeues in FIFO order and
   commits each request as one step, reading availability in that step. Clients may enqueue the same
   request again (resend); the worker answers a resend from the record. Releases come from an
   operator at any time. Responses can be lost after commit; a lost response leads to a resend. *)
EXTENDS CoreActions
VARIABLES queue, responses, sent
vars == <<status, held, queue, responses, sent>>
MaxSends == 2

Init == CoreInit /\ queue = << >> /\ responses = [r \in Reqs |-> << >>] /\ sent = [r \in Reqs |-> 0]

Enqueue(r) == sent[r] < MaxSends /\ queue' = Append(queue, r) /\ sent' = [sent EXCEPT ![r] = @ + 1] /\ UNCHANGED <<status, held, responses>>

Work == /\ queue # << >>
        /\ LET r == Head(queue) IN
           /\ (CoreDecide(r, Available) \/ CoreReplay(r))              \* one step: read, decide, commit
           /\ queue' = Tail(queue)
           /\ LET d == IF status'[r] = "Decl" THEN "Decl" ELSE "Auth" IN
              \/ responses' = [responses EXCEPT ![r] = Append(@, d)]   \* delivered
              \/ responses' = responses                                  \* lost; client will resend
        /\ UNCHANGED sent

Release(r) == CoreRelease(r) /\ UNCHANGED <<queue, responses, sent>>

Next == \E r \in Reqs : Enqueue(r) \/ Release(r) \/ Work
Spec == Init /\ [][Next]_vars

=============================================================================
