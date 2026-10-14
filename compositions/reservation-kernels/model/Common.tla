---- MODULE Common ----
\* What both kernels read and neither owns: the requests, their amounts and the account's limit. The same values as the
\* reservation pack's design model (obligations/design/MC.tla, required.cfg).
EXTENDS Naturals, FiniteSets
CONSTANT Limit
Reqs == 1..3
Amount == <<60, 60, 40>>
RECURSIVE SumOf(_)
SumOf(S) == IF S = {} THEN 0 ELSE LET r == CHOOSE x \in S : TRUE IN Amount[r] + SumOf(S \ {r})
====
