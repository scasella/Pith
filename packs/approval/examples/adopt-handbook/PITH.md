# Pith adoption record

This project protects **one workflow** with the contract pack `pith.approval` 0.9.0 (release pinned by the operator; `python3 gate/release.py id --pack packs/approval` in the Pith checkout).
Written by `gate/cli.py adopt` on 2026-10-13; keep it up to date as the adoption proceeds (docs/ADOPTING.md).

## 1. The operation
Subsystem covered: review of policy documents (handbook/reviews.py), through service/ and cli/

Project code the pack's entrypoints use (`include`): handbook. The judge copies only these paths and the pack's
agent-owned directories (service/, cli/) into the judged artifact. **Nothing else in this repository is covered**, and
"Pith is installed" does not mean the rest of the application is checked.

## 2. The protected behaviour
The pack's behavioral contract records (its INTENT.md explains them):

- A1: Nobody approves or rejects a revision they wrote.
- A2: Only approvers' approvals are recorded; each command needs its role.
- A3: A document is approved only with two approvals of its current revision; stale approvals never count.
- A4: No approval names a revision that does not exist yet.
- A5: Published is final.
- A6: Only an approved document is published.
- A7: Revisions only grow and keep their authors.

Where this project's current behaviour differs from them, decide here whether to change the code or not to adopt.

## 3. The independent checks
Entrypoints the pack's harness starts (its service contract says what each must do):

- `cli/main.py`
- `service/run.py`

Judge with the operator's pristine release, pinned (keep the release outside this repository):

    python3 -I <pristine release>/gate/app_gate.py --candidate <this project> --out <fresh dir outside the project> --expected-release <pinned digest>

## 4. Replace or strengthen
Record each refusal the judge reported, its category and what was changed (code, not checks), until it passes.

| Date | First failure | Category | Change made |
|---|---|---|---|
| 2026-10-13 | `service.entrypoint.python` (no `service/run.py`, `cli/main.py`) | evidence_missing | wrote `service/run.py`, `service/api.py` (HTTP onto `handbook.reviews.Reviews`) and `cli/main.py` |
| 2026-10-13 | `service.lifecycle`, `test_approvals_are_bound_to_a_revision_and_stale_ones_never_count` (A3): after an edit, revision 2 was approved with one approval of revision 2 and one left over from revision 1 | violation | `Reviews._decide` counted every vote on the document toward the quorum; it now counts only the current revision's (`review_votes` already kept the revision) |
| 2026-10-13 | none: every status the pack declares passed | | |

The known-wrong fixture `packs/approval/examples/wrong/adopt-handbook-stale` is this project as it was at the second
row: it must keep failing for exactly that reason (`examples/wrong/expected.yaml`).
