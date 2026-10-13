------------------------------ MODULE WrongStaleApprovals ------------------------------
(* KNOWN-WRONG design for pith.approval (model/wrong/): model/Approval.tla with ONE change, marked DEFECT.    *)
(* Approvals count across revisions: after an edit, votes for earlier revisions still count.                  *)
(* model/wrong/MCWrongStaleApprovals.cfg checks it against BoundToRevision alone, which it must violate (pack.yaml model.adequacy). *)
EXTENDS Naturals, FiniteSets

CONSTANTS Actors, Editors, Approvers, Publishers, Quorum, MaxRev
ASSUME Editors \subseteq Actors /\ Approvers \subseteq Actors /\ Publishers \subseteq Actors /\ Quorum \in 1..Cardinality(Approvers)

None == "none"
Statuses == {"draft", "in_review", "approved", "rejected", "published"}

VARIABLES status, rev, author, approvals, last
vars == <<status, rev, author, approvals, last>>

(* author[r]: who wrote revision r. approvals: <<revision, approver>> pairs ever recorded; old pairs are history *)
(* and never count for a later revision. last: <<command, actor, revision>> of the step that produced this state, *)
(* a history variable that makes WHO did each step observable, so the rules about who may submit, reject,       *)
(* publish and edit can be stated as invariants (and harness/refines.py compares actors, not only actions).      *)
Ops == {"create", "edit", "submit", "approve", "reject", "publish"}
Votes(r) == {a \in Actors : <<r, a>> \in approvals}

TypeOK == /\ status \in Statuses /\ rev \in 1..MaxRev
          /\ author \in [1..MaxRev -> Actors \cup {None}]
          /\ approvals \subseteq (1..MaxRev) \X Actors
          /\ last \in Ops \X Actors \X (1..MaxRev)

Init(a) == /\ a \in Editors
           /\ status = "draft" /\ rev = 1
           /\ author = [r \in 1..MaxRev |-> IF r = 1 THEN a ELSE None]
           /\ approvals = {}
           /\ last = <<"create", a, 1>>
InitAny == \E a \in Editors : Init(a)

Edit(a) ==        \* a new revision by an editor; review, if any, starts over
  /\ a \in Editors /\ status # "published" /\ rev < MaxRev
  /\ rev' = rev + 1 /\ author' = [author EXCEPT ![rev + 1] = a] /\ status' = "draft"
  /\ last' = <<"edit", a, rev + 1>>
  /\ UNCHANGED approvals

Submit(a, r) ==   \* the author of the current revision asks for review of THAT revision
  /\ status = "draft" /\ r = rev /\ a = author[rev]
  /\ status' = "in_review" /\ last' = <<"submit", a, r>> /\ UNCHANGED <<rev, author, approvals>>

Approve(a, r) ==  \* bound to the current revision; never by its author; quorum of distinct approvers
  /\ a \in Approvers /\ status = "in_review" /\ r = rev /\ a # author[rev] /\ <<r, a>> \notin approvals
  /\ approvals' = approvals \cup {<<r, a>>}
  /\ status' = IF Cardinality({p[2] : p \in approvals}) + 1 >= Quorum THEN "approved" ELSE "in_review"   \* DEFECT: every revision's votes count
  /\ last' = <<"approve", a, r>> /\ UNCHANGED <<rev, author>>

Reject(a, r) ==
  /\ a \in Approvers /\ status = "in_review" /\ r = rev /\ a # author[rev]
  /\ status' = "rejected" /\ last' = <<"reject", a, r>> /\ UNCHANGED <<rev, author, approvals>>

Publish(a, r) ==
  /\ a \in Publishers /\ status = "approved" /\ r = rev
  /\ status' = "published" /\ last' = <<"publish", a, r>> /\ UNCHANGED <<rev, author, approvals>>

Next == \E a \in Actors, r \in 1..MaxRev : Edit(a) \/ Submit(a, r) \/ Approve(a, r) \/ Reject(a, r) \/ Publish(a, r)
Spec == InitAny /\ [][Next]_vars

(* ---- obligations ---- *)
SeparationOfDuties == \A p \in approvals : p[2] # author[p[1]]                                  \* [A1]
ApproverRole       == \A p \in approvals : p[2] \in Approvers                                    \* [A2]
BoundToRevision    == status \in {"approved", "published"} => Cardinality(Votes(rev)) >= Quorum  \* [A3] stale approvals never count
NoFutureApprovals  == \A p \in approvals : p[1] <= rev                                           \* [A4]
RejectBySeparation == last[1] = "reject" => last[2] \in Approvers /\ last[2] # author[last[3]]    \* [A1] [A2] nobody rejects a revision they wrote
PublishByPublisher == last[1] = "publish" => last[2] \in Publishers                              \* [A2]
EditByEditor       == last[1] \in {"create", "edit"} => last[2] \in Editors /\ author[last[3]] = last[2]   \* [A2] and the revision is theirs
SubmitByAuthor     == last[1] = "submit" => last[2] = author[last[3]]                             \* [A8]
Safety == TypeOK /\ SeparationOfDuties /\ ApproverRole /\ BoundToRevision /\ NoFutureApprovals
          /\ RejectBySeparation /\ PublishByPublisher /\ EditByEditor /\ SubmitByAuthor

PublishedIsFinal   == [][status = "published" => UNCHANGED vars]_vars                            \* [A5]
PublishOnlyApproved == [][status' = "published" /\ status # "published" => status = "approved"]_vars   \* [A6]
RevisionsGrow      == [][rev' >= rev /\ \A r \in 1..rev : author'[r] = author[r]]_vars           \* [A7] history is never rewritten
ApprovalsGrow      == [][approvals \subseteq approvals']_vars                                    \* [A3] earlier approvals stay in the history
=============================================================================
