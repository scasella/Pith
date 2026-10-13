---- MODULE Integration ----
\* The integration: one atomic transition decides at the ledger and records that decision as the receipt.
EXTENDS Ledger, Receipts
vars == <<held, receipt>>

Init == LedgerInit /\ ReceiptsInit
Reserve(r) ==
    /\ receipt[r] = "none"
    /\ \/ LedgerReserve(r) /\ ReceiptWrite(r, "ok")
       \/ ~LedgerCanReserve(r) /\ UNCHANGED held /\ ReceiptWrite(r, "refused")
Next == \E r \in Reqs : Reserve(r)
Spec == Init /\ [][Next]_vars
====
