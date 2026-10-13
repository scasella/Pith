# pith.approval — intent

Reviewed prose; not an oracle. The oracle is `model/Approval.tla` (the workflow), `harness/SERVICE.md` (the
service) and `delivery/CLI-CONTRACT.md` (the command-line client). This file says what they are meant to capture,
so a reviewer can check the formal statements against it before the pack is sealed.

## What the contract promises

A team writes policy documents, reviews them and publishes them. A document moves through
draft → in review → approved → published, or is rejected; any edit starts a new revision and sends it back to draft.

- **Separation of duties.** Nobody approves or rejects a revision they wrote. Separation is per revision: the
  author of revision 1 may approve revision 2 written by someone else. [A1]
- **Roles.** Only editors create and edit, only approvers approve or reject, only publishers publish. [A2]
- **Approvals are bound to a revision.** An approval counts for the revision it named and no other. After an edit,
  earlier approvals stay in the history and never count again; a command naming a superseded revision is refused as
  `STALE_REVISION`, not applied to the new one. A document is approved only when **two** distinct approvers, neither
  of them its author, approved its current revision. [A3] [A4]
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

Authentication; more than one workflow shape (a configurable quorum, sequential approver chains, conditional
routes); withdrawing a submission; un-publishing; comments and diffs between revisions; notifications; access
control on reading documents. Adding any of these is a behavioural change to the pack: it needs new invariants in
`model/Approval.tla`, a known-wrong design in `model/wrong/` that the new invariant rejects, the reference model
(`harness/reference.py`) updated until `harness/refines.py` passes again, and a new contract version.

## How a behavioural change is made

Edit `model/Approval.tla` and this file together, add a known-wrong design in `model/wrong/`, update
`harness/reference.py` until `harness/refines.py` shows the two equal, re-run the pack's checks, then reseal
(`python3 gate/release.py seal --pack packs/approval`). The contract version in `pack.yaml` changes; evidence from
the old version is not reused (docs/rfc/0001 § Reuse).
