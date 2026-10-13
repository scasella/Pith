------------------------------ MODULE WrongPublishInReview ------------------------------
(* KNOWN-WRONG design for pith.approval (model/wrong/). Publishing is allowed while the revision is still in review.*)
(* Actors and their roles are a SIMULATED actor model: who an actor is, is given; how a production identity      *)
(* provider would establish it is outside the contract (INTENT.md). Obligation tags in square brackets are the   *)
(* contract records of pack.yaml.                                                                                  *)
EXTENDS Naturals, FiniteSets

CONSTANTS Actors, Editors, Approvers, Publishers, Quorum, MaxRev
ASSUME Editors \subseteq Actors /\ Approvers \subseteq Actors /\ Publishers \subseteq Actors /\ Quorum \in 1..Cardinality(Approvers)

None == "none"
Statuses == {"draft", "in_review", "approved", "rejected", "published"}

VARIABLES status, rev, author, approvals
vars == <<status, rev, author, approvals>>

(* author[r]: who wrote revision r. approvals: <<revision, approver>> pairs ever recorded; old pairs are history *)
(* and never count for a later revision.                                                                         *)
Votes(r) == {a \in Actors : <<r, a>> \in approvals}

TypeOK == /\ status \in Statuses /\ rev \in 1..MaxRev
          /\ author \in [1..MaxRev -> Actors \cup {None}]
          /\ approvals \subseteq (1..MaxRev) \X Actors

Init(a) == /\ a \in Editors
           /\ status = "draft" /\ rev = 1
           /\ author = [r \in 1..MaxRev |-> IF r = 1 THEN a ELSE None]
           /\ approvals = {}
InitAny == \E a \in Editors : Init(a)

Edit(a) ==        \* a new revision by an editor; review, if any, starts over
  /\ a \in Editors /\ status # "published" /\ rev < MaxRev
  /\ rev' = rev + 1 /\ author' = [author EXCEPT ![rev + 1] = a] /\ status' = "draft"
  /\ UNCHANGED approvals

Submit(a, r) ==   \* the author of the current revision asks for review of THAT revision
  /\ status = "draft" /\ r = rev /\ a = author[rev]
  /\ status' = "in_review" /\ UNCHANGED <<rev, author, approvals>>

Approve(a, r) ==  \* bound to the current revision; never by its author; quorum of distinct approvers
  /\ a \in Approvers /\ status = "in_review" /\ r = rev /\ a # author[rev] /\ <<r, a>> \notin approvals
  /\ approvals' = approvals \cup {<<r, a>>}
  /\ status' = IF Cardinality(Votes(r)) + 1 >= Quorum THEN "approved" ELSE "in_review"
  /\ UNCHANGED <<rev, author>>

Reject(a, r) ==
  /\ a \in Approvers /\ status = "in_review" /\ r = rev /\ a # author[rev]
  /\ status' = "rejected" /\ UNCHANGED <<rev, author, approvals>>

Publish(a, r) ==
  /\ a \in Publishers /\ status \in {"approved", "in_review"} /\ r = rev   \* DEFECT: publish before the quorum
  /\ status' = "published" /\ UNCHANGED <<rev, author, approvals>>

Next == \E a \in Actors, r \in 1..MaxRev : Edit(a) \/ Submit(a, r) \/ Approve(a, r) \/ Reject(a, r) \/ Publish(a, r)
Spec == InitAny /\ [][Next]_vars

(* ---- obligations ---- *)
SeparationOfDuties == \A p \in approvals : p[2] # author[p[1]]                                  \* [A1]
ApproverRole       == \A p \in approvals : p[2] \in Approvers                                    \* [A2]
BoundToRevision    == status \in {"approved", "published"} => Cardinality(Votes(rev)) >= Quorum  \* [A3] stale approvals never count
NoFutureApprovals  == \A p \in approvals : p[1] <= rev                                           \* [A4]
Safety == TypeOK /\ SeparationOfDuties /\ ApproverRole /\ BoundToRevision /\ NoFutureApprovals

PublishedIsFinal   == [][status = "published" => UNCHANGED vars]_vars                            \* [A5]
PublishOnlyApproved == [][status' = "published" /\ status # "published" => status = "approved"]_vars   \* [A6]
RevisionsGrow      == [][rev' >= rev /\ \A r \in 1..rev : author'[r] = author[r]]_vars           \* [A7] history is never rewritten
=============================================================================
