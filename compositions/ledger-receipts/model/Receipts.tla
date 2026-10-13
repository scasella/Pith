---- MODULE Receipts ----
\* Component "receipts": owns `receipt`, the recorded outcome of each request. A receipt is written once.
EXTENDS Common
VARIABLE receipt

ReceiptsInit == receipt = [r \in Reqs |-> "none"]
ReceiptWrite(r, v) == receipt[r] = "none" /\ v \in {"ok", "refused"} /\ receipt' = [receipt EXCEPT ![r] = v]

\* Local invariant: the receipt store's own rule, stated over its own state only.
ReceiptsInv == receipt \in [Reqs -> {"none", "ok", "refused"}]
====
