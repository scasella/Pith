---- MODULE MC ----
(* Frozen model-checking wrapper. The candidate's Design must declare a VARIABLE named `responses`
   (Reqs -> Seq({"Auth","Decl"})) and must NOT define Idempotent, Consistent or CovRetry: those names
   are bound HERE to the frozen predicates, so the candidate cannot redefine what is checked. *)
EXTENDS Design
MCReqs     == 1..3
MCAmount   == <<60, 60, 40>>
Idempotent == IdempotentResp(responses)
Consistent == ConsistentResp(responses)
CovRetry   == RetryCov(responses)
====
