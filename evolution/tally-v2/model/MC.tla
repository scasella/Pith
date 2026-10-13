---- MODULE MC ----
(* The bounded configuration TLC checks. FROZEN once sealed. *)
EXTENDS Spec
MCReqs == {"r1", "r2", "r3", "r4"}
MCCounters == {"default", "other"}
====
