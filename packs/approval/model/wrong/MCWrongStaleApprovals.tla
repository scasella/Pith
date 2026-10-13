---- MODULE MCWrongStaleApprovals ----
(* The bounded configuration TLC checks, and harness/refines.py compares the reference model against. FROZEN. *)
EXTENDS WrongStaleApprovals
MCActors     == {"alice", "bob", "carol", "dave"}
MCEditors    == {"alice", "bob"}             \* alice and bob both write AND approve: separation of duties is per revision
MCApprovers  == {"alice", "bob", "carol"}
MCPublishers == {"dave"}
====
