---- MODULE Coordinator ----
\* Component "coordinator": owns saga, the durable log of each reservation's progress (idle, begun, booked, denied, done),
\* and receipt, the outcome the client is told. A receipt is written once. The log moves forward only: idle to begun
\* (before anything is called), begun to booked (the booking is confirmed), booked to denied (quota refused; the
\* cancel is still owed), and a saga ends in done together with its receipt (Finish), or is closed over a receipt
\* that is already there (Close).
EXTENDS Common
VARIABLES saga, receipt

Phases == {"idle", "begun", "booked", "denied", "done"}
Verdicts == {"ACCEPTED", "CONFLICT", "QUOTA_EXCEEDED"}

CoordinatorInit == saga = [r \in Reqs |-> "idle"] /\ receipt = [r \in Reqs |-> "none"]

CoordLog(r, s) == /\ \/ saga[r] = "idle" /\ s = "begun"
                     \/ saga[r] = "begun" /\ s = "booked"
                     \/ saga[r] = "booked" /\ s = "denied"
                  /\ saga' = [saga EXCEPT ![r] = s] /\ UNCHANGED receipt
CoordRecord(r, v) == receipt[r] = "none" /\ v \in Verdicts /\ receipt' = [receipt EXCEPT ![r] = v] /\ UNCHANGED saga
CoordFinish(r, v) == /\ saga[r] # "done" /\ receipt[r] = "none" /\ v \in Verdicts
                     /\ saga' = [saga EXCEPT ![r] = "done"] /\ receipt' = [receipt EXCEPT ![r] = v]
CoordClose(r) == saga[r] # "done" /\ receipt[r] # "none" /\ saga' = [saga EXCEPT ![r] = "done"] /\ UNCHANGED receipt

\* Local invariant, over this component's state only: a finished saga has told the client something.
CoordInv == /\ saga \in [Reqs -> Phases]
            /\ receipt \in [Reqs -> Verdicts \cup {"none"}]
            /\ \A r \in Reqs : saga[r] = "done" => receipt[r] # "none"
====
