---------------------------- MODULE BrokenDesign ----------------------------
(* Adequacy for the ring-1 obligations: a design that reads availability at receipt and commits
   later. The gate requires TLC to find an INV1 violation here, so the obligations are known to
   reject the design they exist to reject, independent of whatever the agent builds.          *)
EXTENDS CoreActions
VARIABLES phase, snapshot
vars == <<status, held, phase, snapshot>>
Init == CoreInit /\ phase = [r \in Reqs |-> "idle"] /\ snapshot = [r \in Reqs |-> 0]
Begin(r)  == phase[r] = "idle" /\ phase' = [phase EXCEPT ![r] = "inflight"] /\ snapshot' = [snapshot EXCEPT ![r] = Available] /\ UNCHANGED coreVars
Commit(r) == phase[r] = "inflight" /\ phase' = [phase EXCEPT ![r] = "done"] /\ (CoreDecide(r, snapshot[r]) \/ CoreReplay(r)) /\ UNCHANGED snapshot
Next == \E r \in Reqs : Begin(r) \/ Commit(r)
Spec == Init /\ [][Next]_vars
=============================================================================
