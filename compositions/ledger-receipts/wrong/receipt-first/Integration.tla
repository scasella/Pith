---- MODULE Integration ----
\* DEFECT (known-wrong integration): checks for room, records the receipt, then applies the effect, in three separate
\* steps. Each component keeps its own rules (the ledger never exceeds Cap, a receipt is written once, each changes
\* only through its own operations), yet a receipt can report an effect that is not there: between the steps, and for
\* good when two requests both saw room and only one effect fits.
EXTENDS Ledger, Receipts
VARIABLES pc, seen
vars == <<held, receipt, pc, seen>>

Init == LedgerInit /\ ReceiptsInit /\ pc = [r \in Reqs |-> "idle"] /\ seen = [r \in Reqs |-> FALSE]
Check(r) == pc[r] = "idle" /\ pc' = [pc EXCEPT ![r] = "checked"] /\ seen' = [seen EXCEPT ![r] = LedgerCanReserve(r)] /\ UNCHANGED <<held, receipt>>
Record(r) == pc[r] = "checked" /\ ReceiptWrite(r, IF seen[r] THEN "ok" ELSE "refused") /\ pc' = [pc EXCEPT ![r] = "recorded"] /\ UNCHANGED <<held, seen>>
Apply(r) == pc[r] = "recorded" /\ pc' = [pc EXCEPT ![r] = "done"] /\ UNCHANGED <<receipt, seen>>
            /\ IF seen[r] /\ LedgerCanReserve(r) THEN LedgerReserve(r) ELSE UNCHANGED held
Next == \E r \in Reqs : Check(r) \/ Record(r) \/ Apply(r)
Spec == Init /\ [][Next]_vars
====
