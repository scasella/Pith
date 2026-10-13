# pith.approval — intent

Reviewed prose; not an oracle. The oracle is `model/Approval.tla` (the workflow), `harness/SERVICE.md` (the
service) and `delivery/CLI-CONTRACT.md` (the command-line client). This file says what they are meant to capture,
so a reviewer can check the formal statements against it before the pack is sealed.

## What the contract promises

A team writes policy documents, reviews them and publishes them. A document moves through
draft → in review → approved → published, or is rejected; any edit starts a new revision and sends it back to draft.

- **Separation of duties.** Nobody approves or rejects a revision they wrote. Separation is per revision: the
  author of revision 1 may approve revision 2 written by someone else. [A1]
- **Roles.** Only editors create and edit, only approvers approve or reject, only publishers publish. Any editor
  may edit any document that is not published, and becomes the author of the revision they write. [A2]
- **Only the author of the current revision submits it for review.** After someone else edits a document, its
  creator can no longer submit it: the new revision is the editor's. [A8]
- **Approvals are bound to a revision.** An approval counts for the revision it named and no other. After an edit,
  earlier approvals stay in the history and never count again; a command naming any revision other than the current
  one (a superseded one, or one that does not exist yet) is refused as `STALE_REVISION`, not applied to the current one.
  A document is approved only when **its quorum** of distinct approvers, none of them the author of its current
  revision, approved that revision. An approver who already approved the current revision is refused
  (`ALREADY_APPROVED`): a repeat never counts twice. [A3] [A4]
- **Each document has its own quorum, fixed at creation.** The editor who creates a document says how many distinct
  approvals its current revision needs, from 2 to 5 (2 when they do not say), so a high-stakes document can require
  more. Two is the floor: separation of duties still means at least two people besides the author. Nothing changes
  the quorum afterwards: not an edit, not an approval, no other command; an edit starts review over against the same
  quorum. A quorum outside 2 to 5 is not a refusal but invalid input (`400`), and creates nothing. [A9]
- **After approval or rejection.** An approved revision can only be published, or superseded by an edit; it can no
  longer be approved or rejected. A rejected revision cannot be resubmitted: it must be edited into a new revision,
  which is then reviewed from the start.
- **Published is final.** A published document never changes again, and only an approved revision is published. [A5] [A6]
- **Revisions only grow**, and each revision keeps its author. [A7]
- **A refusal changes nothing and says which rule refused it**, in a fixed precedence (harness/SERVICE.md § Refusals).
- **Every command is idempotent by request id**, survives a crash once acknowledged, and is decided against the
  latest committed state even under concurrent requests (two approvals racing for the quorum, an edit racing an
  approval).
- **The command-line client never confuses a refusal, an error and an unknown outcome**, and after an unknown
  outcome it gives the person what they need to retry safely (delivery/CLI-CONTRACT.md).

## The actor model is simulated

Actors and roles are registered through the API and named in each command. The contract says what an actor with
given roles may do. It does **not** say how a caller proves who they are: authentication, sessions, an identity
provider and delegation are out of scope, and an application that ships this contract still needs them.

## What it explicitly does not promise

Authentication; more than one workflow shape (sequential approver chains, conditional routes, a quorum that
changes during review, a quorum of one); withdrawing a submission; un-publishing; comments and diffs between revisions; notifications; access
control on reading documents. Adding any of these is a behavioural change to the pack: it needs new invariants in
`model/Approval.tla`, a known-wrong design in `model/wrong/` that the new invariant rejects, the reference model
(`harness/reference.py`) updated until `harness/refines.py` passes again, and a new contract version.

## How a behavioural change is made

Edit `model/Approval.tla` and this file together, add a known-wrong design in `model/wrong/`, update
`harness/reference.py` until `harness/refines.py` shows the two equal, re-run the pack's checks, then reseal
(`python3 gate/release.py seal --pack packs/approval`). The contract version in `pack.yaml` changes; evidence from
the old version is not reused (docs/rfc/0001 § Reuse). When running deployments hold state, the new version also
ships a migration from the old one (`migrations/`, below).

## Version 2 and upgrading from version 1

`approval-workflow/v2` (pack 0.12.0) is the first behavioural change made this way: the per-document quorum. A3 now
reads "its quorum" where version 1 read "two" (version 2 of the record); A9 is new (the quorum is fixed at creation:
`QuorumFixed` in the model); BoundaryConformance is at version 2 because the API changed (create takes `quorum`, every
document view carries it, an out-of-domain quorum is `400`). Two known-wrong designs show the model rejects the
likely mistakes: `model/wrong/WrongConstantQuorum.tla` (the approval rule still reads a constant two) violates
BoundToRevision, and `model/wrong/WrongQuorumChanges.tla` (an edit puts the document back on the default quorum)
violates QuorumFixed. Traces T12 to T14 in `model/traces.yaml` show a quorum of three: two approvals leave it in
review, the third approves it, and an edit does not lower it.

**Upgrading a running version 1 deployment** (MIG1, `migrations/from-v1.yaml`, harness/SERVICE.md § Upgrading from
version 1) keeps everything version 1 acknowledged, and decides nothing again:

- every version 1 document becomes a document with quorum 2, which is what version 1 meant; its revisions, authors,
  bodies, status and every approval ever recorded stay, the approvals of superseded revisions included: they never
  count again, but they are history, and dropping them as dead data erases it;
- actors keep their roles, and the event log stays;
- every result version 1 recorded stays replayable: a version 1 client retrying an old request id gets the recorded
  result with `replayed: true` (an old approval retried is a replay, never `ALREADY_APPROVED`), and reusing it for
  something else is still `409`. A version 1 create named no quorum, and is the same command as a create naming 2;
- a command in flight when the version 1 service was killed is decided at most once;
- rollback is forward-only: once a document has a quorum other than 2, version 1 cannot represent it.

The judge holds each application to this on state the application's own accepted version 1 service produced
(`migrations/populate.py`, `migrations/verify.py`), and three known-wrong migrations in
`examples/wrong-migrations/` (dropping stale approvals, dropping the request ledger, leaving old creates without
their quorum) each run the conforming service, and are refused by that run for exactly their defect; the first two
are also judged ordinarily, which accepts them: only the run with populated state catches them.
