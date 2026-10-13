---- MODULE Contract ----
\* The joint obligation no component can state alone: a receipt and the effect it reports agree.
EXTENDS Integration
ReceiptAgrees ==
    \A r \in Reqs : /\ (receipt[r] = "ok" => r \in held)
                    /\ (receipt[r] = "refused" => r \notin held)
                    /\ (r \in held => receipt[r] = "ok")
====
